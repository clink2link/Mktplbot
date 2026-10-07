from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.context import FSMContext
from datetime import timedelta

from database import get_pool
from .dashboard import is_admin, rupiah

router = Router()


# =========================
# STATES
# =========================

class SearchUserState(StatesGroup):
    telegram_id = State()


class BalanceState(StatesGroup):
    waiting_user = State()


class BanUserState(StatesGroup):
    waiting_user = State()


class UnbanUserState(StatesGroup):
    waiting_user = State()


class VvipState(StatesGroup):
    waiting_user = State()
    waiting_type = State()
    waiting_days = State()


class CreatorState(StatesGroup):
    waiting_user = State()


# =========================
# MENU USER
# =========================

@router.callback_query(F.data == "admin_users")
async def admin_users(call: CallbackQuery):

    if not is_admin(call.from_user.id):
        return await call.answer("No access", show_alert=True)

    kb = InlineKeyboardBuilder()

    kb.button(text="👤 Total User", callback_data="users_total")
    kb.button(text="🆕 User Baru", callback_data="users_latest")
    kb.button(text="🔍 Cari User", callback_data="users_search")
    kb.button(text="💰 Balance User", callback_data="users_balance")
    kb.button(text="🚫 Ban User", callback_data="users_ban")
    kb.button(text="✅ Unban User", callback_data="users_unban")
    kb.button(text="👑 Set VVIP", callback_data="users_vvip")
    kb.button(text="🎨 Jadikan Kreator", callback_data="users_creator")
    kb.button(text="⬅ Back", callback_data="admin_home")

    kb.adjust(2)

    await call.message.edit_text(
        "👤 <b>USER MANAGER</b>",
        parse_mode="HTML",
        reply_markup=kb.as_markup()
    )

    await call.answer()


# =========================
# BACK BUTTON GLOBAL
# =========================

@router.callback_query(F.data == "back_users")
async def back_users(call: CallbackQuery):
    await admin_users(call)


# =========================
# TOTAL USERS
# =========================

@router.callback_query(F.data == "users_total")
async def users_total(call: CallbackQuery):

    if not is_admin(call.from_user.id):
        return await call.answer(
            "❌ Tidak memiliki akses.",
            show_alert=True
        )

    pool = await get_pool()

    try:
        total = await pool.fetchval(
            """
            SELECT COUNT(*)
            FROM users
            """
        ) or 0

    except Exception:
        total = 0

    kb = InlineKeyboardBuilder()

    kb.button(
        text="⬅ Kembali",
        callback_data="admin_users"
    )

    await call.message.edit_text(
        (
            "👥 <b>TOTAL USER</b>\n"
            "━━━━━━━━━━━━━━━━━━\n\n"
            f"👤 Total Pengguna : <b>{total:,}</b>"
        ).replace(",", "."),
        parse_mode="HTML",
        reply_markup=kb.as_markup()
    )

    await call.answer()


# =========================
# LATEST USERS
# =========================

@router.callback_query(F.data == "users_latest")
async def users_latest(call: CallbackQuery):

    if not is_admin(call.from_user.id):
        return await call.answer(
            "❌ Tidak memiliki akses.",
            show_alert=True
        )

    pool = await get_pool()

    try:
        users = await pool.fetch(
            """
            SELECT
                chat_id,
                username,
                full_name,
                balance,
                created_at
            FROM users
            ORDER BY created_at DESC
            LIMIT 10
            """
        )

    except Exception:

        users = []

    kb = InlineKeyboardBuilder()

    kb.button(
        text="⬅ Kembali",
        callback_data="admin_users"
    )

    if not users:

        return await call.message.edit_text(
            "❌ <b>Belum ada data user.</b>",
            parse_mode="HTML",
            reply_markup=kb.as_markup()
        )

    text = (
        "🆕 <b>10 USER TERBARU</b>\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
    )

    for i, user in enumerate(users, start=1):

        username = (
            f"@{user['username']}"
            if user["username"]
            else "-"
        )

        fullname = user["full_name"] or "-"

        created = (
            user["created_at"].strftime("%d-%m-%Y %H:%M")
            if user["created_at"]
            else "-"
        )

        text += (
            f"<b>{i}.</b> <code>{user['chat_id']}</code>\n"
            f"👤 {fullname}\n"
            f"🏷 {username}\n"
            f"💰 {rupiah(user['balance'])}\n"
            f"📅 {created}\n"
            "━━━━━━━━━━━━━━━━━━\n"
        )

    await call.message.edit_text(
        text,
        parse_mode="HTML",
        reply_markup=kb.as_markup()
    )

    await call.answer()


