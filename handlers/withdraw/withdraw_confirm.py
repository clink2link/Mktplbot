import logging
from aiogram import F, Router
from aiogram.types import CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder
from config import (
    ADMIN_IDS,
    WITHDRAW_CHANNEL_ID,
)
from database import get_pool
from handlers.withdraw.utils import (
    INSTANT_AMOUNT,
    INSTANT_FEE,
    WITHDRAW_FEE,
    rupiah,
    withdraw_is_open,
)
router = Router()
logger = logging.getLogger(__name__)
# =====================================================
# MASK DATA
# =====================================================
def mask_name(name):
    if not name:
        return "-"
    name = str(name)
    if len(name) <= 3:
        return "***"
    return (
        name[:2]
        + "*" * (len(name) - 4)
        + name[-2:]
    )
def mask_id(uid):
    uid = str(uid)
    if len(uid) <= 4:
        return "***"
    return (
        uid[:2]
        + "*" * (len(uid) - 4)
        + uid[-2:]
    )
# =====================================================
# GET USER PAYMENT METHOD
# =====================================================
async def get_user_payment_method(
    conn,
    user_id: int,
):
    """
    Ambil payment method milik user.
    payment_method_id pada withdraws harus menunjuk
    ke ID payment method yang digunakan user.
    """
    return await conn.fetchrow(
        """
        SELECT
            id,
            method_name,
            account_number,
            account_name
        FROM user_payment_methods
        WHERE user_id = $1
        ORDER BY id ASC
        LIMIT 1
        """,
        user_id,
    )
