from aiogram import Router, F
from aiogram.types import CallbackQuery, Message
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.utils.keyboard import InlineKeyboardBuilder

from database import get_pool


router = Router()


class SearchCodeState(StatesGroup):
    waiting = State()



@router.callback_query(F.data == "search_code")
async def search_menu(call: CallbackQuery, state: FSMContext):

    await state.set_state(
        SearchCodeState.waiting
    )

    kb = InlineKeyboardBuilder()

    kb.button(
        text="❌ Batal",
        callback_data="code"
    )

    kb.adjust(1)

    await call.message.edit_text(
        "<b>🔍 CARI CODE</b>\n\n"
        "Kirim kode atau nama file yang ingin dicari.\n\n"
        "Contoh:\n"
        "<code>ABC123</code>",
        parse_mode="HTML",
        reply_markup=kb.as_markup()
    )

    await call.answer()



@router.message(SearchCodeState.waiting)
async def search_result(message: Message, state: FSMContext):

    keyword = message.text.strip()

    pool = await get_pool()


    rows = await pool.fetch(
        """
        SELECT
            code,
            title,
            price,
            view_count
        FROM files
        WHERE
            code ILIKE $1
            OR title ILIKE $1
        ORDER BY
            view_count DESC
        LIMIT 10
        """,
        f"%{keyword}%"
    )


    if not rows:

        await message.answer(
            "❌ Code tidak ditemukan."
        )

        return


    text = (
        "🔍 <b>HASIL PENCARIAN</b>\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
    )


    for i,row in enumerate(rows,1):

        harga = (
            "Gratis"
            if row["price"] == 0
            else f"Rp{row['price']:,}"
        )

        text += (
            f"{i}. 📌 <b>{row['title']}</b>\n"
            f"🔑 <code>{row['code']}</code>\n"
            f"💰 {harga}\n"
            f"👁 {row['view_count']}x\n\n"
        )
        kb.button(
            text=f"📂 Buka {row['code']}",
            callback_data=f"open_code:{row['code']}"
        )



    kb = InlineKeyboardBuilder()

    kb.button(
        text="↪️ kembali",
        callback_data="code"
    )

    kb.button(
        text="🏠 Home",
        callback_data="home"
    )

    kb.adjust(1)


    await message.answer(
        text,
        parse_mode="HTML",
        reply_markup=kb.as_markup()
    )

    await state.clear()
