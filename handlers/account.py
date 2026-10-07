from __future__ import annotations

import html
import logging
from urllib.parse import quote

from aiogram import Router, F
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)

from database import get_pool
from config import BOT_USERNAME
from keyboards.menu import account_kb


router = Router()

logger = logging.getLogger(__name__)

CREATOR_REQUIRED_REFERRAL = 100


# ============================================================
# HELPERS
# ============================================================

def safe_html(value) -> str:
    """
    Escape value agar aman digunakan di HTML Telegram.
    """
    return html.escape(str(value or ""))


def rupiah(value) -> str:
    """
    Format angka menjadi Rupiah.
    """
    try:
        return f"Rp {int(value):,}".replace(",", ".")
    except (TypeError, ValueError):
        return "Rp 0"


async def safe_callback_answer(
    call: CallbackQuery,
    text: str | None = None,
    *,
    show_alert: bool = False,
) -> bool:
    """
    ACK callback secepat mungkin.

    Telegram callback mempunyai waktu respons yang pendek.
    Jangan melakukan database query sebelum fungsi ini.
    """
    try:
        await call.answer(
            text=text,
            show_alert=show_alert,
        )
        return True

    except TelegramBadRequest as exc:
        error = str(exc).lower()

        if (
            "query is too old" in error
            or "query id is invalid" in error
            or "response timeout expired" in error
        ):
            logger.debug(
                "Account callback expired: %s",
                error,
            )
            return False

        logger.warning(
            "Account callback error: %s",
            exc,
        )
        return False

    except TelegramForbiddenError:
        return False

    except Exception:
        logger.exception(
            "Unexpected callback answer error"
        )
        return False


async def safe_edit(
    message: Message,
    text: str,
    *,
    reply_markup=None,
    parse_mode: str = "HTML",
    disable_web_page_preview: bool = False,
) -> bool:
    """
    Edit message dengan aman.
    """
    try:
        await message.edit_text(
            text,
            parse_mode=parse_mode,
            reply_markup=reply_markup,
            disable_web_page_preview=disable_web_page_preview,
        )
        return True

    except TelegramBadRequest as exc:
        error = str(exc).lower()

        if "message is not modified" in error:
            return True

        logger.debug(
            "Account edit ignored: %s",
            exc,
        )
        return False

    except TelegramForbiddenError:
        return False

    except Exception:
        logger.exception(
            "Account message edit error"
        )
        return False


async def safe_answer(
    message: Message,
    text: str,
    *,
    reply_markup=None,
    parse_mode: str = "HTML",
) -> bool:
    """
    Kirim message dengan aman.
    """
    try:
        await message.answer(
            text,
            parse_mode=parse_mode,
            reply_markup=reply_markup,
        )
        return True

    except (
        TelegramBadRequest,
        TelegramForbiddenError,
    ):
        logger.warning(
            "Account answer failed"
        )
        return False

    except Exception:
        logger.exception(
            "Account answer unexpected error"
        )
        return False


def loading_keyboard(
    lang: str = "id",
) -> InlineKeyboardMarkup:
    """
    Keyboard sederhana ketika proses loading.
    """
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=(
                        "⏳ Memuat..."
                        if lang == "id"
                        else "⏳ Loading..."
                    ),
                    callback_data="account_loading",
                )
            ]
        ]
    )


# ============================================================
# LOADING CALLBACK
# ============================================================

@router.callback_query(
    F.data == "account_loading"
)
async def account_loading(
    call: CallbackQuery,
):
    """
    Tombol loading sengaja tidak melakukan apa-apa.
    Tetap ACK supaya Telegram tidak menampilkan spinner.
    """
    await safe_callback_answer(call)


# ============================================================
# OPEN ACCOUNT
# ============================================================

