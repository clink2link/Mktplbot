from aiogram import Router, F
from aiogram.types import CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder

router = Router()


@router.callback_query(F.data == "code")
async def code_menu(call: CallbackQuery):

    kb = InlineKeyboardBuilder()

    kb.button(
        text="🏆 Top 10 Code",
        callback_data="top_code"
    )

    kb.button(
        text="🆕 New Code",
        callback_data="new_code"
    )

    kb.button(
        text="📂 Category Code",
        callback_data="category_code"
    )

    kb.button(
        text="💰 Harga Code",
        callback_data="price_code"
    )

    kb.button(
        text="🔍 Cari Code",
        callback_data="search_code"
    )

    kb.button(
        text="⬅️ Kembali",
        callback_data="home"
    )

    kb.adjust(1)

    await call.message.edit_text(
        "<b>📦 MENU CODE</b>\n\n"
        "Silakan pilih menu yang tersedia.",
        parse_mode="HTML",
        reply_markup=kb.as_markup()
    )

    await call.answer()
