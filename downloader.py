"""
Telegram media downloader using Telethon.
Handles connecting, listing chats, and downloading media files.
"""

import os
import logging
from datetime import datetime

from telethon import TelegramClient
from telethon.tl.types import (
    MessageMediaDocument,
    MessageMediaPhoto,
    DocumentAttributeFilename,
    DocumentAttributeAudio,
    DocumentAttributeVideo,
)

from config import Config

logger = logging.getLogger(__name__)


class TelegramDownloader:
    def __init__(self):
        self.client: TelegramClient | None = None
        self.connected = False
        self.downloading = False
        self.progress = {}  # course_id -> {total, done, current_file, status}

    # -- Connection --

    async def connect(self):
        if self.client and self.connected:
            return True

        session_path = os.path.join(os.path.dirname(__file__), "session")
        self.client = TelegramClient(session_path, Config.API_ID, Config.API_HASH)
        await self.client.connect()

        if await self.client.is_user_authorized():
            self.connected = True
            logger.info("Telegram client connected (existing session).")
            return True

        logger.warning("Telegram client not authorized. Need to send code.")
        return False

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
        if not self.connected:
            raise RuntimeError("Not connected to Telegram")

        entity = await self.client.get_entity(chat_id)
        files = []

        async for message in self.client.iter_messages(entity):
            if message.media is None:
                continue
            file_info = self._extract_file_info(message)
            if file_info:
                files.append(file_info)

        files.sort(key=lambda f: f["date"])

        for i, f in enumerate(files, 1):
            f["index"] = i

        return files

    def _extract_file_info(self, message) -> dict | None:
        media = message.media

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
            }

        elif isinstance(media, MessageMediaPhoto):
            return {
                "msg_id": message.id,
                "filename": f"photo_{message.id}.jpg",
                "size": 0,
                "type": "photo",
                "mime": "image/jpeg",
                "date": message.date.isoformat(),
            }

        return None

    # -- Downloading --

    async def download_single(self, chat_id: int, msg_id: int,
                              filename: str, course_dir: str):
        """Download a single file by message ID."""
        os.makedirs(course_dir, exist_ok=True)
        filepath = os.path.join(course_dir, filename)
        entity = await self.client.get_entity(chat_id)
        message = await self.client.get_messages(entity, ids=msg_id)
        if message and message.media:
            await self.client.download_media(message, file=filepath)
            logger.info(f"Downloaded: {filename}")
            return True
        return False

    async def download_course(self, course_id: str, chat_id: int,
                              file_list: list[dict], course_dir: str):
        """Download all files from file_list. Updates self.progress as it goes."""
        if self.downloading:
            raise RuntimeError("Another download is already in progress")

        self.downloading = True
        os.makedirs(course_dir, exist_ok=True)

        total = len(file_list)
        self.progress[course_id] = {
            "total": total,
            "done": 0,
            "current_file": "",
            "status": "downloading",
            "errors": [],
        }

        entity = await self.client.get_entity(chat_id)

        for i, file_info in enumerate(file_list):
            filename = file_info["filename"]
            filepath = os.path.join(course_dir, filename)

            # Skip already downloaded
            if os.path.exists(filepath) and os.path.getsize(filepath) > 0:
                if file_info["size"] == 0 or os.path.getsize(filepath) >= file_info["size"]:
                    self.progress[course_id]["done"] = i + 1
                    continue

            self.progress[course_id]["current_file"] = filename

            try:
                message = await self.client.get_messages(entity, ids=file_info["msg_id"])
                if message and message.media:
                    await self.client.download_media(message, file=filepath)
                    logger.info(f"Downloaded: {filename}")
            except Exception as e:
                logger.error(f"Error downloading {filename}: {e}")
                self.progress[course_id]["errors"].append(
                    {"file": filename, "error": str(e)}
                )

            self.progress[course_id]["done"] = i + 1

        self.progress[course_id]["status"] = "completed"
        self.progress[course_id]["current_file"] = ""
        self.downloading = False
        return self.progress[course_id]

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