async def open_account(
    message: Message,
    user_id: int,
):
    """
    Tampilkan halaman Account.
    """

    pool = await get_pool()

    try:
        user = await pool.fetchrow(
            """
            SELECT
                referral_count,
                is_creator,
                creator_status,
                creator_verified_at,
                balance,
                language
            FROM users
            WHERE user_id = $1
            """,
            user_id,
        )

    except Exception:
        logger.exception(
            "ACCOUNT DATABASE ERROR user=%s",
            user_id,
        )

        await safe_edit(
            message,
            (
                "❌ <b>Gagal memuat Account</b>\n\n"
                "Terjadi masalah saat mengambil "
                "data akun.\n\n"
                "Silakan coba lagi."
            ),
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="🔄 Coba Lagi",
                            callback_data="account",
                        )
                    ]
                ]
            ),
        )
        return

    if not user:
        await safe_edit(
            message,
            "❌ Data akun tidak ditemukan.",
        )
        return

    referral_count = int(
        user["referral_count"] or 0
    )

    is_creator = bool(
        user["is_creator"]
    )

    creator_status = (
        user["creator_status"]
        or "none"
    )

    creator_verified_at = (
        user["creator_verified_at"]
    )

    balance = (
        user["balance"]
        or 0
    )

    lang = (
        user["language"]
        or "id"
    )

    if lang not in ("id", "en"):
        lang = "id"

    # ========================================================
    # REFERRAL LINK
    # ========================================================

    bot_username = str(
        BOT_USERNAME or ""
    ).lstrip("@")

    ref_link = (
        f"https://t.me/{bot_username}"
        f"?start=ref_{user_id}"
    )

    # ========================================================
    # CREATOR STATUS
    # ========================================================

    if (
        is_creator
        and creator_status == "approved"
    ):
        creator_text = (
            "🎨 <b>STATUS KREATOR</b>\n"
            "✅ <b>Terverifikasi</b>\n"
        )

        if creator_verified_at:
            creator_text += (
                "📅 Verifikasi : "
                f"<b>{creator_verified_at:%d-%m-%Y}</b>\n"
            )

    elif creator_status == "pending":

        creator_text = (
            "🎨 <b>STATUS KREATOR</b>\n"
            "⏳ <b>Menunggu Verifikasi Admin</b>\n"
        )

    elif creator_status == "rejected":

        creator_text = (
            "🎨 <b>STATUS KREATOR</b>\n"
            "❌ <b>Pengajuan Ditolak</b>\n"
        )

    elif referral_count >= CREATOR_REQUIRED_REFERRAL:

        creator_text = (
            "🎨 <b>STATUS KREATOR</b>\n"
            "🔓 <b>Syarat Terpenuhi</b>\n"
            f"👥 Referral : "
            f"<b>{referral_count}/"
            f"{CREATOR_REQUIRED_REFERRAL}</b>\n"
        )

    else:

        remaining = (
            CREATOR_REQUIRED_REFERRAL
            - referral_count
        )

        creator_text = (
            "🎨 <b>STATUS KREATOR</b>\n"
            "🔒 <b>Belum Memenuhi Syarat</b>\n"
            f"👥 Referral : "
            f"<b>{referral_count}/"
            f"{CREATOR_REQUIRED_REFERRAL}</b>\n"
            f"📊 Kekurangan : "
            f"<b>{remaining} referral</b>\n"
        )

    # ========================================================
    # ACCOUNT TEXT
    # ========================================================

    text = (
        "👤 <b>ACCOUNT INFO</b>\n"
        "━━━━━━━━━━━━━━━━━━\n\n"

        "🆔 <b>User ID</b>\n"
        f"<code>{user_id}</code>\n\n"

        "💰 <b>Saldo</b>\n"
        f"<b>{rupiah(balance)}</b>\n\n"

        "🎯 <b>REFERRAL</b>\n"
        f"👥 Total Undangan : "
        f"<b>{referral_count}</b>\n\n"

        "🔗 <b>Link Referral</b>\n"
        f"<code>{safe_html(ref_link)}</code>\n\n"

        f"{creator_text}\n"
    )

    # ========================================================
    # ACCOUNT KEYBOARD
    # ========================================================

    try:
        menu = account_kb(
            lang=lang,
            is_creator=(
                is_creator
                and creator_status == "approved"
            ),
        )
    except Exception:
        logger.exception(
            "ACCOUNT KEYBOARD ERROR"
        )

        menu = InlineKeyboardMarkup(
            inline_keyboard=[]
        )

    if menu is None:
        menu = InlineKeyboardMarkup(
            inline_keyboard=[]
        )

    # ========================================================
    # SHARE REFERRAL
    # ========================================================

    share_text = quote(
        "🤖 Gabung marketplace bot saya! "
        "Upload, jual, beli, dan bagikan code Telegram."
    )

    share_url = (
        "https://t.me/share/url"
        f"?url={quote(ref_link)}"
        f"&text={share_text}"
    )

    share_button = InlineKeyboardButton(
        text=(
            "📤 Bagikan Referral"
            if lang == "id"
            else "📤 Share Referral"
        ),
        url=share_url,
    )

    # Jangan memodifikasi object keyboard
    # secara berbahaya jika keyboard berasal dari cache.
    keyboard_rows = list(
        menu.inline_keyboard or []
    )

    keyboard_rows.insert(
        0,
        [share_button],
    )

    final_menu = InlineKeyboardMarkup(
        inline_keyboard=keyboard_rows
    )

    # ========================================================
    # SHOW ACCOUNT
    # ========================================================

    await safe_edit(
        message,
        text,
        reply_markup=final_menu,
        disable_web_page_preview=True,
    )


