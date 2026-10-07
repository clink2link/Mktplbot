from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from utils.force_sub import get_force_sub_channel

async def join_kb(bot_username: str | None = None, user_id: int | None = None, lang: str = "id"):
    rows = []
    channel = await get_force_sub_channel()
    if channel:
        name = channel.get("name") or ("Channel Update" if lang == "id" else "Update Channel" if lang == "en" else "更新频道")
        url = channel.get("url") or ""
        if url:
            rows.append([InlineKeyboardButton(text=f"📢 {name}", url=url)])
    rows.append([InlineKeyboardButton(
        text=("✅ Saya Sudah Join" if lang == "id" else "✅ I Joined" if lang == "en" else "✅ 我已加入"),
        callback_data="check_sub"
    )])
    return InlineKeyboardMarkup(inline_keyboard=rows)
