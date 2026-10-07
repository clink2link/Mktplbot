import logging

from aiogram import Router, F
from aiogram.types import CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder

from database import get_pool
from config import (
    ADMIN_IDS,
    WITHDRAW_CHANNEL_ID
)
from handlers.withdraw.utils import rupiah


router = Router()

logger = logging.getLogger(__name__)


# =====================================================
# LIST WITHDRAW PENDING
# =====================================================

@router.callback_query(F.data=="admin_withdraw")
async def admin_withdraw(call: CallbackQuery):

    if call.from_user.id not in ADMIN_IDS:
        return

    pool = await get_pool()

    rows = await pool.fetch(
        """
        SELECT
            id,
            user_id,
            amount,
            status
        FROM withdraws
        WHERE status IN(
            'pending',
            'instant_pending'
        )
        ORDER BY id DESC
        LIMIT 10
        """
    )


    if not rows:
        return await call.answer(
            "Tidak ada withdraw pending",
            show_alert=True
        )


    kb = InlineKeyboardBuilder()

    text = (
        "🏧 <b>WITHDRAW PENDING</b>\n"
        "━━━━━━━━━━━━━━\n\n"
    )


    for row in rows:

        text += (
            f"🆔 {row['id']}\n"
            f"👤 {row['user_id']}\n"
            f"💰 {rupiah(row['amount'])}\n"
            f"📌 {row['status']}\n\n"
        )

        kb.button(
            text=f"Proses #{row['id']}",
            callback_data=f"admin_wd:view:{row['id']}"
        )


    kb.button(
        text="🔙 Kembali",
        callback_data="admin_home"
    )

    kb.adjust(1)


    await call.message.edit_text(
        text,
        reply_markup=kb.as_markup(),
        parse_mode="HTML"
    )

    await call.answer()



# =====================================================
# ADMIN BUTTON
# =====================================================

@router.callback_query(F.data.startswith("admin_wd:"))
async def admin_withdraw_action(call: CallbackQuery):

    if call.from_user.id not in ADMIN_IDS:
        return await call.answer(
            "Tidak memiliki akses.",
            show_alert=True
        )


    data = call.data.split(":")


    if len(data) < 3:
        return await call.answer(
            "Data tidak valid.",
            show_alert=True
        )


    action = data[1]


    try:
        withdraw_id = int(data[2])

    except ValueError:
        return await call.answer(
            "ID withdraw tidak valid.",
            show_alert=True
        )


    if action == "view":

        await withdraw_detail(
            call,
            withdraw_id
        )


    elif action == "approve":

        await approve_withdraw(
            call,
            withdraw_id
        )


    elif action == "reject":

        await reject_menu(
            call,
            withdraw_id
        )


    else:

        await call.answer(
            "Aksi tidak dikenal.",
            show_alert=True
        )

# =====================================================
# WITHDRAW DETAIL
# =====================================================

async def withdraw_detail(
    call: CallbackQuery,
    withdraw_id: int
):

    pool = await get_pool()

    withdraw = await pool.fetchrow(
        """
        SELECT
            user_id,
            method_name,
            account_number,
            account_name,
            amount,
            fee,
            total_cut,
            status

        FROM withdraws

        WHERE id=$1
        """,
        withdraw_id
    )


    if not withdraw:
        return await call.answer(
            "Withdraw tidak ditemukan.",
            show_alert=True
        )


    kb = InlineKeyboardBuilder()


    kb.button(
        text="✅ APPROVE",
        callback_data=f"admin_wd:approve:{withdraw_id}"
    )


    kb.button(
        text="❌ REJECT",
        callback_data=f"admin_wd:reject:{withdraw_id}"
    )


    kb.button(
        text="🔙 Kembali",
        callback_data="admin_withdraw"
    )


    kb.adjust(2,1)


    await call.message.edit_text(

        (
            "🏧 <b>DETAIL WITHDRAW</b>\n"
            "━━━━━━━━━━━━━━\n\n"

            f"🆔 ID : <code>{withdraw_id}</code>\n"
            f"👤 User ID : <code>{withdraw['user_id']}</code>\n\n"

            "🏦 <b>Tujuan</b>\n"
            f"• {withdraw['method_name']}\n"
            f"• <code>{withdraw['account_number']}</code>\n"
            f"• {withdraw['account_name']}\n\n"

            "💰 <b>Nominal</b>\n"
            f"• Request : {rupiah(withdraw['amount'])}\n"
            f"• Fee : {rupiah(withdraw['fee'])}\n"
            f"• Potong : {rupiah(withdraw['total_cut'])}\n\n"

            f"📌 Status : {withdraw['status']}"
        ),

        parse_mode="HTML",
        reply_markup=kb.as_markup()
    )


    await call.answer()


