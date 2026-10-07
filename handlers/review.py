from html import escape
from urllib.parse import quote
from aiogram import Router, F
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.types import (
    CallbackQuery,
    Message,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from database import get_pool
from utils.share_unlock import share_url, get_share_status
router = Router()
# ============================================================================
# CONSTANTS
# ============================================================================
MAX_REVIEW_LENGTH = 1000
MAX_REVIEWS_PER_PAGE = 10
MAX_MARKET_REVIEWS = 20
# Telegram callback_data maksimal 64 byte.
# Kita batasi callback code secara defensif.
MAX_CALLBACK_CODE_LENGTH = 40
# ============================================================================
# LANGUAGE
# ============================================================================
async def lang_of(user_id: int) -> str:
    """
    Get user's language from database.
    Returns:
        "id" -> Indonesian
        "en" -> English
    Safe fallback:
        Indonesian
    """
    try:
        pool = await get_pool()
        language = await pool.fetchval(
            """
            SELECT language
            FROM users
            WHERE id = $1
            LIMIT 1
            """,
            user_id,
        )
        language = str(language or "").lower().strip()
        if language in {"en", "english"}:
            return "en"
        return "id"
    except Exception:
        # Language lookup must never break the actual handler.
        return "id"
# ============================================================================
# SAFE CALLBACK ANSWER
# ============================================================================
async def safe_answer(
    call: CallbackQuery,
    text: str | None = None,
    show_alert: bool = False,
):
    """
    Safely acknowledge Telegram callback query.
    IMPORTANT:
    This must be called as early as possible in callback handlers.
    Telegram callback queries have a limited lifetime. If database queries
    or message edits happen before call.answer(), Telegram may return:
        Bad Request:
        query is too old and response timeout expired or query ID is invalid
    """
    try:
        return await call.answer(
            text=text,
            show_alert=show_alert,
        )
    except TelegramBadRequest as e:
        error_text = str(e).lower()
        # Callback sudah expired / invalid.
        # Tidak perlu membuat polling/handler crash.
        if (
            "query is too old" in error_text
            or "query id is invalid" in error_text
            or "response timeout expired" in error_text
        ):
            return None
        raise
# ============================================================================
# SAFE MESSAGE EDIT
# ============================================================================
async def safe_edit_message(
    call: CallbackQuery,
    text: str,
    reply_markup: InlineKeyboardMarkup | None = None,
):
    """
    Safely edit the callback message.
    Handles common Telegram errors:
    - message is not modified
    - message was deleted
    - message can't be edited
    """
    if not call.message:
        return None
    try:
        return await call.message.edit_text(
            text,
            parse_mode="HTML",
            reply_markup=reply_markup,
        )
    except TelegramBadRequest as e:
        error_text = str(e).lower()
        if (
            "message is not modified" in error_text
            or "message to edit not found" in error_text
            or "message can't be edited" in error_text
        ):
            return None
        raise
    except TelegramForbiddenError:
        return None
# ============================================================================
# REVIEW STATE
# ============================================================================
class ReviewState(StatesGroup):
    waiting_text = State()
# ============================================================================
# DATABASE
# ============================================================================
async def ensure_review_table(pool):
    """
    Compatibility helper.
    IMPORTANT:
    For production, file_reviews should be created by the main SQL
    migration instead of being created on every user request.
    This function is intentionally NOT called from every callback anymore.
    """
    await pool.execute(
        """
        CREATE TABLE IF NOT EXISTS file_reviews (
            id BIGSERIAL PRIMARY KEY,
            user_id BIGINT NOT NULL,
            file_code TEXT NOT NULL,
            review TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT NOW(),
            updated_at TIMESTAMP DEFAULT NOW(),
            UNIQUE(user_id, file_code)
        )
        """
    )
# ============================================================================
# START REVIEW
# ============================================================================
@router.callback_query(F.data.startswith("review:"))
async def review_start(
    call: CallbackQuery,
    state: FSMContext,
):
    """
    Start writing/editing a review.
    IMPORTANT:
    callback is acknowledged BEFORE database queries.
    """
    # ------------------------------------------------------------------------
    # ACK CALLBACK IMMEDIATELY
    # ------------------------------------------------------------------------
    await safe_answer(call)
    # ------------------------------------------------------------------------
    # VALIDATE CALLBACK
    # ------------------------------------------------------------------------
    data = call.data or ""
    code = data.split(":", 1)[1].strip() if ":" in data else ""
    if not code:
        return await safe_answer(
            call,
            "❌ Code tidak valid.",
            show_alert=True,
        )
    # ------------------------------------------------------------------------
    # LANGUAGE
    # ------------------------------------------------------------------------
    lang = await lang_of(call.from_user.id)
    # ------------------------------------------------------------------------
    # DATABASE
    # ------------------------------------------------------------------------
    try:
        pool = await get_pool()
        exists = await pool.fetchval(
            """
            SELECT 1
            FROM files
            WHERE code = $1
            LIMIT 1
            """,
            code,
        )
    except Exception:
        if lang == "en":
            error_text = "❌ Failed to access the database. Please try again."
        else:
            error_text = "❌ Gagal mengakses database. Silakan coba lagi."
        return await safe_edit_message(
            call,
            error_text,
        )
    if not exists:
        return await safe_answer(
            call,
            "❌ Code not found."
            if lang == "en"
            else "❌ Code tidak ditemukan.",
            show_alert=True,
        )
    # ------------------------------------------------------------------------
    # SAVE STATE
    # ------------------------------------------------------------------------
    await state.update_data(
        review_code=code,
    )
    await state.set_state(
        ReviewState.waiting_text
    )
    # ------------------------------------------------------------------------
    # TEXT
    # ------------------------------------------------------------------------
    if lang == "en":
        text = (
            "💬 <b>WRITE A REVIEW</b>\n\n"
            "Share your experience with this code/media.\n"
            "A clear review helps other buyers make better decisions.\n\n"
            "Type <b>cancel</b> to cancel."
        )
        cancel_text = "⬅️ Cancel"
    else:
        text = (
            "💬 <b>TULIS REVIEW</b>\n\n"
            "Tulis pengalaman kamu tentang code/media ini.\n"
            "Review yang jelas membantu pembeli lain mengambil keputusan.\n\n"
            "Ketik <b>batal</b> untuk membatalkan."
        )
        cancel_text = "⬅️ Batal"
    # ------------------------------------------------------------------------
    # KEYBOARD
    # ------------------------------------------------------------------------
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=cancel_text,
                    callback_data=f"market:{code}",
                )
            ]
        ]
    )
    # ------------------------------------------------------------------------
    # EDIT MESSAGE
    # ------------------------------------------------------------------------
    return await safe_edit_message(
        call,
        text,
        keyboard,
    )
