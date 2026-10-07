from __future__ import annotations
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
def _button(
    text: str,
    callback_data: str | None = None,
    url: str | None = None,
) -> InlineKeyboardButton:
    return InlineKeyboardButton(
        text=text,
        callback_data=callback_data,
        url=url,
    )
# ============================================================
# HOME
# ============================================================
def home_kb(
    user_id: int,
    lang: str = "id",
    is_creator: bool = False,
) -> InlineKeyboardMarkup:
    """Clean 2-column main dashboard keyboard."""
    labels = {
        "id": ("📤 Up File", "📥 Get File", "⭐ Poin", "🛍️ Marketplace", "👤 Akun", "💎 VIP / 🎨 Kreator", "📂 Menu Lainnya", "❓ Help"),
        "en": ("📤 Up File", "📥 Get File", "⭐ Points", "🛍️ Marketplace", "👤 Account", "💎 VIP / 🎨 Creator", "📂 More Menu", "❓ Help"),
        "zh": ("📤 上传文件", "📥 获取文件", "⭐ 积分", "🛍️ 市场", "👤 账户", "💎 VIP / 🎨 创作者", "📂 更多菜单", "❓ 帮助"),
    }
    L=labels.get(lang,labels["id"])
    return InlineKeyboardMarkup(inline_keyboard=[
        [_button(L[0],callback_data="upfile"),_button(L[1],callback_data="getfile")],
        [_button(L[2],callback_data="points"),_button(L[3],callback_data="marketplace")],
        [_button(L[4],callback_data="account"),_button(L[5],callback_data="vip_creator")],
        [_button(L[6],callback_data="menu_lainnya"),_button(L[7],callback_data="help")],
    ])

# ============================================================
# ACCOUNT
# ============================================================
def account_kb(
    lang: str = "id",
    is_creator: bool = False,
) -> InlineKeyboardMarkup:
    idn = lang == "id"
    rows = [
        [
            _button(
                "⚙️ Pengaturan" if idn else "⚙️ Settings",
                callback_data="account_settings",
            )
        ],
        [
            _button(
                "🎨 Kreator" if idn else "🎨 Creator",
                callback_data="creator",
            ),
            _button(
                "💎 VIP",
                callback_data="vvip",
            ),
        ],
    ]
    if is_creator:
        rows.append(
            [
                _button(
                    "💸 Withdraw",
                    callback_data="withdraw",
                )
            ]
        )
    rows.append(
        [
            _button(
                "⬅️ Kembali" if idn else "⬅️ Back",
                callback_data="home",
            )
        ]
    )
    return InlineKeyboardMarkup(
        inline_keyboard=rows
    )
# ============================================================
# SETTINGS
# ============================================================
def settings_kb(
    lang: str = "id",
) -> InlineKeyboardMarkup:
    idn = lang == "id"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                _button(
                    "💳 Setting Withdraw"
                    if idn
                    else "💳 Withdraw Settings",
                    callback_data="ewallet",
                )
            ],
            [
                _button(
                    "🌐 Bahasa" if idn else "🌐 Language",
                    callback_data="change_language",
                )
            ],
            [
                _button(
                    "⬅️ Account",
                    callback_data="account",
                )
            ],
        ]
    )
# ============================================================
# OTHER MENU
# ============================================================
def other_menu_kb(lang: str = "id") -> InlineKeyboardMarkup:
    idn = lang == "id"
    labels = (
        "📤 Share Code" if idn else "📤 Share Code",
        "📦 Code Saya" if idn else "📦 My Code",
        "🌐 Pilih Bahasa" if idn else "🌐 Language",
        "🏦 Metode Bank" if idn else "🏦 Bank Method",
        "💸 Withdraw" if idn else "💸 Withdraw",
        "⭐ Channel Review" if idn else "⭐ Review Channel",
        "💳 Channel Transaksi" if idn else "💳 Transaction Channel",
        "🔔 Channel Notifikasi" if idn else "🔔 Notification Channel",
        "❓ Help / Bantuan" if idn else "❓ Help",
        "⬅️ Kembali" if idn else "⬅️ Back",
    )
    callbacks = (
        "share_code", "my_code", "change_language", "ewallet", "withdraw",
        "channel_review", "channel_transaction", "channel_notification",
        "help", "home"
    )
    rows = []
    for i in range(0, len(labels), 2):
        row = [_button(labels[i], callback_data=callbacks[i])]
        if i + 1 < len(labels):
            row.append(_button(labels[i+1], callback_data=callbacks[i+1]))
        rows.append(row)
    return InlineKeyboardMarkup(inline_keyboard=rows)
