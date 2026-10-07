from aiogram import Router, F
from aiogram.types import CallbackQuery, Message
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State

from database import get_pool


router = Router()


class EditPriceState(StatesGroup):

    waiting_price = State()



# =========================
# MULAI EDIT
# =========================

@router.callback_query(F.data.startswith("edit_price:"))
async def edit_price_start(
    call: CallbackQuery,
    state: FSMContext
):

    code = call.data.split(":",1)[1]


    await state.update_data(
        code=code
    )


    await state.set_state(
        EditPriceState.waiting_price
    )


    await call.message.answer(
        "✏️ <b>Edit Harga File</b>\n\n"
        "Masukkan harga baru.\n\n"
        "Contoh:\n"
        "5000",
        parse_mode="HTML"
    )


    await call.answer()



# =========================
# SIMPAN HARGA
# =========================

@router.message(EditPriceState.waiting_price)
async def save_price(
    message: Message,
    state: FSMContext
):

    if not message.text.isdigit():

        return await message.answer(
            "❌ Harga harus berupa angka."
        )


    price = int(message.text)


    data = await state.get_data()

    code = data["code"]


    pool = await get_pool()


    result = await pool.execute(
        """
        UPDATE files

        SET price=$1

        WHERE code=$2
        AND owner_id=$3
        """,
        price,
        code,
        message.from_user.id
    )


    await state.clear()


    await message.answer(
        "✅ <b>Harga berhasil diubah</b>\n\n"
        f"💰 Harga baru : Rp {price:,}".replace(",","."),
        parse_mode="HTML"
    )
