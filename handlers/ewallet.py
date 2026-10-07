from aiogram import Router, F
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import (
    StatesGroup,
    State
)

from database import get_pool


router = Router()


# =====================================
# FSM
# =====================================

class EwalletState(StatesGroup):

    waiting_method = State()
    waiting_number = State()
    waiting_name = State()

    edit_method = State()
    edit_number = State()
    edit_name = State()

# =====================================
# KEYBOARD
# =====================================

def ewallet_menu_kb():

    return InlineKeyboardMarkup(
        inline_keyboard=[

            [
                InlineKeyboardButton(
                    text="➕ Tambah",
                    callback_data="ewallet_add"
                )
            ],

            [
                InlineKeyboardButton(
                    text="✏ Edit",
                    callback_data="ewallet_edit"
                ),
                InlineKeyboardButton(
                    text="🗑 Hapus",
                    callback_data="ewallet_delete"
                )
            ],

            [
                InlineKeyboardButton(
                    text="🏠 Home",
                    callback_data="home"
                )
            ]
        ]
    )


# =====================================
# MENU
# =====================================

@router.callback_query(F.data == "ewallet")
async def ewallet_menu(
    call: CallbackQuery,
    state: FSMContext
):

    await call.answer()

    await state.clear()

    pool = await get_pool()

    rows = await pool.fetch(
        """
        SELECT
            method_name,
            account_number,
            account_name
        FROM user_payment_methods
        WHERE user_id=$1
        ORDER BY id
        """,
        call.from_user.id
    )

    if not rows:

        text = (
            "💳 <b>E-Wallet / Bank Saya</b>\n\n"
            "Belum ada metode pembayaran yang tersimpan.\n\n"
            "Silakan tekan <b>Tambah</b>."
        )

    else:

        text = "💳 <b>E-Wallet / Bank Saya</b>\n\n"

        for i, row in enumerate(rows, start=1):

            text += (
                f"<b>{i}.</b> {row['method_name']}\n"
                f"👤 {row['account_name']}\n"
                f"💳 <code>{row['account_number']}</code>\n\n"
            )

    try:

        await call.message.edit_text(
            text,
            parse_mode="HTML",
            reply_markup=ewallet_menu_kb()
        )

    except:

        await call.message.answer(
            text,
            parse_mode="HTML",
            reply_markup=ewallet_menu_kb()
        )

from aiogram.types import Message

# =====================================
# TAMBAH
# =====================================

@router.callback_query(F.data == "ewallet_add")
async def ewallet_add(
    call: CallbackQuery,
    state: FSMContext
):
    await call.answer()

    await state.set_state(
        EwalletState.waiting_method
    )

    await call.message.edit_text(
        (
            "➕ <b>Tambah E-Wallet / Bank</b>\n\n"
            "Masukkan nama Bank / E-Wallet.\n\n"
            "Contoh:\n"
            "• DANA\n"
            "• OVO\n"
            "• GoPay\n"
            "• ShopeePay\n"
            "• BCA\n"
            "• BRI\n"
            "• Mandiri"
        ),
        parse_mode="HTML"
    )


# =====================================
# INPUT METHOD
# =====================================

@router.message(EwalletState.waiting_method)
async def input_method(
    message: Message,
    state: FSMContext
):
    method = message.text.strip()

    if len(method) < 2:

        return await message.answer(
            "❌ Nama Bank / E-Wallet tidak valid."
        )

    await state.update_data(
        method_name=method
    )

    await state.set_state(
        EwalletState.waiting_number
    )

    await message.answer(
        (
            "💳 Sekarang kirim nomor rekening / nomor e-wallet."
        )
    )


# =====================================
# INPUT NUMBER
# =====================================

@router.message(EwalletState.waiting_number)
async def input_number(
    message: Message,
    state: FSMContext
):
    number = message.text.strip()

    if len(number) < 5:

        return await message.answer(
            "❌ Nomor tidak valid."
        )

    await state.update_data(
        account_number=number
    )

    await state.set_state(
        EwalletState.waiting_name
    )

    await message.answer(
        (
            "👤 Terakhir kirim nama pemilik rekening."
        )
    )


# =====================================
# INPUT NAME + SAVE DB
# =====================================

@router.message(EwalletState.waiting_name)
async def input_name(
    message: Message,
    state: FSMContext
):
    name = message.text.strip()

    if len(name) < 2:

        return await message.answer(
            "❌ Nama tidak valid."
        )

    data = await state.get_data()

    pool = await get_pool()

    # maksimal 5 akun
    total = await pool.fetchval(
        """
        SELECT COUNT(*)
        FROM user_payment_methods
        WHERE user_id=$1
        """,
        message.from_user.id
    )

    if total >= 5:

        await state.clear()

        return await message.answer(
            "❌ Maksimal hanya dapat menyimpan 5 metode pembayaran."
        )

    # cek duplikat
    exists = await pool.fetchval(
        """
        SELECT EXISTS(
            SELECT 1
            FROM user_payment_methods
            WHERE user_id=$1
            AND method_name=$2
            AND account_number=$3
        )
        """,
        message.from_user.id,
        data["method_name"],
        data["account_number"]
    )

    if exists:

        await state.clear()

        return await message.answer(
            "❌ Metode pembayaran tersebut sudah tersimpan."
        )

    await pool.execute(
        """
        INSERT INTO user_payment_methods(
            user_id,
            method_name,
            account_number,
            account_name
        )
        VALUES($1,$2,$3,$4)
        """,
        message.from_user.id,
        data["method_name"],
        data["account_number"],
        name
    )

    await state.clear()

    await message.answer(
        (
            "✅ <b>Berhasil disimpan.</b>\n\n"
            f"🏦 {data['method_name']}\n"
            f"💳 <code>{data['account_number']}</code>\n"
            f"👤 {name}"
        ),
        parse_mode="HTML",
        reply_markup=ewallet_menu_kb()
    )


