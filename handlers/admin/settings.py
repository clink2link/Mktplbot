from aiogram import Router, F, Bot
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from datetime import datetime
import asyncio

from database import get_pool
from handlers.admin.admins import is_admin
from handlers.qrid import QRIDState


router = Router()


# =========================
# DB SETTINGS
# =========================

async def get_setting(pool, key, default=None):
    value = await pool.fetchval(
        """
        SELECT value
        FROM settings
        WHERE key=$1
        """,
        key
    )

    return value if value is not None else default


async def set_setting(pool, key, value):
    await pool.execute(
        """
        INSERT INTO settings(key, value)
        VALUES($1, $2)

        ON CONFLICT(key)
        DO UPDATE
        SET value = EXCLUDED.value
        """,
        key,
        str(value)
    )


# =========================
# FSM
# =========================

class AdminState(StatesGroup):
    add_admin = State()
    add_owner = State()


class SchedulerState(StatesGroup):
    waiting_time = State()
    waiting_text = State()


class MaintenanceState(StatesGroup):
    waiting_text = State()

class BinanceAddressState(StatesGroup):
    waiting = State()

class BinanceAccountState(StatesGroup):
    waiting = State()

class SafetyState(StatesGroup):
    waiting_user_delay = State()
    waiting_storage_delay = State()
    waiting_channel_delay = State()


# =========================
# SETTINGS MENU
# =========================

@router.callback_query(F.data == "admin_settings")
async def admin_settings(call: CallbackQuery):

    if not is_admin(call.from_user.id):
        return await call.answer(
            "❌ Tidak memiliki akses",
            show_alert=True
        )

    pool = await get_pool()

    maintenance = await get_setting(
        pool,
        "maintenance",
        "off"
    )

    scheduler = await get_setting(
        pool,
        "scheduler",
        "off"
    )

    maintenance_icon = "🟢 ON" if maintenance == "on" else "🔴 OFF"
    scheduler_icon = "🟢 ON" if scheduler == "on" else "🔴 OFF"

    kb = InlineKeyboardMarkup(
        inline_keyboard=[

            [
                InlineKeyboardButton(
                    text="👑 Add Owner",
                    callback_data="add_owner"
                )
            ],

            [
                InlineKeyboardButton(
                    text="🛡 Add Admin",
                    callback_data="add_admin"
                )
            ],

            [
                InlineKeyboardButton(
                    text=f"🛠 Maintenance ({maintenance_icon})",
                    callback_data="set_maintenance"
                )
            ],

            [
                InlineKeyboardButton(
                    text=f"⏰ Scheduler ({scheduler_icon})",
                    callback_data="set_scheduler"
                )
            ],

            [
                InlineKeyboardButton(
                    text="🛡️ Telegram Safety",
                    callback_data="telegram_safety"
                )
            ],
            [
                InlineKeyboardButton(
                    text="🎯 Share Unlock",
                    callback_data="admin_share_unlock"
                )
            ],

            [
                InlineKeyboardButton(
                    text="⬅ Admin Menu",
                    callback_data="admin_home"
                )
            ]

        ]
    )

    await call.message.edit_text(
        (
            "⚙️ <b>ADMIN SETTINGS</b>\n"
            "━━━━━━━━━━━━━━\n\n"
            "Kelola seluruh pengaturan bot dari menu di bawah."
        ),
        parse_mode="HTML",
        reply_markup=kb
    )

    await call.answer()



# =========================
# ADD ADMIN
# =========================

@router.callback_query(F.data == "add_admin")
async def add_admin(
    call: CallbackQuery,
    state: FSMContext
):

    if not is_admin(call.from_user.id):
        return await call.answer(
            "❌ Tidak memiliki akses",
            show_alert=True
        )

    await state.clear()
    await state.set_state(AdminState.add_admin)

    await call.message.answer(
        (
            "🛡 <b>TAMBAH ADMIN</b>\n\n"
            "Kirim Telegram ID user."
        ),
        parse_mode="HTML"
    )

    await call.answer()


