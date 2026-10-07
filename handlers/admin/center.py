"""Full Admin Control Center for the Pastele bot."""
from aiogram import Router, F
from aiogram.types import CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder
from database import get_pool
from config import ADMIN_IDS, SHOWJS_DATABASE_URL
from handlers.admin.admins import is_admin
from utils.b2_storage import get_b2_accounts

router = Router()

# Only expose switches that are actually consumed by runtime code.
FEATURES = [
    ("maintenance", "🛠 Maintenance", "off"),
    ("scheduler", "⏰ Scheduler", "off"),
    ("telegram_safety_enabled", "🛡 Telegram Safety", "on"),
    ("b2_upload_enabled", "☁️ B2 Upload", "on"),
    ("showjs_bridge_enabled", "🔗 Showjs CODE", "on"),
    ("showjs_b2_enabled", "🗄️ Showjs B2", "on"),
    ("payment_cashi_enabled", "📲 Cashi", "on"),
    ("payment_bayargg_enabled", "⚡ BayarGG", "on"),
    ("payment_manual_enabled", "📷 QR Manual", "off"),
    ("payment_binance_enabled", "₿ Binance/USDT", "off"),
]

async def setting(pool, key, default):
    v = await pool.fetchval("SELECT value FROM settings WHERE key=$1", key)
    return str(v if v is not None else default).lower() in {"1", "true", "on", "yes"}

async def set_setting(pool, key, value):
    await pool.execute(
        """INSERT INTO settings(key,value) VALUES($1,$2)
           ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value""",
        key, "on" if value else "off",
    )

def main_kb():
    kb = InlineKeyboardBuilder()
    buttons = [
        ("👤 Users", "admin_users"),
        ("📂 Files / CODE", "admin_files"),
        ("💳 Payments", "admin_payments"),
        ("🏧 Withdraw", "admin_withdraw"),
        ("💰 Balance / Points", "admin_balance"),
        ("📢 Broadcast", "admin_broadcast"),
        ("🗄️ B2 Storage", "admin_b2"),
        ("🔗 Showjs Media", "admin_showjs"),
        ("⚙️ Feature Control", "admin_features"),
        ("🩺 Health / Repair", "admin_health"),
        ("🛡️ Settings", "admin_settings"),
        ("📜 Logs", "admin_logs"),
        ("👮 Admins", "admin_admins"),
        ("📊 Dashboard", "admin_home"),
    ]
    for label, data in buttons:
        kb.button(text=label, callback_data=data)
    kb.adjust(2, 2, 2, 2, 2, 2, 2)
    return kb.as_markup()

async def render(call):
    if not is_admin(call.from_user.id):
        return await call.answer("❌ Tidak memiliki akses", show_alert=True)
    pool = await get_pool()
    users = await pool.fetchval("SELECT COUNT(*) FROM users") or 0
    files = await pool.fetchval("SELECT COUNT(*) FROM files") or 0
    pending = await pool.fetchval("SELECT COUNT(*) FROM payments WHERE status='pending'") or 0
    wd = await pool.fetchval("SELECT COUNT(*) FROM withdraws WHERE status IN ('pending','instant_pending','process','processing')") or 0
    b2 = await get_b2_accounts()
    text = (
        "🎛 <b>PASTELE FULL ADMIN CONTROL CENTER</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"👤 Users: <b>{users}</b>\n"
        f"📂 Files: <b>{files}</b>\n"
        f"💳 Pending payment: <b>{pending}</b>\n"
        f"🏧 Pending/process withdraw: <b>{wd}</b>\n"
        f"☁️ B2 accounts: <b>{len(b2)}</b>\n"
        f"🔗 Showjs DB: <b>{'READY' if SHOWJS_DATABASE_URL else 'NOT SET'}</b>\n\n"
        "Pilih modul di bawah untuk mengelola bot tanpa menyentuh source code."
    )
    await call.message.edit_text(text, parse_mode="HTML", reply_markup=main_kb())
    await call.answer()

@router.callback_query(F.data == "admin_center")
async def admin_center(call: CallbackQuery):
    await render(call)

