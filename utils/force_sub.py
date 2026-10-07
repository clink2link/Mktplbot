import logging
from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError

from database import get_pool

DEFAULT_CHANNEL_NAME = "Force Sub"


async def _setting(key: str, default=None):
    try:
        pool = await get_pool()
        value = await pool.fetchval(
            "SELECT value FROM settings WHERE key=$1",
            key,
        )
        return value if value is not None else default
    except Exception:
        return default


async def get_force_sub_channel() -> dict | None:
    """Return the single Force Sub channel configured from Admin Panel."""
    enabled = str(await _setting("force_sub_enabled", "on")).lower() in {
        "1", "true", "on", "yes"
    }
    if not enabled:
        return None

    raw_id = str(await _setting("force_sub_channel_id", "") or "").strip()
    url = str(await _setting("force_sub_channel_url", "") or "").strip()
    name = str(await _setting("force_sub_channel_name", DEFAULT_CHANNEL_NAME) or DEFAULT_CHANNEL_NAME).strip()

    if not raw_id:
        # No channel configured yet: don't block users.
        return None

    try:
        channel_id = int(raw_id)
    except (TypeError, ValueError):
        channel_id = raw_id

    return {
        "id": channel_id,
        "name": name,
        "url": url,
    }


async def get_missing_channels(bot: Bot, user_id: int) -> list[dict]:
    channel = await get_force_sub_channel()
    if not channel:
        return []

    try:
        member = await bot.get_chat_member(channel["id"], user_id)
        if member.status not in ("member", "administrator", "creator"):
            return [channel]
    except (TelegramBadRequest, TelegramForbiddenError) as exc:
        logging.warning(
            "ForceSub check failed channel=%s user=%s: %s",
            channel["id"],
            user_id,
            exc,
        )
        return [channel]
    except Exception:
        logging.exception(
            "ForceSub unexpected error channel=%s user=%s",
            channel["id"],
            user_id,
        )
        return [channel]

    return []


async def check_force_sub(bot: Bot, user_id: int) -> bool:
    return not await get_missing_channels(bot, user_id)
