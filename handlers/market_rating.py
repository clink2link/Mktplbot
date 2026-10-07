from aiogram import Router, F
from aiogram.types import CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder

from database import fetch


router = Router()


@router.callback_query(F.data == "market_rating")
async def market_rating(call: CallbackQuery):

    await call.answer()

    # =====================================
    # RATING TERTINGGI
    # =====================================
    #
    # Menggunakan weighted rating.
    #
    # rating virtual = 4.0
    # minimal review virtual = 10
    #
    # Tujuannya supaya:
    #
    # 5.0 / 1 review
    #
    # tidak langsung mengalahkan:
    #
    # 4.8 / 100 review
    #
    # =====================================

    rows = await fetch(
        """
        SELECT
            code,
            title,
            price,
            media_count,

            COALESCE(rating, 0) AS rating,
            COALESCE(review_count, 0) AS review_count,

            COALESCE(sold, 0) AS sold,
            COALESCE(favorite_count, 0) AS favorite_count,

            (
                (
                    COALESCE(rating, 0)
                    * COALESCE(review_count, 0)
                )
                +
                (4.0 * 10)
            )
            /
            (
                COALESCE(review_count, 0)
                + 10
            ) AS rating_score

        FROM files

        WHERE is_paid = true

        ORDER BY
            rating_score DESC,
            review_count DESC,
            sold DESC,
            favorite_count DESC

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
        "⭐ <b>RATING TERTINGGI</b>\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "🏆 Ranking berdasarkan kualitas "
        "rating dan jumlah ulasan.\n\n"
    )

    # =====================================
    # EMPTY
    # =====================================

    if not rows:

        text += (
            "📭 Belum ada file yang memiliki "
            "rating."
        )

    # =====================================
    # FILE
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
        # RATING
        # ==============================

        rating = float(
            row["rating"] or 0
        )

        review_count = int(
            row["review_count"] or 0
        )

        rating_score = float(
            row["rating_score"] or 0
        )


        # ==============================
        # OTHER DATA
        # ==============================

        sold = int(
            row["sold"] or 0
        )

        favorites = int(
            row["favorite_count"] or 0
        )

        media_count = int(
            row["media_count"] or 0
        )


        # ==============================
        # CARD
        # ==============================

        text += (
            f"{rank} "
            f"<b>{row['title']}</b>\n"

            f"💰 {harga}\n"

            f"📁 {media_count} Media\n"

            f"⭐ <b>{rating:.1f}</b> "
            f"({review_count} ulasan)\n"

            f"🔥 {sold} Terjual\n"

            f"❤️ {favorites} Favorite\n"

            f"📊 Score: "
            f"{rating_score:.2f}\n\n"
        )


        # ==============================
        # OPEN FILE
        # ==============================

        kb.button(
            text=(
                f"⭐ "
                f"{str(row['title'])[:25]}"
            ),
            callback_data=(
                f"market:{row['code']}"
            )
        )


    # =====================================
    # BACK
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
