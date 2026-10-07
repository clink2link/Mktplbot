from aiogram import Router, F
from aiogram.types import CallbackQuery, Message
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder

from database import get_pool
from .dashboard import is_admin, rupiah


router = Router()


# =========================
# STATE
# =========================

class BalanceAdminState(StatesGroup):
    waiting_user = State()
    waiting_add = State()
    waiting_minus = State()



# =========================
# MENU BALANCE
# =========================

@router.callback_query(F.data == "admin_balance")
async def admin_balance(
    call: CallbackQuery,
    state: FSMContext
):

    if not is_admin(call.from_user.id):
        return await call.answer(
            "❌ Tidak memiliki akses",
            show_alert=True
        )

    await state.clear()

    await state.set_state(
        BalanceAdminState.waiting_user
    )


    kb = InlineKeyboardBuilder()

    kb.button(
        text="⬅ Admin Menu",
        callback_data="admin_home"
    )


    await call.message.edit_text(
        (
            "💰 <b>USER FINANCE</b>\n"
            "━━━━━━━━━━━━━━\n\n"
            "Kirim:\n"
            "• Telegram ID\n"
            "• Username (@username)"
        ),
        parse_mode="HTML",
        reply_markup=kb.as_markup()
    )

    await call.answer()



# =========================
# SEARCH USER
# =========================

@router.message(BalanceAdminState.waiting_user)
async def process_balance(
    message: Message,
    state: FSMContext
):

    if not is_admin(message.from_user.id):
        await state.clear()
        return


    key = (message.text or "").strip()

    if not key:
        return await message.answer(
            "❌ Input kosong"
        )


    pool = await get_pool()


    if key.isdigit():

        user = await pool.fetchrow(
            """
            SELECT
                chat_id,
                username,
                full_name,
                balance,
                total_earn,
                total_deposit,
                total_withdraw,
                total_upload,
                total_download,
                total_file,
                plan,
                vip,
                vip_until,
                vvip,
                vvip_until,
                is_banned

            FROM users
            WHERE chat_id=$1
            """,
            int(key)
        )


    else:

        username = key.replace("@","").lower()


        user = await pool.fetchrow(
            """
            SELECT
                chat_id,
                username,
                full_name,
                balance,
                total_earn,
                total_deposit,
                total_withdraw,
                total_upload,
                total_download,
                total_file,
                plan,
                vip,
                vip_until,
                vvip,
                vvip_until,
                is_banned

            FROM users
            WHERE LOWER(username)=$1
            """,
            username
        )


    if not user:

        return await message.answer(
            "❌ User tidak ditemukan"
        )


    await state.update_data(
        balance_user=user["chat_id"]
    )


    if user["vvip"]:
        member = (
            f"👑 VVIP\n"
            f"📅 {user['vvip_until']}"
        )

    elif user["vip"]:
        member = (
            f"🔥 VIP\n"
            f"📅 {user['vip_until']}"
        )

    else:
        member="🆓 FREE"



    status = (
        "🚫 BANNED"
        if user["is_banned"]
        else
        "✅ ACTIVE"
    )



    text = (

        "👤 <b>USER FINANCE DETAIL</b>\n"
        "━━━━━━━━━━━━━━\n\n"

        f"🆔 ID : <code>{user['chat_id']}</code>\n"
        f"👤 Username : @{user['username'] or '-'}\n"
        f"📛 Nama : {user['full_name'] or '-'}\n\n"

        "💎 MEMBERSHIP\n"
        f"{member}\n\n"

        "💰 FINANCE\n"
        f"👛 Balance : {rupiah(user['balance'])}\n"
        f"💵 Earn : {rupiah(user['total_earn'])}\n"
        f"📥 Deposit : {rupiah(user['total_deposit'])}\n"
        f"📤 Withdraw : {rupiah(user['total_withdraw'])}\n\n"

        "📂 FILE\n"
        f"📤 Upload : {user['total_upload']}\n"
        f"📥 Download : {user['total_download']}\n"
        f"📁 Total : {user['total_file']}\n\n"

        f"🔐 Status : {status}"

    )


    kb = InlineKeyboardBuilder()


    kb.button(
        text="➕ Tambah Balance",
        callback_data=f"balance_add:{user['chat_id']}"
    )


    kb.button(
        text="➖ Kurangi Balance",
        callback_data=f"balance_minus:{user['chat_id']}"
    )


    kb.button(
        text="⬅ Admin Menu",
        callback_data="admin_home"
    )


    kb.adjust(2)


    await message.answer(
        text,
        parse_mode="HTML",
        reply_markup=kb.as_markup()
    )


    await state.clear()


