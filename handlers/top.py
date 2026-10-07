from math import ceil

from aiogram import Router, F
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton
)
from aiogram.utils.keyboard import InlineKeyboardBuilder

from database import get_pool


router = Router()

LIMIT = 10


async def show_top_code(target, page=1):

    pool = await get_pool()

    msg = target.message if isinstance(target, CallbackQuery) else target

    # =========================
    # TOTAL FILE
    # =========================

    total = await pool.fetchval(
        """
        SELECT COUNT(*)
        FROM files
        """
    )

    if not total:

        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="🏪 Marketplace",
                        callback_data="marketplace"
                    )
                ]
            ]
        )

        await msg.edit_text(
            "❌ Belum ada file.",
            reply_markup=kb
        )

        if isinstance(target, CallbackQuery):
            await target.answer()

        return


    # =========================
    # PAGINATION
    # =========================

    max_page = ceil(total / LIMIT)

    page = max(
        1,
        min(page, max_page)
    )

    offset = (
        page - 1
    ) * LIMIT


    # =========================
    # TERLARIS
    # =========================
    #
    # PRIORITAS:
    #
    # 1. sold       = jumlah pembelian
    # 2. views      = jumlah dilihat
    # 3. favorite   = jumlah favorit
    # 4. rating     = rating
    # 5. created_at = file terbaru
    #
    # Jadi file yang benar-benar
    # banyak dibeli akan berada
    # di posisi paling atas.
    # =========================

    rows = await pool.fetch(
        """
        SELECT
            code,
            title,
            price,
            media_count,

            COALESCE(sold, 0) AS sold,
            COALESCE(views, 0) AS views,
            COALESCE(favorite_count, 0) AS favorite_count,

            COALESCE(rating, 0) AS rating,
            COALESCE(review_count, 0) AS review_count,

            is_premium

        FROM files

        ORDER BY
            COALESCE(sold, 0) DESC,
            COALESCE(views, 0) DESC,
            COALESCE(favorite_count, 0) DESC,
            COALESCE(rating, 0) DESC,
            created_at DESC

        LIMIT $1
        OFFSET $2
        """,
        LIMIT,
        offset
    )


    # =========================
    # HEADER
    # =========================

    text = (
        "🔥 <b>TOP FILE TERLARIS</b>\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "File dengan jumlah pembelian "
        "terbanyak akan tampil di atas.\n\n"
    )


    kb = InlineKeyboardBuilder()


    # =========================
    # FILE LIST
    # =========================

    for i, row in enumerate(
        rows,
        start=offset + 1
    ):

        # =========================
        # RANK
        # =========================

        if i == 1:
            icon = "🥇"

        elif i == 2:
            icon = "🥈"

        elif i == 3:
            icon = "🥉"

        else:
            icon = f"{i}."


        # =========================
        # HARGA
        # =========================

        harga = (
            "Gratis"
            if not row["price"]
            else f"Rp {row['price']:,}".replace(
                ",",
                "."
            )
        )


        # =========================
        # PREMIUM
        # =========================

        premium = (
            " 👑"
            if row["is_premium"]
            else ""
        )


        # =========================
        # RATING
        # =========================

        rating = float(
            row["rating"] or 0
        )

        review_count = int(
            row["review_count"] or 0
        )


        # =========================
        # DATA
        # =========================

        sold = int(
            row["sold"] or 0
        )

        views = int(
            row["views"] or 0
        )

        favorites = int(
            row["favorite_count"] or 0
        )

        media_count = int(
            row["media_count"] or 0
        )


        # =========================
        # CARD
        # =========================

        text += (
            f"{icon} "
            f"<b>{row['title']}</b>"
            f"{premium}\n"

            f"💰 {harga}\n"

            f"📁 {media_count} Media\n"

            f"🔥 <b>{sold}</b> Terjual\n"

            f"👁 {views} Dilihat\n"

            f"❤️ {favorites} Favorite\n"

            f"⭐ {rating:.1f} "
            f"({review_count} ulasan)\n\n"
        )


        # =========================
        # OPEN FILE
        # =========================

        kb.button(
            text=(
                f"📦 "
                f"{str(row['title'])[:30]}"
            ),
            callback_data=(
                f"market:{row['code']}"
            )
        )


    # =========================
    # NAVIGATION
    # =========================

    nav = []


    if page > 1:

        nav.append(
            InlineKeyboardButton(
                text="⬅️",
                callback_data=(
                    f"top:{page-1}"
                )
            )
        )


    nav.append(
        InlineKeyboardButton(
            text=f"{page}/{max_page}",
            callback_data="ignore"
        )
    )


    if page < max_page:

        nav.append(
            InlineKeyboardButton(
                text="➡️",
                callback_data=(
                    f"top:{page+1}"
                )
            )
        )


    kb.row(*nav)


    # =========================
    # BACK MARKETPLACE
    # =========================

    kb.button(
        text="🏪 Marketplace",
        callback_data="marketplace"
    )


    kb.adjust(1)


    # =========================
    # SEND
    # =========================

    await msg.edit_text(
        text,
        parse_mode="HTML",
        reply_markup=kb.as_markup()
    )


    if isinstance(
        target,
        CallbackQuery
    ):

        await target.answer()


# =========================
# BUTTON TOP
# =========================

@router.callback_query(
    F.data == "top_code"
)
async def top_open(
    call: CallbackQuery
):

    await show_top_code(
        call,
        1
    )


# =========================
# PAGINATION
# =========================

@router.callback_query(
    F.data.startswith("top:")
)
async def top_page(
    call: CallbackQuery
):

    page = int(
        call.data.split(":")[1]
    )

    await show_top_code(
        call,
        page
    )


# =========================
# IGNORE
# =========================

@router.callback_query(
    F.data == "ignore"
)
async def ignore(
    call: CallbackQuery
):

    await call.answer()


# =========================
# COMMAND
# =========================

async def top_command(
    message: Message
):

    await show_top_code(
        message,
        1
    )
