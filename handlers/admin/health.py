"""Admin Control Center: diagnostics and safe repairs for the Pastele bot."""
import asyncio
import os
import signal
from aiogram import Router, F
from aiogram.types import CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder

from config import ADMIN_IDS
from database import get_pool, init_db
from handlers.admin.admins import is_admin
from utils.b2_storage import get_b2_accounts, check_b2_account

router = Router()

CONTROL_KEYS = (
    ("b2_upload_enabled", "☁️ B2 Upload"),
    ("admin_auto_repair", "🛠 Auto Repair"),
)

async def _setting(pool, key, default="off"):
    value = await pool.fetchval("SELECT value FROM settings WHERE key=$1", key)
    return str(value if value is not None else default).lower() in {"on", "1", "true", "yes"}

async def _set_setting(pool, key, value):
    await pool.execute(
        """INSERT INTO settings(key,value) VALUES($1,$2)
           ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value""",
        key, "on" if value else "off"
    )

def _kb():
    kb = InlineKeyboardBuilder()
    kb.button(text="🩺 Cek Sistem", callback_data="admin_health")
    kb.button(text="🛠 Perbaiki Aman", callback_data="admin_repair")
    kb.button(text="☁️ Cek Semua B2", callback_data="admin_b2_health")
    for key, label in CONTROL_KEYS:
        kb.button(text=label, callback_data=f"admin_ctl:{key}")
    kb.button(text="🔄 Refresh", callback_data="admin_control")
    kb.button(text="♻️ Restart Bot", callback_data="admin_restart_confirm")
    kb.button(text="⬅️ Admin", callback_data="admin_home")
    kb.adjust(2, 2, 2, 2, 1)
    return kb.as_markup()

async def _status_text():
    pool = await get_pool()
    lines = ["🎛 <b>CONTROL CENTER</b>", "━━━━━━━━━━━━━━━━━━"]
    for key, label in CONTROL_KEYS:
        enabled = await _setting(pool, key, "on")
        lines.append(f"{label}: <b>{'🟢 ON' if enabled else '🔴 OFF'}</b>")
    try:
        b2 = await get_b2_accounts()
        lines.append(f"\n☁️ B2 configured: <b>{len(b2)}</b>")
        targets = [x for x in b2 if x.get("is_target")]
        lines.append(f"🎯 B2 target: <b>{targets[0]['account_id'] if targets else 'AUTO'}</b>")
    except Exception:
        lines.append("\n☁️ B2: <b>ERROR</b>")
    return "\n".join(lines)

