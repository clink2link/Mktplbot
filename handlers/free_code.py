from aiogram import Router, F
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from database import get_pool
from utils.points import get_points, fmt_points

router = Router()


@router.callback_query(F.data == "free_codes")
async def free_codes(call: CallbackQuery):
    pool = await get_pool()
    lang = (await pool.fetchval(
        "SELECT language FROM users WHERE user_id=$1", call.from_user.id
    )) or "id"

    rows = await pool.fetch(
        """
        SELECT
            f.code,
            COALESCE(f.title,f.code) AS title,
            COALESCE(f.media_count,0) AS media_count,
            COALESCE(f.is_paid,FALSE) AS is_paid
        FROM files f
        WHERE COALESCE(f.is_paid,FALSE)=FALSE
        ORDER BY f.created_at DESC
        LIMIT 30
        """
    )

    if lang == "en":
        text = (
            "⭐ <b>FREE CODE • POINTS</b>\n"
            "━━━━━━━━━━━━━━━━━━\n\n"
            "Free code requires points based on media count. Sharing is optional; the owner earns +1 point when another unique user actually opens the code.\n\n"
        )
    else:
        text = (
            "⭐ <b>FREE CODE • POINTS</b>\n"
            "━━━━━━━━━━━━━━━━━━\n\n"
            "Free code membutuhkan poin sesuai jumlah media. Share hanya untuk mendapatkan +1 poin saat user unik benar-benar membuka code.\n\n"
        )

    buttons = []
    for row in rows:
        points = await get_points(pool, call.from_user.id)
        required = int(row["media_count"] or 0)
        status = f"⭐ {fmt_points(points)}/{required}"
        label = str(row["title"])[:22]
        buttons.append([InlineKeyboardButton(text=f"📦 {label} • {status}", callback_data=f"open_code:{row['code']}")])

    if not buttons:
        text += "📭 Belum ada code published."

    buttons += [
        [InlineKeyboardButton(text="🛍 Marketplace", callback_data="marketplace")],
        [InlineKeyboardButton(text="🏠 Home", callback_data="home")]
    ]
    await call.message.edit_text(
        text, parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )
    await call.answer()
