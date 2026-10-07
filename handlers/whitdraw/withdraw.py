import logging

from aiogram import Router, F
from aiogram.types import CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.exceptions import TelegramBadRequest

from database import get_pool

from handlers.withdraw.utils import (
    withdraw_is_open,
    rupiah,
    MIN_WITHDRAW,
    WITHDRAW_FEE,
    WITHDRAW_NOMINALS,
    INSTANT_AMOUNT,
    INSTANT_FEE,
    INSTANT_MIN_BALANCE,
)


router = Router()
logger = logging.getLogger(__name__)


# =========================================================
# CEK KREATOR TERVERIFIKASI
# =========================================================

async def is_verified_creator(user_id: int) -> bool:

    pool = await get_pool()

    creator = await pool.fetchrow(
        """
        SELECT
            is_creator,
            creator_status
        FROM users
        WHERE user_id = $1
        """,
        user_id
    )

    if not creator:
        return False

    return (
        bool(creator["is_creator"])
        and creator["creator_status"] == "approved"
    )


# =========================================================
# NOTIFIKASI BUKAN KREATOR
# =========================================================

async def check_creator(call: CallbackQuery) -> bool:

    if await is_verified_creator(call.from_user.id):
        return True

    await call.answer(
        "🔒 Withdraw hanya tersedia untuk Kreator Terverifikasi.",
        show_alert=True
    )

    return False


# =========================================================
# MENU WITHDRAW
# =========================================================

@router.callback_query(F.data == "withdraw")
async def withdraw_menu(call: CallbackQuery):

    # =====================================
    # WAJIB KREATOR
    # =====================================

    if not await check_creator(call):
        return

    await call.answer()

    kb = InlineKeyboardBuilder()

    kb.button(
        text="🏦 Rekening / E-Wallet",
        callback_data="ewallet"
    )

    # =====================================
    # REGULER
    # =====================================

    if withdraw_is_open():

        status = "🟢 <b>REGULER BUKA</b>"

        kb.button(
            text="💸 Withdraw Reguler",
            callback_data="withdraw_create"
        )

    else:

        status = "🔴 <b>REGULER TUTUP</b>"

    # =====================================
    # INSTANT
    # =====================================

    kb.button(
        text="⚡ Withdraw Instant",
        callback_data="withdraw_instant"
    )

    kb.button(
        text="📜 Riwayat Withdraw",
        callback_data="withdraw_history"
    )

    kb.button(
        text="🔙 Kembali",
        callback_data="home"
    )

    kb.adjust(1)

    text = (
        "💸 <b>WITHDRAW SALDO</b>\n"
        "━━━━━━━━━━━━━━\n\n"

        "🎨 Status : "
        "<b>Kreator Terverifikasi</b> ✅\n\n"

        f"📌 Status : {status}\n\n"

        "🕘 <b>Jam Operasional Reguler</b>\n"
        "• Senin - Jumat\n"
        "• 09:00 - 19:00 WIB\n"
        "• Sabtu & Minggu Libur\n\n"

        "💸 <b>Withdraw Reguler</b>\n"
        f"• Minimal : {rupiah(MIN_WITHDRAW)}\n"
        f"• Fee Admin : {rupiah(WITHDRAW_FEE)}\n\n"

        "⚡ <b>Withdraw Instant</b>\n"
        f"• Nominal : {rupiah(INSTANT_AMOUNT)}\n"
        f"• Fee : {rupiah(INSTANT_FEE)}\n"
        f"• Minimal Saldo : {rupiah(INSTANT_MIN_BALANCE)}\n\n"

        "⚡ Withdraw Instant tersedia 24 jam."
    )

    try:

        await call.message.edit_text(
            text,
            parse_mode="HTML",
            reply_markup=kb.as_markup()
        )

    except TelegramBadRequest as e:

        if "message is not modified" not in str(e).lower():
            logger.exception("WITHDRAW MENU ERROR")


# =========================================================
# WITHDRAW REGULER
# =========================================================