# ============================================================================
# SAVE REVIEW
# ============================================================================
@router.message(ReviewState.waiting_text)
async def review_save(
    message: Message,
    state: FSMContext,
):
    """
    Save or update user's review.
    """
    lang = await lang_of(
        message.from_user.id
    )
    text = (message.text or "").strip()
    data = await state.get_data()
    code = str(
        data.get("review_code") or ""
    ).strip()
    # ------------------------------------------------------------------------
    # SESSION EXPIRED
    # ------------------------------------------------------------------------
    if not code:
        await state.clear()
        return await message.answer(
            "❌ Sesi review berakhir. Silakan buka detail code lagi."
            if lang == "id"
            else
            "❌ Your review session has expired. Please open the code details again."
        )
    # ------------------------------------------------------------------------
    # CANCEL
    # ------------------------------------------------------------------------
    if text.lower() in {
        "batal",
        "cancel",
        "/cancel",
    }:
        await state.clear()
        return await message.answer(
            "↩️ Review dibatalkan."
            if lang == "id"
            else
            "↩️ Review cancelled."
        )
    # ------------------------------------------------------------------------
    # VALIDATION
    # ------------------------------------------------------------------------
    if len(text) < 3:
        return await message.answer(
            "⚠️ Review terlalu singkat. Tulis minimal 3 karakter."
            if lang == "id"
            else
            "⚠️ Your review is too short. Please write at least 3 characters."
        )
    # Limit review length.
    text = text[:MAX_REVIEW_LENGTH]
    # ------------------------------------------------------------------------
    # DATABASE
    # ------------------------------------------------------------------------
    try:
        pool = await get_pool()
        # NOTE:
        # Do NOT create the table on every request.
        #
        # The table should exist from the production SQL migration.
        # --------------------------------------------------------------------
        # CHECK CODE
        # --------------------------------------------------------------------
        file_exists = await pool.fetchval(
            """
            SELECT 1
            FROM files
            WHERE code = $1
            LIMIT 1
            """,
            code,
        )
        if not file_exists:
            await state.clear()
            return await message.answer(
                "❌ Code tidak ditemukan."
                if lang == "id"
                else
                "❌ Code not found."
            )
        # --------------------------------------------------------------------
        # SAVE / UPDATE REVIEW
        # --------------------------------------------------------------------
        await pool.execute(
            """
            INSERT INTO file_reviews (
                user_id,
                file_code,
                review
            )
            VALUES ($1, $2, $3)
            ON CONFLICT (user_id, file_code)
            DO UPDATE SET
                review = EXCLUDED.review,
                updated_at = NOW()
            """,
            message.from_user.id,
            code,
            text,
        )
        # --------------------------------------------------------------------
        # UPDATE REVIEW COUNT
        # --------------------------------------------------------------------
        await pool.execute(
            """
            UPDATE files
            SET review_count = (
                SELECT COUNT(*)
                FROM file_reviews
                WHERE file_code = $1
            )
            WHERE code = $1
            """,
            code,
        )
    except Exception:
        return await message.answer(
            "❌ Gagal menyimpan review. Silakan coba lagi."
            if lang == "id"
            else
            "❌ Failed to save the review. Please try again."
        )
    # ------------------------------------------------------------------------
    # CLEAR STATE
    # ------------------------------------------------------------------------
    await state.clear()
    # ------------------------------------------------------------------------
    # SUCCESS
    # ------------------------------------------------------------------------
    return await message.answer(
        "✅ Review berhasil disimpan. Terima kasih sudah membantu marketplace!"
        if lang == "id"
        else
        "✅ Your review has been saved. Thank you for helping the marketplace!"
    )
