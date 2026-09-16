"""
Telegram media downloader using Telethon.
Handles connecting, listing chats, and downloading media files.
"""

import os
import logging
from urllib.parse import urlparse
from datetime import datetime

from telethon import TelegramClient
from telethon.tl.types import (
    MessageMediaDocument,
    MessageMediaPhoto,
    DocumentAttributeFilename,
    DocumentAttributeAudio,
    DocumentAttributeVideo,
)
from telethon.utils import get_input_location

from config import Config
from parallel_download import SenderPool, ParallelUnsupported, download_document

logger = logging.getLogger(__name__)

MB = 1024 * 1024


class DownloadCancelled(Exception):
    """Raised to abort an in-progress download (via the progress callback)."""
    pass


class TelegramDownloader:
    def __init__(self):
        self.client: TelegramClient | None = None
        self.connected = False
        self.downloading = False
        self.cancel_requested = False
        self.progress = {}  # course_id -> {total, done, current_file, status}

    # -- Connection --

    @staticmethod
    def _parse_proxy(proxy_url: str) -> dict | None:
        """Parse proxy URL into Telethon proxy dict."""
        if not proxy_url:
            return None
        parsed = urlparse(proxy_url)
        scheme = parsed.scheme.lower()
        proxy_type = {
            "http": 3, "https": 3,       # python-socks: HTTP=3
            "socks5": 2, "socks4": 1,    # python-socks: SOCKS4=1, SOCKS5=2
        }.get(scheme)
        if proxy_type is None:
            logger.warning(f"Unknown proxy scheme: {scheme}")
            return None
        return {
            "proxy_type": proxy_type,
            "addr": parsed.hostname,
            "port": parsed.port or (1080 if scheme.startswith("socks") else 3128),
            "username": parsed.username,
            "password": parsed.password,
        }

    async def connect(self):
        if self.client and self.connected and self.client.is_connected():
            return True

        session_path = os.path.join(os.path.dirname(__file__), "session")
        proxy = self._parse_proxy(Config.PROXY)
        if proxy:
            logger.info(f"Using proxy: {proxy['addr']}:{proxy['port']}")
        self.client = TelegramClient(session_path, Config.API_ID, Config.API_HASH,
                                     proxy=proxy)
        await self.client.connect()

        if await self.client.is_user_authorized():
            self.connected = True
            logger.info("Telegram client connected (existing session).")
            return True

        logger.warning("Telegram client not authorized. Need to send code.")
        return False

    async def ensure_connected(self):
        """Reconnect if Telethon's TCP connection dropped. Call before every TG op."""
        if not self.client:
            await self.connect()
            return
        if not self.client.is_connected():
            logger.warning("Telegram connection dropped, reconnecting...")
            self.connected = False
            try:
                await self.client.connect()
                if await self.client.is_user_authorized():
                    self.connected = True
                    logger.info("Telegram reconnected.")
            except Exception as e:
                logger.error(f"Reconnect failed: {e}")
                raise

    async def send_code(self):
        if not self.client:
            await self.connect()
        result = await self.client.send_code_request(Config.PHONE)
        return result.phone_code_hash

    async def sign_in(self, code: str, phone_code_hash: str):
        await self.client.sign_in(Config.PHONE, code, phone_code_hash=phone_code_hash)
        self.connected = True
        logger.info("Successfully signed in.")
        return True

    async def disconnect(self):
        if self.client:
            await self.client.disconnect()
            self.connected = False

    # -- Chat resolution --

    async def resolve_chat(self, chat_link: str):
        """Resolve a chat link/username to entity info."""
        await self.ensure_connected()
        if not self.connected:
            raise RuntimeError("Not connected to Telegram")

        link = chat_link.strip()

        if "t.me/" in link:
            part = link.split("t.me/")[-1].split("?")[0].strip("/")
            if part.startswith("c/"):
                # Private channel link: t.me/c/CHANNEL_ID/...
                # Extract channel ID and convert to Telethon format
                channel_id = int(part.split("/")[1])
                entity = await self.client.get_entity(int(f"-100{channel_id}"))
            elif part.startswith("+"):
                from telethon.tl.functions.messages import ImportChatInviteRequest
                try:
                    updates = await self.client(ImportChatInviteRequest(part[1:]))
                    entity = updates.chats[0]
                except Exception:
                    entity = await self.client.get_entity(link)
            else:
                entity = await self.client.get_entity(part)
        elif link.startswith("@"):
            entity = await self.client.get_entity(link)
        elif link.lstrip("-").isdigit():
            entity = await self.client.get_entity(int(link))
        else:
            entity = await self.client.get_entity(link)

        title = getattr(entity, "title", None) or getattr(entity, "first_name", "Unknown")
        return {
            "id": entity.id,
            "title": title,
            "type": type(entity).__name__,
        }

    # -- Scanning --

    async def scan_chat(self, chat_id: int):
        """Scan a chat and return a list of downloadable media files."""
        await self.ensure_connected()
        if not self.connected:
            raise RuntimeError("Not connected to Telegram")

        entity = await self.client.get_entity(chat_id)
        files = []

        async for message in self.client.iter_messages(entity):
            if message.media is not None:
                file_info = self._extract_file_info(message)
                if file_info:
                    files.append(file_info)
            else:
                # Text-only message (no media) — capture as a text entry.
                # getattr guards service messages that lack a .message attr.
                text = (getattr(message, "message", "") or "").strip()
                if text:
                    files.append({
                        "msg_id": message.id,
                        "type": "text",
                        "text": text,
                        "date": message.date.isoformat(),
                    })

        files.sort(key=lambda f: f["date"])

        # Deduplicate filenames by appending _msgID (text entries have no filename)
        seen = {}
        for f in files:
            name = f.get("filename")
            if not name:
                continue
            if name in seen:
                seen[name].append(f)
            else:
                seen[name] = [f]
        for name, group in seen.items():
            if len(group) > 1:
                base, ext = os.path.splitext(name)
                for f in group:
                    f["filename"] = f"{base}_{f['msg_id']}{ext}"

        for i, f in enumerate(files, 1):
            f["index"] = i

        return files

    def _extract_file_info(self, message) -> dict | None:
        media = message.media
        caption = (getattr(message, "message", "") or "").strip()

        if isinstance(media, MessageMediaDocument) and media.document:
            doc = media.document
            filename = None
            file_type = "document"

            for attr in doc.attributes:
                if isinstance(attr, DocumentAttributeFilename):
                    filename = attr.file_name
                if isinstance(attr, DocumentAttributeVideo):
                    file_type = "video"
                if isinstance(attr, DocumentAttributeAudio):
                    file_type = "voice" if attr.voice else "audio"

            if not filename:
                ext = self._mime_to_ext(doc.mime_type)
                filename = f"{file_type}_{message.id}{ext}"

            return {
                "msg_id": message.id,
                "filename": self._safe_filename(filename),
                "size": doc.size,
                "type": file_type,
                "mime": doc.mime_type,
                "date": message.date.isoformat(),
                "caption": caption,
            }

        elif isinstance(media, MessageMediaPhoto):
            return {
                "msg_id": message.id,
                "filename": f"photo_{message.id}.jpg",
                "size": 0,
                "type": "photo",
                "mime": "image/jpeg",
                "date": message.date.isoformat(),
                "caption": caption,
            }

        return None

    # -- Downloading --

    def request_cancel(self):
        """Signal any in-progress download to stop ASAP. Safe to call from
        another thread (plain bool flag, atomic under the GIL)."""
        if self.downloading:
            self.cancel_requested = True

    @staticmethod
    def _cleanup_partial(filepath: str):
        """Remove a partially-downloaded file after cancellation or error.
        Downloads have no resume, so a leftover partial is just garbage."""
        try:
            if filepath and os.path.exists(filepath):
                os.remove(filepath)
                logger.info(f"Removed partial file: {filepath}")
        except OSError as e:
            logger.warning(f"Could not remove partial file {filepath}: {e}")

    def _make_progress_cb(self, course_id: str):
        """Create a callback for Telethon download_media to track byte progress.
        Raising inside the callback aborts the download mid-file (Telethon
        propagates it and closes the file in its finally block)."""
        def callback(received, total):
            if self.cancel_requested:
                raise DownloadCancelled()
            prog = self.progress.get(course_id)
            if prog:
                prog["bytes_done"] = received
                prog["bytes_total"] = total
        return callback

    def _new_pool(self) -> SenderPool | None:
        if Config.DOWNLOAD_CONNECTIONS > 1:
            return SenderPool(self.client, Config.DOWNLOAD_CONNECTIONS)
        return None

    @staticmethod
    async def _close_pool(pool: SenderPool | None):
        """Close extra connections. Called after the downloading flag is
        reset, so a failing disconnect can't block future downloads."""
        if not pool:
            return
        try:
            await pool.close()
        except Exception as e:
            logger.warning(f"Closing download connections failed: {e}")

    async def _download_message(self, message, filepath: str, course_id: str,
                                pool: SenderPool | None):
        """Download message media into filepath. Writes to a .part file and
        renames on success: a preallocated or interrupted file never shows
        up under the real name, and a failed re-download keeps the old copy."""
        part_path = filepath + ".part"
        self._cleanup_partial(part_path)
        progress_cb = self._make_progress_cb(course_id)
        media = message.media
        doc = media.document if isinstance(media, MessageMediaDocument) else None
        try:
            if pool and doc and doc.size >= Config.PARALLEL_MIN_MB * MB:
                try:
                    await download_document(pool, doc, part_path, progress_cb)
                except ParallelUnsupported as e:
                    logger.info(f"Parallel download not possible ({e}), "
                                f"single stream: {os.path.basename(filepath)}")
                    await self._download_single_stream(message, part_path, progress_cb)
            else:
                await self._download_single_stream(message, part_path, progress_cb)
            os.replace(part_path, filepath)
        except BaseException:
            self._cleanup_partial(part_path)
            raise

    async def _download_single_stream(self, message, path: str, progress_cb):
        result = await self.client.download_media(
            message, file=path, progress_callback=progress_cb,
        )
        if not result or os.path.abspath(result) != os.path.abspath(path):
            raise RuntimeError(f"Telegram не отдал файл (получено: {result})")

    async def download_single(self, course_id: str, chat_id: int, msg_id: int,
                              filename: str, file_size: int, course_dir: str):
        """Download a single file by message ID (async, updates progress)."""
        if self.downloading:
            raise RuntimeError("Another download is already in progress")

        await self.ensure_connected()
        self.downloading = True
        self.cancel_requested = False
        filepath = os.path.join(course_dir, filename)

        self.progress[course_id] = {
            "total": 1,
            "done": 0,
            "current_file": filename,
            "status": "downloading",
            "bytes_done": 0,
            "bytes_total": file_size,
            "errors": [],
        }

        cancelled = False
        pool = self._new_pool()
        # try/finally guarantees the downloading flag is always reset, even if
        # get_entity/makedirs raise — otherwise the whole subsystem would wedge.
        # Partial files are removed by _download_message itself.
        try:
            os.makedirs(course_dir, exist_ok=True)
            entity = await self.client.get_entity(chat_id)
            message = await self.client.get_messages(entity, ids=msg_id)
            if message and message.media:
                await self._download_message(message, filepath, course_id, pool)
                logger.info(f"Downloaded: {filename}")
                self.progress[course_id]["done"] = 1
        except DownloadCancelled:
            logger.info(f"Download cancelled: {filename}")
            cancelled = True
        except Exception as e:
            logger.error(f"Error downloading {filename}: {e}")
            self.progress[course_id]["errors"].append(
                {"file": filename, "error": str(e)}
            )
        finally:
            self.progress[course_id]["status"] = "cancelled" if cancelled else "completed"
            self.progress[course_id]["current_file"] = ""
            self.downloading = False
            self.cancel_requested = False
            await self._close_pool(pool)

    async def download_course(self, course_id: str, chat_id: int,
                              file_list: list[dict], course_dir: str):
        """Download all files from file_list. Updates self.progress as it goes."""
        if self.downloading:
            raise RuntimeError("Another download is already in progress")

        await self.ensure_connected()
        self.downloading = True
        self.cancel_requested = False

        total = len(file_list)
        self.progress[course_id] = {
            "total": total,
            "done": 0,
            "current_file": "",
            "status": "downloading",
            "bytes_done": 0,
            "bytes_total": 0,
            "errors": [],
        }

        cancelled = False
        # Connections are opened on the first large file and reused for the rest
        pool = self._new_pool()
        # Outer try/finally guarantees the downloading flag is always reset,
        # even if makedirs/get_entity raise — otherwise every future download
        # would be blocked until the process restarts.
        try:
            os.makedirs(course_dir, exist_ok=True)
            entity = await self.client.get_entity(chat_id)

            for i, file_info in enumerate(file_list):
                # Cancellation requested between files
                if self.cancel_requested:
                    cancelled = True
                    break

                filename = file_info["filename"]
                filepath = os.path.join(course_dir, filename)

                # Skip already downloaded
                if os.path.exists(filepath) and os.path.getsize(filepath) > 0:
                    if file_info["size"] == 0 or os.path.getsize(filepath) >= file_info["size"]:
                        self.progress[course_id]["done"] = i + 1
                        continue

                self.progress[course_id]["current_file"] = filename
                self.progress[course_id]["bytes_done"] = 0
                self.progress[course_id]["bytes_total"] = file_info.get("size", 0)

                try:
                    message = await self.client.get_messages(entity, ids=file_info["msg_id"])
                    if message and message.media:
                        await self._download_message(message, filepath, course_id, pool)
                        logger.info(f"Downloaded: {filename}")
                except DownloadCancelled:
                    logger.info(f"Download cancelled during: {filename}")
                    cancelled = True
                    break
                except Exception as e:
                    logger.error(f"Error downloading {filename}: {e}")
                    self.progress[course_id]["errors"].append(
                        {"file": filename, "error": str(e)}
                    )

                self.progress[course_id]["done"] = i + 1
        except DownloadCancelled:
            cancelled = True
        except Exception as e:
            logger.error(f"Download course failed: {e}")
            self.progress[course_id]["errors"].append({"file": "", "error": str(e)})
        finally:
            self.progress[course_id]["status"] = "cancelled" if cancelled else "completed"
            self.progress[course_id]["current_file"] = ""
            self.downloading = False
            self.cancel_requested = False
            await self._close_pool(pool)

        return self.progress[course_id]

    # -- Thumbnails --

    async def download_thumbs(self, chat_id: int, file_list: list[dict],
                              course_dir: str):
        """Download Telegram-generated thumbnails for video/photo files."""
        await self.ensure_connected()
        thumbs_dir = os.path.join(course_dir, ".thumbs")
        os.makedirs(thumbs_dir, exist_ok=True)

        entity = await self.client.get_entity(chat_id)

        for file_info in file_list:
            if file_info["type"] not in ("video", "photo"):
                continue

            thumb_path = os.path.join(thumbs_dir, file_info["filename"] + ".jpg")
            if os.path.exists(thumb_path):
                continue

            try:
                message = await self.client.get_messages(entity, ids=file_info["msg_id"])
                if not message or not message.media:
                    continue

                # Download the smallest available thumb
                thumb = await self.client.download_media(
                    message, file=thumb_path, thumb=-1
                )
                if thumb:
                    logger.info(f"Thumb saved: {file_info['filename']}")
            except Exception as e:
                logger.debug(f"No thumb for {file_info['filename']}: {e}")

    # -- Helpers --

    @staticmethod
    def _safe_filename(name: str) -> str:
        for ch in ['/', '\\', ':', '*', '?', '"', '<', '>', '|']:
            name = name.replace(ch, '_')
        return name.strip()

    @staticmethod
    def _mime_to_ext(mime: str) -> str:
        mapping = {
            "video/mp4": ".mp4",
            "video/quicktime": ".mov",
            "video/x-matroska": ".mkv",
            "audio/mpeg": ".mp3",
            "audio/ogg": ".ogg",
            "audio/mp4": ".m4a",
            "audio/x-wav": ".wav",
            "application/pdf": ".pdf",
            "image/jpeg": ".jpg",
            "image/png": ".png",
        }
        return mapping.get(mime, ".bin")

    @staticmethod
    def format_size(size_bytes: int) -> str:
        if size_bytes == 0:
            return ""
        for unit in ["Б", "КБ", "МБ", "ГБ"]:
            if size_bytes < 1024:
                return f"{size_bytes:.1f} {unit}"
            size_bytes /= 1024
        return f"{size_bytes:.1f} ТБ"


# Singleton
downloader = TelegramDownloader()