# ============================================================
# OPEN ACCOUNT FROM CALLBACK
# ============================================================

@router.callback_query(
    F.data == "account"
)
async def account_handler(
    call: CallbackQuery,
):
    """
    Account callback.

    ACK HARUS dilakukan sebelum database.
    """

    await safe_callback_answer(call)

    if not call.message:
        return

    # Loading langsung
    await safe_edit(
        call.message,
        (
            "⏳ <b>Memuat Account...</b>\n"
            "━━━━━━━━━━━━━━"
        ),
        reply_markup=loading_keyboard(
            "id"
        ),
    )

    await open_account(
        call.message,
        call.from_user.id,
    )


# ============================================================
# ACCOUNT REPLY BUTTON
# ============================================================

@router.message(
    F.text.in_(
        [
            "👤 Akun",
            "👤 Account",
        ]
    )
)
async def account(
    message: Message,
):
    """
    Account dari reply keyboard.
    """

    loading = await message.answer(
        "⏳ <b>Memuat Account...</b>",
        parse_mode="HTML",
    )

    await open_account(
        loading,
        message.from_user.id,
    )


# ============================================================
# WITHDRAW LOCKED
# ============================================================

@router.callback_query(
    F.data == "withdraw_locked"
)
async def withdraw_locked(
    call: CallbackQuery,
):
    """
    Tampilkan alasan Withdraw terkunci.
    """

    await safe_callback_answer(call)

    pool = await get_pool()

    try:
        user = await pool.fetchrow(
            """
            SELECT
                referral_count,
                is_creator,
                creator_status
            FROM users
            WHERE user_id = $1
            """,
            call.from_user.id,
        )

    except Exception:
        logger.exception(
            "WITHDRAW LOCKED DB ERROR"
        )

        await safe_callback_answer(
            call,
            "❌ Gagal mengambil data akun.",
            show_alert=True,
        )
        return

    if not user:
        await safe_callback_answer(
            call,
            "❌ Data akun tidak ditemukan.",
            show_alert=True,
        )
        return

    referral_count = int(
        user["referral_count"] or 0
    )

    is_creator = bool(
        user["is_creator"]
    )

    creator_status = (
        user["creator_status"]
        or "none"
    )

    if (
        is_creator
        and creator_status == "approved"
    ):
        await safe_callback_answer(
            call,
            (
                "✅ Kamu sudah menjadi Kreator.\n"
                "Silakan buka menu Withdraw."
            ),
            show_alert=True,
        )
        return

    if creator_status == "pending":
        await safe_callback_answer(
            call,
            (
                "⏳ Pengajuan Kreator kamu "
                "sedang diperiksa admin."
            ),
            show_alert=True,
        )
        return

    if referral_count >= CREATOR_REQUIRED_REFERRAL:
        await safe_callback_answer(
            call,
            (
                "🔒 Withdraw masih terkunci.\n\n"
                "Kamu sudah memenuhi 100 referral. "
                "Silakan ajukan verifikasi Kreator."
            ),
            show_alert=True,
        )
        return

    remaining = (
        CREATOR_REQUIRED_REFERRAL
        - referral_count
    )

    await safe_callback_answer(
        call,
        (
            "🔒 WITHDRAW TERKUNCI\n\n"
            "Withdraw hanya tersedia untuk "
            "Kreator terverifikasi.\n\n"
            f"👥 Referral : "
            f"{referral_count}/"
            f"{CREATOR_REQUIRED_REFERRAL}\n"
            f"📊 Kekurangan : "
            f"{remaining} referral"
        ),
        show_alert=True,
    )


