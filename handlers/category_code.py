from aiogram import Router, F
from aiogram.types import CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder

from database import get_pool


router = Router()


@router.callback_query(F.data == "category_code")
async def category_menu(call: CallbackQuery):

    pool = await get_pool()

    rows = await pool.fetch(
        """
        SELECT
            category,
            COUNT(*) as total
        FROM files
        GROUP BY category
        ORDER BY total DESC
        """
    )

    if not rows:

        await call.message.edit_text(
            "❌ Belum ada category code.",
            reply_markup=back_keyboard()
        )

        return await call.answer()


    kb = InlineKeyboardBuilder()


    for row in rows:

        kb.button(
            text=f"📂 {row['category']} ({row['total']})",
            callback_data=f"cat:{row['category']}"
        )


    kb.button(
        text="⬅️ Kembali",
        callback_data="marketplace"
    )


    kb.adjust(1)


    await call.message.edit_text(
        "<b>📂 CATEGORY CODE</b>\n\n"
        "Pilih kategori code yang ingin dilihat:",
        parse_mode="HTML",
        reply_markup=kb.as_markup()
    )

    await call.answer()



@router.callback_query(F.data.startswith("cat:"))
async def category_detail(call: CallbackQuery):

    category = call.data.split(":",1)[1]

    pool = await get_pool()


    rows = await pool.fetch(
        """
        SELECT
            code,
            title,
            view_count
        FROM files
        WHERE category=$1
        ORDER BY view_count DESC
        LIMIT 10
        """,
        category
    )


    if not rows:

        return await call.answer(
            "Tidak ada code",
            show_alert=True
        )


    text = (
        f"📂 <b>CATEGORY : {category}</b>\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
    )


    for i,row in enumerate(rows,1):

        text += (
            f"{i}. 📌 <b>{row['title']}</b>\n"
            f"🔑 <code>{row['code']}</code>\n"
            f"👁 {row['view_count']}x\n\n"
        )


    kb = InlineKeyboardBuilder()

    kb.button(
        text="⬅️ Kembali Category",
        callback_data="category_code"
    )

    kb.button(
        text="🏠 Home",
        callback_data="home"
    )

    kb.adjust(1)


    await call.message.edit_text(
        text,
        parse_mode="HTML",
        reply_markup=kb.as_markup()
    )


    await call.answer()



def back_keyboard():

    kb = InlineKeyboardBuilder()

    kb.button(
        text="⬅️ Kembali",
        callback_data="code"
    )

    return kb.as_markup()