@router.message(AdminState.add_admin)
async def save_admin(
    message: Message,
    state: FSMContext
):

    if not message.text or not message.text.isdigit():
        return await message.answer(
            "❌ Telegram ID harus berupa angka."
        )

    user_id = int(message.text)

    pool = await get_pool()

    user = await pool.fetchrow(
        """
        SELECT chat_id
        FROM users
        WHERE chat_id=$1
        """,
        user_id
    )

    if not user:
        await state.clear()
        return await message.answer(
            "❌ User tidak ditemukan."
        )

    await pool.execute(
        """
        INSERT INTO admins(user_id, role)
        VALUES($1,'admin')

        ON CONFLICT(user_id)
        DO UPDATE
        SET role='admin'
        """,
        user_id
    )

    await pool.execute(
        """
        UPDATE users
        SET is_admin=TRUE
        WHERE chat_id=$1
        """,
        user_id
    )

    await message.answer(
        (
            "✅ <b>Admin berhasil ditambahkan.</b>\n\n"
            f"🆔 <code>{user_id}</code>"
        ),
        parse_mode="HTML"
    )

    await state.clear()


# =========================
# ADD OWNER
# =========================

@router.callback_query(F.data == "add_owner")
async def add_owner(
    call: CallbackQuery,
    state: FSMContext
):

    if not is_admin(call.from_user.id):
        return await call.answer(
            "❌ Tidak memiliki akses",
            show_alert=True
        )

    await state.clear()
    await state.set_state(AdminState.add_owner)

    await call.message.answer(
        (
            "👑 <b>TAMBAH OWNER</b>\n\n"
            "Kirim Telegram ID user."
        ),
        parse_mode="HTML"
    )

    await call.answer()


@router.message(AdminState.add_owner)
async def save_owner(
    message: Message,
    state: FSMContext
):

    if not message.text or not message.text.isdigit():
        return await message.answer(
            "❌ Telegram ID harus berupa angka."
        )

    user_id = int(message.text)

    pool = await get_pool()

    user = await pool.fetchrow(
        """
        SELECT chat_id
        FROM users
        WHERE chat_id=$1
        """,
        user_id
    )

    if not user:
        await state.clear()
        return await message.answer(
            "❌ User tidak ditemukan."
        )

    await pool.execute(
        """
        INSERT INTO admins(user_id, role)
        VALUES($1,'owner')

        ON CONFLICT(user_id)
        DO UPDATE
        SET role='owner'
        """,
        user_id
    )

    await pool.execute(
        """
        UPDATE users
        SET is_admin=TRUE
        WHERE chat_id=$1
        """,
        user_id
    )

    await message.answer(
        (
            "👑 <b>Owner berhasil ditambahkan.</b>\n\n"
            f"🆔 <code>{user_id}</code>"
        ),
        parse_mode="HTML"
    )

    await state.clear()



# =========================
# MAINTENANCE
# =========================

@router.callback_query(F.data == "set_maintenance")
async def maintenance_menu(call: CallbackQuery):

    if not is_admin(call.from_user.id):
        return await call.answer(
            "❌ Tidak memiliki akses",
            show_alert=True
        )

    pool = await get_pool()

    status = await get_setting(
        pool,
        "maintenance",
        "off"
    )

    text_status = "🟢 ON" if status == "on" else "🔴 OFF"

    kb = InlineKeyboardMarkup(
        inline_keyboard=[

            [
                InlineKeyboardButton(
                    text=f"{text_status}",
                    callback_data="toggle_maintenance"
                )
            ],

            [
                InlineKeyboardButton(
                    text="✏️ Ubah Pesan",
                    callback_data="set_maint_text"
                )
            ],

            [
                InlineKeyboardButton(
                    text="⬅ Kembali",
                    callback_data="admin_settings"
                )
            ]

        ]
    )

    await call.message.edit_text(
        (
            "🛠 <b>MAINTENANCE MODE</b>\n"
            "━━━━━━━━━━━━━━\n\n"
            f"Status : <b>{text_status}</b>"
        ),
        parse_mode="HTML",
        reply_markup=kb
    )

    await call.answer()


# =========================
# TOGGLE MAINTENANCE
# =========================

@router.callback_query(F.data == "toggle_maintenance")
async def toggle_maintenance(call: CallbackQuery):

    if not is_admin(call.from_user.id):
        return

    pool = await get_pool()

    old = await get_setting(
        pool,
        "maintenance",
        "off"
    )

    new = "off" if old == "on" else "on"

    await set_setting(
        pool,
        "maintenance",
        new
    )

    await call.answer(
        f"Maintenance {new.upper()}",
        show_alert=True
    )

    await maintenance_menu(call)


# =========================
# SET MAINTENANCE MESSAGE
# =========================