# ============================================================
# CREATOR STATUS
# ============================================================

@router.callback_query(
    F.data == "creator_status"
)
async def creator_status_handler(
    call: CallbackQuery,
):
    """
    Tampilkan status creator.
    """

    await safe_callback_answer(call)

    if not call.message:
        return

    # Loading
    await safe_edit(
        call.message,
        "⏳ <b>Memuat status kreator...</b>",
    )

    pool = await get_pool()

    try:
        user = await pool.fetchrow(
            """
            SELECT
                referral_count,
                is_creator,
                creator_status,
                creator_verified_at
            FROM users
            WHERE user_id = $1
            """,
            call.from_user.id,
        )

    except Exception:
        logger.exception(
            "CREATOR STATUS DB ERROR"
        )

        await safe_edit(
            call.message,
            (
                "❌ <b>Gagal memuat status kreator.</b>\n\n"
                "Silakan coba lagi."
            ),
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="🔄 Coba Lagi",
                            callback_data="creator_status",
                        )
                    ],
                    [
                        InlineKeyboardButton(
                            text="🔙 Account",
                            callback_data="account",
                        )
                    ],
                ]
            ),
        )
        return

    if not user:
        await safe_edit(
            call.message,
            "❌ Data akun tidak ditemukan.",
        )
        return

    referral_count = int(
        user["referral_count"] or 0
    )

    is_creator = bool(
        user["is_creator"]
    )

    status = (
        user["creator_status"]
        or "none"
    )

    verified_at = (
        user["creator_verified_at"]
    )

    # ========================================================
    # APPROVED
    # ========================================================

    if (
        is_creator
        and status == "approved"
    ):

        verified_text = ""

        if verified_at:
            verified_text = (
                "📅 Terverifikasi : "
                f"<b>{verified_at:%d-%m-%Y}</b>\n"
            )

        text = (
            "🎨 <b>STATUS KREATOR</b>\n"
            "━━━━━━━━━━━━━━━━━━\n\n"
            "Status : "
            "✅ <b>Kreator Terverifikasi</b>\n"
            f"{verified_text}\n"
            f"👥 Referral : "
            f"<b>{referral_count}</b>\n\n"
            "🎉 Kamu sudah resmi menjadi Kreator.\n\n"
            "Kamu dapat:\n"
            "📤 Menjual file berbayar\n"
            "💰 Mendapatkan saldo dari penjualan\n"
            "🏦 Melakukan Withdraw\n"
        )

    # ========================================================
    # PENDING
    # ========================================================

    elif status == "pending":

        text = (
            "🎨 <b>STATUS KREATOR</b>\n"
            "━━━━━━━━━━━━━━━━━━\n\n"
            "Status : "
            "⏳ <b>Menunggu Verifikasi</b>\n\n"
            "Pengajuan kamu sedang diperiksa "
            "oleh admin.\n\n"
            "Mohon tunggu sampai proses "
            "verifikasi selesai."
        )

    # ========================================================
    # REJECTED
    # ========================================================

    elif status == "rejected":

        text = (
            "🎨 <b>STATUS KREATOR</b>\n"
            "━━━━━━━━━━━━━━━━━━\n\n"
            "Status : ❌ <b>Ditolak</b>\n\n"
            f"👥 Referral : "
            f"<b>{referral_count}/"
            f"{CREATOR_REQUIRED_REFERRAL}</b>\n\n"
            "Kamu dapat mengajukan verifikasi "
            "kembali."
        )

    # ========================================================
    # READY
    # ========================================================

    elif (
        referral_count
        >= CREATOR_REQUIRED_REFERRAL
    ):

        text = (
            "🎨 <b>STATUS KREATOR</b>\n"
            "━━━━━━━━━━━━━━━━━━\n\n"
            "Status : 🔓 "
            "<b>Syarat Terpenuhi</b>\n\n"
            f"👥 Referral : "
            f"<b>{referral_count}/"
            f"{CREATOR_REQUIRED_REFERRAL}</b>\n\n"
            "🎉 Kamu sudah memenuhi syarat "
            "untuk menjadi Kreator.\n\n"
            "Silakan lanjutkan proses verifikasi."
        )

    # ========================================================
    # NOT ENOUGH
    # ========================================================

    else:

        remaining = (
            CREATOR_REQUIRED_REFERRAL
            - referral_count
        )

        text = (
            "🎨 <b>STATUS KREATOR</b>\n"
            "━━━━━━━━━━━━━━━━━━\n\n"
            "Status : 🔒 "
            "<b>Belum Memenuhi Syarat</b>\n\n"
            f"👥 Referral : "
            f"<b>{referral_count}/"
            f"{CREATOR_REQUIRED_REFERRAL}</b>\n"
            f"📊 Kekurangan : "
            f"<b>{remaining} referral</b>\n\n"
            "Capai 100 referral terlebih dahulu "
            "untuk mengajukan verifikasi."
        )

    # ========================================================
    # BUTTONS
    # ========================================================

    buttons = []

    if (
        not is_creator
        and status in (
            "none",
            "rejected",
        )
        and referral_count >= CREATOR_REQUIRED_REFERRAL
    ):
        buttons.append(
            [
                InlineKeyboardButton(
                    text="🎨 Ajukan Kreator",
                    callback_data="creator_apply",
                )
            ]
        )

    buttons.append(
        [
            InlineKeyboardButton(
                text="🔙 Account",
                callback_data="account",
            )
        ]
    )

    await safe_edit(
        call.message,
        text,
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=buttons
        ),
    )


# ============================================================
# CHANGE LANGUAGE
# ============================================================

@router.callback_query(
    F.data == "change_language"
)
async def change_language(
    call: CallbackQuery,
):
    """
    Menu pemilihan bahasa.
    """

    await safe_callback_answer(call)

    if not call.message:
        return

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🇮🇩 Indonesia",
                    callback_data="lang:id",
                ),
                InlineKeyboardButton(
                    text="🇬🇧 English",
                    callback_data="lang:en",
                ),
                InlineKeyboardButton(
                    text="🇨🇳 中文",
                    callback_data="lang:zh",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="🔙 Kembali",
                    callback_data="account",
                )
            ],
        ]
    )

    await safe_edit(
        call.message,
        "🌐 <b>Pilih Bahasa / Choose Language / 选择语言</b>",
        reply_markup=kb,
    )