# =====================================================
# WITHDRAW REGULER CONFIRM
# =====================================================
@router.callback_query(
    F.data.startswith("withdraw_confirm:")
)
async def withdraw_confirm(
    call: CallbackQuery,
):
    await call.answer()
    if not withdraw_is_open():
        return await call.answer(
            "Withdraw sedang tutup.",
            show_alert=True,
        )
    # =================================================
    # PARSE AMOUNT
    # =================================================
    try:
        amount = int(
            call.data.split(":", 1)[1]
        )
    except (IndexError, ValueError):
        return await call.answer(
            "Data withdraw tidak valid.",
            show_alert=True,
        )
    if amount <= 0:
        return await call.answer(
            "Nominal withdraw tidak valid.",
            show_alert=True,
        )
    pool = await get_pool()
    withdraw_id = None
    total_cut = amount + WITHDRAW_FEE
    try:
        async with pool.acquire() as conn:
            async with conn.transaction():
                # =====================================
                # LOCK USER
                # =====================================
                user = await conn.fetchrow(
                    """
                    SELECT balance
                    FROM users
                    WHERE user_id = $1
                    FOR UPDATE
                    """,
                    call.from_user.id,
                )
                if not user:
                    return await call.answer(
                        "User tidak ditemukan.",
                        show_alert=True,
                    )
                balance = user["balance"] or 0
                if balance < total_cut:
                    return await call.answer(
                        "Saldo tidak cukup.",
                        show_alert=True,
                    )
                # =====================================
                # CEK WITHDRAW AKTIF
                # =====================================
                pending = await conn.fetchval(
                    """
                    SELECT id
                    FROM withdraws
                    WHERE user_id = $1
                    AND status IN (
                        'pending',
                        'instant_pending'
                    )
                    LIMIT 1
                    """,
                    call.from_user.id,
                )
                if pending:
                    return await call.answer(
                        "Masih ada withdraw yang diproses.",
                        show_alert=True,
                    )
                # =====================================
                # PAYMENT METHOD
                # =====================================
                account = await get_user_payment_method(
                    conn,
                    call.from_user.id,
                )
                if not account:
                    return await call.answer(
                        "Tambahkan rekening / e-wallet terlebih dahulu.",
                        show_alert=True,
                    )
                payment_method_id = account["id"]
                # =====================================
                # INSERT WITHDRAW
                #
                # PENTING:
                # payment_method_id wajib diisi.
                # =====================================
                withdraw_id = await conn.fetchval(
                    """
                    INSERT INTO withdraws
                    (
                        user_id,
                        payment_method_id,
                        method_name,
                        account_number,
                        account_name,
                        amount,
                        fee,
                        receive_amount,
                        total_cut,
                        status,
                        created_at
                    )
                    VALUES
                    (
                        $1,
                        $2,
                        $3,
                        $4,
                        $5,
                        $6,
                        $7,
                        $8,
                        $9,
                        'pending',
                        NOW()
                    )
                    RETURNING id
                    """,
                    call.from_user.id,
                    payment_method_id,
                    account["method_name"],
                    account["account_number"],
                    account["account_name"],
                    amount,
                    WITHDRAW_FEE,
                    amount,
                    total_cut,
                )
                # =====================================
                # POTONG SALDO
                #
                # Dijalankan dalam transaction yang sama.
                # Jika UPDATE gagal, INSERT ikut rollback.
                # =====================================
                await conn.execute(
                    """
                    UPDATE users
                    SET balance = balance - $1
                    WHERE user_id = $2
                    """,
                    total_cut,
                    call.from_user.id,
                )
    except Exception:
        logger.exception(
            "WITHDRAW REGULER ERROR"
        )
        return await call.answer(
            "Terjadi kesalahan sistem.",
            show_alert=True,
        )
    # =================================================
    # ADMIN NOTIFICATION
    # =================================================
    await send_admin_notification(
        call,
        withdraw_id,
        amount,
        WITHDRAW_FEE,
        "pending",
    )
    # =================================================
    # CHANNEL
    # =================================================
    await send_withdraw_channel(
        call,
        withdraw_id,
        amount,
        WITHDRAW_FEE,
        "pending",
    )
    # =================================================
    # SUCCESS KEYBOARD
    # =================================================
    kb = InlineKeyboardBuilder()
    kb.button(
        text="📜 Riwayat Withdraw",
        callback_data="withdraw_history",
    )
    kb.button(
        text="🔙 Menu Withdraw",
        callback_data="withdraw",
    )
    kb.adjust(1)
    # =================================================
    # SUCCESS
    # =================================================
    await call.message.edit_text(
        (
            "✅ <b>WITHDRAW BERHASIL DIBUAT</b>\n"
            "━━━━━━━━━━━━━━\n\n"
            f"🆔 ID : <code>{withdraw_id}</code>\n\n"
            f"💰 Nominal : "
            f"<b>{rupiah(amount)}</b>\n"
            f"💸 Fee Admin : "
            f"<b>{rupiah(WITHDRAW_FEE)}</b>\n"
            f"📉 Total Potong : "
            f"<b>{rupiah(total_cut)}</b>\n\n"
            "⏳ Status : MENUNGGU ADMIN"
        ),
        parse_mode="HTML",
        reply_markup=kb.as_markup(),
    )