@router.callback_query(F.data == "set_maint_text")
async def maint_text(
    call: CallbackQuery,
    state: FSMContext
):

    if not is_admin(call.from_user.id):
        return

    await state.clear()
    await state.set_state(
        MaintenanceState.waiting_text
    )

    await call.message.answer(
        (
            "✏️ <b>UBAH PESAN MAINTENANCE</b>\n\n"
            "Silakan kirim pesan baru."
        ),
        parse_mode="HTML"
    )

    await call.answer()


@router.message(MaintenanceState.waiting_text)
async def save_maint(
    message: Message,
    state: FSMContext
):

    text = (message.text or "").strip()

    if not text:
        return await message.answer(
            "❌ Pesan tidak boleh kosong."
        )

    pool = await get_pool()

    await set_setting(
        pool,
        "maintenance_text",
        text
    )

    await message.answer(
        "✅ Pesan maintenance berhasil disimpan."
    )

    await state.clear()



# =========================
# SCHEDULER
# =========================

@router.callback_query(F.data == "set_scheduler")
async def scheduler_menu(call: CallbackQuery):

    if not is_admin(call.from_user.id):
        return await call.answer(
            "❌ Tidak memiliki akses",
            show_alert=True
        )

    pool = await get_pool()

    status = await get_setting(
        pool,
        "scheduler",
        "off"
    )

    jam = await get_setting(
        pool,
        "schedule_time",
        "09:00"
    )

    status_text = "🟢 ON" if status == "on" else "🔴 OFF"

    kb = InlineKeyboardMarkup(
        inline_keyboard=[

            [
                InlineKeyboardButton(
                    text=status_text,
                    callback_data="toggle_scheduler"
                )
            ],

            [
                InlineKeyboardButton(
                    text="🕒 Set Jam",
                    callback_data="set_time"
                )
            ],

            [
                InlineKeyboardButton(
                    text="📝 Set Pesan",
                    callback_data="set_text"
                )
            ],

            [
                InlineKeyboardButton(
                    text="⬅ Kembali",
                    callback_data="admin_settings"
                )
            ]

        ]
    )

    await call.message.edit_text(
        (
            "⏰ <b>SCHEDULER</b>\n"
            "━━━━━━━━━━━━━━\n\n"
            f"Status : <b>{status_text}</b>\n"
            f"Jam : <code>{jam}</code>"
        ),
        parse_mode="HTML",
        reply_markup=kb
    )

    await call.answer()


# =========================
# TOGGLE SCHEDULER
# =========================

@router.callback_query(F.data == "toggle_scheduler")
async def toggle_scheduler(call: CallbackQuery):

    if not is_admin(call.from_user.id):
        return

    pool = await get_pool()

    old = await get_setting(
        pool,
        "scheduler",
        "off"
    )

    new = "off" if old == "on" else "on"

    await set_setting(
        pool,
        "scheduler",
        new
    )

    await call.answer(
        f"Scheduler {new.upper()}",
        show_alert=True
    )

    await scheduler_menu(call)


# =========================
# SET TIME
# =========================

@router.callback_query(F.data == "set_time")
async def set_time(
    call: CallbackQuery,
    state: FSMContext
):

    await state.clear()
    await state.set_state(
        SchedulerState.waiting_time
    )

    await call.message.answer(
        (
            "🕒 Kirim jam scheduler.\n\n"
            "Format:\n"
            "<code>09:00</code>"
        ),
        parse_mode="HTML"
    )

    await call.answer()


@router.message(SchedulerState.waiting_time)
async def save_time(
    message: Message,
    state: FSMContext
):

    value = (message.text or "").strip()

    try:
        datetime.strptime(value, "%H:%M")
    except ValueError:
        return await message.answer(
            "❌ Format salah.\nGunakan HH:MM"
        )

    pool = await get_pool()

    await set_setting(
        pool,
        "schedule_time",
        value
    )

    await message.answer(
        f"✅ Jam scheduler disimpan : <code>{value}</code>",
        parse_mode="HTML"
    )

    await state.clear()


# =========================
# SET TEXT
# =========================

@router.callback_query(F.data == "set_text")
async def set_text(
    call: CallbackQuery,
    state: FSMContext
):

    await state.clear()

    await state.set_state(
        SchedulerState.waiting_text
    )

    await call.message.answer(
        "📝 Kirim pesan scheduler."
    )

    await call.answer()


