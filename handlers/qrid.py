from aiogram import Router, F
from aiogram.types import Message
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from database import get_pool
from handlers.admin.admins import is_admin
from utils.user_lang import get_user_language

router = Router()


class QRIDState(StatesGroup):
    waiting_qr = State()


def _setting_sql():
    return """
        INSERT INTO settings(key, value)
        VALUES($1, $2)
        ON CONFLICT(key)
        DO UPDATE SET value = EXCLUDED.value
    """


@router.message(F.text == "/qrid")
async def qrid_start(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return await message.answer("❌ Kamu bukan admin.")

    lang = await get_user_language(message.from_user.id)

    prompt = {
        "id": (
            "📷 <b>SET QR MANUAL</b>\n\n"
            "Kirim foto QR Manual sekarang di chat ini.\n"
            "Bot akan menyimpan Chat ID, Message ID, dan File ID secara otomatis."
        ),
        "en": (
            "📷 <b>SET MANUAL QR</b>\n\n"
            "Send the Manual QR image now in this chat.\n"
            "The bot will automatically save the Chat ID, Message ID, and File ID."
        ),
        "zh": (
            "📷 <b>设置手动二维码</b>\n\n"
            "请现在在此聊天中发送手动二维码图片。\n"
            "机器人会自动保存聊天 ID、消息 ID 和文件 ID。"
        ),
    }.get(lang, "📷 <b>SET QR MANUAL</b>\n\nKirim foto QR Manual sekarang di chat ini.")

    await state.set_state(QRIDState.waiting_qr)
    await message.answer(prompt, parse_mode="HTML")


@router.message(QRIDState.waiting_qr)
async def qrid_receive(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return

    if not (message.photo or message.document):
        lang = await get_user_language(message.from_user.id)
        error = {
            "id": "❌ Kirim QR sebagai foto atau gambar.",
            "en": "❌ Send the QR as a photo or image.",
            "zh": "❌ 请发送二维码照片或图片。",
        }.get(lang, "❌ Kirim QR sebagai foto atau gambar.")
        return await message.answer(error)

    # Ambil file_id terbesar untuk photo Telegram.
    file_id = (
        message.photo[-1].file_id
        if message.photo
        else message.document.file_id
    )

    pool = await get_pool()
    sql = _setting_sql()

    # Simpan semua metadata QR dalam satu flow.
    await pool.execute(sql, "manual_qr_chat_id", str(message.chat.id))
    await pool.execute(sql, "manual_qr_message_id", str(message.message_id))
    await pool.execute(sql, "manual_qr_file_id", file_id)

    # PENTING:
    # Setelah QR berhasil disimpan, metode QR Manual langsung ON.
    await pool.execute(sql, "manual_qr_configured", "on")
    await pool.execute(sql, "payment_manual_enabled", "on")

    await state.clear()

    lang = await get_user_language(message.from_user.id)

    text = {
        "id": (
            "✅ <b>QR Manual berhasil disimpan & diaktifkan.</b>\n\n"
            f"🆔 Chat ID: <code>{message.chat.id}</code>\n"
            f"🆔 Message ID: <code>{message.message_id}</code>\n"
            f"🆔 File ID: <code>{file_id}</code>\n\n"
            "📷 Metode <b>QR Manual</b> sekarang tersedia di pembayaran."
        ),
        "en": (
            "✅ <b>Manual QR saved & enabled.</b>\n\n"
            f"🆔 Chat ID: <code>{message.chat.id}</code>\n"
            f"🆔 Message ID: <code>{message.message_id}</code>\n"
            f"🆔 File ID: <code>{file_id}</code>\n\n"
            "📷 The <b>Manual QR</b> payment method is now available."
        ),
        "zh": (
            "✅ <b>手动二维码已保存并启用。</b>\n\n"
            f"🆔 聊天 ID：<code>{message.chat.id}</code>\n"
            f"🆔 消息 ID：<code>{message.message_id}</code>\n"
            f"🆔 文件 ID：<code>{file_id}</code>\n\n"
            "📷 <b>手动二维码</b>支付方式现在已可用。"
        ),
    }.get(lang, "✅ QR Manual berhasil disimpan & diaktifkan.")

    await message.answer(text, parse_mode="HTML")
