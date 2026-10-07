from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder

from datetime import datetime
import pytz

from database import get_pool
from config import ADMIN_IDS


router = Router()


# =========================
# ADMIN CHECK
# =========================

def is_admin(user_id:int):
    return user_id in ADMIN_IDS



# =========================
# RUPIAH
# =========================

def rupiah(value):

    try:
        value = int(value or 0)

    except:
        value = 0

    return f"Rp {value:,}".replace(",", ".")



# =========================
# SAFE QUERY
# =========================

async def safe_count(pool, table):

    try:
        return await pool.fetchval(
            f"""
            SELECT COUNT(*)
            FROM {table}
            """
        ) or 0

    except Exception as e:
        print("COUNT ERROR:", e)
        return 0



async def safe_sum(pool, column, table):

    try:

        return await pool.fetchval(
            f"""
            SELECT COALESCE(SUM({column}),0)
            FROM {table}
            """
        ) or 0

    except Exception as e:

        print("SUM ERROR:", e)
        return 0



# =========================
# DASHBOARD
# =========================

async def dashboard_text():

    pool = await get_pool()

    # SYSTEM
    users = await safe_count(pool, "users")
    files = await safe_count(pool, "files")
    media = await safe_sum(pool, "media_count", "files")

    # FINANCE
    balance = await safe_sum(pool, "balance", "users")
    revenue = await safe_sum(pool, "total_income", "files")

    # PAYMENT
    pending_payment = 0
    paid_payment = 0
    failed_payment = 0

    try:
        pending_payment = await pool.fetchval(
            """
            SELECT COUNT(*)
            FROM payments
            WHERE status='pending'
            """
        ) or 0

        paid_payment = await pool.fetchval(
            """
            SELECT COUNT(*)
            FROM payments
            WHERE status='paid'
            """
        ) or 0

        failed_payment = await pool.fetchval(
            """
            SELECT COUNT(*)
            FROM payments
            WHERE status='failed'
            """
        ) or 0

    except Exception as e:
        print("PAYMENT ERROR:", e)

    # WITHDRAW
    withdraw_pending = 0
    withdraw_process = 0
    withdraw_success = 0
    withdraw_reject = 0

    try:
        withdraw_pending = await pool.fetchval(
            """
            SELECT COUNT(*)
            FROM withdraws
            WHERE status IN (
                'pending',
                'instant_pending'
            )
            """
        ) or 0

        withdraw_process = await pool.fetchval(
            """
            SELECT COUNT(*)
            FROM withdraws
            WHERE status IN (
                'process',
                'processing'
            )
            """
        ) or 0

        withdraw_success = await pool.fetchval(
            """
            SELECT COUNT(*)
            FROM withdraws
            WHERE status='success'
            """
        ) or 0

        withdraw_reject = await pool.fetchval(
            """
            SELECT COUNT(*)
            FROM withdraws
            WHERE status='rejected'
            """
        ) or 0

    except Exception as e:
        print("WITHDRAW ERROR:", e)

    now = datetime.now(
        pytz.timezone("Asia/Jakarta")
    ).strftime("%d-%m-%Y %H:%M WIB")

    return (
        "🛠 <b>ADMIN PANEL</b>\n"
        "━━━━━━━━━━━━\n"

        "📊 <b>SYSTEM</b>\n"
        f"👤 User : <b>{users}</b>\n"
        f"📂 File : <b>{files}</b>\n"
        f"🖼 Media : <b>{media}</b>\n\n"

        "💰 <b>FINANCE</b>\n"
        f"👛 Balance : <b>{rupiah(balance)}</b>\n"
        f"💵 Revenue : <b>{rupiah(revenue)}</b>\n\n"

        "💳 <b>PAYMENT</b>\n"
        f"🟡 Pending : <b>{pending_payment}</b>\n"
        f"🟢 Paid : <b>{paid_payment}</b>\n"
        f"🔴 Failed : <b>{failed_payment}</b>\n\n"

        "🏧 <b>WITHDRAW</b>\n"
        f"🟡 Pending : <b>{withdraw_pending}</b>\n"
        f"🔵 Process : <b>{withdraw_process}</b>\n"
        f"🟢 Success : <b>{withdraw_success}</b>\n"
        f"🔴 Reject : <b>{withdraw_reject}</b>\n\n"

        "━━━━━━━━━━━━━━━━━━\n"
        f"🕒 <i>{now}</i>"
    )

# =========================
# BUTTON
# =========================

def dashboard_keyboard():

    kb = InlineKeyboardBuilder()


    kb.button(
        text="👤 Users",
        callback_data="admin_users"
    )

    kb.button(
        text="📂 Files",
        callback_data="admin_files"
    )

    kb.button(
        text="💳 Payment",
        callback_data="admin_payments"
    )

    kb.button(
        text="🏧 Withdraw",
        callback_data="admin_withdraw"
    )

    kb.button(
        text="💰 Balance",
        callback_data="admin_balance"
    )

    kb.button(
        text="📢 Broadcast",
        callback_data="admin_broadcast"
    )

    kb.button(
        text="📜 Logs",
        callback_data="admin_logs"
    )

    kb.button(
        text="⚙️ Settings",
        callback_data="admin_settings"
    )


    kb.adjust(2)


    return kb.as_markup()



# =========================
# /ADMIN
# =========================

@router.message(Command("admin"))
async def admin_command(
    message:Message
):

    if not is_admin(
        message.from_user.id
    ):
        return await message.answer(
            "❌ Tidak punya akses"
        )


    await message.answer(
        await dashboard_text(),
        reply_markup=dashboard_keyboard(),
        parse_mode="HTML"
    )



# =========================
# HOME
# =========================

@router.callback_query(
    F.data=="admin_home"
)
async def admin_home(
    call:CallbackQuery
):

    if not is_admin(
        call.from_user.id
    ):
        return


    await call.message.edit_text(
        await dashboard_text(),
        reply_markup=dashboard_keyboard(),
        parse_mode="HTML"
    )


    await call.answer()