# =========================
# SEARCH USER
# =========================

@router.callback_query(F.data == "users_search")
async def users_search(call: CallbackQuery, state: FSMContext):

    if not is_admin(call.from_user.id):
        return await call.answer(
            "No access",
            show_alert=True
        )

    await state.clear()
    await state.set_state(SearchUserState.telegram_id)

    kb = InlineKeyboardBuilder()
    kb.button(
        text="⬅ Kembali",
        callback_data="admin_users"
    )

    await call.message.edit_text(
        "🔍 <b>CARI USER</b>\n\n"
        "Kirim salah satu:\n"
        "• Telegram ID\n"
        "• Username (@username)",
        parse_mode="HTML",
        reply_markup=kb.as_markup()
    )

    await call.answer()


@router.message(SearchUserState.telegram_id)
async def process_search(message: Message, state: FSMContext):

    if not is_admin(message.from_user.id):
        await state.clear()
        return

    key = (message.text or "").strip()

    pool = await get_pool()

    if key.isdigit():

        user = await pool.fetchrow(
            """
            SELECT *
            FROM users
            WHERE chat_id=$1
            """,
            int(key)
        )

    else:

        username = key.replace("@", "").lower()

        user = await pool.fetchrow(
            """
            SELECT *
            FROM users
            WHERE LOWER(username)=LOWER($1)
            """,
            username
        )

    if not user:

        await state.clear()

        return await message.answer(
            "❌ User tidak ditemukan."
        )

    username = (
        f"@{user['username']}"
        if user.get("username")
        else "-"
    )

    fullname = user.get("full_name") or "-"

    created = "-"

    if user.get("created_at"):
        created = user["created_at"].strftime(
            "%d-%m-%Y %H:%M"
        )

    vip = "❌"

    if user.get("vvip"):
        vip = "👑 VVIP"

    elif user.get("vip"):
        vip = "🔥 VIP"

    banned = (
        "🚫 Ya"
        if user.get("is_banned")
        else "✅ Tidak"
    )

    kb = InlineKeyboardBuilder()
    kb.button(
        text="⬅ Kembali",
        callback_data="admin_users"
    )

    await message.answer(
        (
            "👤 <b>DETAIL USER</b>\n\n"
            f"🆔 ID : <code>{user['chat_id']}</code>\n"
            f"👤 Nama : {fullname}\n"
            f"🌐 Username : {username}\n"
            f"💰 Balance : {rupiah(user.get('balance',0))}\n"
            f"⭐ Membership : {vip}\n"
            f"🚫 Banned : {banned}\n"
            f"📅 Bergabung : {created}"
        ),
        parse_mode="HTML",
        reply_markup=kb.as_markup()
    )

    await state.clear()


# =========================
# BALANCE USER
# =========================

@router.callback_query(F.data == "users_balance")
async def users_balance(call: CallbackQuery, state: FSMContext):

    if not is_admin(call.from_user.id):
        return await call.answer(
            "❌ Tidak memiliki akses.",
            show_alert=True
        )

    await state.clear()
    await state.set_state(BalanceState.waiting_user)

    kb = InlineKeyboardBuilder()
    kb.button(
        text="⬅ Kembali",
        callback_data="admin_users"
    )

    await call.message.edit_text(
        "💰 <b>CEK BALANCE USER</b>\n\n"
        "Kirim salah satu:\n"
        "• Telegram ID\n"
        "• Username (@username)",
        parse_mode="HTML",
        reply_markup=kb.as_markup()
    )

    await call.answer()