@router.message(SchedulerState.waiting_text)
async def save_text(
    message: Message,
    state: FSMContext
):

    text = (message.text or "").strip()

    if not text:
        return await message.answer(
            "❌ Pesan tidak boleh kosong."
        )

    pool = await get_pool()

    await set_setting(
        pool,
        "schedule_text",
        text
    )

    await message.answer(
        "✅ Pesan scheduler berhasil disimpan."
    )

    await state.clear()


# =========================
# WORKER
# =========================

async def scheduler_loop(bot: Bot):

    last = None

    while True:

        try:

            pool = await get_pool()

            enabled = await get_setting(
                pool,
                "scheduler",
                "off"
            )

            jam = await get_setting(
                pool,
                "schedule_time",
                "09:00"
            )

            text = await get_setting(
                pool,
                "schedule_text",
                "Halo!"
            )

            now = datetime.now().astimezone().strftime("%H:%M")

            if enabled == "on" and now == jam and last != now:

                users = await pool.fetch(
                    """
                    SELECT chat_id
                    FROM users
                    """
                )

                for user in users:

                    try:

                        await bot.send_message(
                            chat_id=user["chat_id"],
                            text=text
                        )

                        await asyncio.sleep(0.05)

                    except Exception:
                        pass

                last = now

            await asyncio.sleep(10)

        except Exception as e:

            print("Scheduler Error:", e)

            await asyncio.sleep(10)


# =========================================================
# TELEGRAM SAFETY
# =========================================================

@router.callback_query(F.data == "telegram_safety")
async def telegram_safety(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        return await call.answer("❌ Tidak memiliki akses", show_alert=True)

    pool = await get_pool()
    enabled = await get_setting(pool, "telegram_safety_enabled", "on")
    user_delay = await get_setting(pool, "telegram_user_send_delay", "3")
    storage_delay = await get_setting(pool, "telegram_storage_delay", "1")
    channel_delay = await get_setting(pool, "telegram_channel_delay", "1")
    concurrency = await get_setting(pool, "telegram_storage_concurrency", "1")

    status = "🟢 ON" if enabled == "on" else "🔴 OFF"
    await call.message.edit_text(
        "🛡️ <b>TELEGRAM SAFETY</b>\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        f"Status: <b>{status}</b>\n"
        f"📤 User media delay: <b>{user_delay}s</b>\n"
        f"☁️ Storage delay: <b>{storage_delay}s</b>\n"
        f"📢 Channel update delay: <b>{channel_delay}s</b>\n"
        f"🔒 Storage concurrency: <b>{concurrency}</b>\n\n"
        "Mode konservatif mencegah bot melakukan burst request. "
        "Jika Telegram mengirim RetryAfter, bot tetap mengikuti waktu dari Telegram.",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=f"Safety {status}", callback_data="toggle_telegram_safety")],
            [InlineKeyboardButton(text="📤 Set User Delay", callback_data="safety_user_delay")],
            [InlineKeyboardButton(text="☁️ Set Storage Delay", callback_data="safety_storage_delay")],
            [InlineKeyboardButton(text="📢 Set Channel Delay", callback_data="safety_channel_delay")],
            [InlineKeyboardButton(text="⬅️ Settings", callback_data="admin_settings")],
        ])
    )
    await call.answer()