# ============================================================================
# REVIEW LIST
# ============================================================================
@router.callback_query(F.data.startswith("reviews:"))
async def review_list(
    call: CallbackQuery,
):
    """
    Display latest reviews for a code.
    """
    # ------------------------------------------------------------------------
    # ACK FIRST
    # ------------------------------------------------------------------------
    await safe_answer(call)
    # ------------------------------------------------------------------------
    # CALLBACK DATA
    # ------------------------------------------------------------------------
    data = call.data or ""
    code = data.split(":", 1)[1].strip() if ":" in data else ""
    if not code:
        return await safe_answer(
            call,
            "❌ Code tidak valid.",
            show_alert=True,
        )
    # ------------------------------------------------------------------------
    # LANGUAGE
    # ------------------------------------------------------------------------
    lang = await lang_of(
        call.from_user.id
    )
    # ------------------------------------------------------------------------
    # DATABASE
    # ------------------------------------------------------------------------
    try:
        pool = await get_pool()
        rows = await pool.fetch(
            """
            SELECT
                user_id,
                review,
                created_at
            FROM file_reviews
            WHERE file_code = $1
            ORDER BY created_at DESC
            LIMIT $2
            """,
            code,
            MAX_REVIEWS_PER_PAGE,
        )
    except Exception:
        return await safe_edit_message(
            call,
            (
                "❌ Failed to load reviews. Please try again."
                if lang == "en"
                else
                "❌ Gagal memuat review. Silakan coba lagi."
            ),
        )
    # ------------------------------------------------------------------------
    # LANGUAGE TEXT
    # ------------------------------------------------------------------------
    if lang == "en":
        title = "💬 <b>LATEST REVIEWS</b>"
        empty = "No reviews for this code yet."
        write_review = "💬 Write Review"
        back = "⬅️ Back"
    else:
        title = "💬 <b>REVIEW TERBARU</b>"
        empty = "Belum ada review untuk code ini."
        write_review = "💬 Tulis Review"
        back = "⬅️ Kembali"
    # ------------------------------------------------------------------------
    # EMPTY
    # ------------------------------------------------------------------------
    if not rows:
        text = (
            f"{title}\n\n"
            f"📭 {empty}"
        )
    # ------------------------------------------------------------------------
    # REVIEWS
    # ------------------------------------------------------------------------
    else:
        parts = [
            title,
            "━━━━━━━━━━━━━━━━━━",
        ]
        for i, row in enumerate(rows, 1):
            user_id = escape(
                str(row["user_id"])
            )
            review = escape(
                str(row["review"])
            )
            parts.append(
                f"\n"
                f"<b>{i}.</b> User <code>{user_id}</code>\n"
                f"{review}"
            )
        text = "\n".join(parts)
    # ------------------------------------------------------------------------
    # KEYBOARD
    # ------------------------------------------------------------------------
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=write_review,
                    callback_data=f"review:{code}",
                )
            ],
            [
                InlineKeyboardButton(
                    text=back,
                    callback_data=f"market:{code}",
                )
            ],
        ]
    )
    # ------------------------------------------------------------------------
    # EDIT
    # ------------------------------------------------------------------------
    return await safe_edit_message(
        call,
        text,
        keyboard,
    )