@router.callback_query(F.data == "withdraw_create")
async def withdraw_create(call: CallbackQuery):

    # =====================================
    # WAJIB KREATOR
    # =====================================

    if not await check_creator(call):
        return

    await call.answer()

    # =====================================
    # CEK JAM OPERASIONAL
    # =====================================

    if not withdraw_is_open():

        return await call.answer(
            "🔴 Withdraw Reguler sedang tutup.",
            show_alert=True
        )

    pool = await get_pool()

    # =====================================
    # AMBIL REKENING
    # =====================================

    account = await pool.fetchrow(
        """
        SELECT
            id,
            method_name,
            account_number,
            account_name
        FROM user_payment_methods
        WHERE user_id = $1
        ORDER BY id
        LIMIT 1
        """,
        call.from_user.id
    )

    if not account:

        kb = InlineKeyboardBuilder()

        kb.button(
            text="➕ Tambah Rekening / E-Wallet",
            callback_data="ewallet"
        )

        kb.button(
            text="🔙 Kembali",
            callback_data="withdraw"
        )

        kb.adjust(1)

        return await call.message.edit_text(
            (
                "❌ <b>REKENING BELUM ADA</b>\n\n"
                "Silakan tambahkan rekening atau "
                "e-wallet terlebih dahulu."
            ),
            parse_mode="HTML",
            reply_markup=kb.as_markup()
        )

    # =====================================
    # CEK SALDO
    # =====================================

    balance = await pool.fetchval(
        """
        SELECT balance
        FROM users
        WHERE user_id = $1
        """,
        call.from_user.id
    ) or 0

    # =====================================
    # BUTTON NOMINAL
    # =====================================

    kb = InlineKeyboardBuilder()

    for amount in WITHDRAW_NOMINALS:

        kb.button(
            text=rupiah(amount),
            callback_data=f"wd_amount:{amount}"
        )

    kb.button(
        text="❌ Batal",
        callback_data="withdraw"
    )

    kb.adjust(2)

    text = (
        "💸 <b>WITHDRAW REGULER</b>\n"
        "━━━━━━━━━━━━━━\n\n"

        "🎨 Status : "
        "<b>Kreator Terverifikasi</b> ✅\n\n"

        f"💰 Saldo : <b>{rupiah(balance)}</b>\n\n"

        "🏦 <b>Tujuan Pencairan</b>\n"
        f"• {account['method_name']}\n"
        f"• {account['account_name']}\n"
        f"• <code>{account['account_number']}</code>\n\n"

        f"💸 Fee Admin : <b>{rupiah(WITHDRAW_FEE)}</b>\n\n"

        "👇 <b>Pilih nominal withdraw</b>"
    )

    await call.message.edit_text(
        text,
        parse_mode="HTML",
        reply_markup=kb.as_markup()
    )


# =========================================================
# WITHDRAW INSTANT
# =========================================================

