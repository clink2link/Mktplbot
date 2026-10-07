"""Text notification / direct-code detection handler.

Responsibilities:
- Detect Pastelebot codes sent as ordinary text.
- Open valid codes with an inline button.
- Offer upload when the text is not a valid code.
- Keep FSM handlers untouched.
- Use the user's selected language.
- Use Telegram typing feedback without creating noisy loading messages.
"""

from __future__ import annotations

import re

from aiogram import BaseMiddleware, Router, F
from aiogram.enums import ChatAction
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    Message,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)

from database import get_pool
from utils.user_lang import get_user_language


router = Router()


# =========================================================
# CODE REGEX
# =========================================================

# Pastelebot_ + exactly 14 alphanumeric characters.
CODE_REGEX = re.compile(
    r"(?<![A-Za-z0-9])Pastelebot_[A-Za-z0-9]{14}(?![A-Za-z0-9])",
    re.IGNORECASE,
)


def normalize_code(code: str) -> str:
    """Normalize a code safely for lookup."""
    if not code:
        return ""

    return re.sub(r"\s+", "", code).strip()


# =========================================================
# LANGUAGE
# =========================================================

async def user_lang(user_id: int) -> str:
    """Return normalized user language."""
    try:
        lang = await get_user_language(user_id)
    except Exception:
        lang = "id"

    lang = str(lang or "id").lower().strip()

    if lang not in {"id", "en", "zh"}:
        return "id"

    return lang


# =========================================================
# LOADING / TYPING
# =========================================================

async def send_typing(message: Message) -> None:
    """Show Telegram's native typing status.

    We intentionally do NOT send a temporary 'Loading...' message.
    This avoids message spam and unnecessary Telegram API requests.
    """
    try:
        await message.bot.send_chat_action(
            chat_id=message.chat.id,
            action=ChatAction.TYPING,
        )
    except Exception:
        pass


# =========================================================
# KEYBOARDS
# =========================================================

def kb_open(code: str, lang: str = "id") -> InlineKeyboardMarkup:
    labels = {
        "id": "📂 Buka Code",
        "en": "📂 Open Code",
        "zh": "📂 打开代码",
    }

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=labels.get(lang, labels["id"]),
                    callback_data=f"open_code:{code}",
                )
            ]
        ]
    )


def kb_upload(lang: str = "id") -> InlineKeyboardMarkup:
    labels = {
        "id": "📤 Buat Code / Upload",
        "en": "📤 Create Code / Upload",
        "zh": "📤 创建代码 / 上传",
    }

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=labels.get(lang, labels["id"]),
                    callback_data="upfile",
                )
            ]
        ]
    )


def kb_channel(lang: str = "id") -> InlineKeyboardMarkup:
    labels = {
        "id": ("📢 Channel", "🏠 Menu Utama"),
        "en": ("📢 Channel", "🏠 Main Menu"),
        "zh": ("📢 频道", "🏠 主菜单"),
    }

    channel_text, home_text = labels.get(lang, labels["id"])

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=channel_text,
                    callback_data="channel",
                )
            ],
            [
                InlineKeyboardButton(
                    text=home_text,
                    callback_data="home",
                )
            ],
        ]
    )


def kb_vip(lang: str = "id") -> InlineKeyboardMarkup:
    labels = {
        "id": ("👑 Buka VIP", "🏠 Menu Utama"),
        "en": ("👑 Open VIP", "🏠 Main Menu"),
        "zh": ("👑 打开 VIP", "🏠 主菜单"),
    }

    vip_text, home_text = labels.get(lang, labels["id"])

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=vip_text,
                    callback_data="vip",
                )
            ],
            [
                InlineKeyboardButton(
                    text=home_text,
                    callback_data="home",
                )
            ],
        ]
    )


def kb_marketplace(lang: str = "id") -> InlineKeyboardMarkup:
    labels = {
        "id": ("🛍 Marketplace", "🏠 Menu Utama"),
        "en": ("🛍 Marketplace", "🏠 Main Menu"),
        "zh": ("🛍 市场", "🏠 主菜单"),
    }

    market_text, home_text = labels.get(lang, labels["id"])

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=market_text,
                    callback_data="marketplace",
                )
            ],
            [
                InlineKeyboardButton(
                    text=home_text,
                    callback_data="home",
                )
            ],
        ]
    )


def kb_creator(lang: str = "id") -> InlineKeyboardMarkup:
    labels = {
        "id": ("🎨 Buka Kreator", "🏠 Menu Utama"),
        "en": ("🎨 Open Creator", "🏠 Main Menu"),
        "zh": ("🎨 打开创作者", "🏠 主菜单"),
    }

    creator_text, home_text = labels.get(lang, labels["id"])

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=creator_text,
                    callback_data="creator",
                )
            ],
            [
                InlineKeyboardButton(
                    text=home_text,
                    callback_data="home",
                )
            ],
        ]
    )