@router.message(BalanceState.waiting_user)
async def balance_user(message: Message, state: FSMContext):

    if not is_admin(message.from_user.id):
        await state.clear()
        return

    key = (message.text or "").strip()

    pool = await get_pool()

    if key.isdigit():

        user = await pool.fetchrow(
            """
            SELECT *
            FROM users
            WHERE chat_id=$1
            """,
            int(key)
        )

    else:

        user = await pool.fetchrow(
            """
            SELECT *
            FROM users
            WHERE LOWER(username)=LOWER($1)
            """,
            key.replace("@", "")
        )

    if not user:

        await state.clear()

        return await message.answer(
            "❌ User tidak ditemukan."
        )

    username = (
        f"@{user['username']}"
        if user["username"]
        else "-"
    )

    fullname = user["full_name"] or "-"

    balance = user["balance"] or 0

    total_deposit = user["total_deposit"] if "total_deposit" in user else 0
    total_withdraw = user["total_withdraw"] if "total_withdraw" in user else 0
    total_earn = user["total_earn"] if "total_earn" in user else 0

    kb = InlineKeyboardBuilder()
    kb.button(
        text="⬅ Kembali",
        callback_data="admin_users"
    )

    await message.answer(
        (
            "💰 <b>INFORMASI SALDO USER</b>\n\n"
            f"🆔 ID : <code>{user['chat_id']}</code>\n"
            f"👤 Nama : {fullname}\n"
            f"🌐 Username : {username}\n\n"
            f"👛 Balance : <b>{rupiah(balance)}</b>\n"
            f"📥 Deposit : {rupiah(total_deposit)}\n"
            f"📤 Withdraw : {rupiah(total_withdraw)}\n"
            f"💵 Total Earn : {rupiah(total_earn)}"
        ),
        parse_mode="HTML",
        reply_markup=kb.as_markup()
    )

    await state.clear()


# =========================
# BAN USER
# =========================

@router.callback_query(F.data == "users_ban")
async def users_ban(call: CallbackQuery, state: FSMContext):

    if not is_admin(call.from_user.id):
        return await call.answer(
            "❌ Tidak memiliki akses.",
            show_alert=True
        )

    await state.clear()
    await state.set_state(BanUserState.waiting_user)

    kb = InlineKeyboardBuilder()
    kb.button(
        text="⬅ Kembali",
        callback_data="admin_users"
    )

    await call.message.edit_text(
        "🚫 <b>BAN USER</b>\n\n"
        "Kirim salah satu:\n"
        "• Telegram ID\n"
        "• Username (@username)",
        parse_mode="HTML",
        reply_markup=kb.as_markup()
    )

    await call.answer()


@router.message(BanUserState.waiting_user)
async def ban_user(message: Message, state: FSMContext):

    if not is_admin(message.from_user.id):
        await state.clear()
        return

    key = (message.text or "").strip()

    pool = await get_pool()

    if key.isdigit():

        user = await pool.fetchrow(
            """
            SELECT *
            FROM users
            WHERE chat_id=$1
            """,
            int(key)
        )

    else:

        user = await pool.fetchrow(
            """
            SELECT *
            FROM users
            WHERE LOWER(username)=LOWER($1)
            """,
            key.replace("@", "")
        )

    if not user:

        await state.clear()

        return await message.answer(
            "❌ User tidak ditemukan."
        )

    if user["chat_id"] in ADMIN_IDS:

        await state.clear()

        return await message.answer(
            "❌ Admin tidak bisa diban."
        )

    if user["is_banned"]:

        await state.clear()

        return await message.answer(
            "⚠️ User sudah diban."
        )

    await pool.execute(
        """
        UPDATE users
        SET is_banned=TRUE
        WHERE chat_id=$1
        """,
        user["chat_id"]
    )

    try:
        await message.bot.send_message(
            user["chat_id"],
            "🚫 Akun kamu telah diblokir oleh admin."
        )
    except Exception:
        pass

    kb = InlineKeyboardBuilder()
    kb.button(
        text="⬅ Kembali",
        callback_data="admin_users"
    )

    await message.answer(
        (
            "✅ <b>User berhasil diban</b>\n\n"
            f"🆔 <code>{user['chat_id']}</code>\n"
            f"👤 {user['full_name'] or '-'}"
        ),
        parse_mode="HTML",
        reply_markup=kb.as_markup()
    )

    await state.clear()


