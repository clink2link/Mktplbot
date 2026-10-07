import logging
from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError

CHANNELS = [
    {
        "id": -1004441808999,
        "name": "Channel Update",
        "url": "https://t.me/+JUGpWnRLT8ljNGZk",
    },
    {
        "id": -1003971846572,
        "name": "Saluran Notification",
        "url": "https://t.me/noticsaluran",
    },
]

async def get_missing_channels(bot: Bot, user_id: int) -> list[dict]:
    missing = []
    for channel in CHANNELS:
        try:
            member = await bot.get_chat_member(channel["id"], user_id)
            if member.status not in ("member", "administrator", "creator"):
                missing.append(channel)
        except (TelegramBadRequest, TelegramForbiddenError) as exc:
            logging.warning("ForceSub check failed channel=%s user=%s: %s", channel["id"], user_id, exc)
            missing.append(channel)
        except Exception:
            logging.exception("ForceSub unexpected error channel=%s user=%s", channel["id"], user_id)
            missing.append(channel)
    return missing

async def check_force_sub(bot: Bot, user_id: int) -> bool:
    return not await get_missing_channels(bot, user_id)
