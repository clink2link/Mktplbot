import asyncio
import json
from aiogram import Router, F
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, InputMediaPhoto, InputMediaVideo, InputMediaDocument, InputMediaAudio

from database import get_pool
from utils.media_sender import deliver_one, safe_copy_from_storage, media_message_id

router = Router()

PAGE_SIZE = 10
CHANGE_PAGE_COOLDOWN = 3.0
_last_page = {}


def _caption(code: str, index: int, total: int, media: dict) -> str:
    watermark = media.get("caption") or media.get("watermark")
    if watermark:
        return str(watermark)
    return (
        f"🔑 {code}-M{index:03d}\n"
        f"🤖 @Telecodrobot\n"
        f"📦 Media {index}/{total}"
    )


def _page_kb(code: str, page_no: int, pages: int):
    nav = []
    if page_no > 1:
        nav.append(("⬅️ Prev", f"page:{code}:{page_no-1}"))
    nav.append((f"📄 {page_no}/{pages}", f"page:{code}:{page_no}"))
    if page_no < pages:
        nav.append(("Next ➡️", f"page:{code}:{page_no+1}"))

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=t, callback_data=d) for t, d in nav],
            [
                InlineKeyboardButton(text="👍 Like", callback_data=f"like:{code}"),
                InlineKeyboardButton(text="👎 No Like", callback_data=f"dislike:{code}"),
            ],
            [
                InlineKeyboardButton(text="🛍 Marketplace", callback_data="marketplace"),
                InlineKeyboardButton(text="🔎 Cari Code", callback_data="search_code"),
            ],
        ]
    )


async def _load(code: str):
    pool = await get_pool()
    row = await pool.fetchrow(
        """
        SELECT *
        FROM files
        WHERE lower(code)=lower($1)
        LIMIT 1
        """,
        code,
    )
    if not row:
        return None, []

    data = dict(row)
    raw = data.get("media") or data.get("medias") or []
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except Exception:
            raw = []
    if not isinstance(raw, list):
        raw = []

    return data, [dict(x) if not isinstance(x, dict) else x for x in raw]


def _album_items(items, code, offset, total):
    result = []
    for i, m in enumerate(items, start=offset + 1):
        fid = m.get("file_id")
        typ = str(m.get("file_type") or m.get("type") or "").lower()
        if not fid:
            return None
        cap = _caption(code, i, total, m)
        if typ in {"photo", "image"}:
            result.append(InputMediaPhoto(media=fid, caption=cap))
        elif typ == "video":
            result.append(InputMediaVideo(media=fid, caption=cap))
        else:
            return None
    return result


async def send_page(message, code: str, page_no: int = 1, user_id: int | None = None):
    data, medias = await _load(code)
    if not data:
        await message.answer("❌ Code tidak ditemukan.")
        return False

    from utils.media_access import can_open_media
    # Callback buttons belong to a bot message, so message.from_user is the BOT.
    # Always use the Telegram user who pressed the button for access checks.
    opener_id = int(user_id) if user_id else int(message.from_user.id)
    data["media_count"] = len(medias)
    allowed, reason = await can_open_media(opener_id, data)
    if not allowed:
        if reason == "payment_required":
            from handlers.pay import paid_unlock_keyboard
            price = int(data.get("price") or 0)
            await message.answer(
                f"🔒 <b>CODE MEDIA BERBAYAR</b>\n\n📦 Total Media: <b>{int(data.get('media_count') or 0)}</b>\n💰 Harga: <b>Rp{price:,}</b>\n\nSilakan bayar untuk membuka media.",
                parse_mode="HTML", reply_markup=paid_unlock_keyboard(str(data.get("code")), "id")
            )
        else:
            await message.answer("⭐ <b>Poin tidak cukup untuk membuka code ini.</b>", parse_mode="HTML")
        return False

    if reason != "owner":
        try:
            from utils.media_access import reward_owner_for_open
            await reward_owner_for_open(opener_id, data)
        except Exception:
            pass

    total = len(medias)
    if total == 0:
        await message.answer("❌ Tidak ada media pada Code ini.")
        return False

    pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    page_no = max(1, min(int(page_no), pages))
    start = (page_no - 1) * PAGE_SIZE
    items = medias[start:start + PAGE_SIZE]

    # Preferred: one Telegram album/bubble for photo/video pages.
    album = _album_items(items, code, start, total)
    if album:
        try:
            await message.bot.send_media_group(
                chat_id=message.chat.id,
                media=album,
            )
            await message.answer(
                f"📄 <b>Page {page_no}/{pages}</b> • {len(items)} media",
                parse_mode="HTML",
                reply_markup=_page_kb(code, page_no, pages),
            )
            return True
        except Exception:
            pass

    # Durable fallback: copy each stored/source message, still sequential.
    sent = 0
    for idx, m in enumerate(items, start=start + 1):
        result = await deliver_one(
            message.bot,
            message.chat.id,
            m,
            caption=_caption(code, idx, total, m),
        )
        if result:
            sent += 1
        await asyncio.sleep(0.35)

    await message.answer(
        f"📄 <b>Page {page_no}/{pages}</b> • {sent}/{len(items)} media",
        parse_mode="HTML",
        reply_markup=_page_kb(code, page_no, pages),
    )
    return sent > 0


@router.callback_query(F.data.startswith("page:"))
async def page_handler(call: CallbackQuery):
    parts = call.data.split(":", 2)
    if len(parts) != 3:
        await call.answer("Invalid page.", show_alert=True)
        return

    code, page_no = parts[1], int(parts[2])
    key = (call.from_user.id, code)
    now = asyncio.get_running_loop().time()
    if now - _last_page.get(key, 0) < CHANGE_PAGE_COOLDOWN:
        await call.answer("⏳ Tunggu sebentar...", show_alert=True)
        return

    _last_page[key] = now
    await call.answer("⏳ Membuka media...")
    # Do not replace the original menu bubble with a permanent loading message.
    # Use a short-lived status message instead, then remove it after delivery.
    try:
        pool = await get_pool()
        lang = (await pool.fetchval(
            "SELECT language FROM users WHERE user_id=$1", call.from_user.id
        ) or "id")
    except Exception:
        lang = "id"
    loading = {
        "id": "🔎 <b>Mencari Media Code...</b>\n\n⏳ Mohon tunggu sebentar...",
        "en": "🔎 <b>Searching Code Media...</b>\n\n⏳ Please wait a moment...",
        "zh": "🔎 <b>正在查找 Code 媒体...</b>\n\n⏳ 请稍候...",
    }.get(lang, "🔎 <b>Mencari Media Code...</b>\n\n⏳ Mohon tunggu sebentar...")
    status = None
    try:
        status = await call.message.answer(loading, parse_mode="HTML")
        await send_page(call.message, code, page_no, user_id=call.from_user.id)
    except Exception:
        import logging
        logging.getLogger(__name__).exception("PAGE OPEN ERROR | code=%s | user=%s", code, call.from_user.id)
        if status:
            try:
                await status.edit_text("❌ Gagal membuka media. Silakan coba lagi.")
            except Exception:
                pass
    finally:
        if status:
            try:
                await status.delete()
            except Exception:
                pass
