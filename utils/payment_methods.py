from __future__ import annotations

import os
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from database import get_pool

OWNER_USERNAME = "ownergbot"


def enabled(value, default=False) -> bool:
    if value is None:
        return default
    return str(value).strip().lower() in {"on", "1", "true", "yes"}


async def payment_methods_enabled() -> dict[str, bool]:
    pool = await get_pool()
    async def get(key: str, default: str = "off") -> bool:
        value = await pool.fetchval("SELECT value FROM settings WHERE key=$1", key)
        return enabled(value, enabled(default))

    return {
        "cashi": await get("payment_cashi_enabled", "on") and bool(os.getenv("CASHI_API_KEY", "").strip()),
        "bayargg": await get("payment_bayargg_enabled", "on") and bool(os.getenv("BAYARGG_API_KEY", "").strip()),
        "manual": await get("payment_manual_enabled", "on") and bool(await pool.fetchval("SELECT value FROM settings WHERE key=$1", "manual_qr_message_id")),
        "binance": await get("payment_binance_enabled", "off"),
    }


def payment_selector_markup(prefix: str, lang: str, methods: dict[str, bool]) -> InlineKeyboardMarkup:
    lang = lang if lang in {"id", "en", "zh"} else "id"
    labels = {
        "id": {"qr": "📲 QR", "cashi": "📲 QR Otomatis 1 • Cashi", "bayargg": "⚡ QR Otomatis 2 • BayarGG", "manual": "📷 QR Manual", "binance": "₿ Binance / USDT → @ownergbot", "cancel": "❌ Batal"},
        "en": {"qr": "📲 QR", "cashi": "📲 Automatic QR 1 • Cashi", "bayargg": "⚡ Automatic QR 2 • BayarGG", "manual": "📷 Manual QR", "binance": "₿ Binance / USDT → @ownergbot", "cancel": "❌ Cancel"},
        "zh": {"qr": "📲 二维码", "cashi": "📲 自动二维码 1 • Cashi", "bayargg": "⚡ 自动二维码 2 • BayarGG", "manual": "📷 手动二维码", "binance": "₿ Binance / USDT → @ownergbot", "cancel": "❌ 取消"},
    }[lang]
    rows = []
    if methods.get("cashi") or methods.get("bayargg") or methods.get("manual"):
        rows.append([InlineKeyboardButton(text=labels["qr"], callback_data=f"{prefix}:qr")])
    if methods.get("binance"):
        rows.append([InlineKeyboardButton(text=labels["binance"], url=f"https://t.me/{OWNER_USERNAME}")])
    rows.append([InlineKeyboardButton(text=labels["cancel"], callback_data=f"{prefix}:cancel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def qr_selector_markup(prefix: str, lang: str, methods: dict[str, bool]) -> InlineKeyboardMarkup:
    lang = lang if lang in {"id", "en", "zh"} else "id"
    labels = {
        "id": {"cashi": "📲 QR Otomatis 1 • Cashi", "bayargg": "⚡ QR Otomatis 2 • BayarGG", "manual": "📷 QR Manual", "back": "🔙 Kembali"},
        "en": {"cashi": "📲 Automatic QR 1 • Cashi", "bayargg": "⚡ Automatic QR 2 • BayarGG", "manual": "📷 Manual QR", "back": "🔙 Back"},
        "zh": {"cashi": "📲 自动二维码 1 • Cashi", "bayargg": "⚡ 自动二维码 2 • BayarGG", "manual": "📷 手动二维码", "back": "🔙 返回"},
    }[lang]
    rows=[]
    if methods.get("cashi"):
        rows.append([InlineKeyboardButton(text=labels["cashi"], callback_data=f"{prefix}:cashi")])
    if methods.get("bayargg"):
        rows.append([InlineKeyboardButton(text=labels["bayargg"], callback_data=f"{prefix}:bayargg")])
    if methods.get("manual"):
        rows.append([InlineKeyboardButton(text=labels["manual"], callback_data=f"{prefix}:manual")])
    rows.append([InlineKeyboardButton(text=labels["back"], callback_data=f"{prefix}:back")])
    return InlineKeyboardMarkup(inline_keyboard=rows)
