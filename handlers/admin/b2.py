from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from database import get_pool
from utils.b2_storage import encrypt_b2_secret
from handlers.admin.admins import is_admin

router = Router()


class B2State(StatesGroup):
    account_id = State()
    name = State()
    region = State()
    endpoint = State()
    bucket = State()
    key_id = State()
    application_key = State()


def menu_kb():
    kb = InlineKeyboardBuilder()
    kb.button(text="➕ Tambah B2", callback_data="admin_b2_add")
    kb.button(text="📋 Daftar B2", callback_data="admin_b2_list")
    kb.button(text="🎯 Pilih Target", callback_data="admin_b2_target")
    kb.button(text="🗑 Hapus B2", callback_data="admin_b2_delete")
    kb.button(text="⬅️ Kembali", callback_data="admin_home")
    kb.adjust(2, 2, 1)
    return kb.as_markup()


async def render(call_or_message):
    pool = await get_pool()
    rows = await pool.fetch("""
        SELECT account_id,name,region,bucket,is_enabled,is_target
        FROM b2_storage_accounts ORDER BY account_id
    """)
    if rows:
        lines = ["🗄️ <b>B2 STORAGE</b>\n━━━━━━━━━━━━"]
        for r in rows:
            status = "🟢" if r["is_enabled"] else "🔴"
            target = " 🎯" if r["is_target"] else ""
            lines.append(f"{status} <b>B2 #{r['account_id']}</b> — {r['name']}{target}\n   {r['bucket']} · {r['region']}")
        text = "\n".join(lines)
    else:
        text = "🗄️ <b>B2 STORAGE</b>\n━━━━━━━━━━━━\nBelum ada B2."
    if isinstance(call_or_message, CallbackQuery):
        await call_or_message.message.edit_text(text, parse_mode="HTML", reply_markup=menu_kb())
        await call_or_message.answer()
    else:
        await call_or_message.answer(text, parse_mode="HTML", reply_markup=menu_kb())