# =====================================================
# WITHDRAW INSTANT
# =====================================================
@router.callback_query(
    F.data == "withdraw_instant_confirm"
)
async def withdraw_instant_confirm(
    call: CallbackQuery,
):
    await call.answer()
    pool = await get_pool()
    withdraw_id = None
    total_cut = (
        INSTANT_AMOUNT
        + INSTANT_FEE
    )
    try:
        async with pool.acquire() as conn:
            async with conn.transaction():
                # =====================================
                # LOCK USER BALANCE
                # =====================================
                user = await conn.fetchrow(
                    """
                    SELECT balance
                    FROM users
                    WHERE user_id = $1
                    FOR UPDATE
                    """,
                    call.from_user.id,
                )
                if not user:
                    return await call.answer(
                        "User tidak ditemukan.",
                        show_alert=True,
                    )
                balance = user["balance"] or 0
                if balance < total_cut:
                    return await call.answer(
                        "Saldo tidak cukup.",
                        show_alert=True,
                    )
                # =====================================
                # CEK WITHDRAW AKTIF
                # =====================================
                pending = await conn.fetchval(
                    """
                    SELECT id
                    FROM withdraws
                    WHERE user_id = $1
                    AND status IN (
                        'pending',
                        'instant_pending'
                    )
                    LIMIT 1
                    """,
                    call.from_user.id,
                )
                if pending:
                    return await call.answer(
                        "Masih ada withdraw yang diproses.",
                        show_alert=True,
                    )
                # =====================================
                # PAYMENT METHOD
                # =====================================
                account = await get_user_payment_method(
                    conn,
                    call.from_user.id,
                )
                if not account:
                    return await call.answer(
                        "Tambahkan rekening / e-wallet terlebih dahulu.",
                        show_alert=True,
                    )
                payment_method_id = account["id"]
                # =====================================
                # INSERT WITHDRAW
                # =====================================
                withdraw_id = await conn.fetchval(
                    """
                    INSERT INTO withdraws
                    (
                        user_id,
                        payment_method_id,
                        method_name,
                        account_number,
                        account_name,
                        amount,
                        fee,
                        receive_amount,
                        total_cut,
                        status,
                        created_at
                    )
                    VALUES
                    (
                        $1,
                        $2,
                        $3,
                        $4,
                        $5,
                        $6,
                        $7,
                        $8,
                        $9,
                        'instant_pending',
                        NOW()
                    )
                    RETURNING id
                    """,
                    call.from_user.id,
                    payment_method_id,
                    account["method_name"],
                    account["account_number"],
                    account["account_name"],
                    INSTANT_AMOUNT,
                    INSTANT_FEE,
                    INSTANT_AMOUNT,
                    total_cut,
                )
                # =====================================
                # POTONG SALDO
                # =====================================
                await conn.execute(
                    """
                    UPDATE users
                    SET balance = balance - $1
                    WHERE user_id = $2
                    """,
                    total_cut,
                    call.from_user.id,
                )
    except Exception:
        logger.exception(
            "WITHDRAW INSTANT ERROR"
        )
        return await call.answer(
            "Terjadi kesalahan sistem.",
            show_alert=True,
        )
    # =================================================
    # ADMIN
    # =================================================
    await send_admin_notification(
        call,
        withdraw_id,
        INSTANT_AMOUNT,
        INSTANT_FEE,
        "instant_pending",
    )
    # =================================================
    # CHANNEL
    # =================================================
    await send_withdraw_channel(
        call,
        withdraw_id,
        INSTANT_AMOUNT,
        INSTANT_FEE,
        "instant_pending",
    )
    # =================================================
    # SUCCESS KEYBOARD
    # =================================================
    kb = InlineKeyboardBuilder()
    kb.button(
        text="📜 Riwayat Withdraw",
        callback_data="withdraw_history",
    )
    kb.button(
        text="🔙 Menu Withdraw",
        callback_data="withdraw",
    )
    kb.adjust(1)
    # =================================================
    # SUCCESS MESSAGE
    # =================================================
    await call.message.edit_text(
        (
            "⚡ <b>WITHDRAW INSTANT BERHASIL</b>\n"
            "━━━━━━━━━━━━━━\n\n"
            f"🆔 ID : <code>{withdraw_id}</code>\n\n"
            f"💰 Nominal : "
            f"<b>{rupiah(INSTANT_AMOUNT)}</b>\n"
            f"💸 Fee Admin : "
            f"<b>{rupiah(INSTANT_FEE)}</b>\n"
            f"📉 Total Potong : "
            f"<b>{rupiah(total_cut)}</b>\n\n"
            "⚡ Status : PRIORITAS ADMIN"
        ),
        parse_mode="HTML",
        reply_markup=kb.as_markup(),
    )