@router.callback_query(F.data == "admin_control")
async def admin_control(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        return await call.answer("❌ Tidak memiliki akses", show_alert=True)
    await call.message.edit_text(await _status_text(), parse_mode="HTML", reply_markup=_kb())
    await call.answer()

@router.callback_query(F.data == "admin_health")
async def admin_health(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        return await call.answer("❌ Tidak memiliki akses", show_alert=True)
    checks = []
    try:
        pool = await get_pool()
        await pool.fetchval("SELECT 1")
        checks.append("🟢 Main DB")
        required = ["users", "files", "settings", "point_transactions", "point_code_unlocks", "b2_storage_accounts"]
        rows = await pool.fetch("""
            SELECT table_name FROM information_schema.tables
            WHERE table_schema='public' AND table_name = ANY($1::text[])
        """, required)
        found = {r["table_name"] for r in rows}
        missing = [x for x in required if x not in found]
        checks.append("🟢 Schema" if not missing else f"🔴 Schema missing: {', '.join(missing)}")
    except Exception as exc:
        checks.append(f"🔴 Main DB: {str(exc)[:160]}")


    try:
        me = await call.bot.get_me()
        checks.append(f"🟢 Telegram: @{me.username or me.id}")
    except Exception as exc:
        checks.append(f"🔴 Telegram: {str(exc)[:160]}")

    try:
        accounts = await get_b2_accounts()
        if not accounts:
            checks.append("🟡 B2: belum ada account")
        else:
            checks.append(f"🟢 B2 config: {len(accounts)} account")
    except Exception as exc:
        checks.append(f"🔴 B2 config: {str(exc)[:160]}")

    text = "🩺 <b>SYSTEM HEALTH</b>\n━━━━━━━━━━━━━━━━━━\n" + "\n".join(checks)
    kb = InlineKeyboardBuilder()
    kb.button(text="🛠 Perbaiki Aman", callback_data="admin_repair")
    kb.button(text="☁️ Cek B2", callback_data="admin_b2_health")
    kb.button(text="⬅️ Control Center", callback_data="admin_control")
    kb.adjust(1)
    await call.message.edit_text(text, parse_mode="HTML", reply_markup=kb.as_markup())
    await call.answer()

@router.callback_query(F.data == "admin_repair")
async def admin_repair(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        return await call.answer("❌ Tidak memiliki akses", show_alert=True)
    try:
        await init_db()
        pool = await get_pool()
        defaults = {
            "b2_upload_enabled": "on",
            "admin_auto_repair": "on",
        }
        for key, value in defaults.items():
            await pool.execute(
                """INSERT INTO settings(key,value) VALUES($1,$2)
                   ON CONFLICT(key) DO NOTHING""", key, value
            )
        await call.answer("✅ Perbaikan aman selesai", show_alert=True)
        await admin_health(call)
    except Exception as exc:
        await call.answer(f"❌ Repair gagal: {str(exc)[:180]}", show_alert=True)

@router.callback_query(F.data == "admin_b2_health")
async def admin_b2_health(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        return await call.answer("❌ Tidak memiliki akses", show_alert=True)
    try:
        accounts = await get_b2_accounts()
        if not accounts:
            text = "☁️ <b>B2 HEALTH</b>\n\n🟡 Belum ada B2."
        else:
            lines = ["☁️ <b>B2 HEALTH</b>", "━━━━━━━━━━━━━━━━━━"]
            for acc in accounts:
                result = await check_b2_account(int(acc["account_id"]))
                icon = "🟢" if result.get("ok") else "🔴"
                lines.append(f"{icon} B2 #{acc['account_id']} — {acc['name']}")
                if not result.get("ok"):
                    lines.append(f"   <code>{str(result.get('error',''))[:180]}</code>")
            text = "\n".join(lines)
    except Exception as exc:
        text = f"☁️ <b>B2 HEALTH</b>\n\n🔴 {str(exc)[:250]}"
    kb = InlineKeyboardBuilder()
    kb.button(text="🔄 Refresh", callback_data="admin_b2_health")
    kb.button(text="⬅️ Control Center", callback_data="admin_control")
    kb.adjust(1)
    await call.message.edit_text(text, parse_mode="HTML", reply_markup=kb.as_markup())
    await call.answer()

@router.callback_query(F.data.startswith("admin_ctl:"))
async def admin_control_toggle(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        return await call.answer("❌ Tidak memiliki akses", show_alert=True)
    key = call.data.split(":", 1)[1]
    valid = {x[0] for x in CONTROL_KEYS}
    if key not in valid:
        return await call.answer("❌ Kontrol tidak valid", show_alert=True)
    pool = await get_pool()
    current = await _setting(pool, key, "on")
    await _set_setting(pool, key, not current)
    await call.answer(f"{'ON' if not current else 'OFF'}")
    await admin_control(call)

@router.callback_query(F.data == "admin_restart_confirm")
async def admin_restart_confirm(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        return await call.answer("❌ Tidak memiliki akses", show_alert=True)
    kb = InlineKeyboardBuilder()
    kb.button(text="⚠️ YA, RESTART", callback_data="admin_restart")
    kb.button(text="❌ Batal", callback_data="admin_control")
    kb.adjust(2)
    await call.message.edit_text(
        "⚠️ <b>RESTART BOT</b>\n\nBot akan berhenti dan Railway/host harus menjalankannya kembali.",
        parse_mode="HTML", reply_markup=kb.as_markup()
    )
    await call.answer()

@router.callback_query(F.data == "admin_restart")
async def admin_restart(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        return await call.answer("❌ Tidak memiliki akses", show_alert=True)
    await call.answer("♻️ Restarting...", show_alert=True)
    await asyncio.sleep(0.5)
    os.kill(os.getpid(), signal.SIGTERM)