# =========================
# TAMBAH BALANCE
# =========================

@router.callback_query(F.data.startswith("balance_add:"))
async def balance_add(
    call: CallbackQuery,
    state: FSMContext
):

    if not is_admin(call.from_user.id):
        return await call.answer(
            "❌ No access",
            show_alert=True
        )


    user_id = int(call.data.split(":")[1])


    await state.update_data(
        balance_user=user_id
    )


    await state.set_state(
        BalanceAdminState.waiting_add
    )


    await call.message.answer(
        f"➕ <b>TAMBAH BALANCE</b>\n\n"
        f"User ID:\n"
        f"<code>{user_id}</code>\n\n"
        "Kirim nominal:",
        parse_mode="HTML"
    )


    await call.answer()



@router.message(BalanceAdminState.waiting_add)
async def process_add_balance(
    message: Message,
    state: FSMContext
):

    if not message.text or not message.text.isdigit():
        return await message.answer(
            "❌ Nominal harus angka."
        )


    amount = int(message.text)


    data = await state.get_data()

    user_id = data.get(
        "balance_user"
    )


    if not user_id:
        await state.clear()
        return await message.answer(
            "❌ Session expired."
        )


    pool = await get_pool()


    result = await pool.execute(
        """
        UPDATE users
        SET balance = COALESCE(balance,0) + $1
        WHERE chat_id=$2
        """,
        amount,
        user_id
    )


    await message.answer(
        "✅ <b>Balance berhasil ditambah</b>\n\n"
        f"👤 User: <code>{user_id}</code>\n"
        f"➕ {rupiah(amount)}",
        parse_mode="HTML"
    )


    await state.clear()



# =========================
# KURANGI BALANCE
# =========================

@router.callback_query(F.data.startswith("balance_minus:"))
async def balance_minus(
    call: CallbackQuery,
    state: FSMContext
):

    if not is_admin(call.from_user.id):
        return await call.answer(
            "❌ No access",
            show_alert=True
        )


    user_id = int(call.data.split(":")[1])


    await state.update_data(
        balance_user=user_id
    )


    await state.set_state(
        BalanceAdminState.waiting_minus
    )


    await call.message.answer(
        f"➖ <b>KURANGI BALANCE</b>\n\n"
        f"User ID:\n"
        f"<code>{user_id}</code>\n\n"
        "Kirim nominal:",
        parse_mode="HTML"
    )


    await call.answer()



@router.message(BalanceAdminState.waiting_minus)
async def process_minus_balance(
    message: Message,
    state: FSMContext
):

    if not message.text or not message.text.isdigit():
        return await message.answer(
            "❌ Nominal harus angka."
        )


    amount = int(message.text)


    data = await state.get_data()

    user_id = data.get(
        "balance_user"
    )


    if not user_id:
        await state.clear()
        return await message.answer(
            "❌ Session expired."
        )


    pool = await get_pool()


    await pool.execute(
        """
        UPDATE users
        SET balance =
            GREATEST(
                COALESCE(balance,0) - $1,
                0
            )
        WHERE chat_id=$2
        """,
        amount,
        user_id
    )


    await message.answer(
        "✅ <b>Balance berhasil dikurangi</b>\n\n"
        f"👤 User: <code>{user_id}</code>\n"
        f"➖ {rupiah(amount)}",
        parse_mode="HTML"
    )


    await state.clear()