# =====================================================
# ADMIN NOTIFICATION
# =====================================================
async def send_admin_notification(
    call: CallbackQuery,
    withdraw_id: int,
    amount: int,
    fee: int,
    status: str,
):
    pool = await get_pool()
    withdraw = await pool.fetchrow(
        """
        SELECT
            user_id,
            payment_method_id,
            method_name,
            account_number,
            account_name,
            total_cut
        FROM withdraws
        WHERE id = $1
        """,
        withdraw_id,
    )
    if not withdraw:
        return
    kb = InlineKeyboardBuilder()
    kb.button(
        text="✅ APPROVE",
        callback_data=f"admin_wd:approve:{withdraw_id}",
    )
    kb.button(
        text="❌ REJECT",
        callback_data=f"admin_wd:reject:{withdraw_id}",
    )
    kb.adjust(2)
    status_text = {
        "pending": "⏳ PENDING",
        "instant_pending": "⚡ INSTANT PENDING",
    }.get(
        status,
        status.upper(),
    )
    for admin_id in ADMIN_IDS:
        try:
            await call.bot.send_message(
                chat_id=admin_id,
                text=(
                    "🚨 <b>REQUEST WITHDRAW BARU</b>\n"
                    "━━━━━━━━━━━━━━\n\n"
                    f"🆔 ID : "
                    f"<code>{withdraw_id}</code>\n"
                    f"👤 User ID : "
                    f"<code>{withdraw['user_id']}</code>\n\n"
                    "🏦 <b>Tujuan</b>\n"
                    f"• {withdraw['method_name']}\n"
                    f"• <code>{withdraw['account_number']}</code>\n"
                    f"• {withdraw['account_name']}\n\n"
                    f"💰 Nominal : "
                    f"<b>{rupiah(amount)}</b>\n"
                    f"💸 Fee : "
                    f"<b>{rupiah(fee)}</b>\n"
                    f"📉 Total Potong : "
                    f"<b>{rupiah(withdraw['total_cut'])}</b>\n\n"
                    f"📌 Status : "
                    f"<b>{status_text}</b>"
                ),
                parse_mode="HTML",
                reply_markup=kb.as_markup(),
            )
        except Exception:
            logger.exception(
                "FAILED SEND ADMIN NOTIFICATION"
            )
# =====================================================
# POST CHANNEL WITHDRAW
# =====================================================
async def send_withdraw_channel(
    call: CallbackQuery,
    withdraw_id: int,
    amount: int,
    fee: int,
    status: str,
):
    try:
        pool = await get_pool()
        withdraw = await pool.fetchrow(
            """
            SELECT
                user_id,
                payment_method_id,
                method_name,
                account_number,
                account_name,
                total_cut
            FROM withdraws
            WHERE id = $1
            """,
            withdraw_id,
        )
        if not withdraw:
            return
        status_text = {
            "pending": "⏳ PENDING",
            "instant_pending": "⚡ INSTANT PENDING",
        }.get(
            status,
            status.upper(),
        )
        # =========================================
        # SENSOR NOMOR
        # =========================================
        account_number = (
            withdraw["account_number"]
            or "-"
        )
        if len(account_number) > 6:
            account_number = (
                account_number[:3]
                + "*" * (
                    len(account_number) - 6
                )
                + account_number[-3:]
            )
        else:
            account_number = "***"
        # =========================================
        # SENSOR NAMA
        # =========================================
        account_name = (
            withdraw["account_name"]
            or "-"
        )
        parts = account_name.split()
        if len(parts) > 1:
            account_name = (
                parts[0]
                + " ***"
            )
        else:
            account_name = "***"
        # =========================================
        # SEND CHANNEL
        # =========================================
        msg = await call.bot.send_message(
            chat_id=WITHDRAW_CHANNEL_ID,
            text=(
                "💸 <b>REQUEST WITHDRAW BARU</b>\n"
                "━━━━━━━━━━━━━━\n\n"
                f"🆔 ID : "
                f"<code>{withdraw_id}</code>\n"
                f"👤 User ID : "
                f"<code>{mask_id(withdraw['user_id'])}</code>\n\n"
                "🏦 <b>Tujuan</b>\n"
                f"• {withdraw['method_name']}\n"
                f"• <code>{account_number}</code>\n"
                f"• {account_name}\n\n"
                f"💰 Nominal : "
                f"<b>{rupiah(amount)}</b>\n"
                f"📌 Status : "
                f"<b>{status_text}</b>\n\n"
                "⏳ Menunggu proses admin."
            ),
            parse_mode="HTML",
        )
        # =========================================
        # SAVE CHANNEL MESSAGE ID
        # =========================================
        await pool.execute(
            """
            UPDATE withdraws
            SET channel_message_id = $1
            WHERE id = $2
            """,
            msg.message_id,
            withdraw_id,
        )
    except Exception:
        logger.exception(
            "CHANNEL WITHDRAW POST ERROR"
        )
