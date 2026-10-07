from aiogram import Router, F
from aiogram.types import (
    CallbackQuery,
    Message,
)
from aiogram.fsm.state import (
    StatesGroup,
    State,
)
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder

from database import get_pool
from .dashboard import is_admin, rupiah

router = Router()

PAGE_SIZE = 10


# =========================
# STATE
# =========================

class PaymentsState(StatesGroup):
    waiting_search = State()


# =========================
# MENU PAYMENT
# =========================

@router.callback_query(F.data == "admin_payments")
async def admin_payments(
    call: CallbackQuery,
    state: FSMContext
):

    if not is_admin(call.from_user.id):
        return await call.answer(
            "No Access",
            show_alert=True
        )

    await state.clear()

    pool = await get_pool()

    total = await pool.fetchval(
        """
        SELECT COUNT(*)
        FROM payments
        """
    ) or 0

    pending = await pool.fetchval(
        """
        SELECT COUNT(*)
        FROM payments
        WHERE status='pending'
        """
    ) or 0

    paid = await pool.fetchval(
        """
        SELECT COUNT(*)
        FROM payments
        WHERE status='paid'
        """
    ) or 0

    expired = await pool.fetchval(
        """
        SELECT COUNT(*)
        FROM payments
        WHERE status='expired'
        """
    ) or 0

    total_amount = await pool.fetchval(
        """
        SELECT COALESCE(SUM(amount),0)
        FROM payments
        WHERE status='paid'
        """
    ) or 0

    kb = InlineKeyboardBuilder()

    kb.button(
        text="📋 List Payment",
        callback_data="payments_list:1"
    )

    kb.button(
        text="🔍 Cari Payment",
        callback_data="payments_search"
    )

    kb.button(
        text="⚙️ Metode Pembayaran",
        callback_data="admin_payment_methods"
    )

    kb.button(
        text="⬅ Admin Menu",
        callback_data="admin_home"
    )

    kb.adjust(1)

    await call.message.edit_text(
        (
            "💳 <b>PAYMENTS PANEL</b>\n"
            "━━━━━━━━━━━━━━\n\n"

            f"🧾 Total Payment : <b>{total}</b>\n"
            f"🟡 Pending : <b>{pending}</b>\n"
            f"🟢 Paid : <b>{paid}</b>\n"
            f"🔴 Expired : <b>{expired}</b>\n\n"

            f"💰 Total Revenue\n"
            f"<b>{rupiah(total_amount)}</b>"
        ),
        parse_mode="HTML",
        reply_markup=kb.as_markup()
    )

    await call.answer()

# =========================
# LIST PAYMENT
# =========================

@router.callback_query(F.data.startswith("payments_list:"))
async def payments_list(
    call: CallbackQuery
):

    if not is_admin(call.from_user.id):
        return

    page = int(call.data.split(":")[1])

    if page < 1:
        page = 1

    offset = (page - 1) * PAGE_SIZE

    pool = await get_pool()

    total = await pool.fetchval(
        """
        SELECT COUNT(*)
        FROM payments
        """
    ) or 0

    pages = max(
        (total + PAGE_SIZE - 1) // PAGE_SIZE,
        1
    )

    rows = await pool.fetch(
        """
        SELECT
            id,
            invoice_id,
            user_id,
            code,
            amount,
            status,
            type,
            created_at
        FROM payments
        ORDER BY created_at DESC
        LIMIT $1
        OFFSET $2
        """,
        PAGE_SIZE,
        offset
    )

    text = (
        "💳 <b>DAFTAR PAYMENT</b>\n"
        "━━━━━━━━━━━━━━\n\n"
    )

    if not rows:

        text += "Belum ada data payment."

    else:

        for i, pay in enumerate(
            rows,
            start=offset + 1
        ):

            if pay["status"] == "paid":
                icon = "🟢"

            elif pay["status"] == "pending":
                icon = "🟡"

            elif pay["status"] == "expired":
                icon = "🔴"

            else:
                icon = "⚪"

            text += (
                f"{i}. {icon} "
                f"<code>{pay['invoice_id']}</code>\n"
                f"👤 {pay['user_id']}\n"
                f"📦 {pay['code'] or '-'}\n"
                f"💰 {rupiah(pay['amount'])}\n"
                f"📌 {pay['status'].upper()}\n\n"
            )

    kb = InlineKeyboardBuilder()

    if page > 1:
        kb.button(
            text="⬅",
            callback_data=f"payments_list:{page-1}"
        )

    kb.button(
        text=f"{page}/{pages}",
        callback_data="ignore"
    )

    if page < pages:
        kb.button(
            text="➡",
            callback_data=f"payments_list:{page+1}"
        )

    kb.button(
        text="🏠 Payment Menu",
        callback_data="admin_payments"
    )

    kb.adjust(3, 1)

    await call.message.edit_text(
        text,
        parse_mode="HTML",
        reply_markup=kb.as_markup()
    )

    await call.answer()


# =========================
# SEARCH PAYMENT
# =========================

@router.callback_query(F.data == "payments_search")
async def payments_search(
    call: CallbackQuery,
    state: FSMContext
):

    if not is_admin(call.from_user.id):
        return

    await state.clear()
    await state.set_state(
        PaymentsState.waiting_search
    )

    kb = InlineKeyboardBuilder()

    kb.button(
        text="⬅ Kembali",
        callback_data="admin_payments"
    )

    await call.message.edit_text(
        (
            "🔍 <b>CARI PAYMENT</b>\n\n"
            "Kirim salah satu:\n\n"
            "• Invoice ID\n"
            "• CODE\n"
            "• User ID"
        ),
        parse_mode="HTML",
        reply_markup=kb.as_markup()
    )

    await call.answer()


