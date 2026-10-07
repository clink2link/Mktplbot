"""
Canonical media delivery helpers for Pastele.

New media delivery uses Telegram file_id as the primary/fast path.
Media smaller than 20 MiB also has a B2 backup and is recovered from B2
when the Telegram file_id is no longer usable. Legacy message-id fallbacks
are retained only for old database rows.

The helper is deliberately sequential and RetryAfter-aware.
"""
import asyncio
import os
import tempfile
from typing import Any, Optional

from aiogram.exceptions import TelegramRetryAfter, TelegramBadRequest, TelegramForbiddenError
from aiogram.types import FSInputFile

async def _safety_setting(key: str, default):
    try:
        from database import get_pool
        pool = await get_pool()
        value = await pool.fetchval("SELECT value FROM settings WHERE key=$1", key)
        return value if value is not None else default
    except Exception:
        return default

async def _safety_delay(kind: str, default: float = 0.0) -> float:
    enabled = str(await _safety_setting("telegram_safety_enabled", "on")).lower() in {"1", "true", "on", "yes"}
    if not enabled:
        return 0.0
    try:
        return max(0.0, float(await _safety_setting(kind, str(default))))
    except Exception:
        return default


def _storage_chat_id() -> Optional[int]:
    # Storage Channel has been removed from the active Pastele architecture.
    # New media is delivered from Telegram file_id / B2 only.
    return None


async def _retry_sleep(exc: TelegramRetryAfter) -> None:
    await asyncio.sleep(max(1.0, float(getattr(exc, "retry_after", 1)) + 0.5))


async def safe_copy_from_storage(bot, chat_id: int, message_id: int, **kwargs):
    storage = _storage_chat_id()
    if not storage or not message_id:
        return None

    for attempt in range(4):
        try:
            delay = await _safety_delay("telegram_storage_delay", 1.0)
            if delay:
                await asyncio.sleep(delay)
            return await bot.copy_message(
                chat_id=chat_id,
                from_chat_id=storage,
                message_id=int(message_id),
                **kwargs,
            )
        except TelegramRetryAfter as e:
            await _retry_sleep(e)
        except (TelegramBadRequest, TelegramForbiddenError):
            return None
        except Exception:
            if attempt >= 3:
                return None
            await asyncio.sleep(1.5)
    return None


async def safe_copy_from_source(bot, chat_id: int, source_chat_id: int, message_id: int, **kwargs):
    if not source_chat_id or not message_id:
        return None

    for attempt in range(4):
        try:
            return await bot.copy_message(
                chat_id=chat_id,
                from_chat_id=int(source_chat_id),
                message_id=int(message_id),
                **kwargs,
            )
        except TelegramRetryAfter as e:
            await _retry_sleep(e)
        except (TelegramBadRequest, TelegramForbiddenError):
            return None
        except Exception:
            if attempt >= 3:
                return None
            await asyncio.sleep(1.5)
    return None


async def safe_send_file_id(bot, chat_id: int, media: dict, caption: Optional[str] = None):
    """
    file_id fallback. Used only if copy_message cannot be used.
    """
    file_id = media.get("file_id")
    if not file_id:
        return None

    file_type = str(media.get("file_type") or media.get("type") or "document").lower()
    kwargs = {"chat_id": chat_id, "caption": caption}

    for attempt in range(4):
        try:
            delay = await _safety_delay("telegram_user_send_delay", 2.0)
            if delay:
                await asyncio.sleep(delay)
            if file_type in {"photo", "image"}:
                return await bot.send_photo(photo=file_id, **kwargs)
            if file_type in {"video"}:
                return await bot.send_video(video=file_id, **kwargs)
            if file_type in {"audio"}:
                return await bot.send_audio(audio=file_id, **kwargs)
            if file_type in {"voice"}:
                return await bot.send_voice(voice=file_id, **kwargs)
            if file_type in {"animation", "gif"}:
                return await bot.send_animation(animation=file_id, **kwargs)
            return await bot.send_document(document=file_id, **kwargs)
        except TelegramRetryAfter as e:
            await _retry_sleep(e)
        except (TelegramBadRequest, TelegramForbiddenError):
            return None
        except Exception:
            if attempt >= 3:
                return None
            await asyncio.sleep(1.5)
    return None


def media_message_id(media: dict) -> Optional[int]:
    for key in (
        "storage_message_id",
        "channel_message_id",
        "storage_id",
        "message_id",
    ):
        value = media.get(key)
        if value:
            try:
                return int(value)
            except Exception:
                pass
    return None



async def _safe_send_b2(bot, chat_id: int, media: dict, caption: Optional[str] = None):
    """Send a bot-independent B2 backup after Telegram file_id fails."""
    account_id = media.get("b2_account_id")
    object_key = media.get("b2_object_key")
    if not account_id or not object_key:
        return None

    tmp_path = None
    try:
        from utils.b2_storage import download_file_from_b2

        name = str(media.get("file_name") or "media")
        suffix = ""
        if "." in name:
            suffix = "." + name.rsplit(".", 1)[-1][:12]

        fd, tmp_path = tempfile.mkstemp(
            prefix="pastele_b2_send_",
            suffix=suffix,
        )
        os.close(fd)

        ok = await download_file_from_b2(
            int(account_id),
            str(object_key),
            tmp_path,
        )
        if not ok:
            return None

        file_type = str(
            media.get("file_type") or media.get("type") or "document"
        ).lower()

        for attempt in range(4):
            try:
                delay = await _safety_delay("telegram_user_send_delay", 2.0)
                if delay:
                    await asyncio.sleep(delay)

                inp = FSInputFile(tmp_path, filename=name)
                kwargs = {"chat_id": chat_id, "caption": caption}

                if file_type in {"photo", "image"}:
                    return await bot.send_photo(photo=inp, **kwargs)
                if file_type == "video":
                    return await bot.send_video(video=inp, **kwargs)
                if file_type == "audio":
                    return await bot.send_audio(audio=inp, **kwargs)
                if file_type == "voice":
                    return await bot.send_voice(voice=inp, **kwargs)
                if file_type in {"animation", "gif"}:
                    return await bot.send_animation(animation=inp, **kwargs)
                return await bot.send_document(document=inp, **kwargs)

            except TelegramRetryAfter as exc:
                await _retry_sleep(exc)
            except (TelegramBadRequest, TelegramForbiddenError):
                return None
            except Exception:
                if attempt >= 3:
                    return None
                await asyncio.sleep(1.5)

        return None
    except Exception:
        logger = __import__("logging").getLogger(__name__)
        logger.exception("B2 FALLBACK SEND FAILED")
        return None
    finally:
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except Exception:
                pass


async def deliver_one(bot, chat_id: int, media: dict, caption: Optional[str] = None):
    """Deliver media using Telegram file_id as the canonical storage.

    Source/storage message IDs are retained only for backwards compatibility
    with old rows. New uploads always use file_id first.
    """
    result = await safe_send_file_id(bot, chat_id, media, caption=caption)
    if result:
        return result

    # Bot-independent B2 backup. This is the recovery path when the
    # original Telegram bot/file_id is no longer usable.
    result = await _safe_send_b2(bot, chat_id, media, caption=caption)
    if result:
        return result

    # Legacy fallback for old database rows created before file_id-only storage.
    source_chat = media.get("source_chat_id")
    mid = media_message_id(media)
    if source_chat and mid:
        return await safe_copy_from_source(bot, chat_id, int(source_chat), mid, caption=caption)
    if mid:
        return await safe_copy_from_storage(bot, chat_id, mid, caption=caption)
    return None