# =====================================================
# APPROVE WITHDRAW
# =====================================================

async def approve_withdraw(
    call: CallbackQuery,
    withdraw_id: int
):

    pool = await get_pool()

    async with pool.acquire() as conn:
        async with conn.transaction():

            withdraw = await conn.fetchrow(
                """
                SELECT
                    user_id,
                    amount,
                    fee,
                    receive_amount,
                    channel_message_id

                FROM withdraws

                WHERE id=$1

                AND status IN(
                    'pending',
                    'instant_pending'
                )

                FOR UPDATE
                """,
                withdraw_id
            )

            if not withdraw:
                return await call.answer(
                    "Withdraw sudah diproses.",
                    show_alert=True
                )

            receive = withdraw["receive_amount"]

            if receive is None:
                receive = withdraw["amount"] - withdraw["fee"]

            await conn.execute(
                """
                UPDATE withdraws
                SET
                    status='success',
                    processed_at=NOW(),
                    paid_at=NOW(),
                    updated_at=NOW()
                WHERE id=$1
                """,
                withdraw_id
            )

            await conn.execute(
                """
                UPDATE users
                SET total_withdraw = COALESCE(total_withdraw,0) + $1,
                    updated_at = NOW()
                WHERE user_id=$2
                """,
                receive,
                withdraw["user_id"]
            )


    # UPDATE CHANNEL

    if withdraw["channel_message_id"]:

        try:
            await call.bot.edit_message_text(
                chat_id=WITHDRAW_CHANNEL_ID,
                message_id=withdraw["channel_message_id"],

                text=(
                    "✅ <b>WITHDRAW BERHASIL</b>\n"
                    "━━━━━━━━━━━━━━\n\n"

                    f"🆔 ID : <code>{withdraw_id}</code>\n\n"

                    f"💰 Nominal : "
                    f"<b>{rupiah(withdraw['amount'])}</b>\n"

                    f"📤 Diterima : "
                    f"<b>{rupiah(receive)}</b>\n\n"

                    "📌 Status : ✅ SUCCESS\n\n"
                    "Dana telah berhasil dikirim."
                ),

                parse_mode="HTML"
            )

        except Exception:
            logger.exception(
                "UPDATE CHANNEL SUCCESS ERROR"
            )


    # USER NOTIFICATION

    try:

        await call.bot.send_message(
            chat_id=withdraw["user_id"],

            text=(
                "✅ <b>WITHDRAW BERHASIL</b>\n"
                "━━━━━━━━━━━━━━\n\n"

                f"🆔 ID : <code>{withdraw_id}</code>\n\n"

                f"💰 Nominal : "
                f"<b>{rupiah(withdraw['amount'])}</b>\n"

                f"📤 Diterima : "
                f"<b>{rupiah(receive)}</b>\n\n"

                "Dana telah berhasil dikirim."
            ),

            parse_mode="HTML"
        )

    except Exception:
        logger.exception(
            "SEND USER SUCCESS ERROR"
        )


    try:

        await call.message.edit_reply_markup(
            reply_markup=None
        )

    except Exception:
        pass


    await call.answer(
        "Withdraw berhasil disetujui."
    )

# =====================================================
# REJECT MENU
# =====================================================

async def reject_menu(call, withdraw_id):

    kb = InlineKeyboardBuilder()

    reasons = [
        ("❌ Nomor E-Wallet Salah", "nomor salah"),
        ("❌ Nama Tidak Sesuai", "nama tidak sesuai"),
        ("❌ Rekening Tidak Aktif", "rekening tidak aktif"),
        ("❌ Alasan Lain", "lain")
    ]

    for text, reason in reasons:
        kb.button(
            text=text,
            callback_data=f"wd_reject:{withdraw_id}:{reason}"
        )

    kb.button(
        text="🔙 Batal",
        callback_data="wd_cancel"
    )

    kb.adjust(1)

    await call.message.edit_text(
        (
            "❌ <b>ALASAN REJECT WITHDRAW</b>\n"
            "━━━━━━━━━━━━━━\n\n"
            "Silakan pilih alasan penolakan."
        ),
        parse_mode="HTML",
        reply_markup=kb.as_markup()
    )