# =========================================================
# TEXTS
# =========================================================

VIP_TEXT = {
    "id": (
        "👑 <b>VIP / VVIP</b>\n\n"
        "✨ Konten VIP tersedia di sini.\n\n"
        "Silakan tekan tombol di bawah "
        "untuk membuka menu VIP."
    ),
    "en": (
        "👑 <b>VIP / VVIP</b>\n\n"
        "✨ VIP content is available here.\n\n"
        "Press the button below to open the VIP menu."
    ),
    "zh": (
        "👑 <b>VIP / VVIP</b>\n\n"
        "✨ VIP 内容已在这里提供。\n\n"
        "点击下方按钮打开 VIP 菜单。"
    ),
}


MARKETPLACE_TEXT = {
    "id": (
        "🛍 <b>MARKETPLACE</b>\n\n"
        "🔥 Code dan media yang tersedia "
        "dapat kamu temukan di Marketplace.\n\n"
        "Silakan buka Marketplace untuk "
        "melihat semua code yang tersedia."
    ),
    "en": (
        "🛍 <b>MARKETPLACE</b>\n\n"
        "🔥 Available codes and media can be "
        "found in the Marketplace.\n\n"
        "Open Marketplace to see all available codes."
    ),
    "zh": (
        "🛍 <b>市场</b>\n\n"
        "🔥 你可以在市场中找到可用的代码和媒体。\n\n"
        "打开市场查看所有可用代码。"
    ),
}


CREATOR_TEXT = {
    "id": (
        "🎨 <b>PROGRAM KREATOR</b>\n\n"
        "🚀 Jadilah Kreator dan dapatkan "
        "penghasilan dari code yang kamu upload.\n\n"
        "✨ Kamu dapat mengelola code, "
        "menjualnya melalui Marketplace, "
        "dan mendapatkan penghasilan dari "
        "setiap penjualan.\n\n"
        "Tekan tombol di bawah untuk membuka "
        "Program Kreator."
    ),
    "en": (
        "🎨 <b>CREATOR PROGRAM</b>\n\n"
        "🚀 Become a Creator and earn income "
        "from the codes you upload.\n\n"
        "✨ Manage your codes, sell them through "
        "the Marketplace, and earn from every sale.\n\n"
        "Press the button below to open the Creator Program."
    ),
    "zh": (
        "🎨 <b>创作者计划</b>\n\n"
        "🚀 成为创作者，通过上传代码赚取收入。\n\n"
        "✨ 你可以管理代码，在市场中出售，"
        "并从每笔销售中获得收入。\n\n"
        "点击下方按钮打开创作者计划。"
    ),
}


CHANNEL_TEXT = {
    "id": (
        "📢 <b>MENU CHANNEL</b>\n\n"
        "Silakan buka daftar channel yang tersedia."
    ),
    "en": (
        "📢 <b>CHANNEL MENU</b>\n\n"
        "Open the list of available channels."
    ),
    "zh": (
        "📢 <b>频道菜单</b>\n\n"
        "打开可用频道列表。"
    ),
}


CODE_FOUND_TEXT = {
    "id": (
        "🔑 <b>CODE TERDETEKSI</b>\n\n"
        "✅ Kode file ditemukan.\n\n"
        "Tekan tombol di bawah untuk membuka file."
    ),
    "en": (
        "🔑 <b>CODE DETECTED</b>\n\n"
        "✅ File code found.\n\n"
        "Press the button below to open the file."
    ),
    "zh": (
        "🔑 <b>检测到代码</b>\n\n"
        "✅ 找到文件代码。\n\n"
        "点击下方按钮打开文件。"
    ),
}


CODE_NOT_FOUND_TEXT = {
    "id": (
        "❌ <b>CODE TIDAK DITEMUKAN</b>\n\n"
        "Kode tidak tersedia di database."
    ),
    "en": (
        "❌ <b>CODE NOT FOUND</b>\n\n"
        "That code is not available in the database."
    ),
    "zh": (
        "❌ <b>未找到代码</b>\n\n"
        "该代码不在数据库中。"
    ),
}


NOT_CODE_TEXT = {
    "id": (
        "👋 <b>Pesan bukan CODE.</b>\n\n"
        "Kalau ingin membuat code, upload file terlebih dahulu."
    ),
    "en": (
        "👋 <b>This is not a code.</b>\n\n"
        "To create a code, upload a file first."
    ),
    "zh": (
        "👋 <b>这不是代码。</b>\n\n"
        "如果要创建代码，请先上传文件。"
    ),
}