# =====================================
# EDIT MENU
# =====================================

@router.callback_query(F.data == "ewallet_edit")
async def ewallet_edit(
    call: CallbackQuery,
    state: FSMContext
):
    await call.answer()

    pool = await get_pool()

    rows = await pool.fetch(
        """
        SELECT
            id,
            method_name,
            account_number
        FROM user_payment_methods
        WHERE user_id=$1
        ORDER BY id
        """,
        call.from_user.id
    )

    if not rows:

        return await call.answer(
            "Belum ada data.",
            show_alert=True
        )

    keyboard = []

    for row in rows:

        keyboard.append(
            [
                InlineKeyboardButton(
                    text=f"{row['method_name']} • {row['account_number']}",
                    callback_data=f"editwallet:{row['id']}"
                )
            ]
        )

    keyboard.append(
        [
            InlineKeyboardButton(
                text="⬅ Kembali",
                callback_data="ewallet"
            )
        ]
    )

    await call.message.edit_text(
        "✏ Pilih akun yang ingin diedit.",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=keyboard
        )
    )


# =====================================
# PILIH DATA YANG DIEDIT
# =====================================

@router.callback_query(F.data.startswith("editwallet:"))
async def editwallet_select(
    call: CallbackQuery,
    state: FSMContext
):
    await call.answer()

    wallet_id = int(
        call.data.split(":")[1]
    )

    pool = await get_pool()

    row = await pool.fetchrow(
        """
        SELECT
            id,
            method_name,
            account_number,
            account_name
        FROM user_payment_methods
        WHERE id=$1
        AND user_id=$2
        """,
        wallet_id,
        call.from_user.id
    )

    if not row:

        return await call.answer(
            "Data tidak ditemukan.",
            show_alert=True
        )

    await state.update_data(
        wallet_id=wallet_id
    )

    await state.set_state(
        EwalletState.edit_method
    )

    await call.message.edit_text(
        (
            "✏ <b>Edit Metode Pembayaran</b>\n\n"
            f"Metode saat ini : <b>{row['method_name']}</b>\n\n"
            "Silakan kirim nama Bank / E-Wallet yang baru."
        ),
        parse_mode="HTML"
    )

# =====================================
# EDIT METHOD
# =====================================

@router.message(EwalletState.edit_method)
async def edit_method(
    message: Message,
    state: FSMContext
):
    method = message.text.strip()

    if len(method) < 2:

        return await message.answer(
            "❌ Nama Bank / E-Wallet tidak valid."
        )

    await state.update_data(
        method_name=method
    )

    await state.set_state(
        EwalletState.edit_number
    )

    await message.answer(
        (
            "💳 Sekarang kirim nomor rekening / "
            "nomor e-wallet yang baru."
        )
    )

# =====================================
# EDIT NUMBER
# =====================================

@router.message(EwalletState.edit_number)
async def edit_number(
    message: Message,
    state: FSMContext
):
    number = message.text.strip()

    if len(number) < 5:

        return await message.answer(
            "❌ Nomor tidak valid."
        )

    await state.update_data(
        account_number=number
    )

    await state.set_state(
        EwalletState.edit_name
    )

    await message.answer(
        "👤 Sekarang kirim nama pemilik rekening yang baru."
    )

# =====================================
# EDIT NAME + UPDATE DB
# =====================================

@router.message(EwalletState.edit_name)
async def edit_name(
    message: Message,
    state: FSMContext
):
    name = message.text.strip()

    if len(name) < 2:

        return await message.answer(
            "❌ Nama tidak valid."
        )

    data = await state.get_data()

    pool = await get_pool()

    await pool.execute(
        """
        UPDATE user_payment_methods
        SET
            method_name=$1,
            account_number=$2,
            account_name=$3
        WHERE id=$4
        AND user_id=$5
        """,
        data["method_name"],
        data["account_number"],
        name,
        data["wallet_id"],
        message.from_user.id
    )

    await state.clear()

    await message.answer(
        (
            "✅ <b>Metode pembayaran berhasil diperbarui.</b>\n\n"
            f"🏦 {data['method_name']}\n"
            f"💳 <code>{data['account_number']}</code>\n"
            f"👤 {name}"
        ),
        parse_mode="HTML",
        reply_markup=ewallet_menu_kb()
    )
