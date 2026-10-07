"""
Canonical media delivery helpers for Pastele.

New media delivery uses Telegram file_id as the canonical storage.
Legacy message-id fallbacks are retained only for old database rows.

The helper is deliberately sequential and RetryAfter-aware.
"""
import asyncio
from typing import Any, Optional

from aiogram.exceptions import TelegramRetryAfter, TelegramBadRequest, TelegramForbiddenError


def _storage_chat_id() -> Optional[int]:
    try:
        from config import STORAGE_CHANNEL_ID
        return int(STORAGE_CHANNEL_ID)
    except Exception:
        try:
            from config import CHANNEL_DB
            return int(CHANNEL_DB)
        except Exception:
            return None


async def _retry_sleep(exc: TelegramRetryAfter) -> None:
    await asyncio.sleep(max(1.0, float(getattr(exc, "retry_after", 1)) + 0.5))


async def safe_copy_from_storage(bot, chat_id: int, message_id: int, **kwargs):
    storage = _storage_chat_id()
    if not storage or not message_id:
        return None

    for attempt in range(4):
        try:
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


async def deliver_one(bot, chat_id: int, media: dict, caption: Optional[str] = None):
    """Deliver media using Telegram file_id as the canonical storage.

    Source/storage message IDs are retained only for backwards compatibility
    with old rows. New uploads always use file_id first.
    """
    result = await safe_send_file_id(bot, chat_id, media, caption=caption)
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