# ============================================================================
# SHARE CODE
# ============================================================================
@router.callback_query(F.data.startswith("share:"))
async def share_code(
    call: CallbackQuery,
):
    """
    Show share options for a code.
    """
    # ------------------------------------------------------------------------
    # ACK FIRST
    # ------------------------------------------------------------------------
    await safe_answer(call)
    # ------------------------------------------------------------------------
    # CALLBACK DATA
    # ------------------------------------------------------------------------
    data = call.data or ""
    code = data.split(":", 1)[1].strip() if ":" in data else ""
    if not code:
        return await safe_answer(
            call,
            "❌ Code tidak valid.",
            show_alert=True,
        )
    # ------------------------------------------------------------------------
    # LANGUAGE
    # ------------------------------------------------------------------------
    lang = await lang_of(
        call.from_user.id
    )
    # ------------------------------------------------------------------------
    # DATABASE
    # ------------------------------------------------------------------------
    try:
        pool = await get_pool()
        row = await pool.fetchrow(
            """
            SELECT title
            FROM files
            WHERE code = $1
            LIMIT 1
            """,
            code,
        )
    except Exception:
        return await safe_edit_message(
            call,
            (
                "❌ Failed to load this code. Please try again."
                if lang == "en"
                else
                "❌ Gagal memuat code. Silakan coba lagi."
            ),
        )
    if not row:
        return await safe_answer(
            call,
            "❌ Code not found."
            if lang == "en"
            else "❌ Code tidak ditemukan.",
            show_alert=True,
        )
    # ------------------------------------------------------------------------
    # BOT USERNAME
    # ------------------------------------------------------------------------
    try:
        me = await call.bot.get_me()
        bot_username = me.username
    except Exception:
        bot_username = None
    if not bot_username:
        return await safe_answer(
            call,
            (
                "❌ Bot username is not configured."
                if lang == "en"
                else
                "❌ Bot username belum dikonfigurasi."
            ),
            show_alert=True,
        )
    # ------------------------------------------------------------------------
    # DEEP LINK
    # ------------------------------------------------------------------------
    target = share_url(
        bot_username,
        code,
        call.from_user.id,
        row["title"] or code,
    ).split("&text=", 1)[0]
    share_text_id = (
        "🤖 Coba code Telegram ini dari Marketplace!"
    )
    share_text_en = (
        "🤖 Check out this Telegram code from the Marketplace!"
    )
    share_url = (
        "https://t.me/share/url?"
        f"url={quote(target)}&"
        f"text={quote(share_text_id if lang == 'id' else share_text_en)}"
    )
    # ------------------------------------------------------------------------
    # TEXT
    # ------------------------------------------------------------------------
    if lang == "en":
        text = (
            "📤 <b>SHARE CODE</b>\n\n"
            "Share this code with friends or potential buyers.\n"
            "Progress increases when a genuinely new member opens the bot from this link."
        )
        share_now = "📤 Share Now"
        progress = "🎁 Check Progress"
        back = "⬅️ Back"
    else:
        text = (
            "📤 <b>BAGIKAN CODE</b>\n\n"
            "Bagikan code ini ke teman atau calon pembeli.\n"
            "Progress bertambah saat member baru membuka bot melalui link ini."
        )
        share_now = "📤 Bagikan Sekarang"
        progress = "🎁 Cek Progress"
        back = "⬅️ Kembali"
    # ------------------------------------------------------------------------
    # KEYBOARD
    # ------------------------------------------------------------------------
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=share_now,
                    url=share_url,
                )
            ],
            [
                InlineKeyboardButton(
                    text=progress,
                    callback_data=f"freeopen:{code}",
                )
            ],
            [
                InlineKeyboardButton(
                    text=back,
                    callback_data=f"market:{code}",
                )
            ],
        ]
    )
    # ------------------------------------------------------------------------
    # EDIT
    # ------------------------------------------------------------------------
    return await safe_edit_message(
        call,
        text,
        keyboard,
    )