FALLBACK_TEXT = {
    "id": (
        "🤖 <b>BOT MARKET</b>\n\n"
        "🔎 Pesan sedang diproses.\n\n"
        "Gunakan menu yang tersedia untuk melanjutkan."
    ),
    "en": (
        "🤖 <b>BOT MARKET</b>\n\n"
        "🔎 Your message is being processed.\n\n"
        "Use the available menu to continue."
    ),
    "zh": (
        "🤖 <b>BOT MARKET</b>\n\n"
        "🔎 正在处理你的消息。\n\n"
        "使用可用菜单继续。"
    ),
}


# =========================================================
# TEXT HANDLER
# =========================================================

@router.message(F.text)
async def notify_text(
    message: Message,
    state: FSMContext,
):
    """Handle ordinary text without interfering with active FSM."""

    current_state = await state.get_state()

    # Never intercept active upload/getfile/payment FSM.
    if current_state:
        return

    text = (message.text or "").strip()

    if not text:
        return

    # Commands belong to their own handlers.
    if text.startswith("/"):
        return

    lang = await user_lang(message.from_user.id)
    lower = text.casefold()

    # Native Telegram typing feedback.
    await send_typing(message)

    # =====================================================
    # VIP / VVIP
    # =====================================================

    if lower in {"vip", "vvip"}:
        await message.answer(
            VIP_TEXT[lang],
            parse_mode="HTML",
            reply_markup=kb_vip(lang),
        )
        return

    # =====================================================
    # MARKETPLACE
    # =====================================================

    if lower in {"video", "viral"}:
        await message.answer(
            MARKETPLACE_TEXT[lang],
            parse_mode="HTML",
            reply_markup=kb_marketplace(lang),
        )
        return

    # =====================================================
    # CREATOR
    # =====================================================

    if lower in {"kreator", "creator"}:
        await message.answer(
            CREATOR_TEXT[lang],
            parse_mode="HTML",
            reply_markup=kb_creator(lang),
        )
        return

    # =====================================================
    # CHANNEL
    # =====================================================

    if lower in {
        "group",
        "grup",
        "channel",
        "ch",
        "info",
        "bokep",
        "bocil",
        "indo",
        "ngewe",
    }:
        await message.answer(
            CHANNEL_TEXT[lang],
            parse_mode="HTML",
            reply_markup=kb_channel(lang),
        )
        return

    # =====================================================
    # CODE DETECTION
    # =====================================================

    match = CODE_REGEX.search(text)

    if match:
        code = normalize_code(match.group(0))

        if not code:
            await message.answer(
                CODE_NOT_FOUND_TEXT[lang],
                parse_mode="HTML",
                reply_markup=kb_upload(lang),
            )
            return

        # IMPORTANT:
        # Compare LOWER(code) with LOWER(input).
        # The previous implementation compared:
        #
        #   LOWER(TRIM(code)) = $1
        #
        # while $1 could still contain uppercase letters.
        #
        # This caused valid Pastelebot codes to return NOT FOUND.
        pool = await get_pool()

        exists = await pool.fetchval(
            """
            SELECT EXISTS (
                SELECT 1
                FROM files
                WHERE LOWER(TRIM(code)) = LOWER(TRIM($1))
            )
            """,
            code,
        )

        if exists:
            # SINGLE CODE ENTRY POINT:
            # Every code typed directly in chat must enter the
            # canonical Get File flow. Do not create a separate
            # "found code" menu here and do not send media here.
            try:
                await message.bot.send_chat_action(
                    chat_id=message.chat.id,
                    action=ChatAction.TYPING,
                )
            except Exception:
                pass

            from handlers.getfile import process_code
            return await process_code(message, code)

        await message.answer(
            CODE_NOT_FOUND_TEXT[lang],
            parse_mode="HTML",
            reply_markup=kb_upload(lang),
        )
        return

    # =====================================================
    # DEFAULT
    # =====================================================

    await message.answer(
        NOT_CODE_TEXT[lang],
        parse_mode="HTML",
        reply_markup=kb_upload(lang),
    )


# =========================================================
# MEDIA
# =========================================================

# Media is intentionally NOT handled here.
#
# Upload media:
#     handlers.upfile
#
# Get File code:
#     handlers.getfile
#
# This prevents this generic router from interfering with
# upload sessions and media processing.


# =========================================================
# FALLBACK
# =========================================================

@router.message()
async def notify_other(
    message: Message,
    state: FSMContext,
):
    """Fallback for unsupported message types."""

    current_state = await state.get_state()

    if current_state:
        return

    lang = await user_lang(message.from_user.id)

    await send_typing(message)

    await message.answer(
        FALLBACK_TEXT[lang],
        parse_mode="HTML",
        reply_markup=kb_upload(lang),
    )
