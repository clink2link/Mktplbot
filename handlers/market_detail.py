from aiogram import Router, F
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton
)
from database import fetchrow, fetchval, execute, get_pool
from utils.share_unlock import get_share_status, ensure_share_progress, share_url, gate_message
router = Router()
# ============================================================
# SHARE URL
# ============================================================
def share_url_for_code(me, code, title="", sharer_id=0):
    return share_url(
        me.username,
        code,
        sharer_id,
        title,
    )

# ============================================================
# MARKETPLACE DETAIL
# ============================================================
@router.callback_query(F.data.startswith("market:"))
async def market_detail(call: CallbackQuery):
    await call.answer()
    code=call.data.split(":",1)[1].strip()
    try:
        from handlers.getfile import process_code
        return await process_code(call.message,code,user_id=call.from_user.id)
    except Exception:
        logger.exception("MARKET -> GETFILE ERROR | code=%s",code)
        return await call.message.answer("❌ Gagal membuka code.")
# ============================================================
# FREE OPEN
# ============================================================
@router.callback_query(F.data.startswith("freeopen:"))
async def free_open(call: CallbackQuery):
    await call.answer()
    code=call.data.split(":",1)[1].strip()
    from handlers.getfile import process_code
    return await process_code(call.message,code,user_id=call.from_user.id)
# ============================================================
# FREE SHARE / CHECK PROGRESS
# ============================================================
@router.callback_query(F.data.startswith(("freeshare:", "sharecheck:")))
async def free_share(call: CallbackQuery):
    code = call.data.split(":", 1)[1].strip()
    pool = await get_pool()

    file = await fetchrow(
        """
        SELECT code,title,media_count,is_paid,free_unlock_enabled
        FROM files WHERE code=$1 LIMIT 1
        """,
        code,
    )
    if not file:
        return await call.answer("❌ Code tidak ditemukan.", show_alert=True)

    if not file["free_unlock_enabled"]:
        return await call.answer("❌ Fitur unlock tidak tersedia.", show_alert=True)

    progress, target, completed = await get_share_status(
        pool, code, call.from_user.id,
        is_paid=bool(file["is_paid"]),
        media_count=int(file["media_count"] or 0),
    )
    await ensure_share_progress(
        pool, code, call.from_user.id,
        is_paid=bool(file["is_paid"]),
        media_count=int(file["media_count"] or 0),
    )

    if completed or progress >= target:
        from handlers.open_menu import open_keyboard
        lang = await get_user_language(call.from_user.id)
        return await call.message.edit_text(
            "🎉 <b>CODE TERBUKA</b>\n\n"
            f"🔑 <code>{code}</code>\n"
            f"📈 Progress: <b>{target}/{target}</b>\n\n"
            "File sudah terbuka. Pilih metode pengiriman.",
            parse_mode="HTML",
            reply_markup=open_keyboard(code, lang),
        )

    me = await call.bot.get_me()
    url = share_url_for_code(
        me, code, file["title"] or code, call.from_user.id
    )
    label = "PAID" if file["is_paid"] else "FREE"
    await call.message.edit_text(
        f"🔐 <b>UNLOCK {label}</b>\n\n"
        "Bagikan code ini. Progress bertambah hanya saat "
        "member baru benar-benar membuka bot melalui link share.\n\n"
        f"📈 Progress: <b>{progress}/{target}</b>\n"
        f"👥 Target: <b>{target} member baru</b>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=f"📤 Bagikan Code • {progress}/{target}", url=url)],
            [InlineKeyboardButton(text="🔄 Cek Progress", callback_data=f"sharecheck:{code}")],
            [InlineKeyboardButton(text="⬅️ Kembali", callback_data=f"market:{code}")],
        ]),
    )
    await call.answer("🔄 Progress diperbarui.")
