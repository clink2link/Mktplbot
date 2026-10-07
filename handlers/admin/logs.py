from aiogram import Router, F
from aiogram.types import CallbackQuery, Message
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder

from database import get_pool
from .dashboard import is_admin

router = Router()

PAGE_SIZE = 10


# =========================
# STATE
# =========================

class LogsState(StatesGroup):
    waiting_search = State()


# =========================
# MENU LOGS
# =========================

@router.callback_query(F.data == "admin_logs")
async def admin_logs(
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
        FROM logs
        """
    ) or 0

    today = await pool.fetchval(
        """
        SELECT COUNT(*)
        FROM logs
        WHERE DATE(created_at)=CURRENT_DATE
        """
    ) or 0

    kb = InlineKeyboardBuilder()

    kb.button(
        text="📋 List Logs",
        callback_data="logs_list:1"
    )

    kb.button(
        text="🔍 Cari Logs",
        callback_data="logs_search"
    )

    kb.button(
        text="🧹 Hapus Semua",
        callback_data="logs_clear"
    )

    kb.button(
        text="⬅ Admin Menu",
        callback_data="admin_home"
    )

    kb.adjust(1)

    await call.message.edit_text(
        (
            "📜 <b>LOGS PANEL</b>\n"
            "━━━━━━━━━━━━━━\n\n"

            f"📄 Total Log : <b>{total}</b>\n"
            f"📅 Hari Ini : <b>{today}</b>"
        ),
        parse_mode="HTML",
        reply_markup=kb.as_markup()
    )

    await call.answer()


# =========================
# LIST LOGS
# =========================

@router.callback_query(F.data.startswith("logs_list:"))
async def logs_list(
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
        FROM logs
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
            user_id,
            action,
            data,
            created_at
        FROM logs
        ORDER BY created_at DESC
        LIMIT $1
        OFFSET $2
        """,
        PAGE_SIZE,
        offset
    )

    text = (
        "📜 <b>DAFTAR LOGS</b>\n"
        "━━━━━━━━━━━━━━\n\n"
    )

    if not rows:

        text += "Belum ada data log."

    else:

        for i, log in enumerate(
            rows,
            start=offset + 1
        ):

            action = log["action"] or "-"
            data = (log["data"] or "-")[:30]

            if len(log["data"] or "") > 30:
                data += "..."

            text += (
                f"{i}. #{log['id']}\n"
                f"👤 <code>{log['user_id']}</code>\n"
                f"📌 {action}\n"
                f"📝 {data}\n\n"
            )

    kb = InlineKeyboardBuilder()

    if page > 1:
        kb.button(
            text="⬅",
            callback_data=f"logs_list:{page-1}"
        )

    kb.button(
        text=f"{page}/{pages}",
        callback_data="ignore"
    )

    if page < pages:
        kb.button(
            text="➡",
            callback_data=f"logs_list:{page+1}"
        )

    kb.button(
        text="🏠 Logs Menu",
        callback_data="admin_logs"
    )

    kb.adjust(3, 1)

    await call.message.edit_text(
        text,
        parse_mode="HTML",
        reply_markup=kb.as_markup()
    )

    await call.answer()


# =========================
# SEARCH LOGS
# =========================

@router.callback_query(F.data == "logs_search")
async def logs_search(
    call: CallbackQuery,
    state: FSMContext
):

    if not is_admin(call.from_user.id):
        return

    await state.clear()
    await state.set_state(
        LogsState.waiting_search
    )

    kb = InlineKeyboardBuilder()

    kb.button(
        text="⬅ Kembali",
        callback_data="admin_logs"
    )

    await call.message.edit_text(
        (
            "🔍 <b>CARI LOG</b>\n\n"
            "Kirim salah satu:\n\n"
            "• Log ID\n"
            "• User ID\n"
            "• Action"
        ),
        parse_mode="HTML",
        reply_markup=kb.as_markup()
    )

    await call.answer()


# =========================
# PROCESS SEARCH
# =========================

@router.message(LogsState.waiting_search)
async def process_search_log(
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

        log = await pool.fetchrow(
            """
            SELECT *
            FROM logs
            WHERE id=$1
               OR user_id=$1
            ORDER BY created_at DESC
            LIMIT 1
            """,
            int(key)
        )

    else:

        log = await pool.fetchrow(
            """
            SELECT *
            FROM logs
            WHERE LOWER(action)=LOWER($1)
            ORDER BY created_at DESC
            LIMIT 1
            """,
            key
        )

    if not log:

        await state.clear()

        return await message.answer(
            "❌ Log tidak ditemukan."
        )

    text = (
        "📜 <b>DETAIL LOG</b>\n"
        "━━━━━━━━━━━━━━\n\n"

        f"🆔 Log ID\n"
        f"<code>{log['id']}</code>\n\n"

        f"👤 User ID\n"
        f"<code>{log['user_id']}</code>\n\n"

        f"📌 Action\n"
        f"{log['action'] or '-'}\n\n"

        f"📝 Data\n"
        f"<code>{log['data'] or '-'}</code>\n\n"

        f"📅 Waktu\n"
        f"{log['created_at']}"
    )

    kb = InlineKeyboardBuilder()

    kb.button(
        text="🗑 Hapus",
        callback_data=f"log_delete:{log['id']}"
    )

    kb.button(
        text="⬅ Logs Menu",
        callback_data="admin_logs"
    )

    kb.adjust(1)

    await message.answer(
        text,
        parse_mode="HTML",
        reply_markup=kb.as_markup()
    )

    await state.clear()


# =========================
# DELETE LOG
# =========================

@router.callback_query(F.data.startswith("log_delete:"))
async def log_delete(
    call: CallbackQuery,
    state: FSMContext
):

    if not is_admin(call.from_user.id):
        return

    log_id = int(
        call.data.split(":")[1]
    )

    pool = await get_pool()

    result = await pool.execute(
        """
        DELETE FROM logs
        WHERE id=$1
        """,
        log_id
    )

    if result.endswith("0"):
        return await call.answer(
            "❌ Log tidak ditemukan.",
            show_alert=True
        )

    await call.answer(
        "✅ Log berhasil dihapus.",
        show_alert=True
    )

    await admin_logs(call, state)


# =========================
# CLEAR LOGS
# =========================

@router.callback_query(F.data == "logs_clear")
async def logs_clear(
    call: CallbackQuery,
    state: FSMContext
):

    if not is_admin(call.from_user.id):
        return

    pool = await get_pool()

    total = await pool.fetchval(
        """
        SELECT COUNT(*)
        FROM logs
        """
    ) or 0

    if total == 0:
        return await call.answer(
            "📭 Logs sudah kosong.",
            show_alert=True
        )

    await pool.execute(
        """
        DELETE FROM logs
        """
    )

    await call.answer(
        f"✅ {total} log berhasil dihapus.",
        show_alert=True
    )

    await admin_logs(call, state)


# =========================
# IGNORE
# =========================

@router.callback_query(F.data == "ignore")
async def ignore_callback(
    call: CallbackQuery
):
    await call.answer()