@router.callback_query(F.data == "withdraw_instant")
async def withdraw_instant(call: CallbackQuery):

    # =====================================
    # WAJIB KREATOR
    # =====================================

    if not await check_creator(call):
        return

    await call.answer()

    pool = await get_pool()

    # =====================================
    # AMBIL REKENING
    # =====================================

    account = await pool.fetchrow(
        """
        SELECT
            method_name,
            account_number,
            account_name
        FROM user_payment_methods
        WHERE user_id = $1
        ORDER BY id
        LIMIT 1
        """,
        call.from_user.id
    )

    if not account:

        kb = InlineKeyboardBuilder()

        kb.button(
            text="➕ Tambah Rekening / E-Wallet",
            callback_data="ewallet"
        )

        kb.button(
            text="🔙 Kembali",
            callback_data="withdraw"
        )

        kb.adjust(1)

        return await call.message.edit_text(
            (
                "❌ <b>REKENING BELUM ADA</b>\n\n"
                "Tambahkan rekening atau e-wallet terlebih dahulu."
            ),
            parse_mode="HTML",
            reply_markup=kb.as_markup()
        )

    # =====================================
    # SALDO
    # =====================================

    balance = await pool.fetchval(
        """
        SELECT balance
        FROM users
        WHERE user_id = $1
        """,
        call.from_user.id
    ) or 0

    total = INSTANT_AMOUNT + INSTANT_FEE

    # =====================================
    # BUTTON
    # =====================================

    kb = InlineKeyboardBuilder()

    if balance >= total:

        kb.button(
            text="⚡ Request Withdraw Instant",
            callback_data="withdraw_instant_confirm"
        )

    else:

        kb.button(
            text="❌ Saldo Tidak Cukup",
            callback_data="withdraw"
        )

    kb.button(
        text="🔙 Kembali",
        callback_data="withdraw"
    )

    kb.adjust(1)

    text = (
        "⚡ <b>WITHDRAW INSTANT</b>\n"
        "━━━━━━━━━━━━━━\n\n"

        "🎨 Status : "
        "<b>Kreator Terverifikasi</b> ✅\n\n"

        f"💰 Saldo : <b>{rupiah(balance)}</b>\n\n"

        "🏦 <b>Tujuan Pencairan</b>\n"
        f"• {account['method_name']}\n"
        f"• {account['account_name']}\n"
        f"• <code>{account['account_number']}</code>\n\n"

        f"⚡ Nominal : <b>{rupiah(INSTANT_AMOUNT)}</b>\n"
        f"💸 Fee Instant : <b>{rupiah(INSTANT_FEE)}</b>\n"
        f"📉 Total Potong : <b>{rupiah(total)}</b>\n\n"

        "⚡ Withdraw Instant diproses secara prioritas."
    )

    await call.message.edit_text(
        text,
        parse_mode="HTML",
        reply_markup=kb.as_markup()
    )


# =========================================================
# PILIH NOMINAL REGULER
# =========================================================

@router.callback_query(F.data.startswith("wd_amount:"))
async def withdraw_amount(call: CallbackQuery):

    # =====================================
    # WAJIB KREATOR
    # =====================================

    if not await check_creator(call):
        return

    await call.answer()

    try:

        amount = int(
            call.data.split(":", 1)[1]
        )

    except (ValueError, IndexError):

        return await call.answer(
            "❌ Nominal tidak valid.",
            show_alert=True
        )

    if amount not in WITHDRAW_NOMINALS:

        return await call.answer(
            "❌ Nominal tidak valid.",
            show_alert=True
        )

    pool = await get_pool()

    # =====================================
    # CEK SALDO TERBARU
    # =====================================

    balance = await pool.fetchval(
        """
        SELECT balance
        FROM users
        WHERE user_id = $1
        """,
        call.from_user.id
    ) or 0

    total = amount + WITHDRAW_FEE

    if balance < total:

        return await call.answer(
            (
                "❌ Saldo tidak cukup.\n"
                f"Dibutuhkan {rupiah(total)}."
            ),
            show_alert=True
        )

    # =====================================
    # KONFIRMASI
    # =====================================

    kb = InlineKeyboardBuilder()

    kb.button(
        text="✅ Lanjutkan",
        callback_data=f"withdraw_confirm:{amount}"
    )

    kb.button(
        text="❌ Batal",
        callback_data="withdraw"
    )

    kb.adjust(1)

    text = (
        "💸 <b>DETAIL WITHDRAW</b>\n"
        "━━━━━━━━━━━━━━\n\n"

        "🎨 Status : "
        "<b>Kreator Terverifikasi</b> ✅\n\n"

        f"💰 Saldo : <b>{rupiah(balance)}</b>\n"
        f"💵 Nominal : <b>{rupiah(amount)}</b>\n"
        f"💸 Fee Admin : <b>{rupiah(WITHDRAW_FEE)}</b>\n"
        f"📉 Total Potong : <b>{rupiah(total)}</b>\n\n"

        "Saldo akan dipotong sebesar total biaya di atas "
        "setelah withdraw berhasil dibuat.\n\n"

        "Klik <b>Lanjutkan</b> untuk membuat "
        "permintaan withdraw."
    )

    await call.message.edit_text(
        text,
        parse_mode="HTML",
        reply_markup=kb.as_markup()
    )
