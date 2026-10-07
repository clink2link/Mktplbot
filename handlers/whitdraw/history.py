from aiogram import Router, F
from aiogram.types import CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder

from database import get_pool
from .utils import rupiah


router = Router()


PAGE_SIZE = 10


# =========================
# STATUS FORMAT
# =========================

def status_text(status):

    data = {
        "pending": "🟡 Pending",
        "success": "🟢 Berhasil",
        "paid": "🟢 Berhasil",
        "rejected": "🔴 Ditolak",
        "cancelled": "⚪ Dibatalkan",
    }

    return data.get(
        status,
        f"⚪ {status}"
    )



# =========================
# RIWAYAT WITHDRAW
# =========================

@router.callback_query(F.data.startswith("withdraw_history"))
async def withdraw_history(
    call: CallbackQuery
):

    await call.answer()


    parts = call.data.split(":")

    page = 1

    if len(parts) > 1:

        try:
            page = int(parts[1])

        except:
            page = 1


    if page < 1:
        page = 1



    offset = (
        page - 1
    ) * PAGE_SIZE



    pool = await get_pool()



    total = await pool.fetchval(
        """
        SELECT COUNT(*)
        FROM withdraws
        WHERE user_id=$1
        """,
        call.from_user.id
    ) or 0



    pages = max(
        (total + PAGE_SIZE - 1) // PAGE_SIZE,
        1
    )



    rows = await pool.fetch(
        """
        SELECT
            id,
            amount,
            fee,
            net_amount,
            method,
            account_name,
            account_number,
            status,
            created_at
        FROM withdraws
        WHERE user_id=$1
        ORDER BY created_at DESC
        LIMIT $2
        OFFSET $3
        """,
        call.from_user.id,
        PAGE_SIZE,
        offset
    )



    text = (
        "📜 <b>RIWAYAT WITHDRAW</b>\n"
        "━━━━━━━━━━━━━━\n\n"
    )


    if not rows:

        text += (
            "Belum ada riwayat withdraw."
        )


    else:

        for i, wd in enumerate(
            rows,
            start=offset + 1
        ):

            text += (
                f"{i}. 💸 <b>{rupiah(wd['amount'])}</b>\n"
                f"📌 {status_text(wd['status'])}\n"
                f"🏦 {wd['method'] or '-'}\n"
                f"📅 {wd['created_at']}\n\n"
            )



    kb = InlineKeyboardBuilder()



    if page > 1:

        kb.button(
            text="⬅",
            callback_data=f"withdraw_history:{page-1}"
        )


    kb.button(
        text=f"{page}/{pages}",
        callback_data="ignore"
    )



    if page < pages:

        kb.button(
            text="➡",
            callback_data=f"withdraw_history:{page+1}"
        )



    kb.button(
        text="🔙 Kembali",
        callback_data="withdraw"
    )


    kb.adjust(3,1)



    await call.message.edit_text(
        text,
        parse_mode="HTML",
        reply_markup=kb.as_markup()
    )



# =========================
# DETAIL WITHDRAW
# =========================

@router.callback_query(
    F.data.startswith("withdraw_detail:")
)
async def withdraw_detail(
    call: CallbackQuery
):

    await call.answer()


    withdraw_id = int(
        call.data.split(":")[1]
    )


    pool = await get_pool()


    wd = await pool.fetchrow(
        """
        SELECT *
        FROM withdraws
        WHERE id=$1
        AND user_id=$2
        """,
        withdraw_id,
        call.from_user.id
    )



    if not wd:

        return await call.answer(
            "Withdraw tidak ditemukan.",
            show_alert=True
        )



    text = (
        "💸 <b>DETAIL WITHDRAW</b>\n"
        "━━━━━━━━━━━━━━\n\n"

        f"🆔 ID\n"
        f"<code>{wd['id']}</code>\n\n"

        f"💰 Nominal\n"
        f"{rupiah(wd['amount'])}\n\n"

        f"💸 Fee\n"
        f"{rupiah(wd['fee'])}\n\n"

        f"📥 Diterima\n"
        f"{rupiah(wd['net_amount'])}\n\n"

        f"🏦 Metode\n"
        f"{wd['method']}\n\n"

        f"👤 Nama\n"
        f"{wd['account_name']}\n\n"

        f"🔢 Nomor\n"
        f"<code>{wd['account_number']}</code>\n\n"

        f"📌 Status\n"
        f"{status_text(wd['status'])}\n\n"

        f"📅 Dibuat\n"
        f"{wd['created_at']}"
    )


    kb = InlineKeyboardBuilder()


    kb.button(
        text="🔙 Riwayat",
        callback_data="withdraw_history:1"
    )


    kb.adjust(1)



    await call.message.edit_text(
        text,
        parse_mode="HTML",
        reply_markup=kb.as_markup()
    )



# =========================
# IGNORE BUTTON
# =========================

@router.callback_query(F.data=="ignore")
async def ignore_callback(
    call: CallbackQuery
):
    await call.answer()
