"""Automatic BayarGG QR payment for file purchases.
Uses the existing file_purchases/finish_payment flow and the signed webhook.
"""
import io, logging, qrcode, secrets, base64, binascii
from datetime import datetime
from aiogram import Router, F
from aiogram.types import CallbackQuery, BufferedInputFile, InlineKeyboardMarkup, InlineKeyboardButton
from database import fetchrow, execute
from utils.bayargg import BayarGG
from handlers.pay import finish_payment, get_file_by_code, get_paid_purchase, get_or_create_purchase, get_active_method_purchase, purchase_method, format_rupiah, clean_html
from config import BAYARGG_ENABLED, BAYARGG_WEBHOOK_URL, BOT_URL

logger=logging.getLogger(__name__)
router=Router()


def _parse_expires(value):
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value
    text = str(value).strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except Exception:
        logger.warning("BAYARGG EXPIRES PARSE FAILED: %r", value)
        return None


def _qr_bytes(value):
    if not value:
        return None
    value = str(value).strip()
    if value.startswith("data:image/"):
        try:
            _, encoded = value.split(",", 1)
            data = base64.b64decode(encoded, validate=True)
            return data or None
        except (ValueError, binascii.Error):
            logger.exception("BAYARGG DATA QR INVALID")
            return None
    try:
        img = qrcode.make(value)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()
    except Exception:
        logger.exception("BAYARGG QR RENDER ERROR")
        return None

def kb(purchase_id:int):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 Cek Pembayaran", callback_data=f"bayarggcheck:{purchase_id}")],
        [InlineKeyboardButton(text="❌ Tutup", callback_data="close")]
    ])

async def create_bayargg(call:CallbackQuery, code:str, file):
    if not BAYARGG_ENABLED:
        return await call.message.answer("❌ BayarGG sedang tidak tersedia.")
    uid=int(call.from_user.id); price=int(file.get("price") or 0)
    if price<=0: return await call.message.answer("❌ Harga file tidak valid.")
    paid=await get_paid_purchase(uid,code)
    if paid:
        from handlers.getfile import process_code
        return await process_code(call.message, code, paid_override=True, user_id=call.from_user.id)
    existing=await get_active_method_purchase(uid,code,"BAYARGG-")
    if existing:
        return await call.message.answer("⏳ Transaksi BayarGG masih aktif. Tekan cek pembayaran.", reply_markup=kb(existing["id"]))
    result=await get_or_create_purchase(uid,code,file,payment_prefix="BAYARGG-")
    if not result: return await call.message.answer("❌ Gagal membuat transaksi.")
    purchase=result["purchase"]
    if result.get("already_paid"):
        from handlers.getfile import process_code
        return await process_code(call.message, code, paid_override=True, user_id=call.from_user.id)
    if result.get("existing"):
        if purchase_method(purchase)=="bayargg":
            return await call.message.answer("⏳ Transaksi BayarGG masih aktif.",reply_markup=kb(purchase["id"]))
        return await call.message.answer("⚠️ Gunakan transaksi aktif yang sudah ada.")
    local_id=str(purchase["payment_id"])
    try:
        data=await BayarGG.create_payment(
            amount=price,
            description=f"File {code}",
            callback_url=BAYARGG_WEBHOOK_URL or None,
            redirect_url=BOT_URL,
            customer_name=call.from_user.full_name,
            payment_method="qris",
        )
    except Exception:
        logger.exception("BAYARGG CREATE ERROR")
        data=None
    if not data:
        await execute("UPDATE file_purchases SET status='failed' WHERE id=$1 AND status='pending'",purchase["id"])
        return await call.message.answer("❌ Gagal membuat QR BayarGG. Silakan pilih QR otomatis lainnya.")
    invoice=str(data["invoice_id"])
    qr=str(
        data.get("qris_string")
        or data.get("qris")
        or data.get("qr_string")
        or data.get("qr")
        or data.get("qrUrl")
        or data.get("qr_url")
        or ""
    ).strip()
    expires=_parse_expires(data.get("expires_at"))
    saved=await fetchrow("""UPDATE file_purchases SET payment_id=$1,qr_string=$2,payment_url=$3,expires_at=$4 WHERE id=$5 AND status='pending' RETURNING *""",
                         invoice,qr,data.get("payment_url"),expires,purchase["id"])
    if not saved: return await call.message.answer("❌ Transaksi berubah saat diproses.")
    try:
        qr_data = _qr_bytes(qr)
        if not qr_data:
            raise ValueError("QR BayarGG kosong atau tidak valid")
        msg=await call.message.answer_photo(
            BufferedInputFile(qr_data,"bayargg_qris.png"),
            caption=("⚡ <b>QR OTOMATIS 2 • BAYARGG</b>\n\n"
                     f"📄 <b>{clean_html(file.get('title'))}</b>\n"
                     f"🔑 <code>{clean_html(code)}</code>\n"
                     f"💰 <b>{format_rupiah(price)}</b>\n\n"
                     "Scan QR, bayar sesuai nominal. Pembayaran akan diverifikasi otomatis."),
            parse_mode="HTML",reply_markup=kb(saved["id"]))
        await execute("UPDATE file_purchases SET qr_message_id=$1,qr_chat_id=$2 WHERE id=$3 AND status='pending'",msg.message_id,msg.chat.id,saved["id"])
    except Exception:
        logger.exception("BAYARGG QR SEND ERROR")
        return await call.message.answer("⚠️ Pembayaran dibuat, tetapi QR gagal ditampilkan. Gunakan cek pembayaran.")

# INTERNAL: routed centrally by handlers.pay
async def bayargg_entry(call:CallbackQuery):
    await call.answer("⏳ Membuat QR BayarGG...")
    code=call.data.split(":",1)[1].strip()
    file=await get_file_by_code(code)
    if not file: return await call.message.answer("❌ File tidak ditemukan.")
    return await create_bayargg(call,code,file)

# INTERNAL: routed centrally by handlers.pay
async def bayargg_check(call:CallbackQuery):
    await call.answer("⏳ Mengecek BayarGG...")
    pid=int(call.data.split(":",1)[1])
    purchase=await fetchrow("SELECT * FROM file_purchases WHERE id=$1 AND user_id=$2 LIMIT 1",pid,call.from_user.id)
    if not purchase: return await call.message.answer("❌ Transaksi tidak ditemukan.")
    if purchase["status"]=="paid": return await call.message.answer("✅ Pembayaran sudah berhasil diproses.")
    invoice=str(purchase.get("payment_id") or "")
    if not invoice: return await call.message.answer("❌ Invoice BayarGG tidak ditemukan.")
    data=await BayarGG.check_payment(invoice)
    status=str((data or {}).get("status") or "").lower()
    if status in {"paid","success","settled","completed","completed_payment","success_payment"}:
        file=await get_file_by_code(str(purchase.get("file_code") or purchase.get("code") or ""))
        if not file: return await call.message.answer("❌ File tidak ditemukan.")
        return await finish_payment(call.bot,purchase,file,invoice,call.message)
    if status in {"expired","cancel","cancelled","failed","rejected","void"}:
        await execute("UPDATE file_purchases SET status=$1 WHERE id=$2 AND status IN ('pending','verifying')",status,pid)
        return await call.message.answer("❌ Pembayaran tidak berhasil.",reply_markup=None)
    return await call.message.answer("⏳ Belum terkonfirmasi. Jangan bayar ulang.",reply_markup=kb(pid))