# =========================
# PROCESS SEARCH
# =========================

@router.message(PaymentsState.waiting_search)
async def process_search_payment(
    message: Message,
    state: FSMContext
):

    if not is_admin(message.from_user.id):
        return

    key = (message.text or "").strip()

    if not key:
        return await message.answer(
            "❌ Input kosong."
        )

    pool = await get_pool()

    if key.isdigit():

        payment = await pool.fetchrow(
            """
            SELECT *
            FROM payments
            WHERE user_id=$1
            ORDER BY created_at DESC
            LIMIT 1
            """,
            int(key)
        )

    else:

        payment = await pool.fetchrow(
            """
            SELECT *
            FROM payments
            WHERE LOWER(invoice_id)=LOWER($1)
               OR LOWER(code)=LOWER($1)
            LIMIT 1
            """,
            key
        )

    if not payment:

        await state.clear()

        return await message.answer(
            "❌ Payment tidak ditemukan."
        )

    status_icon = {
        "pending": "🟡",
        "paid": "🟢",
        "expired": "🔴"
    }.get(payment["status"], "⚪")

    text = (
        "💳 <b>DETAIL PAYMENT</b>\n"
        "━━━━━━━━━━━━━━\n\n"

        f"🧾 Invoice\n"
        f"<code>{payment['invoice_id']}</code>\n\n"

        f"👤 User ID\n"
        f"<code>{payment['user_id']}</code>\n\n"

        f"📦 CODE\n"
        f"<code>{payment['code'] or '-'}</code>\n\n"

        f"💰 Nominal\n"
        f"{rupiah(payment['amount'])}\n\n"

        f"📌 Status\n"
        f"{status_icon} {payment['status'].upper()}\n\n"

        f"💳 Type\n"
        f"{payment['type'] or '-'}\n\n"

        f"📅 Dibuat\n"
        f"{payment['created_at']}\n\n"

        f"⏳ Expired\n"
        f"{payment['expires_at']}\n"
    )

    kb = InlineKeyboardBuilder()

    kb.button(
        text="🔄 Refresh",
        callback_data=f"payment_refresh:{payment['id']}"
    )

    kb.button(
        text="🗑 Hapus",
        callback_data=f"payment_delete:{payment['id']}"
    )

    kb.button(
        text="⬅ Payment Menu",
        callback_data="admin_payments"
    )

    kb.adjust(2, 1)

    await message.answer(
        text,
        parse_mode="HTML",
        reply_markup=kb.as_markup()
    )

    await state.clear()


# =========================
# REFRESH PAYMENT
# =========================

@router.callback_query(F.data.startswith("payment_refresh:"))
async def payment_refresh(
    call: CallbackQuery
):

    if not is_admin(call.from_user.id):
        return

    payment_id = int(
        call.data.split(":")[1]
    )

    pool = await get_pool()

    payment = await pool.fetchrow(
        """
        SELECT *
        FROM payments
        WHERE id=$1
        """,
        payment_id
    )

    if not payment:
        return await call.answer(
            "❌ Payment tidak ditemukan.",
            show_alert=True
        )

    status_icon = {
        "pending": "🟡",
        "paid": "🟢",
        "expired": "🔴"
    }.get(payment["status"], "⚪")

    text = (
        "💳 <b>DETAIL PAYMENT</b>\n"
        "━━━━━━━━━━━━━━\n\n"

        f"🧾 Invoice\n"
        f"<code>{payment['invoice_id']}</code>\n\n"

        f"👤 User ID\n"
        f"<code>{payment['user_id']}</code>\n\n"

        f"📦 CODE\n"
        f"<code>{payment['code'] or '-'}</code>\n\n"

        f"💰 Nominal\n"
        f"{rupiah(payment['amount'])}\n\n"

        f"📌 Status\n"
        f"{status_icon} {payment['status'].upper()}\n\n"

        f"💳 Type\n"
        f"{payment['type'] or '-'}\n\n"

        f"📅 Dibuat\n"
        f"{payment['created_at']}\n\n"

        f"⏳ Expired\n"
        f"{payment['expires_at']}\n"
    )

    kb = InlineKeyboardBuilder()

    kb.button(
        text="🔄 Refresh",
        callback_data=f"payment_refresh:{payment_id}"
    )

    kb.button(
        text="🗑 Hapus",
        callback_data=f"payment_delete:{payment_id}"
    )

    kb.button(
        text="⬅ Payment Menu",
        callback_data="admin_payments"
    )

    kb.adjust(2, 1)

    await call.message.edit_text(
        text,
        parse_mode="HTML",
        reply_markup=kb.as_markup()
    )

    await call.answer()


# =========================
# DELETE PAYMENT
# =========================

@router.callback_query(F.data.startswith("payment_delete:"))
async def payment_delete(
    call: CallbackQuery,
    state: FSMContext
):

    if not is_admin(call.from_user.id):
        return

    payment_id = int(call.data.split(":")[1])

    pool = await get_pool()

    await pool.execute(
        """
        DELETE FROM payments
        WHERE id=$1
        """,
        payment_id
    )

    await call.answer(
        "✅ Payment berhasil dihapus.",
        show_alert=True
    )

    await admin_payments(call, state)


# =========================
# IGNORE
# =========================

@router.callback_query(F.data == "ignore")
async def ignore_callback(
    call: CallbackQuery
):
    await call.answer()