@router.callback_query(F.data == "toggle_telegram_safety")
async def toggle_telegram_safety(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        return
    pool = await get_pool()
    old = await get_setting(pool, "telegram_safety_enabled", "on")
    new = "off" if old == "on" else "on"
    await set_setting(pool, "telegram_safety_enabled", new)
    await call.answer(f"Telegram Safety {new.upper()}", show_alert=True)
    await telegram_safety(call)


async def _ask_safety_delay(call: CallbackQuery, state: FSMContext, state_obj, title: str):
    if not is_admin(call.from_user.id):
        return
    await state.clear()
    await state.set_state(state_obj)
    await call.message.answer(
        f"🛡️ <b>{title}</b>\n\nKirim angka detik, contoh <code>3</code>.\n"
        "Gunakan angka >= 0.",
        parse_mode="HTML"
    )
    await call.answer()


@router.callback_query(F.data == "safety_user_delay")
async def safety_user_delay(call: CallbackQuery, state: FSMContext):
    await _ask_safety_delay(call, state, SafetyState.waiting_user_delay, "USER MEDIA DELAY")


@router.message(SafetyState.waiting_user_delay)
async def save_safety_user_delay(message: Message, state: FSMContext):
    try:
        value = float((message.text or "").strip())
        if value < 0 or value > 60:
            raise ValueError
    except ValueError:
        return await message.answer("❌ Masukkan angka 0-60 detik.")
    pool = await get_pool()
    await set_setting(pool, "telegram_user_send_delay", value)
    await state.clear()
    await message.answer(f"✅ User media delay disimpan: <b>{value:g}s</b>", parse_mode="HTML")


@router.callback_query(F.data == "safety_storage_delay")
async def safety_storage_delay(call: CallbackQuery, state: FSMContext):
    await _ask_safety_delay(call, state, SafetyState.waiting_storage_delay, "STORAGE DELAY")


@router.message(SafetyState.waiting_storage_delay)
async def save_safety_storage_delay(message: Message, state: FSMContext):
    try:
        value = float((message.text or "").strip())
        if value < 0 or value > 60:
            raise ValueError
    except ValueError:
        return await message.answer("❌ Masukkan angka 0-60 detik.")
    pool = await get_pool()
    await set_setting(pool, "telegram_storage_delay", value)
    await state.clear()
    await message.answer(f"✅ Storage delay disimpan: <b>{value:g}s</b>", parse_mode="HTML")


@router.callback_query(F.data == "safety_channel_delay")
async def safety_channel_delay(call: CallbackQuery, state: FSMContext):
    await _ask_safety_delay(call, state, SafetyState.waiting_channel_delay, "CHANNEL UPDATE DELAY")


@router.message(SafetyState.waiting_channel_delay)
async def save_safety_channel_delay(message: Message, state: FSMContext):
    try:
        value = float((message.text or "").strip())
        if value < 0 or value > 60:
            raise ValueError
    except ValueError:
        return await message.answer("❌ Masukkan angka 0-60 detik.")
    pool = await get_pool()
    await set_setting(pool, "telegram_channel_delay", value)
    await state.clear()
    await message.answer(f"✅ Channel delay disimpan: <b>{value:g}s</b>", parse_mode="HTML")


# =========================================================
# SHARE UNLOCK ADMIN MONITOR
# =========================================================

@router.callback_query(F.data == "admin_share_unlock")
async def admin_share_unlock(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        return await call.answer("❌ Tidak memiliki akses", show_alert=True)

    pool = await get_pool()
    try:
        campaigns = await pool.fetchval("SELECT COUNT(*) FROM code_share_progress")
        completed = await pool.fetchval(
            "SELECT COUNT(*) FROM code_share_progress WHERE completed=TRUE"
        )
        events = await pool.fetchval("SELECT COUNT(*) FROM code_share_events")
        active = await pool.fetchval(
            "SELECT COUNT(*) FROM code_share_progress WHERE completed=FALSE"
        )
    except Exception:
        campaigns = completed = events = active = 0

    await call.message.edit_text(
        "🎯 <b>SHARE UNLOCK MONITOR</b>\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        f"📌 Campaign: <b>{campaigns}</b>\n"
        f"🟢 Selesai: <b>{completed}</b>\n"
        f"🟡 Aktif: <b>{active}</b>\n"
        f"👥 Member baru terverifikasi: <b>{events}</b>\n\n"
        "Setiap event hanya dihitung sekali untuk kombinasi "
        "<code>code + pemilik + member baru</code>.",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔄 Refresh", callback_data="admin_share_unlock")],
            [InlineKeyboardButton(text="⬅️ Settings", callback_data="admin_settings")],
        ])
    )
    await call.answer()

# =========================
# PAYMENT METHOD CONTROL
# =========================
async def _payment_value(pool, key, default="off"):
    v = await pool.fetchval("SELECT value FROM settings WHERE key=$1", key)
    return str(v if v is not None else default).lower() in {"on","1","true","yes"}