@router.callback_query(F.data == "admin_b2")
async def admin_b2(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        return await call.answer("❌ Tidak memiliki akses", show_alert=True)
    await render(call)


@router.callback_query(F.data == "admin_b2_list")
async def admin_b2_list(call: CallbackQuery):
    if not is_admin(call.from_user.id): return
    await render(call)


@router.callback_query(F.data == "admin_b2_add")
async def admin_b2_add(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id): return
    await state.clear(); await state.set_state(B2State.account_id)
    await call.message.edit_text("➕ <b>TAMBAH B2</b>\n\nKirim Account ID <b>1-10</b>.\nID harus sesuai <code>drive_account</code> media Showjs.", parse_mode="HTML")
    await call.answer()


@router.message(B2State.account_id)
async def b2_account_id(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id): return
    try: value=int((message.text or '').strip())
    except ValueError: return await message.answer("❌ Account ID harus angka 1-10.")
    if value < 1 or value > 10: return await message.answer("❌ Account ID harus 1-10.")
    await state.update_data(account_id=value); await state.set_state(B2State.name)
    await message.answer("Nama B2?")

@router.message(B2State.name)
async def b2_name(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id): return
    await state.update_data(name=(message.text or '').strip()[:100]); await state.set_state(B2State.region)
    await message.answer("Region B2? Contoh: <code>us-east-005</code>", parse_mode="HTML")

@router.message(B2State.region)
async def b2_region(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id): return
    await state.update_data(region=(message.text or '').strip()); await state.set_state(B2State.endpoint)
    await message.answer("S3 endpoint? Contoh: <code>https://s3.us-east-005.backblazeb2.com</code>", parse_mode="HTML")

@router.message(B2State.endpoint)
async def b2_endpoint(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id): return
    await state.update_data(endpoint=(message.text or '').strip().rstrip('/')); await state.set_state(B2State.bucket)
    await message.answer("Nama bucket?")

@router.message(B2State.bucket)
async def b2_bucket(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id): return
    await state.update_data(bucket=(message.text or '').strip()); await state.set_state(B2State.key_id)
    await message.answer("Application Key ID?")

@router.message(B2State.key_id)
async def b2_key_id(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id): return
    await state.update_data(key_id=(message.text or '').strip())
    try:
        await message.delete()
    except Exception:
        pass
    await state.set_state(B2State.application_key)
    await message.answer("Application Key?")

@router.message(B2State.application_key)
async def b2_application_key(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id): return
    data=await state.get_data()
    data["application_key"]=(message.text or '').strip()

    # Application keys are secrets. Remove the admin's message as soon as
    # it has been captured so the credential is not left in chat history.
    try:
        await message.delete()
    except Exception:
        pass

    pool=await get_pool()
    await pool.execute("""
        INSERT INTO b2_storage_accounts(account_id,name,region,endpoint,bucket,key_id,application_key,is_enabled,is_target)
        VALUES($1,$2,$3,$4,$5,$6,$7,TRUE,FALSE)
        ON CONFLICT(account_id) DO UPDATE SET
          name=EXCLUDED.name, region=EXCLUDED.region, endpoint=EXCLUDED.endpoint,
          bucket=EXCLUDED.bucket, key_id=EXCLUDED.key_id, application_key=EXCLUDED.application_key,
          is_enabled=TRUE, updated_at=NOW()
    """, data["account_id"],data["name"],data["region"],data["endpoint"],data["bucket"],
        data["key_id"], encrypt_b2_secret(data["application_key"]))
    await state.clear()
    await message.answer("✅ B2 berhasil disimpan. Credential tidak ditampilkan kembali.")


@router.callback_query(F.data == "admin_b2_target")
async def admin_b2_target(call: CallbackQuery):
    if not is_admin(call.from_user.id): return
    pool=await get_pool(); rows=await pool.fetch("SELECT account_id,name,is_target FROM b2_storage_accounts WHERE is_enabled=TRUE ORDER BY account_id")
    kb=InlineKeyboardBuilder()
    for r in rows: kb.button(text=("🎯 " if r["is_target"] else "☑️ ")+f"B2 #{r['account_id']} {r['name']}",callback_data=f"admin_b2_settarget:{r['account_id']}")
    kb.button(text="⬅️ Kembali",callback_data="admin_b2"); kb.adjust(1)
    await call.message.edit_text("🎯 <b>PILIH TARGET B2</b>",parse_mode="HTML",reply_markup=kb.as_markup()); await call.answer()

@router.callback_query(F.data.startswith("admin_b2_settarget:"))
async def admin_b2_settarget(call: CallbackQuery):
    if not is_admin(call.from_user.id): return
    account_id=int(call.data.split(":",1)[1]); pool=await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute("UPDATE b2_storage_accounts SET is_target=FALSE, updated_at=NOW()")
            await conn.execute("UPDATE b2_storage_accounts SET is_target=TRUE, updated_at=NOW() WHERE account_id=$1 AND is_enabled=TRUE",account_id)
    await call.answer("✅ Target B2 diubah")
    await render(call)

@router.callback_query(F.data == "admin_b2_delete")
async def admin_b2_delete(call: CallbackQuery):
    if not is_admin(call.from_user.id): return
    pool=await get_pool(); rows=await pool.fetch("SELECT account_id,name FROM b2_storage_accounts ORDER BY account_id")
    kb=InlineKeyboardBuilder()
    for r in rows: kb.button(text=f"🗑 B2 #{r['account_id']} {r['name']}",callback_data=f"admin_b2_del:{r['account_id']}")
    kb.button(text="⬅️ Kembali",callback_data="admin_b2"); kb.adjust(1)
    await call.message.edit_text("🗑 <b>HAPUS KONFIGURASI B2</b>\n\nObject di B2 TIDAK dihapus.",parse_mode="HTML",reply_markup=kb.as_markup()); await call.answer()

@router.callback_query(F.data.startswith("admin_b2_del:"))
async def admin_b2_del(call: CallbackQuery):
    if not is_admin(call.from_user.id): return
    account_id=int(call.data.split(":",1)[1]); pool=await get_pool()
    await pool.execute("DELETE FROM b2_storage_accounts WHERE account_id=$1",account_id)
    await call.answer("✅ Konfigurasi dihapus; object B2 tetap aman")
    await render(call)
