import json
import logging
import re
from html import escape

from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, InputMediaPhoto

from database import get_pool

router = Router()
logger = logging.getLogger(__name__)
REVIEW_CODE_REGEX = re.compile(r"(?<![A-Za-z0-9])PasteleReview_[A-Za-z0-9]{14}(?![A-Za-z0-9])", re.IGNORECASE)

def normalize(code: str) -> str:
    return re.sub(r"\s+", "", str(code or "")).strip()


async def send_standalone_review(message: Message, review_code: str):
    """Send a standalone /getreview review. Creation never auto-posts anywhere."""
    code = normalize(review_code)
    pool = await get_pool()
    try:
        row = await pool.fetchrow(
            "SELECT review_code, owner_id, photo_ids FROM review_codes WHERE lower(review_code)=lower($1) LIMIT 1",
            code,
        )
    except Exception:
        row = None
    if not row:
        return False

    raw = row["photo_ids"] or []
    try:
        photos = json.loads(raw) if isinstance(raw, str) else list(raw)
    except Exception:
        photos = []
    photos = [str(x) for x in (photos or []) if x][:10]
    if not photos:
        await message.answer("❌ Review untuk code ini belum tersedia.")
        return True

    group = []
    for i, fid in enumerate(photos):
        group.append(
            InputMediaPhoto(
                media=fid,
                caption=(
                    "👀 <b>CODE REVIEW</b>\n"
                    "━━━━━━━━━━━━━━\n"
                    f"🎟️ Code: <code>{escape(code)}</code>\n"
                    f"📸 Total foto: <b>{len(photos)}</b>\n\n"
                    "📌 Review gratis."
                ) if i == 0 else None,
                parse_mode="HTML" if i == 0 else None,
            )
        )
    try:
        await message.bot.send_media_group(chat_id=message.chat.id, media=group)
        await message.answer(
            "✅ <b>Code Review berhasil dibuka.</b>\n"
            f"📸 {len(photos)} foto review."
        )
    except Exception:
        logger.exception("STANDALONE REVIEW SEND ERROR | code=%s", code)
        await message.answer("⚠️ Review gagal dikirim.")
    return True

async def send_review(message: Message, review_code: str):
    code = normalize(review_code)
    pool = await get_pool()
    row = await pool.fetchrow(
        "SELECT code, review_code, title, media_count, is_paid, price, review_photos FROM files WHERE lower(review_code)=lower($1) LIMIT 1",
        code,
    )
    if not row:
        return await message.answer("❌ Code review tidak ditemukan.")

    raw = row["review_photos"] or "[]"
    try:
        photos = json.loads(raw) if isinstance(raw, str) else raw
    except Exception:
        photos = []
    photos = [str(x) for x in (photos or []) if x]
    if not photos:
        return await message.answer("❌ Review untuk code ini belum tersedia.")

    title = escape(str(row["title"] or "Untitled"))
    media_code = escape(str(row["code"] or ""))
    price = int(row["price"] or 0)
    media_status = "PAID" if bool(row["is_paid"]) else "FREE"
    me = await message.bot.get_me()
    bot_username = escape(me.username or "Unknown")

    caption = (
        "👀 <b>CODE REVIEW</b>\n"
        "━━━━━━━━━━━━━━\n"
        f"📝 Judul: <b>{title}</b>\n"
        f"👀 Code review: <code>{escape(code)}</code>\n"
        f"📦 Code media: <code>{media_code}</code>\n"
        f"📦 Total media: <b>{int(row['media_count'] or 0)}</b>\n"
        f"💎 Media: <b>{media_status}</b>\n"
        f"🤖 Bot: @{bot_username}\n\n"
        "🔓 Review gratis. Untuk membuka media, gunakan Code media."
    )

    group = []
    for i, fid in enumerate(photos[:10]):
        if i == 0:
            group.append(InputMediaPhoto(media=fid, caption=caption, parse_mode="HTML"))
        else:
            group.append(InputMediaPhoto(media=fid))
    try:
        await message.bot.send_media_group(chat_id=message.chat.id, media=group)
        await message.answer(
            "👀 <b>Review gratis berhasil dibuka.</b>\n\n"
            f"📦 Code media: <code>{media_code}</code>\n"
            f"💎 Media: <b>{media_status}</b>\n"
            + (f"💰 Harga: <b>Rp{price:,}</b>\n" if price else "")
            + "\nMedia asli tetap mengikuti aturan pembayaran Code media.",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="📦 Buka Code Media", callback_data=f"open_code:{row['code']}")]
            ]),
        )
    except Exception:
        logger.exception("REVIEW CODE SEND ERROR | code=%s", code)
        await message.answer("⚠️ Review gagal dikirim. Silakan coba lagi.")

@router.message(F.text.regexp(REVIEW_CODE_REGEX))
async def review_code_message(message: Message):
    match = REVIEW_CODE_REGEX.search(message.text or "")
    if not match:
        return
    code = normalize(match.group())
    try:
        await message.delete()
    except Exception:
        pass
    if await send_standalone_review(message, code):
        return
    await send_review(message, code)

@router.callback_query(F.data.startswith("reviewcode:"))
async def review_code_callback(call: CallbackQuery):
    await call.answer()
    code = normalize(call.data.split(":", 1)[1])
    try:
        await call.bot.send_message(call.from_user.id, f"<code>{escape(code)}</code>", parse_mode="HTML")
    except Exception:
        pass
    # Reuse a lightweight target message when possible; channel callbacks
    # should not publish the preview back into the channel.
    try:
        row = await (await get_pool()).fetchrow(
            "SELECT review_code, title, media_count, is_paid, price, review_photos, code FROM files WHERE lower(review_code)=lower($1) LIMIT 1", code
        )
        if row:
            raw = row["review_photos"] or "[]"
            photos = json.loads(raw) if isinstance(raw, str) else (raw or [])
            group=[]
            for i,fid in enumerate(photos[:10]):
                group.append(InputMediaPhoto(media=fid, caption=(f"👀 <b>CODE REVIEW</b>\n\n📝 {escape(str(row['title'] or 'Untitled'))}\n👀 <code>{escape(code)}</code>\n📦 Code media: <code>{escape(str(row['code']))}</code>\n📦 Total media: <b>{int(row['media_count'] or 0)}</b>\n💎 Media: <b>{'PAID' if row['is_paid'] else 'FREE'}</b>\n\n🔓 Review gratis.") if i==0 else None, parse_mode="HTML" if i==0 else None))
            await call.bot.send_media_group(call.from_user.id, media=group)
            await call.bot.send_message(call.from_user.id, f"📦 Code media: <code>{escape(str(row['code']))}</code>", parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="📦 Buka Code Media", url=f"https://t.me/{(await call.bot.get_me()).username}?start={row['code']}")]]))
    except Exception:
        logger.exception("REVIEW CALLBACK SEND ERROR | code=%s", code)