@router.callback_query(F.data == "admin_payment_methods")
async def admin_payment_methods(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        return await call.answer("❌ No access", show_alert=True)
    await state.clear()
    pool = await get_pool()
    vals = {k: await _payment_value(pool,k,d) for k,d in [
        ("payment_cashi_enabled","on"),("payment_bayargg_enabled","on"),
        ("payment_manual_enabled","on"),("payment_binance_enabled","off")]} 
    addr = await get_setting(pool,"binance_usdt_address","")
    def icon(v): return "🟢 ON" if v else "🔴 OFF"
    kb=InlineKeyboardMarkup(inline_keyboard=[
      [InlineKeyboardButton(text=f"📲 Cashi ({icon(vals['payment_cashi_enabled'])})",callback_data="paytoggle:cashi")],
      [InlineKeyboardButton(text=f"⚡ BayarGG ({icon(vals['payment_bayargg_enabled'])})",callback_data="paytoggle:bayargg")],
      [InlineKeyboardButton(text=f"📷 QR Manual ({icon(vals['payment_manual_enabled'])})",callback_data="paytoggle:manual")],
      [InlineKeyboardButton(text=f"₿ Binance / USDT ({icon(vals['payment_binance_enabled'])})",callback_data="paytoggle:binance")],
      [InlineKeyboardButton(text="💬 Binance / USDT → @ownergbot",url="https://t.me/ownergbot")],
      [InlineKeyboardButton(text="📷 Set QR Manual • /qrid",callback_data="qrid_help")],
      [InlineKeyboardButton(text="⬅️ Back",callback_data="admin_settings")],
    ])
    await call.message.edit_text(
      "💳 <b>PAYMENT METHODS</b>\n\n"
      "Admin dapat membuka/menutup metode pembayaran secara realtime.\n\n"
      "₿ Binance / USDT diarahkan ke @ownergbot.",
      parse_mode="HTML", reply_markup=kb)
    await call.answer()

@router.callback_query(F.data.startswith("paytoggle:"))
async def admin_payment_toggle(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        return await call.answer("❌ No access", show_alert=True)
    keymap={"cashi":"payment_cashi_enabled","bayargg":"payment_bayargg_enabled","manual":"payment_manual_enabled","binance":"payment_binance_enabled"}
    name=call.data.split(":",1)[1]
    key=keymap.get(name)
    if not key: return await call.answer("❌ Invalid", show_alert=True)
    pool=await get_pool(); current=await _payment_value(pool,key,"off")
    await set_setting(pool,key,"off" if current else "on")
    await call.answer("Updated")
    return await admin_payment_methods(call, None)

@router.callback_query(F.data == "paybinance_address")
async def paybinance_address(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id): return await call.answer("❌ No access",show_alert=True)
    await state.set_state(BinanceAddressState.waiting)
    await call.message.answer("₿ Kirim alamat Binance / USDT sekarang. Sertakan network jika perlu (TRC20/ERC20/BEP20).")
    await call.answer()

@router.callback_query(F.data == "paybinance_account")
async def paybinance_account(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await state.set_state(BinanceAccountState.waiting)
    await call.message.answer("₿ Kirim username/account Binance atau label tujuan pembayaran sekarang.")
    await call.answer()

@router.message(BinanceAccountState.waiting, F.text)
async def receive_binance_account(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    account = message.text.strip()
    if not account:
        return await message.answer("❌ Account Binance tidak boleh kosong.")
    await set_setting(await get_pool(), "binance_account", account)
    await state.clear()
    await message.answer("✅ Akun Binance berhasil disimpan.")

@router.callback_query(F.data == "qrid_help")
async def qrid_help(call: CallbackQuery, state: FSMContext):
    """Open the QR Manual setup flow directly from Admin > Payment Methods."""
    if not is_admin(call.from_user.id):
        return await call.answer("❌ No access", show_alert=True)

    await call.answer()
    await state.set_state(QRIDState.waiting_qr)
    lang = "id"
    try:
        from utils.user_lang import get_user_language
        lang = await get_user_language(call.from_user.id)
    except Exception:
        pass

    prompt = {
        "id": "📷 <b>SET QR MANUAL</b>\n\nKirim foto/gambar QR Manual sekarang di chat ini.\n\nBot akan menyimpan Chat ID, Message ID, dan File ID secara otomatis.",
        "en": "📷 <b>SET MANUAL QR</b>\n\nSend the Manual QR image now in this chat.\n\nThe bot will automatically save the Chat ID, Message ID, and File ID.",
        "zh": "📷 <b>设置手动二维码</b>\n\n请现在在此聊天中发送手动二维码图片。\n\n机器人会自动保存 Chat ID、Message ID 和 File ID。",
    }.get(lang, "📷 <b>SET QR MANUAL</b>\n\nKirim foto/gambar QR Manual sekarang di chat ini.")

    await call.message.answer(prompt, parse_mode="HTML")


@router.message(BinanceAddressState.waiting, F.text)
async def receive_binance_address(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id): return
    address=message.text.strip()
    if len(address)<8: return await message.answer("❌ Alamat terlalu pendek.")
    pool=await get_pool(); await set_setting(pool,"binance_usdt_address",address); await state.clear()
    await message.answer("✅ Alamat Binance / USDT berhasil disimpan.")
