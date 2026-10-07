from aiogram import Router, F
from aiogram.types import CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder

from database import fetch


router = Router()


@router.callback_query(F.data == "market_favorite")
async def market_favorite(call: CallbackQuery):

    await call.answer()

    # =====================================
    # FAVORIT TERBANYAK
    # =====================================

    rows = await fetch(
        """
        SELECT
            code,
            title,
            price,
            media_count,

            COALESCE(favorite_count, 0) AS favorite_count,
            COALESCE(rating, 0) AS rating,
            COALESCE(review_count, 0) AS review_count,
            COALESCE(sold, 0) AS sold,
            COALESCE(views, 0) AS views,

            is_premium

        FROM files

        WHERE is_paid = true

        ORDER BY
            COALESCE(favorite_count, 0) DESC,
            COALESCE(sold, 0) DESC,
            COALESCE(rating, 0) DESC,
            COALESCE(review_count, 0) DESC,
            COALESCE(views, 0) DESC,
            created_at DESC

        LIMIT 20
        """
    )

    # =====================================
    # KEYBOARD
    # =====================================

    kb = InlineKeyboardBuilder()

    # =====================================
    # HEADER
    # =====================================

    text = (
        "❤️ <b>FAVORIT TERBANYAK</b>\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "File yang paling banyak disukai "
        "pengguna marketplace.\n\n"
    )

    # =====================================
    # EMPTY
    # =====================================

    if not rows:

        text += (
            "📭 Belum ada file yang masuk "
            "favorit."
        )

    # =====================================
    # FILE LIST
    # =====================================

    for index, row in enumerate(
        rows,
        start=1
    ):

        # ==============================
        # RANK
        # ==============================

        if index == 1:
            rank = "🥇"

        elif index == 2:
            rank = "🥈"

        elif index == 3:
            rank = "🥉"

        else:
            rank = f"{index}."


        # ==============================
        # PRICE
        # ==============================

        price = row["price"] or 0

        harga = (
            "Gratis"
            if price == 0
            else f"Rp{price:,}".replace(
                ",",
                "."
            )
        )


        # ==============================
        # DATA
        # ==============================

        favorites = int(
            row["favorite_count"] or 0
        )

        rating = float(
            row["rating"] or 0
        )

        reviews = int(
            row["review_count"] or 0
        )

        sold = int(
            row["sold"] or 0
        )

        views = int(
            row["views"] or 0
        )

        media_count = int(
            row["media_count"] or 0
        )


        premium = (
            " 👑"
            if row["is_premium"]
            else ""
        )


        # ==============================
        # CARD
        # ==============================

        text += (
            f"{rank} "
            f"<b>{row['title']}</b>"
            f"{premium}\n"

            f"💰 {harga}\n"

            f"📁 {media_count} Media\n"

            f"❤️ <b>{favorites}</b> Favorite\n"

            f"⭐ {rating:.1f} "
            f"({reviews} ulasan)\n"

            f"🔥 {sold} Terjual\n"

            f"👁 {views} Dilihat\n\n"
        )


        # ==============================
        # OPEN FILE
        # ==============================

        kb.button(
            text=(
                f"❤️ "
                f"{str(row['title'])[:25]}"
            ),
            callback_data=(
                f"market:{row['code']}"
            )
        )


    # =====================================
    # NAVIGATION
    # =====================================

    kb.button(
        text="⬅️ Marketplace",
        callback_data="marketplace"
    )

    kb.adjust(1)


    # =====================================
    # SEND
    # =====================================

    await call.message.edit_text(
        text,
        parse_mode="HTML",
        reply_markup=kb.as_markup()
    )