# =========================
# UNBAN USER
# =========================

@router.callback_query(F.data == "users_unban")
async def users_unban(call: CallbackQuery, state: FSMContext):

    if not is_admin(call.from_user.id):
        return await call.answer(
            "❌ Tidak memiliki akses",
            show_alert=True
        )

    await state.clear()
    await state.set_state(UnbanUserState.waiting_user)

    kb = InlineKeyboardBuilder()
    kb.button(
        text="⬅ Kembali",
        callback_data="admin_users"
    )

    await call.message.edit_text(
        "✅ <b>UNBAN USER</b>\n\n"
        "Kirim salah satu:\n"
        "• Telegram ID\n"
        "• Username (@username)",
        parse_mode="HTML",
        reply_markup=kb.as_markup()
    )

    await call.answer()


@router.message(UnbanUserState.waiting_user)
async def unban_user(message: Message, state: FSMContext):

    if not is_admin(message.from_user.id):
        return

    pool = await get_pool()

    key = (message.text or "").strip()

    if not key:
        return await message.answer(
            "❌ Masukkan Telegram ID atau username."
        )

    if key.isdigit():

        user = await pool.fetchrow(
            """
            SELECT *
            FROM users
            WHERE chat_id=$1
            """,
            int(key)
        )

    else:

        username = key.replace("@", "").lower()

        user = await pool.fetchrow(
            """
            SELECT *
            FROM users
            WHERE LOWER(username)=$1
            """,
            username
        )

    if not user:
        await state.clear()
        return await message.answer(
            "❌ User tidak ditemukan."
        )

    await pool.execute(
        """
        UPDATE users
        SET is_banned = FALSE
        WHERE chat_id = $1
        """,
        user["chat_id"]
    )

    try:
        await message.bot.send_message(
            user["chat_id"],
            "✅ Akun kamu telah di-unban oleh Admin.\n"
            "Sekarang kamu sudah bisa menggunakan bot kembali."
        )
    except Exception:
        pass

    kb = InlineKeyboardBuilder()
    kb.button(
        text="⬅ Kembali",
        callback_data="admin_users"
    )

    await message.answer(
        (
            "✅ <b>USER BERHASIL DI-UNBAN</b>\n\n"
            f"🆔 ID : <code>{user['chat_id']}</code>\n"
            f"👤 Username : @{user['username'] or '-'}"
        ),
        parse_mode="HTML",
        reply_markup=kb.as_markup()
    )

    await state.clear()



# =========================
# SET CREATOR
# =========================