@router.callback_query(F.data == "admin_features")
async def admin_features(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        return await call.answer("❌ Tidak memiliki akses", show_alert=True)
    pool = await get_pool()
    kb = InlineKeyboardBuilder()
    lines = ["🎛 <b>FEATURE CONTROL</b>", "━━━━━━━━━━━━━━━━━━━━"]
    for key, label, default in FEATURES:
        enabled = await setting(pool, key, default)
        lines.append(f"{label}: <b>{'🟢 ON' if enabled else '🔴 OFF'}</b>")
        kb.button(text=f"{label} {'🟢' if enabled else '🔴'}", callback_data=f"admin_feature:{key}")
    kb.button(text="💳 Payment Methods", callback_data="admin_payment_methods")
    kb.button(text="⚙️ Advanced Settings", callback_data="admin_settings")
    kb.button(text="⬅️ Control Center", callback_data="admin_center")
    kb.adjust(2, 2, 2, 2, 2, 2, 1)
    await call.message.edit_text("\n".join(lines), parse_mode="HTML", reply_markup=kb.as_markup())
    await call.answer()

@router.callback_query(F.data.startswith("admin_feature:"))
async def admin_feature_toggle(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        return await call.answer("❌ Tidak memiliki akses", show_alert=True)
    key = call.data.split(":", 1)[1]
    entry = next((x for x in FEATURES if x[0] == key), None)
    if not entry:
        return await call.answer("❌ Feature tidak valid", show_alert=True)
    pool = await get_pool()
    current = await setting(pool, key, entry[2])
    await set_setting(pool, key, not current)
    await call.answer(f"{entry[1]} {'ON' if not current else 'OFF'}")
    await admin_features(call)

@router.callback_query(F.data == "admin_showjs")
async def admin_showjs(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        return await call.answer("❌ Tidak memiliki akses", show_alert=True)
    pool = await get_pool()
    bridge = await setting(pool, "showjs_bridge_enabled", "on")
    b2 = await setting(pool, "showjs_b2_enabled", "on")
    accounts = await get_b2_accounts()
    text = (
        "🔗 <b>SHOWJS MEDIA CONTROL</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"DB Showjs: <b>{'READY' if SHOWJS_DATABASE_URL else 'NOT SET'}</b>\n"
        f"CODE bridge: <b>{'ON' if bridge else 'OFF'}</b>\n"
        f"Showjs B2: <b>{'ON' if b2 else 'OFF'}</b>\n"
        f"B2 accounts: <b>{len(accounts)}</b>\n\n"
        "Media Showjs dibaca dari DB Showjs dan object B2 sesuai drive_account."
    )
    kb = InlineKeyboardBuilder()
    kb.button(text="🔗 Toggle CODE", callback_data="admin_feature:showjs_bridge_enabled")
    kb.button(text="🗄️ Toggle B2", callback_data="admin_feature:showjs_b2_enabled")
    kb.button(text="☁️ Kelola B2", callback_data="admin_b2")
    kb.button(text="🩺 Health", callback_data="admin_health")
    kb.button(text="⬅️ Control Center", callback_data="admin_center")
    kb.adjust(2, 2, 1)
    await call.message.edit_text(text, parse_mode="HTML", reply_markup=kb.as_markup())
    await call.answer()

@router.callback_query(F.data == "admin_admins")
async def admin_admins(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        return await call.answer("❌ Tidak memiliki akses", show_alert=True)
    text = (
        "👮 <b>ADMIN MANAGEMENT</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"Admin aktif dari ADMIN_IDS: <b>{len(ADMIN_IDS)}</b>\n\n"
        "Gunakan Settings untuk menambah owner/admin.\n"
        "Catatan: daftar ADMIN_IDS berasal dari environment host; perubahan permanen harus disimpan di environment."
    )
    kb = InlineKeyboardBuilder()
    kb.button(text="⚙️ Manage Admin/Owner", callback_data="admin_settings")
    kb.button(text="⬅️ Control Center", callback_data="admin_center")
    kb.adjust(1)
    await call.message.edit_text(text, parse_mode="HTML", reply_markup=kb.as_markup())
    await call.answer()
