from aiogram import Router, F
from aiogram.types import CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder

from database import fetch, fetchrow

router = Router()


@router.callback_query(F.data == "marketplace")
async def marketplace_menu(call: CallbackQuery):

    await call.answer()

    # ===============================
    # STATISTIK MARKETPLACE
    # ===============================

    stats = await fetchrow(
        """
        SELECT
            COUNT(*) AS total_files,
            COUNT(DISTINCT seller_id) AS total_sellers,
            COALESCE(SUM(sold), 0) AS total_sold
        FROM files
        WHERE is_paid = true
        """
    )

    # ===============================
    # TRENDING FILE
    # ===============================
    #
    # Score:
    #
    # views                = 1x
    # sold                 = 10x
    # favorite             = 5x
    # rating x review      = 3x
    #
    # File yang benar-benar
    # diminati akan naik.
    # ===============================

    files = await fetch(
        """
        SELECT
            code,
            title,
            price,
            media_count,

            COALESCE(sold, 0) AS sold,
            COALESCE(views, 0) AS views,
            COALESCE(favorite_count, 0) AS favorite_count,
            COALESCE(likes, 0) AS likes,
            COALESCE(dislikes, 0) AS dislikes,
            COALESCE(rating, 0) AS rating,
            COALESCE(review_count, 0) AS review_count,

            (
                COALESCE(views, 0)
                + (COALESCE(sold, 0) * 10)
                + (COALESCE(favorite_count, 0) * 5)
                + (
                    COALESCE(rating, 0)
                    * COALESCE(review_count, 0)
                    * 3
                )
            ) AS trending_score

        FROM files

        WHERE is_paid = true

        ORDER BY
            trending_score DESC,
            created_at DESC

        LIMIT 5
        """
    )

    # ===============================
    # HEADER
    # ===============================

    text = (
        "🛒 <b>MARKETPLACE</b>\n"
        "━━━━━━━━━━━━━━━━━━\n\n"

        f"📦 <b>Total File :</b> {stats['total_files']}\n"
        f"👥 <b>Seller :</b> {stats['total_sellers']}\n"
        f"🛍 <b>Terjual :</b> {stats['total_sold']}\n\n"

        "🔥 <b>TRENDING SEKARANG</b>\n"
        "File yang sedang banyak diminati pengguna.\n\n"
    )

    kb = InlineKeyboardBuilder()

    # ===============================
    # JIKA KOSONG
    # ===============================

    if not files:

        text += (
            "📭 Belum ada file yang dijual.\n\n"
            "Jadilah creator pertama di marketplace!"
        )

    else:

        for index, f in enumerate(files, start=1):

            # ===============================
            # MEDALI
            # ===============================

            if index == 1:
                rank = "🥇"

            elif index == 2:
                rank = "🥈"

            elif index == 3:
                rank = "🥉"

            else:
                rank = f"{index}️⃣"

            # ===============================
            # DATA
            # ===============================

            title = f["title"] or "Tanpa Judul"

            price = f["price"] or 0

            media_count = f["media_count"] or 0

            views = f["views"] or 0

            favorites = f["favorite_count"] or 0
            likes = f["likes"] or 0
            dislikes = f["dislikes"] or 0

            sold = f["sold"] or 0

            review_count = f["review_count"] or 0

            rating = float(
                f["rating"] or 0
            )

            score = int(
                f["trending_score"] or 0
            )

            # ===============================
            # FORMAT HARGA
            # ===============================

            if price:

                price_text = (
                    f"Rp {price:,}"
                    .replace(",", ".")
                )

            else:

                price_text = "Gratis"

            # ===============================
            # FILE CARD
            # ===============================

            text += (
                f"{rank} <b>{title}</b>\n"
                f"💰 {price_text}\n"
                f"📁 {media_count} Media\n"
                f"👁 {views:,} "
                f"| 👍 {likes:,} "
                f"| 👎 {dislikes:,}\n"
                f"❤️ {favorites:,} "
                f"| 🔥 {sold:,}\n"
                f"⭐ {rating:.1f} "
                f"({review_count} ulasan)\n"
                f"📈 Score: {score:,}\n\n"
            )

            # ===============================
            # BUTTON FILE
            # ===============================

            kb.button(
                text=f"📦 {title[:25]}",
                callback_data=f"open_code:{f['code']}"
            )

    # ===============================
    # MENU MARKETPLACE
    # ===============================

    kb.button(
        text="🔍 Cari File",
        callback_data="search_code"
    )

    kb.button(
        text="🔥 Terlaris",
        callback_data="top_code"
    )

    kb.button(
        text="🆕 Terbaru",
        callback_data="new_code"
    )

    kb.button(
        text="📂 Kategori",
        callback_data="category_code"
    )

    kb.button(
        text="🏷 Semua File",
        callback_data="market_all"
    )

    kb.button(
        text="⭐ Rating",
        callback_data="market_rating"
    )

    kb.button(
        text="💬 Review Terbanyak",
        callback_data="market_reviews"
    )

    kb.button(
        text="❤️ Favorit",
        callback_data="market_favorite"
    )

    kb.button(
        text="🛍 Pembelian Saya",
        callback_data="market_purchase"
    )

    kb.button(
        text="🏠 Home",
        callback_data="home"
    )

    # ===============================
    # LAYOUT
    # ===============================

    kb.adjust(
        1,  # file 1
        1,  # file 2
        1,  # file 3
        1,  # file 4
        1,  # file 5

        2,  # cari + terlaris
        2,  # terbaru + kategori
        2,  # semua + rating
        2,  # review + favorit
        2,  # pembelian + home
        1
    )

    # ===============================
    # SEND
    # ===============================

    await call.message.edit_text(
        text,
        parse_mode="HTML",
        reply_markup=kb.as_markup()
    )
