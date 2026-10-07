from aiogram import Router, F
from aiogram.types import CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder

from database import get_pool


router = Router()

LIMIT = 10


@router.callback_query(F.data == "new_code")
async def new_code_menu(call: CallbackQuery):

    await call.answer()

    pool = await get_pool()

    # =====================================
    # FILE TERBARU
    # =====================================

    rows = await pool.fetch(
        """
        SELECT
            code,
            title,
            price,
            media_count,

            COALESCE(views, 0) AS views,
            COALESCE(sold, 0) AS sold,
            COALESCE(favorite_count, 0) AS favorite_count,

            COALESCE(rating, 0) AS rating,
            COALESCE(review_count, 0) AS review_count,

            is_premium,
            created_at

        FROM files

        WHERE is_paid = true

        ORDER BY
            created_at DESC

        LIMIT $1
        """,
        LIMIT
    )

    # =====================================
    # EMPTY
    # =====================================

    if not rows:

        kb = InlineKeyboardBuilder()

        kb.button(
            text="🛒 Marketplace",
            callback_data="marketplace"
        )

        kb.button(
            text="🏠 Home",
            callback_data="home"
        )

        kb.adjust(1)

        await call.message.edit_text(
            "🆕 <b>FILE TERBARU</b>\n\n"
            "📭 Belum ada file baru yang tersedia.",
            parse_mode="HTML",
            reply_markup=kb.as_markup()
        )

        return


    # =====================================
    # HEADER
    # =====================================

    text = (
        "🆕 <b>FILE TERBARU</b>\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "File yang baru dipublikasikan "
        "di marketplace.\n\n"
    )


    kb = InlineKeyboardBuilder()


    # =====================================
    # FILE LIST
    # =====================================

    for index, row in enumerate(
        rows,
        start=1
    ):

        # ==============================
        # PRICE
        # ==============================

        price = row["price"] or 0

        harga = (
            "Gratis"
            if price == 0
            else f"Rp {price:,}".replace(
                ",",
                "."
            )
        )


        # ==============================
        # PREMIUM
        # ==============================

        premium = (
            " 👑"
            if row["is_premium"]
            else ""
        )


        # ==============================
        # STATISTICS
        # ==============================

        views = int(
            row["views"] or 0
        )

        sold = int(
            row["sold"] or 0
        )

        favorites = int(
            row["favorite_count"] or 0
        )

        reviews = int(
            row["review_count"] or 0
        )

        rating = float(
            row["rating"] or 0
        )

        media_count = int(
            row["media_count"] or 0
        )


        # ==============================
        # CARD
        # ==============================

        text += (
            f"🆕 <b>{index}. "
            f"{row['title']}</b>"
            f"{premium}\n"

            f"💰 {harga}\n"

            f"📁 {media_count} Media\n"

            f"👁 {views} Dilihat\n"

            f"❤️ {favorites} Favorite\n"

            f"⭐ {rating:.1f} "
            f"({reviews} ulasan)\n"

            f"🔥 {sold} Terjual\n\n"
        )


        # ==============================
        # OPEN FILE
        # ==============================

        kb.button(
            text=(
                f"📦 "
                f"{str(row['title'])[:30]}"
            ),
            callback_data=(
                f"market:{row['code']}"
            )
        )


    # =====================================
    # BACK MARKETPLACE
    # =====================================

    kb.button(
        text="🛒 Marketplace",
        callback_data="marketplace"
    )


    kb.button(
        text="🏠 Home",
        callback_data="home"
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
