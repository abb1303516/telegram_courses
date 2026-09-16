"""
Parallel download of large Telegram documents over several separate
connections to the file's DC.

Telegram throttles each authorization (3.4-5.3 MB/s single stream from NL),
and ranges multiplexed over one connection are no faster than a single
stream. So every range gets its own connection with its own exported
authorization. Measured 2026-09-16 on NL: 4 connections give ~9 MB/s
transfer, close to the non-premium account ceiling of ~10 MB/s.
Details and numbers: CLAUDE.md, "Параллельная загрузка".
"""

import asyncio
import logging
from typing import Callable

from telethon import TelegramClient, errors, functions, utils
from telethon.network import MTProtoSender
from telethon.tl.types import Document
from telethon.tl.types.upload import FileCdnRedirect

logger = logging.getLogger(__name__)

# Non-premium accounts get FloodPremiumWaitError for parallel downloads. It is
# a sibling of FloodWaitError (both derive from FloodError), not a subclass.
FLOOD_ERRORS = (errors.FloodWaitError, errors.FloodPremiumWaitError)
MAX_FLOOD_SLEEP = 60  # longer penalties fail the file instead of hanging
RETRY_ERRORS = (errors.ServerError, errors.TimedOutError, asyncio.TimeoutError)
MAX_RETRIES = 3
REQUEST_TIMEOUT = 60  # seconds per chunk; a dead connection must not hang forever

ProgressCallback = Callable[[int, int], None]


class ParallelUnsupported(Exception):
    """The file can't be fetched by parallel ranges (home DC, CDN redirect,
    expired file reference). The caller should fall back to Telethon's own
    download."""


class SenderPool:
    """Separate connections per DC, created on first use and reused across
    the files of one download run. close() must be called at the end."""

    def __init__(self, client: TelegramClient, size: int):
        self.client = client
        self.size = size
        self._senders: dict[int, list[MTProtoSender]] = {}

    async def get(self, dc_id: int) -> list[MTProtoSender]:
        if dc_id not in self._senders:
            self._senders[dc_id] = await self._create(dc_id)
        return self._senders[dc_id]

    async def discard(self, dc_id: int):
        """Drop the connections of one DC (state unknown after a failure)."""
        for sender in self._senders.pop(dc_id, []):
            await sender.disconnect()

    async def close(self):
        for dc_id in list(self._senders):
            await self.discard(dc_id)

    async def _create(self, dc_id: int) -> list[MTProtoSender]:
        client = self.client
        if dc_id == client.session.dc_id:
            # Exporting auth to our own DC fails (DcIdInvalidError), and extra
            # connections on the session's own key would share its limit
            raise ParallelUnsupported("file is in the account's home DC")

        # Every connection gets its own exported authorization: Telegram
        # limits speed per authorization, not per TCP connection (2026-09-16:
        # 4 connections on one key were no faster than a single stream).
        # One at a time: concurrent exportAuthorization calls invalidate each
        # other (AuthBytesInvalidError). The borrow lock also serializes us
        # with Telethon's own exported senders (thumbnail downloads), which
        # mutate the same client._init_request.
        loop = asyncio.get_running_loop()
        started = loop.time()
        senders = []
        try:
            async with client._borrow_sender_lock:
                for _ in range(self.size):
                    senders.append(await client._create_exported_sender(dc_id))
        except BaseException:
            for sender in senders:
                await sender.disconnect()
            raise
        logger.info(f"Opened {len(senders)} connections to DC {dc_id} "
                    f"in {loop.time() - started:.1f}s")
        return senders


def _split_ranges(size: int, parts: int, chunk: int) -> list[tuple[int, int]]:
    """Split [0, size) into up to `parts` ranges whose offsets are multiples
    of `chunk` (Telegram requires offsets aligned to the request size)."""
    per = -(-size // parts)          # ceil
    per = -(-per // chunk) * chunk   # round up to a whole number of chunks
    return [(off, min(per, size - off)) for off in range(0, size, per)]


async def download_document(pool: SenderPool, document: Document, path: str,
                            progress_callback: ProgressCallback):
    """Download `document` into `path` by ranges over separate connections.

    progress_callback(received, total) is called after every chunk and while
    waiting out flood penalties; raising inside it aborts the download (same
    contract as Telethon's download_media). On any failure the connections
    of the DC are dropped; removing the partial file is up to the caller."""
    dc_id, location = utils.get_input_location(document)
    size = document.size
    chunk = utils.get_appropriated_part_size(size) * 1024
    senders = await pool.get(dc_id)
    ranges = _split_ranges(size, len(senders), chunk)
    loop = asyncio.get_running_loop()
    received = 0

    with open(path, "wb") as f:
        f.truncate(size)

        # No await between seek and write, so ranges can't interleave
        def write(offset: int, data: bytes):
            nonlocal received
            f.seek(offset)
            f.write(data)
            received += len(data)
            progress_callback(received, size)

        async def wait(seconds: float):
            # Poll the callback so a cancel isn't stuck behind the penalty
            deadline = loop.time() + seconds
            while (left := deadline - loop.time()) > 0:
                progress_callback(received, size)
                await asyncio.sleep(min(left, 0.5))

        tasks = [
            asyncio.create_task(_fetch_range(sender, location, offset, length,
                                             chunk, write, wait))
            for sender, (offset, length) in zip(senders, ranges)
        ]
        try:
            await asyncio.gather(*tasks)
        except BaseException:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            await pool.discard(dc_id)
            raise

    if received != size:
        raise IOError(f"Получено {received} байт из {size}")


async def _fetch_range(sender: MTProtoSender, location, offset: int, length: int,
                       chunk: int, write, wait):
    pos, end = offset, offset + length
    retries = 0
    while pos < end:
        request = functions.upload.GetFileRequest(location, offset=pos, limit=chunk)
        try:
            result = await asyncio.wait_for(sender.send(request), REQUEST_TIMEOUT)
        except FLOOD_ERRORS as e:
            if e.seconds > MAX_FLOOD_SLEEP:
                raise
            logger.info(f"{type(e).__name__}: waiting {e.seconds}s at offset {pos}")
            await wait(e.seconds)
            continue
        except errors.FileReferenceExpiredError as e:
            raise ParallelUnsupported("file reference expired") from e
        except RETRY_ERRORS as e:
            retries += 1
            if retries > MAX_RETRIES:
                raise
            logger.warning(f"Retry {retries} at offset {pos}: {type(e).__name__} {e}")
            await wait(retries)
            continue

        if isinstance(result, FileCdnRedirect):
            raise ParallelUnsupported("CDN redirect")
        data = result.bytes
        if not data:
            break
        write(pos, data)
        pos += len(data)
        retries = 0
        if len(data) < chunk:
            break  # last chunk of the file