# =====================================================
# REJECT PROCESS
# =====================================================

@router.callback_query(F.data.startswith("wd_reject:"))
async def process_reject(call: CallbackQuery):

    if call.from_user.id not in ADMIN_IDS:
        return await call.answer(
            "Tidak memiliki akses.",
            show_alert=True
        )

    _, withdraw_id, reason = call.data.split(":", 2)

    withdraw_id = int(withdraw_id)

    pool = await get_pool()

    async with pool.acquire() as conn:
        async with conn.transaction():

            withdraw = await conn.fetchrow(
                """
                SELECT
                    user_id,
                    amount,
                    fee,
                    channel_message_id

                FROM withdraws

                WHERE id=$1

                AND status IN(
                    'pending',
                    'instant_pending'
                )

                FOR UPDATE
                """,
                withdraw_id
            )

            if not withdraw:
                return await call.answer(
                    "Withdraw sudah diproses.",
                    show_alert=True
                )


            total_refund = (
                withdraw["amount"]
                +
                withdraw["fee"]
            )


            # REFUND SALDO

            await conn.execute(
                """
                UPDATE users

                SET balance = balance + $1

                WHERE user_id=$2
                """,

                total_refund,
                withdraw["user_id"]
            )


            # UPDATE WITHDRAW

            await conn.execute(
                """
                UPDATE withdraws

                SET
                    status='rejected',
                    admin_note=$1,
                    processed_at=NOW(),
                    updated_at=NOW()

                WHERE id=$2
                """,

                reason,
                withdraw_id
            )


    # UPDATE CHANNEL

    if withdraw["channel_message_id"]:

        try:

            await call.bot.edit_message_text(
                chat_id=WITHDRAW_CHANNEL_ID,
                message_id=withdraw["channel_message_id"],

                text=(
                    "❌ <b>WITHDRAW DITOLAK</b>\n"
                    "━━━━━━━━━━━━━━\n\n"

                    f"🆔 ID : <code>{withdraw_id}</code>\n\n"

                    f"💰 Nominal : "
                    f"<b>{rupiah(withdraw['amount'])}</b>\n\n"

                    f"📌 Alasan : <b>{reason}</b>\n\n"

                    f"💰 Refund : "
                    f"<b>{rupiah(total_refund)}</b>"
                ),

                parse_mode="HTML"
            )

        except Exception:
            logger.exception(
                "UPDATE CHANNEL REJECT ERROR"
            )


    # USER NOTIFICATION

    try:

        await call.bot.send_message(
            chat_id=withdraw["user_id"],

            text=(
                "❌ <b>WITHDRAW DITOLAK</b>\n"
                "━━━━━━━━━━━━━━\n\n"

                f"🆔 ID : <code>{withdraw_id}</code>\n\n"

                f"📌 Alasan : <b>{reason}</b>\n\n"

                f"💰 Saldo dikembalikan : "
                f"<b>{rupiah(total_refund)}</b>"
            ),

            parse_mode="HTML"
        )

    except Exception:
        logger.exception(
            "SEND USER REJECT ERROR"
        )


    try:

        await call.message.edit_reply_markup(
            reply_markup=None
        )

    except Exception:
        pass


    await call.answer(
        "Withdraw berhasil ditolak."
    )

# =====================================================
# CANCEL
# =====================================================

@router.callback_query(
    F.data == "wd_cancel"
)
async def cancel_reject(
    call: CallbackQuery
):

    await call.answer()

    try:

        await call.message.edit_text(

            (
                "❌ <b>PEMILIHAN REJECT DIBATALKAN</b>\n"
                "━━━━━━━━━━━━━━\n\n"

                "Tidak ada perubahan pada status withdraw.\n\n"

                "Silakan buka kembali menu admin jika ingin memproses withdraw ini."
            ),

            parse_mode="HTML"

        )

    except Exception:

        try:
            await call.message.delete()
        except Exception:
            pass