@router.callback_query(F.data == "users_creator")
async def creator_start(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        return await call.answer("❌ Tidak memiliki akses.", show_alert=True)

    await state.clear()
    await state.set_state(CreatorState.waiting_user)

    kb = InlineKeyboardBuilder()
    kb.button(text="⬅ Kembali", callback_data="admin_users")

    await call.message.edit_text(
        "🎨 <b>JADIKAN KREATOR</b>\n\n"
        "Kirim Telegram ID atau username member.\n\n"
        "Kreator yang disetujui dapat membuka <b>semua file berbayar secara gratis</b>.",
        parse_mode="HTML",
        reply_markup=kb.as_markup()
    )
    await call.answer()


@router.message(CreatorState.waiting_user)
async def creator_set_user(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        await state.clear()
        return

    key = (message.text or "").strip()
    if not key:
        return await message.answer("❌ Masukkan Telegram ID atau username.")

    pool = await get_pool()

    if key.isdigit():
        user = await pool.fetchrow(
            """
            SELECT user_id, chat_id, username, full_name
            FROM users
            WHERE user_id=$1 OR chat_id=$1
            LIMIT 1
            """,
            int(key)
        )
    else:
        username = key.lstrip("@").lower()
        user = await pool.fetchrow(
            """
            SELECT user_id, chat_id, username, full_name
            FROM users
            WHERE LOWER(username)=LOWER($1)
            LIMIT 1
            """,
            username
        )

    if not user:
        await state.clear()
        return await message.answer("❌ Member tidak ditemukan. Pastikan member sudah menekan /start.")

    target_id = user["user_id"] or user["chat_id"]

    await pool.execute(
        """
        UPDATE users
        SET
            is_creator=TRUE,
            creator_status='approved',
            creator_verified_at=NOW(),
            updated_at=NOW()
        WHERE user_id=$1
        """,
        target_id
    )

    try:
        await message.bot.send_message(
            target_id,
            "🎉 <b>Kamu sekarang resmi menjadi KREATOR!</b>\n\n"
            "✅ Kamu dapat membuka semua kode/file berbayar tanpa membayar.\n"
            "📤 Fitur kreator dan pengelolaan file tetap mengikuti aturan bot.",
            parse_mode="HTML"
        )
    except Exception:
        pass

    await message.answer(
        "✅ <b>Member berhasil dijadikan Kreator.</b>\n\n"
        f"🆔 ID: <code>{target_id}</code>\n"
        f"👤 Username: @{user['username'] or '-'}",
        parse_mode="HTML"
    )
    await state.clear()


# =========================
# VIP / VVIP
# =========================

@router.callback_query(F.data == "users_vvip")
async def vvip_start(
    call: CallbackQuery,
    state: FSMContext
):

    if not is_admin(call.from_user.id):
        return await call.answer(
            "❌ Tidak memiliki akses.",
            show_alert=True
        )

    await state.clear()
    await state.set_state(
        VvipState.waiting_user
    )

    kb = InlineKeyboardBuilder()

    kb.button(
        text="⬅ Kembali",
        callback_data="admin_users"
    )

    await call.message.edit_text(
        (
            "👑 <b>VIP / VVIP MANAGER</b>\n\n"
            "Silakan kirim salah satu:\n\n"
            "• Telegram ID\n"
            "• Username (@username)\n\n"
            "Setelah user ditemukan,\n"
            "pilih VIP atau VVIP."
        ),
        parse_mode="HTML",
        reply_markup=kb.as_markup()
    )

    await call.answer()

# =========================
# STEP 1 : CARI USER
# =========================

@router.message(VvipState.waiting_user)
async def vvip_user(message: Message, state: FSMContext):

    if not is_admin(message.from_user.id):
        await state.clear()
        return

    key = (message.text or "").strip()

    if not key:
        return await message.answer(
            "❌ Masukkan Telegram ID atau Username."
        )

    pool = await get_pool()

    if key.isdigit():

        user = await pool.fetchrow(
            """
            SELECT
                chat_id,
                username,
                full_name,
                plan
            FROM users
            WHERE chat_id=$1
            """,
            int(key)
        )

    else:

        username = key.replace("@", "").lower()

        user = await pool.fetchrow(
            """
            SELECT
                chat_id,
                username,
                full_name,
                plan
            FROM users
            WHERE LOWER(username)=$1
            """,
            username
        )

    if not user:

        await state.clear()

        return await message.answer(
            "❌ User tidak ditemukan."
        )

    await state.update_data(
        user_id=user["chat_id"]
    )

    await state.set_state(
        VvipState.waiting_type
    )

    kb = InlineKeyboardBuilder()

    kb.button(
        text="🔥 VIP",
        callback_data="set_type:vip"
    )

    kb.button(
        text="👑 VVIP",
        callback_data="set_type:vvip"
    )

    kb.adjust(2)

    await message.answer(
        (
            "👤 <b>USER DITEMUKAN</b>\n\n"
            f"🆔 ID : <code>{user['chat_id']}</code>\n"
            f"👤 Username : @{user['username'] or '-'}\n"
            f"📝 Nama : {user['full_name'] or '-'}\n"
            f"💎 Plan : <b>{(user['plan'] or 'free').upper()}</b>\n\n"
            "Silakan pilih tipe membership."
        ),
        parse_mode="HTML",
        reply_markup=kb.as_markup()
    )


# =========================
# STEP 2 : PILIH TIPE
# =========================

@router.callback_query(F.data.startswith("set_type:"))
async def set_type(
    call: CallbackQuery,
    state: FSMContext
):

    if not is_admin(call.from_user.id):
        return await call.answer(
            "❌ Tidak memiliki akses.",
            show_alert=True
        )

    data = await state.get_data()

    if not data.get("user_id"):
        await state.clear()

        return await call.message.edit_text(
            "❌ Session telah berakhir.\nSilakan ulangi kembali."
        )

    tipe = call.data.split(":", 1)[1].lower()

    if tipe not in ("vip", "vvip"):
        return await call.answer(
            "❌ Tipe tidak valid.",
            show_alert=True
        )

    await state.update_data(
        type=tipe
    )

    await state.set_state(
        VvipState.waiting_days
    )

    kb = InlineKeyboardBuilder()

    kb.button(
        text="⬅ Kembali",
        callback_data="users_vvip"
    )

    await call.message.edit_text(
        (
            f"💎 <b>{tipe.upper()} MEMBERSHIP</b>\n\n"
            "Masukkan durasi membership.\n\n"
            "Contoh:\n"
            "30\n"
            "90\n"
            "365"
        ),
        parse_mode="HTML",
        reply_markup=kb.as_markup()
    )

    await call.answer()


# =========================
# STEP 3 : SET MEMBERSHIP
# =========================

@router.message(VvipState.waiting_days)
async def set_membership_days(
    message: Message,
    state: FSMContext
):

    if not is_admin(message.from_user.id):
        await state.clear()
        return

    text = (message.text or "").strip()

    if not text.isdigit():
        return await message.answer(
            "❌ Durasi harus berupa angka."
        )

    days = int(text)

    if days < 1 or days > 365:
        return await message.answer(
            "❌ Durasi hanya boleh 1 - 365 hari."
        )

    data = await state.get_data()

    user_id = data.get("user_id")
    tipe = data.get("type")

    if not user_id or not tipe:
        await state.clear()

        return await message.answer(
            "❌ Session telah berakhir."
        )

    pool = await get_pool()

    if tipe == "vvip":

        await pool.execute(
            """
            UPDATE users
            SET
                plan='vvip',

                vip=FALSE,
                is_vip=FALSE,
                vip_until=NULL,

                vvip=TRUE,
                is_vvip=TRUE,

                vvip_until=
                    CASE
                        WHEN vvip_until > NOW()
                        THEN vvip_until + $2
                        ELSE NOW() + $2
                    END

            WHERE chat_id=$1
            """,
            user_id,
            timedelta(days=days)
        )

        title = "👑 VVIP"

    else:

        await pool.execute(
            """
            UPDATE users
            SET
                plan='vip',

                vip=TRUE,
                is_vip=TRUE,

                vip_until=
                    CASE
                        WHEN vip_until > NOW()
                        THEN vip_until + $2
                        ELSE NOW() + $2
                    END,

                vvip=FALSE,
                is_vvip=FALSE,
                vvip_until=NULL

            WHERE chat_id=$1
            """,
            user_id,
            timedelta(days=days)
        )

        title = "🔥 VIP"

    try:

        await message.bot.send_message(
            chat_id=user_id,
            text=(
                f"🎉 Selamat!\n\n"
                f"Membership kamu berhasil diubah menjadi "
                f"{title} selama {days} hari."
            )
        )

    except Exception:
        pass

    await message.answer(
        (
            "✅ <b>Membership berhasil diperbarui.</b>\n\n"
            f"👤 User : <code>{user_id}</code>\n"
            f"💎 Tipe : {title}\n"
            f"📅 Durasi : {days} hari"
        ),
        parse_mode="HTML"
    )

    await state.clear()
