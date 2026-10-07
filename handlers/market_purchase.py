import logging
from math import ceil

from aiogram import Router, F
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from aiogram.exceptions import TelegramBadRequest

from database import fetch, fetchval


router = Router()
logger = logging.getLogger(__name__)

LIMIT = 10


# =========================================================
# PAGINATION KEYBOARD
# =========================================================

def page_keyboard(page: int, max_page: int):

    buttons = []

    if page > 1:
        buttons.append(
            InlineKeyboardButton(
                text="⬅️",
                callback_data=f"market_purchase:{page - 1}",
            )
        )

    buttons.append(
        InlineKeyboardButton(
            text=f"{page}/{max_page}",
            callback_data="ignore",
        )
    )

    if page < max_page:
        buttons.append(
            InlineKeyboardButton(
                text="➡️",
                callback_data=f"market_purchase:{page + 1}",
            )
        )

    return InlineKeyboardMarkup(
        inline_keyboard=[
            buttons,
            [
                InlineKeyboardButton(
                    text="⬅️ Marketplace",
                    callback_data="marketplace",
                )
            ],
        ]
    )


# =========================================================
# SHOW PURCHASE
# =========================================================

async def show_purchase(
    call: CallbackQuery,
    page: int = 1,
):

    user_id = call.from_user.id

    # =====================================================
    # VALIDASI PAGE
    # =====================================================

    try:
        page = int(page)
    except (TypeError, ValueError):
        page = 1

    if page < 1:
        page = 1

    # =====================================================
    # TOTAL PEMBELIAN
    #
    # file_purchases:
    #   user_id
    #   file_code
    # =====================================================

    total = await fetchval(
        """
        SELECT COUNT(*)
        FROM file_purchases
        WHERE user_id = $1
        """,
        user_id,
    )

    total = int(total or 0)

    # =====================================================
    # BELUM ADA PEMBELIAN
    # =====================================================

    if total == 0:

        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="⬅️ Marketplace",
                        callback_data="marketplace",
                    )
                ]
            ]
        )

        text = (
            "🛍 <b>PEMBELIAN SAYA</b>\n"
            "━━━━━━━━━━━━━━━━━━\n\n"
            "📦 Total Pembelian : <b>0</b>\n\n"
            "Belum ada file yang pernah dibeli."
        )

        try:

            await call.message.edit_text(
                text,
                parse_mode="HTML",
                reply_markup=keyboard,
            )

        except TelegramBadRequest as e:

            if "message is not modified" not in str(e).lower():
                logger.exception(
                    "SHOW PURCHASE EMPTY ERROR"
                )

        return

    # =====================================================
    # PAGINATION
    # =====================================================

    max_page = ceil(total / LIMIT)

    if page > max_page:
        page = max_page

    offset = (page - 1) * LIMIT

    # =====================================================
    # AMBIL PEMBELIAN
    #
    # PENTING:
    #
    # file_purchases.file_code
    #       ↓
    # files.code
    #
    # BUKAN p.code
    # =====================================================

    rows = await fetch(
        """
        SELECT
            p.file_code,
            p.paid_price,
            p.status,
            p.created_at,

            f.code,
            f.title,
            f.media_count,
            f.price,
            f.owner_id,
            f.seller_id

        FROM file_purchases p

        LEFT JOIN files f
            ON f.code = p.file_code

        WHERE p.user_id = $1

        ORDER BY p.created_at DESC

        LIMIT $2
        OFFSET $3
        """,
        user_id,
        LIMIT,
        offset,
    )

    # =====================================================
    # TEXT
    # =====================================================

    text = (
        "🛍 <b>PEMBELIAN SAYA</b>\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        f"📦 Total Pembelian : <b>{total}</b>\n"
        f"📄 Halaman : <b>{page}/{max_page}</b>\n\n"
    )

    keyboard = []

    # =====================================================
    # FILE LIST
    # =====================================================

    for i, row in enumerate(
        rows,
        start=offset + 1,
    ):

        file_code = row["file_code"]

        title = (
            row["title"]
            if row["title"]
            else "File"
        )

        media_count = (
            row["media_count"]
            if row["media_count"] is not None
            else 0
        )

        # Harga yang dibayar pembeli
        paid_price = (
            row["paid_price"]
            if row["paid_price"] is not None
            else 0
        )

        status = (
            row["status"]
            if row["status"]
            else "unknown"
        )

        # =================================================
        # STATUS
        # =================================================

        status_lower = str(status).lower()

        if status_lower in (
            "paid",
            "success",
            "completed",
            "completed",
            "successed",
        ):
            status_text = "✅ Selesai"

        elif status_lower in (
            "pending",
            "processing",
        ):
            status_text = "⏳ Diproses"

        elif status_lower in (
            "failed",
            "cancelled",
            "canceled",
            "expired",
        ):
            status_text = "❌ Gagal"

        else:
            status_text = str(status)

        # =================================================
        # JUDUL
        # =================================================

        button_title = str(title)[:30]

        # =================================================
        # TEXT
        # =================================================

        text += (
            f"{i}. <b>{title}</b>\n"
            f"🔑 <code>{file_code}</code>\n"
            f"📁 {media_count} Media\n"
            f"💰 Dibayar : <b>Rp {paid_price:,.0f}</b>\n"
            f"📌 Status : {status_text}\n\n"
        )

        # =================================================
        # BUTTON
        # =================================================

        # Gunakan file_code karena itulah kode file
        # yang tersimpan di file_purchases.

        keyboard.append(
            [
                InlineKeyboardButton(
                    text=f"📂 {button_title}",
                    callback_data=f"page:{file_code}:1",
                )
            ]
        )

    # =====================================================
    # PAGINATION
    # =====================================================

    nav = page_keyboard(
        page,
        max_page,
    )

    keyboard.extend(
        nav.inline_keyboard
    )

    # =====================================================
    # SEND
    # =====================================================

    try:

        await call.message.edit_text(
            text.replace(",", "."),
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=keyboard
            ),
        )

    except TelegramBadRequest as e:

        if "message is not modified" not in str(e).lower():

            logger.exception(
                "SHOW PURCHASE EDIT ERROR"
            )


# =========================================================
# MENU
# =========================================================

@router.callback_query(
    F.data == "market_purchase"
)
async def purchase_menu(
    call: CallbackQuery,
):

    await call.answer()

    await show_purchase(
        call,
        1,
    )


# =========================================================
# PAGINATION
# =========================================================

@router.callback_query(
    F.data.startswith("market_purchase:")
)
async def purchase_page(
    call: CallbackQuery,
):

    try:

        page = int(
            call.data.split(":", 1)[1]
        )

    except (ValueError, IndexError):

        return await call.answer(
            "❌ Halaman tidak valid.",
            show_alert=True,
        )

    await call.answer()

    await show_purchase(
        call,
        page,
    )


# =========================================================
# IGNORE
# =========================================================

@router.callback_query(
    F.data == "ignore"
)
async def ignore(
    call: CallbackQuery,
):

    await call.answer()