# ============================================================================
# MARKETPLACE - MOST REVIEWED
# ============================================================================
@router.callback_query(F.data == "market_reviews")
async def market_reviews(
    call: CallbackQuery,
):
    """
    Display most reviewed marketplace codes.
    IMPORTANT:
    Callback is acknowledged before ANY database operation.
    """
    # ------------------------------------------------------------------------
    # CRITICAL FIX:
    # ANSWER CALLBACK IMMEDIATELY
    # ------------------------------------------------------------------------
    await safe_answer(call)
    # ------------------------------------------------------------------------
    # LANGUAGE
    # ------------------------------------------------------------------------
    lang = await lang_of(
        call.from_user.id
    )
    # ------------------------------------------------------------------------
    # DATABASE
    # ------------------------------------------------------------------------
    try:
        pool = await get_pool()
        rows = await pool.fetch(
            """
            SELECT
                f.code,
                f.title,
                COALESCE(f.review_count, 0) AS review_count,
                COALESCE(f.rating, 0) AS rating,
                COALESCE(f.sold, 0) AS sold
            FROM files f
            WHERE COALESCE(f.review_count, 0) > 0
            ORDER BY
                review_count DESC,
                rating DESC,
                sold DESC
            LIMIT $1
            """,
            MAX_MARKET_REVIEWS,
        )
    except Exception:
        return await safe_edit_message(
            call,
            (
                "❌ Failed to load marketplace reviews. Please try again."
                if lang == "en"
                else
                "❌ Gagal memuat review marketplace. Silakan coba lagi."
            ),
        )
    # ------------------------------------------------------------------------
    # HEADER
    # ------------------------------------------------------------------------
    if lang == "en":
        text = (
            "💬 <b>MOST REVIEWED CODES</b>\n"
            "━━━━━━━━━━━━━━━━━━\n\n"
        )
        empty = "No reviews yet."
        marketplace = "⬅️ Marketplace"
        review_label = "reviews"
        sold_label = "sold"
    else:
        text = (
            "💬 <b>CODE PALING BANYAK DIREVIEW</b>\n"
            "━━━━━━━━━━━━━━━━━━\n\n"
        )
        empty = "Belum ada review."
        marketplace = "⬅️ Marketplace"
        review_label = "review"
        sold_label = "terjual"
    # ------------------------------------------------------------------------
    # EMPTY
    # ------------------------------------------------------------------------
    if not rows:
        text += f"📭 {empty}"
    # ------------------------------------------------------------------------
    # ROWS
    # ------------------------------------------------------------------------
    rows_kb = []
    for i, row in enumerate(rows, 1):
        code = str(
            row["code"] or ""
        ).strip()
        if not code:
            continue
        title = str(
            row["title"] or code
        ).strip()
        safe_title = escape(
            title
        )
        review_count = int(
            row["review_count"] or 0
        )
        sold = int(
            row["sold"] or 0
        )
        try:
            rating = float(
                row["rating"] or 0
            )
        except (TypeError, ValueError):
            rating = 0.0
        text += (
            f"{i}. <b>{safe_title}</b>\n"
            f"💬 {review_count} {review_label} • "
            f"⭐ {rating:.1f} • "
            f"🔥 {sold} {sold_label}\n\n"
        )
        # --------------------------------------------------------------------
        # CALLBACK CODE
        # --------------------------------------------------------------------
        #
        # Telegram callback_data has a 64-byte limit.
        # Existing system uses market:<code>.
        #
        # Keep defensive limit for compatibility.
        #
        callback_code = code[
            :MAX_CALLBACK_CODE_LENGTH
        ]
        # Prevent oversized button text.
        button_title = title[:25]
        rows_kb.append(
            [
                InlineKeyboardButton(
                    text=f"💬 {button_title}",
                    callback_data=f"market:{callback_code}",
                )
            ]
        )
    # ------------------------------------------------------------------------
    # BACK BUTTON
    # ------------------------------------------------------------------------
    rows_kb.append(
        [
            InlineKeyboardButton(
                text=marketplace,
                callback_data="marketplace",
            )
        ]
    )
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=rows_kb
    )
    # ------------------------------------------------------------------------
    # EDIT MESSAGE
    # ------------------------------------------------------------------------
    return await safe_edit_message(
        call,
        text,
        keyboard,
    )
