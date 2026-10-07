from __future__ import annotations
import html
import logging
import qrcode
from io import BytesIO
from datetime import datetime, timedelta
from typing import Optional
from aiogram import Router, F
from aiogram.types import (
    CallbackQuery,
    Message,
    BufferedInputFile,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from aiogram.exceptions import (
    TelegramBadRequest,
    TelegramForbiddenError,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.fsm.context import FSMContext
from database import get_pool
from utils.bayargg import BayarGG
from config_vip import VIP_PACKAGES
from config import MANUAL_QR_FILE_ID, ADMIN_IDS
from utils.user_lang import get_user_language
from utils.payment_methods import payment_methods_enabled, payment_selector_markup, qr_selector_markup
from utils.cashi import Cashi
from states import VipManualState
from utils.payment_channel import send_payment_success_channel
logger = logging.getLogger(__name__)
router = Router()
DEFAULT_LANGUAGE = "id"
# ============================================================
# HELPERS
# ============================================================
def rupiah(value: int | float) -> str:
    try:
        return f"Rp {int(value):,}".replace(",", ".")
    except (TypeError, ValueError):
        return "Rp 0"
def safe_html(value) -> str:
    return html.escape(str(value or ""))
def parse_int(value: str) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
async def safe_callback_answer(
    call: CallbackQuery,
    text: str | None = None,
    *,
    show_alert: bool = False,
) -> bool:
    try:
        await call.answer(
            text=text,
            show_alert=show_alert,
        )
        return True
    except TelegramBadRequest as exc:
        error = str(exc).lower()
        if (
            "query is too old" in error
            or "query id is invalid" in error
            or "response timeout expired" in error
        ):
            logger.debug(
                "VIP callback expired/invalid: %s",
                error,
            )
            return False
        logger.warning(
            "VIP callback Telegram error: %s",
            exc,
        )
        return False
    except TelegramForbiddenError:
        return False
    except Exception:
        logger.exception(
            "Unexpected VIP callback answer error"
        )
        return False
async def safe_delete_message(
    message: Message | None,
) -> None:
    if not message:
        return
    try:
        await message.delete()
    except (
        TelegramBadRequest,
        TelegramForbiddenError,
    ):
        pass
    except Exception:
        logger.exception(
            "VIP message delete error"
        )
async def safe_send_message(
    message: Message,
    text: str,
    *,
    reply_markup=None,
    parse_mode: str = "HTML",
) -> bool:
    try:
        await message.answer(
            text,
            parse_mode=parse_mode,
            reply_markup=reply_markup,
        )
        return True
    except (
        TelegramBadRequest,
        TelegramForbiddenError,
    ):
        logger.warning(
            "VIP message send failed"
        )
        return False
    except Exception:
        logger.exception(
            "VIP message send error"
        )
        return False
# ============================================================
# VIP MENU
# ============================================================
def build_vvip(
    lang: str = DEFAULT_LANGUAGE,
):
    lang = (
        lang
        if lang in ("id", "en")
        else DEFAULT_LANGUAGE
    )
    kb = InlineKeyboardBuilder()
    for key, paket in VIP_PACKAGES.items():
        name = paket.get(
            "name",
            str(key),
        )
        price = paket.get(
            "price",
            0,
        )
        kb.button(
            text=(
                f"💎 {name} • "
                f"{rupiah(price)}"
            ),
            callback_data=f"payvip:{key}",
        )
    kb.button(
        text=(
            "🔙 Kembali"
            if lang == "id"
            else "🔙 Back"
        ),
        callback_data="account",
    )
    kb.adjust(1)
    if lang == "id":
        text = (
            "<b>💎 PREMIUM ACCESS</b>\n"
            "━━━━━━━━━━━━━━\n\n"
            "Pilih paket yang sesuai "
            "kebutuhan kamu.\n\n"
            "💠 <b>VIP</b>\n"
            "• Akses fitur premium\n"
            "• Tidak bisa upload\n\n"
            "💎 <b>VVIP</b>\n"
            "• Semua fitur VIP\n"
            "• Bisa upload & simpan media\n"
            "• Fitur premium terbuka\n\n"
            "📷 Pembayaran menggunakan "
            "<b>QR Manual</b>."
        )
    else:
        text = (
            "<b>💎 PREMIUM ACCESS</b>\n"
            "━━━━━━━━━━━━━━\n\n"
            "Choose the package you need.\n\n"
            "💠 <b>VIP</b>\n"
            "• Premium access\n"
            "• Upload is not available\n\n"
            "💎 <b>VVIP</b>\n"
            "• All VIP features\n"
            "• Upload & save media\n"
            "• Premium features unlocked\n\n"
            "📷 Payment uses "
            "<b>manual QR</b>."
        )
    return text, kb.as_markup()
async def open_vvip(
    message: Message,
    user_id: int,
):
    try:
        lang = await get_user_language(
            user_id
        )
    except Exception:
        logger.exception(
            "VIP language lookup error"
        )
        lang = DEFAULT_LANGUAGE
    text, markup = build_vvip(lang)
    await message.answer(
        text,
        parse_mode="HTML",
        reply_markup=markup,
    )
# ============================================================
# OPEN VIP FROM MESSAGE
# ============================================================
@router.message(F.text == "💎 Upgrade")
async def vvip_message(
    message: Message,
):
    if not message.from_user:
        return
    await open_vvip(
        message,
        message.from_user.id,
    )
# ============================================================
# OPEN VIP FROM ACCOUNT
# ============================================================
@router.callback_query(F.data == "vvip")
async def vvip_menu(
    call: CallbackQuery,
):
    await safe_callback_answer(call)
    if not call.message:
        return
    await open_vvip(
        call.message,
        call.from_user.id,
    )
# ============================================================
# AUTO PAYMENT
# ============================================================
async def _create_auto_vip(
    call: CallbackQuery,
    paket_id: str,
    paket: dict,
):
    pool = await get_pool()
    user_id = call.from_user.id
    # --------------------------------------------------------
    # CHECK EXISTING PENDING PAYMENT
    # --------------------------------------------------------
    try:
        pending = await pool.fetchrow(
            """
            SELECT invoice_id
            FROM payments
            WHERE user_id = $1
              AND status = 'pending'
              AND (
                  expires_at IS NULL
                  OR expires_at > NOW()
              )
            LIMIT 1
            """,
            user_id,
        )
    except Exception:
        logger.exception(
            "VIP pending payment DB error"
        )
        await call.message.answer(
            "❌ Tidak dapat memeriksa "
            "pembayaran sebelumnya."
        )
        return
    if pending:
        await call.message.answer(
            "⚠️ Masih ada pembayaran VIP "
            "yang belum selesai.\n\n"
            "Selesaikan pembayaran tersebut "
            "atau tunggu sampai kedaluwarsa."
        )
        return
    # --------------------------------------------------------
    # CREATE PAYMENT
    # --------------------------------------------------------
    try:
        payment = await BayarGG.create_payment(
            amount=paket["price"],
            description=(
                f"{paket['name']} - "
                f"{paket['days']} Hari"
            ),
            customer_name=call.from_user.full_name,
        )
    except Exception:
        logger.exception(
            "VIP AUTO PAYMENT ERROR"
        )
        await _manual_fallback(
            call,
            paket_id,
            paket,
            "QR otomatis mengalami gangguan.",
        )
        return
    if not payment:
        await _manual_fallback(
            call,
            paket_id,
            paket,
            "Invoice otomatis gagal dibuat.",
        )
        return
    invoice_id = payment.get(
        "invoice_id"
    )
    qr_string = payment.get(
        "qris_string"
    )
    if not invoice_id:
        await _manual_fallback(
            call,
            paket_id,
            paket,
            "Invoice otomatis tidak valid.",
        )
        return
    # --------------------------------------------------------
    # EXPIRY
    # --------------------------------------------------------
    expires_at = None
    raw_exp = payment.get(
        "expires_at"
    )
    if raw_exp:
        if isinstance(
            raw_exp,
            datetime,
        ):
            expires_at = raw_exp
        else:
            raw_exp = str(
                raw_exp
            ).strip()
            formats = (
                "%Y-%m-%d %H:%M:%S",
                "%Y-%m-%d %H:%M",
                "%Y-%m-%dT%H:%M:%S",
            )
            for fmt in formats:
                try:
                    expires_at = datetime.strptime(
                        raw_exp,
                        fmt,
                    )
                    break
                except ValueError:
                    continue
    # --------------------------------------------------------
    # SAVE PAYMENT
    # --------------------------------------------------------
    try:
        await pool.execute(
            """
            INSERT INTO payments
            (
                order_id,
                user_id,
                code,
                reference,
                amount,
                status,
                provider,
                invoice_id,
                payment_url,
                expires_at,
                type
            )
            VALUES
            (
                $1,
                $2,
                $3,
                $4,
                $5,
                'pending',
                'bayargg',
                $6,
                $7,
                $8,
                $9
            )
            ON CONFLICT (invoice_id)
            DO NOTHING
            """,
            invoice_id,
            user_id,
            paket_id,
            invoice_id,
            paket["price"],
            invoice_id,
            payment.get("payment_url"),
            expires_at,
            paket.get("type", "vip"),
        )
    except Exception:
        logger.exception(
            "VIP PAYMENT DB ERROR"
        )
        await _manual_fallback(
            call,
            paket_id,
            paket,
            "Database pembayaran otomatis "
            "bermasalah.",
        )
        return
    # --------------------------------------------------------
    # PAYMENT MESSAGE
    # --------------------------------------------------------
    text = (
        "<b>💳 PEMBAYARAN VIP</b>\n"
        "━━━━━━━━━━━━━━\n\n"
        f"📦 Paket: "
        f"<b>{safe_html(paket['name'])}</b>\n"
        f"💰 Harga: "
        f"<b>{rupiah(paket['price'])}</b>\n"
        f"🧾 Invoice: "
        f"<code>{safe_html(invoice_id)}</code>\n\n"
        "📷 Scan QR otomatis untuk membayar.\n"
        "⚠️ Jika QR otomatis error/"
        "tidak bisa dipakai, tekan "
        "<b>📷 QR Manual</b>.\n\n"
        "Setelah pembayaran berhasil, "
        "VIP akan aktif otomatis."
    )
    kb = InlineKeyboardBuilder()
    kb.button(
        text="⏳ Cek Pembayaran",
        callback_data=(
            f"vipwait:{invoice_id}"
        ),
    )
    kb.button(
        text="📷 QR Manual",
        callback_data=(
            f"payvipmethod:{paket_id}:manual"
        ),
    )
    kb.button(
        text="❌ Batal",
        callback_data="vvip",
    )
    kb.adjust(1)
    await safe_delete_message(
        call.message
    )
    # --------------------------------------------------------
    # AUTOMATIC QR
    # --------------------------------------------------------
    if qr_string:
        try:
            qr = qrcode.make(
                qr_string
            )
            buf = BytesIO()
            qr.save(
                buf,
                format="PNG",
            )
            buf.seek(0)
            await call.message.answer_photo(
                BufferedInputFile(
                    buf.getvalue(),
                    filename="vip-qris.png",
                ),
                caption=text,
                parse_mode="HTML",
                reply_markup=kb.as_markup(),
            )
            return
        except Exception:
            logger.exception(
                "VIP QR GENERATION ERROR"
            )
    # --------------------------------------------------------
    # NO QR
    # --------------------------------------------------------
    await call.message.answer(
        text
        + "\n\n⚠️ <b>QR otomatis "
        "tidak tersedia.</b>\n"
        "Gunakan QR Manual di bawah.",
        parse_mode="HTML",
        reply_markup=kb.as_markup(),
    )
# ============================================================
# BUY VIP
# ============================================================
# INTERNAL: routed centrally by handlers.pay
async def buy_vip(
    call: CallbackQuery,
):
    await safe_callback_answer(call)
    if not call.message:
        return
    parts = call.data.split(
        ":",
        1,
    )
    if len(parts) != 2:
        await call.message.answer(
            "❌ Data paket tidak valid."
        )
        return
    paket_id = parts[1].strip()
    if not paket_id:
        await call.message.answer(
            "❌ Paket tidak valid."
        )
        return
    paket = VIP_PACKAGES.get(
        paket_id
    )
    if not paket:
        await call.message.answer(
            "❌ Paket tidak ditemukan."
        )
        return
    lang = await get_user_language(call.from_user.id)
    methods = await payment_methods_enabled()
    labels = {
        "id": "💳 <b>Pilih Metode Pembayaran</b>\n\nPilih metode pembayaran untuk paket ini.",
        "en": "💳 <b>Choose Payment Method</b>\n\nChoose a payment method for this package.",
        "zh": "💳 <b>选择支付方式</b>\n\n请选择此套餐的支付方式。",
    }
    await call.message.edit_text(
        labels.get(lang, labels["id"]) + f"\n\n📦 <b>{safe_html(paket['name'])}</b>\n💰 <b>{rupiah(paket['price'])}</b>",
        parse_mode="HTML",
        reply_markup=payment_selector_markup(f"payvipmethod:{paket_id}", lang, methods),
    )
# INTERNAL: routed centrally by handlers.pay
async def vip_method(call: CallbackQuery):
    await safe_callback_answer(call)
    parts = call.data.split(":")
    if len(parts) != 3 or parts[0] not in {"vipmethod", "payvipmethod"}:
        return
    paket_id, method = parts[1], parts[2]
    paket = VIP_PACKAGES.get(paket_id)
    if not paket:
        return await call.message.answer("❌ Paket tidak ditemukan.")
    if method == "cancel":
        return await open_vvip(call.message, call.from_user.id)
    if method == "qr":
        lang = await get_user_language(call.from_user.id)
        methods = await payment_methods_enabled()
        return await call.message.edit_reply_markup(reply_markup=qr_selector_markup(f"payvipmethod:{paket_id}", lang, methods))
    if method == "cashi":
        return await _create_cashi_vip(call, paket_id, paket)
    if method == "bayargg":
        return await _create_auto_vip(call, paket_id, paket)
    if method == "manual":
        return await create_manual_vip_payment(call, paket_id, paket)
    if method == "back":
        lang = await get_user_language(call.from_user.id)
        return await call.message.edit_reply_markup(reply_markup=payment_selector_markup(f"payvipmethod:{paket_id}", lang, await payment_methods_enabled()))

async def _create_cashi_vip(call: CallbackQuery, paket_id: str, paket: dict):
    pool = await get_pool()
    user_id = call.from_user.id
    try:
        payment = await Cashi.create_payment(paket["price"], f"{paket['name']} - {paket['days']} Hari", call.from_user.full_name)
    except Exception:
        logger.exception("VIP CASHI CREATE ERROR")
        return await call.message.answer("❌ Cashi sedang tidak tersedia.")
    if not payment:
        return await call.message.answer("❌ Cashi gagal membuat pembayaran.")
    invoice = str(payment.get("invoice_id") or payment.get("order_id") or "").strip()
    if not invoice:
        return await call.message.answer("❌ Invoice Cashi tidak valid.")
    await pool.execute("""
        INSERT INTO payments(order_id,user_id,code,reference,amount,status,provider,invoice_id,payment_url,expires_at,type)
        VALUES($1,$2,$3,$4,$5,'pending','cashi',$6,$7,$8,'vip')
        ON CONFLICT(invoice_id) DO NOTHING
    """, invoice, user_id, paket_id, invoice, paket["price"], invoice, payment.get("payment_url"), payment.get("expires_at"))
    qr = payment.get("qr_string") or payment.get("qr_image")
    text = f"💳 <b>VIP • CASHI</b>\n\n📦 {safe_html(paket['name'])}\n💰 <b>{rupiah(paket['price'])}</b>\n🧾 <code>{safe_html(invoice)}</code>\n\nScan QR lalu tekan cek pembayaran."
    kb=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔄 Cek Pembayaran",callback_data=f"vipcashicheck:{invoice}")],[InlineKeyboardButton(text="❌ Batal",callback_data=f"payvipmethod:{paket_id}:cancel")]])
    if qr:
        try:
            raw = qr
            if isinstance(raw,str) and raw.startswith("data:image/"):
                import base64
                raw=base64.b64decode(raw.split(',',1)[1])
                photo=BufferedInputFile(raw,filename="vip-cashi.png")
            else:
                buf=BytesIO(); qrcode.make(raw).save(buf,format="PNG"); photo=BufferedInputFile(buf.getvalue(),filename="vip-cashi.png")
            await call.message.answer_photo(photo,caption=text,parse_mode="HTML",reply_markup=kb)
            return
        except Exception:
            logger.exception("VIP CASHI QR ERROR")
    await call.message.answer(text,parse_mode="HTML",reply_markup=kb)

# INTERNAL: routed centrally by handlers.pay
async def vip_cashi_check(call: CallbackQuery):
    await safe_callback_answer(call)
    invoice=call.data.split(":",1)[1].strip()
    pool=await get_pool()
    tx=await pool.fetchrow("SELECT * FROM payments WHERE invoice_id=$1 AND user_id=$2 AND type='vip'",invoice,call.from_user.id)
    if not tx: return await call.message.answer("❌ Invoice tidak ditemukan.")
    result=await Cashi.check_payment(invoice)
    status=str((result or {}).get("status") or "").lower()
    if status not in {"settled","paid","success","completed"}:
        return await call.answer("⏳ Pembayaran belum diterima.",show_alert=True)
    updated=await pool.fetchrow("UPDATE payments SET status='paid',paid_at=NOW() WHERE id=$1 AND status!='paid' RETURNING id",tx["id"])
    if not updated:
        return await call.message.answer("✅ Pembayaran sudah diproses.")
    paket=VIP_PACKAGES.get(str(tx["code"]))
    days=int((paket or {}).get("days",1))
    plan_name=str((paket or {}).get("type") or "vip").lower()
    is_vvip=plan_name in {"vvip","premium_vvip"} or "vvip" in str((paket or {}).get("name") or "").lower()
    await pool.execute(
        """UPDATE users SET
            vip=TRUE, is_vip=TRUE,
            vvip=CASE WHEN $3 THEN TRUE ELSE vvip END,
            is_vvip=CASE WHEN $3 THEN TRUE ELSE is_vvip END,
            plan=CASE WHEN $3 THEN 'vvip' ELSE 'vip' END,
            vip_until=CASE WHEN vip_until IS NULL OR vip_until<NOW()
                THEN NOW()+($2||' days')::interval
                ELSE vip_until+($2||' days')::interval END,
            updated_at=NOW()
           WHERE user_id=$1""",
        call.from_user.id, days, is_vvip
    )
    lang=await get_user_language(call.from_user.id)
    msg={
        "id":f"🎉 <b>Pembayaran berhasil!</b>\n\n💎 Status akun: <b>{'VVIP' if is_vvip else 'VIP'}</b>\n📅 Durasi: <b>{days} hari</b>",
        "en":f"🎉 <b>Payment successful!</b>\n\n💎 Account status: <b>{'VVIP' if is_vvip else 'VIP'}</b>\n📅 Duration: <b>{days} days</b>",
        "zh":f"🎉 <b>支付成功！</b>\n\n💎 账户状态：<b>{'VVIP' if is_vvip else 'VIP'}</b>\n📅 有效期：<b>{days} 天</b>",
    }[lang]
    await call.message.answer(msg,parse_mode="HTML")

# ============================================================
# EXTEND VIP
# ============================================================
@router.callback_query(
    F.data.startswith("extendvip:")
)
async def extend_vip(
    call: CallbackQuery,
):
    await safe_callback_answer(call)
    if not call.message:
        return
    parts = call.data.split(
        ":",
        1,
    )
    if len(parts) != 2:
        await call.message.answer(
            "❌ Data paket tidak valid."
        )
        return
    paket_id = parts[1].strip()
    if not paket_id:
        await call.message.answer(
            "❌ Paket tidak valid."
        )
        return
    paket = VIP_PACKAGES.get(
        paket_id
    )
    if not paket:
        await call.message.answer(
            "❌ Paket tidak ditemukan."
        )
        return
    # ========================================================
    # PERPANJANGAN -> QR MANUAL
    # ========================================================
    return await create_manual_vip_payment(
        call,
        paket_id,
        paket,
    )
# ============================================================
# MANUAL FALLBACK
# ============================================================
async def _manual_fallback(
    call: CallbackQuery,
    paket_id: str,
    paket: dict,
    why: str,
):
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📷 QR Manual",
                    callback_data=(
                        f"payvipmethod:{paket_id}:manual"
                    ),
                )
            ],
            [
                InlineKeyboardButton(
                    text="🔙 Kembali",
                    callback_data="vvip",
                )
            ],
        ]
    )
    await call.message.answer(
        (
            "⚠️ <b>QR OTOMATIS ERROR</b>\n\n"
            f"{safe_html(why)}\n\n"
            "Silakan gunakan "
            "<b>QR Manual</b> untuk "
            "melanjutkan pembayaran."
        ),
        parse_mode="HTML",
        reply_markup=kb,
    )
# ============================================================
# CREATE MANUAL VIP PAYMENT
# ============================================================
async def create_manual_vip_payment(
    call: CallbackQuery,
    paket_id: str,
    paket: dict,
):
    """
    SATU pintu untuk membuat pembayaran manual.
    Dipakai oleh:
        buyvip:
        extendvip:
        vipmanual:
    Dengan cara ini paket_id tidak lagi
    bergantung pada variable override.
    """
    if not call.message:
        return
    pool = await get_pool()
    user_id = call.from_user.id
    # --------------------------------------------------------
    # CHECK PENDING
    # --------------------------------------------------------
    try:
        pending = await pool.fetchrow(
            """
            SELECT id
            FROM vip_manual_payments
            WHERE user_id = $1
              AND status = 'pending'
            ORDER BY id DESC
            LIMIT 1
            """,
            user_id,
        )
    except Exception:
        logger.exception(
            "VIP MANUAL PENDING CHECK ERROR"
        )
        await call.message.answer(
            "❌ Gagal memeriksa "
            "pembayaran manual."
        )
        return
    if pending:
        await call.message.answer(
            "⏳ Kamu masih punya "
            "pembayaran manual yang "
            "menunggu verifikasi."
        )
        return
    # --------------------------------------------------------
    # CREATE TRANSACTION
    # --------------------------------------------------------
    try:
        tx = await pool.fetchrow(
            """
            INSERT INTO vip_manual_payments
            (
                user_id,
                package_id,
                amount,
                status
            )
            VALUES
            (
                $1,
                $2,
                $3,
                'pending'
            )
            RETURNING id
            """,
            user_id,
            paket_id,
            paket["price"],
        )
    except Exception:
        logger.exception(
            "VIP MANUAL PAYMENT INSERT ERROR"
        )
        await call.message.answer(
            "❌ Gagal membuat "
            "pembayaran manual."
        )
        return
    if not tx:
        await call.message.answer(
            "❌ Pembayaran manual "
            "gagal dibuat."
        )
        return
    tx_id = tx["id"]
    # --------------------------------------------------------
    # CAPTION
    # --------------------------------------------------------
    caption = (
        "<b>📷 QR MANUAL VIP</b>\n"
        "━━━━━━━━━━━━━━\n\n"
        f"📦 Paket: "
        f"<b>{safe_html(paket['name'])}</b>\n"
        f"💰 Nominal: "
        f"<b>{rupiah(paket['price'])}</b>\n"
        f"🧾 ID Pembayaran: "
        f"<code>VIPM-{tx_id}</code>\n\n"
        "1. Scan QR manual.\n"
        "2. Bayar <b>sesuai nominal</b>.\n"
        "3. Tekan "
        "<b>✅ Saya Sudah Bayar</b>.\n\n"
        "⚠️ Setelah menekan tombol, "
        "pembayaran akan dikirim ke admin "
        "untuk diverifikasi."
    )
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Saya Sudah Bayar",
                    callback_data=(
                        f"vipmanualcheck:{tx_id}"
                    ),
                )
            ],
            [
                InlineKeyboardButton(
                    text="🔙 Kembali",
                    callback_data="vvip",
                )
            ],
        ]
    )
    await safe_delete_message(
        call.message
    )
    # --------------------------------------------------------
    # SEND QR MANUAL
    # --------------------------------------------------------
    try:
        qr_chat = int(await pool.fetchval("SELECT value FROM settings WHERE key=$1", "manual_qr_chat_id") or 0)
        qr_msg = int(await pool.fetchval("SELECT value FROM settings WHERE key=$1", "manual_qr_message_id") or 0)
        if not qr_chat or not qr_msg:
            raise RuntimeError("Manual QR belum diset. Gunakan /qrid.")
        await call.bot.copy_message(
            chat_id=call.message.chat.id,
            from_chat_id=qr_chat,
            message_id=qr_msg,
            caption=caption,
            parse_mode="HTML",
            reply_markup=kb,
        )
    except Exception:
        logger.exception(
            "VIP MANUAL QR SEND ERROR"
        )
        await call.message.answer(
            (
                "❌ QR Manual tidak dapat "
                "ditampilkan.\n\n"
                f"ID pembayaran: "
                f"<code>VIPM-{tx_id}</code>"
            ),
            parse_mode="HTML",
        )
# ============================================================
# OPEN MANUAL PAYMENT
# ============================================================
@router.callback_query(
    F.data.startswith("vipmanual:")
)
async def vip_manual(
    call: CallbackQuery,
):
    await safe_callback_answer(call)
    if not call.message:
        return
    parts = call.data.split(
        ":",
        1,
    )
    if len(parts) != 2:
        await call.message.answer(
            "❌ Data paket tidak valid."
        )
        return
    paket_id = parts[1].strip()
    if not paket_id:
        await call.message.answer(
            "❌ Paket tidak valid."
        )
        return
    paket = VIP_PACKAGES.get(
        paket_id
    )
    if not paket:
        await call.message.answer(
            "❌ Paket tidak ditemukan."
        )
        return
    return await create_manual_vip_payment(
        call,
        paket_id,
        paket,
    )
# ============================================================
# USER CONFIRMS MANUAL PAYMENT
# ============================================================
# INTERNAL: routed centrally by handlers.pay
async def vip_manual_check(
    call: CallbackQuery,
):
    await safe_callback_answer(call)
    if not call.message:
        return
    parts = call.data.split(
        ":",
        1,
    )
    if len(parts) != 2:
        return
    tx_id = parse_int(
        parts[1]
    )
    if tx_id is None:
        await call.message.answer(
            "❌ ID pembayaran tidak valid."
        )
        return
    pool = await get_pool()
    user_id = call.from_user.id
    try:
        tx = await pool.fetchrow(
            """
            SELECT *
            FROM vip_manual_payments
            WHERE id = $1
              AND user_id = $2
              AND status = 'pending'
            """,
            tx_id,
            user_id,
        )
    except Exception:
        logger.exception(
            "VIP MANUAL CHECK DB ERROR"
        )
        await call.message.answer(
            "❌ Gagal memeriksa "
            "pembayaran."
        )
        return
    if not tx:
        await call.message.answer(
            "❌ Transaksi tidak ditemukan "
            "atau sudah diproses."
        )
        return
    paket = VIP_PACKAGES.get(
        tx["package_id"],
        {},
    )
    admin_text = (
        "📥 <b>VIP MANUAL PAYMENT</b>\n"
        "━━━━━━━━━━━━━━\n\n"
        f"👤 User: "
        f"<code>{tx['user_id']}</code>\n"
        f"📦 Paket: "
        f"<b>{safe_html(paket.get('name', tx['package_id']))}</b>\n"
        f"💰 Nominal: "
        f"<b>{rupiah(tx['amount'])}</b>\n"
        f"🧾 ID: "
        f"<code>VIPM-{tx['id']}</code>\n\n"
        "Pilih status setelah "
        "mengecek pembayaran:"
    )
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ APPROVE",
                    callback_data=(
                        f"vipapprove:{tx['id']}"
                    ),
                ),
                InlineKeyboardButton(
                    text="❌ FAILED",
                    callback_data=(
                        f"vipfailed:{tx['id']}"
                    ),
                ),
            ]
        ]
    )
    sent = 0
    for admin in ADMIN_IDS:
        try:
            await call.bot.send_message(
                admin,
                admin_text,
                parse_mode="HTML",
                reply_markup=kb,
            )
            sent += 1
        except (
            TelegramBadRequest,
            TelegramForbiddenError,
        ):
            logger.warning(
                "VIP admin notification failed: %s",
                admin,
            )
        except Exception:
            logger.exception(
                "VIP ADMIN NOTIFY ERROR admin=%s",
                admin,
            )
    if sent:
        await call.message.answer(
            "✅ Permintaan verifikasi "
            "sudah dikirim ke admin.\n\n"
            "Tunggu hasil verifikasi."
        )
    else:
        await call.message.answer(
            "❌ Admin tidak dapat "
            "menerima notifikasi."
        )
# ============================================================
# ACTIVATE VIP
# ============================================================
async def _activate_vip(
    pool,
    user_id: int,
    paket: dict,
):
    now = datetime.now()
    package_type = str(
        paket.get(
            "type",
            "vip",
        )
    ).lower()
    if package_type == "vvip":
        field = "vvip_expired"
    else:
        field = "vip_expired"
    old = await pool.fetchval(
        f"""
        SELECT {field}
        FROM users
        WHERE user_id = $1
        """,
        user_id,
    )
    if old and old > now:
        base = old
    else:
        base = now
    expiry = (
        base
        + timedelta(
            days=int(
                paket["days"]
            )
        )
    )
    if package_type == "vvip":
        await pool.execute(
            """
            UPDATE users
            SET
                vvip = TRUE,
                is_vvip = TRUE,
                vvip_expired = $1,
                vip = TRUE,
                is_vip = TRUE,
                vip_expired = $1
            WHERE user_id = $2
            """,
            expiry,
            user_id,
        )
        return expiry, "VVIP"
    await pool.execute(
        """
        UPDATE users
        SET
            vip = TRUE,
            is_vip = TRUE,
            vip_expired = $1
        WHERE user_id = $2
        """,
        expiry,
        user_id,
    )
    return expiry, "VIP"
# ============================================================
# ADMIN APPROVE
# ============================================================
@router.callback_query(
    F.data.startswith("vipapprove:")
)
async def vip_approve(
    call: CallbackQuery,
):
    await safe_callback_answer(call)
    if not call.message:
        return
    if call.from_user.id not in ADMIN_IDS:
        await call.message.answer(
            "❌ Bukan admin."
        )
        return
    parts = call.data.split(
        ":",
        1,
    )
    if len(parts) != 2:
        return
    tx_id = parse_int(
        parts[1]
    )
    if tx_id is None:
        await call.message.answer(
            "❌ ID pembayaran tidak valid."
        )
        return
    pool = await get_pool()
    try:
        tx = await pool.fetchrow(
            """
            SELECT *
            FROM vip_manual_payments
            WHERE id = $1
              AND status = 'pending'
            """,
            tx_id,
        )
    except Exception:
        logger.exception(
            "VIP APPROVE FETCH ERROR"
        )
        await call.message.answer(
            "❌ Gagal mengambil "
            "data pembayaran."
        )
        return
    if not tx:
        await call.message.answer(
            "❌ Transaksi sudah diproses "
            "atau tidak ditemukan."
        )
        return
    paket = VIP_PACKAGES.get(
        tx["package_id"]
    )
    if not paket:
        await call.message.answer(
            "❌ Paket tidak ditemukan."
        )
        return
    try:
        updated = await pool.fetchrow(
            """
            UPDATE vip_manual_payments
            SET
                status = 'approved',
                admin_id = $1,
                reviewed_at = NOW()
            WHERE id = $2
              AND status = 'pending'
            RETURNING *
            """,
            call.from_user.id,
            tx_id,
        )
    except Exception:
        logger.exception(
            "VIP APPROVE UPDATE ERROR"
        )
        await call.message.answer(
            "❌ Gagal memproses "
            "approval."
        )
        return
    if not updated:
        await call.message.answer(
            "❌ Transaksi sudah "
            "diproses oleh admin lain."
        )
        return
    try:
        expiry, tier = await _activate_vip(
            pool,
            tx["user_id"],
            paket,
        )
    except Exception:
        logger.exception(
            "VIP ACTIVATE ERROR tx=%s",
            tx_id,
        )
        await call.message.answer(
            "⚠️ Pembayaran sudah APPROVED, "
            "tetapi aktivasi VIP mengalami "
            "error database.\n\n"
            f"User: <code>{tx['user_id']}</code>\n"
            f"Transaksi: <code>VIPM-{tx_id}</code>",
            parse_mode="HTML",
        )
        return
    try:
        user_lang = await get_user_language(tx["user_id"])
        notify = {
            "id": (
                f"🎉 <b>{safe_html(tier)} SUDAH AKTIF!</b>\n\n"
                f"📦 Paket: <b>{safe_html(paket['name'])}</b>\n"
                f"⏳ Aktif sampai: <b>{expiry:%d-%m-%Y %H:%M}</b>\n\n"
                "Terima kasih. Selamat menikmati akses premium!"
            ),
            "en": (
                f"🎉 <b>{safe_html(tier)} IS ACTIVE!</b>\n\n"
                f"📦 Package: <b>{safe_html(paket['name'])}</b>\n"
                f"⏳ Active until: <b>{expiry:%d-%m-%Y %H:%M}</b>\n\n"
                "Thank you. Enjoy your premium access!"
            ),
            "zh": (
                f"🎉 <b>{safe_html(tier)} 已激活！</b>\n\n"
                f"📦 套餐：<b>{safe_html(paket['name'])}</b>\n"
                f"⏳ 有效期至：<b>{expiry:%d-%m-%Y %H:%M}</b>\n\n"
                "感谢使用，祝你享受高级功能！"
            ),
        }[user_lang]
        await call.bot.send_message(
            tx["user_id"], notify, parse_mode="HTML"
        )
    except Exception:
        logger.exception(
            "VIP APPROVE USER NOTIFY ERROR"
        )
    await send_payment_success_channel(
        call.bot, "vvip" if str(tier).lower() == "vvip" else "vip",
        tx["user_id"], tx.get("amount"), tx.get("provider") or "manual",
        paket.get("name") or tier, f"VIPM-{tx_id}"
    )
    try:
        await call.message.edit_text(
            (
                "✅ <b>VIP PAYMENT APPROVED</b>\n\n"
                f"User: "
                f"<code>{tx['user_id']}</code>\n"
                f"Paket: "
                f"<b>{safe_html(paket['name'])}</b>\n"
                f"Sampai: "
                f"<b>{expiry:%d-%m-%Y %H:%M}</b>"
            ),
            parse_mode="HTML",
        )
    except TelegramBadRequest as exc:
        logger.debug(
            "VIP admin message already edited: %s",
            exc,
        )
    except Exception:
        logger.exception(
            "VIP APPROVE ADMIN MESSAGE ERROR"
        )
# ============================================================
# ADMIN FAILED
# ============================================================
@router.callback_query(
    F.data.startswith("vipfailed:")
)
async def vip_failed(
    call: CallbackQuery,
    state: FSMContext,
):
    await safe_callback_answer(call)
    if not call.message:
        return
    if call.from_user.id not in ADMIN_IDS:
        await call.message.answer(
            "❌ Bukan admin."
        )
        return
    parts = call.data.split(
        ":",
        1,
    )
    if len(parts) != 2:
        return
    tx_id = parse_int(
        parts[1]
    )
    if tx_id is None:
        await call.message.answer(
            "❌ ID pembayaran tidak valid."
        )
        return
    pool = await get_pool()
    try:
        tx = await pool.fetchrow(
            """
            SELECT *
            FROM vip_manual_payments
            WHERE id = $1
              AND status = 'pending'
            """,
            tx_id,
        )
    except Exception:
        logger.exception(
            "VIP FAILED FETCH ERROR"
        )
        await call.message.answer(
            "❌ Gagal mengambil "
            "data pembayaran."
        )
        return
    if not tx:
        await call.message.answer(
            "❌ Transaksi sudah diproses "
            "atau tidak ditemukan."
        )
        return
    await state.update_data(
        vip_failed_tx=tx_id
    )
    await state.set_state(
        VipManualState.waiting_reason
    )
    await call.message.answer(
        "📝 <b>Masukkan alasan FAILED</b>\n\n"
        "Contoh:\n"
        "<i>Pembayaran belum lunas / "
        "nominal tidak sesuai / "
        "pembayaran belum masuk.</i>\n\n"
        "Ketik alasan yang akan dikirim "
        "ke user.",
        parse_mode="HTML",
    )
# ============================================================
# ADMIN FAILED REASON
# ============================================================
@router.message(
    VipManualState.waiting_reason
)
async def vip_failed_reason(
    message: Message,
    state: FSMContext,
):
    if not message.from_user:
        await state.clear()
        return
    if message.from_user.id not in ADMIN_IDS:
        await state.clear()
        return
    data = await state.get_data()
    tx_id = data.get(
        "vip_failed_tx"
    )
    if not tx_id:
        await state.clear()
        await message.answer(
            "❌ Sesi FAILED tidak ditemukan."
        )
        return
    reason = (
        message.text.strip()
        if message.text
        else "Pembayaran belum terverifikasi."
    )
    if not reason:
        reason = (
            "Pembayaran belum "
            "terverifikasi."
        )
    pool = await get_pool()
    try:
        tx = await pool.fetchrow(
            """
            SELECT *
            FROM vip_manual_payments
            WHERE id = $1
              AND status = 'pending'
            """,
            tx_id,
        )
    except Exception:
        logger.exception(
            "VIP FAILED FETCH ERROR"
        )
        await state.clear()
        await message.answer(
            "❌ Gagal mengambil "
            "data pembayaran."
        )
        return
    if not tx:
        await state.clear()
        await message.answer(
            "❌ Transaksi sudah diproses "
            "atau tidak ditemukan."
        )
        return
    try:
        updated = await pool.fetchrow(
            """
            UPDATE vip_manual_payments
            SET
                status = 'failed',
                reason = $1,
                admin_id = $2,
                reviewed_at = NOW()
            WHERE id = $3
              AND status = 'pending'
            RETURNING *
            """,
            reason,
            message.from_user.id,
            tx_id,
        )
    except Exception:
        logger.exception(
            "VIP FAILED UPDATE ERROR"
        )
        await state.clear()
        await message.answer(
            "❌ Gagal menyimpan "
            "status FAILED."
        )
        return
    if not updated:
        await state.clear()
        await message.answer(
            "❌ Transaksi sudah "
            "diproses oleh admin lain."
        )
        return
    await message.answer(
        (
            "❌ <b>FAILED</b> berhasil disimpan.\n\n"
            "User akan menerima alasan:\n"
            f"<i>{safe_html(reason)}</i>"
        ),
        parse_mode="HTML",
    )
    try:
        await message.bot.send_message(
            tx["user_id"],
            (
                "❌ <b>Pembayaran VIP "
                "belum dapat diverifikasi</b>\n\n"
                f"📝 Masukan admin: "
                f"<i>{safe_html(reason)}</i>\n\n"
                "Silakan lakukan pembayaran "
                "yang benar lalu gunakan "
                "QR Manual lagi."
            ),
            parse_mode="HTML",
        )
    except Exception:
        logger.exception(
            "VIP FAILED USER NOTIFY ERROR"
        )
    await state.clear()
# ============================================================
# CHECK AUTO PAYMENT
# ============================================================
# INTERNAL: routed centrally by handlers.pay
async def vip_wait(
    call: CallbackQuery,
):
    await safe_callback_answer(call)
    if not call.message:
        return
    invoice = call.data.split(":", 1)[1].strip()
    if not invoice:
        return await call.message.answer("❌ Invoice tidak valid.")
    pool = await get_pool()
    tx = await pool.fetchrow(
        "SELECT * FROM payments WHERE invoice_id=$1 AND user_id=$2 AND type='vip' LIMIT 1",
        invoice, call.from_user.id,
    )
    if not tx:
        return await call.message.answer("❌ Invoice tidak ditemukan.")

    status = str(tx.get("status") or "").lower()
    if status != "paid":
        provider = str(tx.get("provider") or "bayargg").lower()
        try:
            result = await (Cashi.check_payment(invoice) if provider == "cashi" else BayarGG.check_payment(invoice))
            remote = str((result or {}).get("status") or "").lower()
            if remote in {"paid","success","settled","completed","completed_payment","success_payment","settlement"}:
                await pool.execute("UPDATE payments SET status='paid',paid_at=NOW() WHERE id=$1 AND status!='paid'",tx["id"])
                status="paid"
        except Exception:
            logger.exception("VIP AUTO CHECK ERROR | provider=%s invoice=%s",provider,invoice)

    if status != "paid":
        lang=await get_user_language(call.from_user.id)
        return await call.answer({
            "id":"⏳ Pembayaran belum diterima.",
            "en":"⏳ Payment has not been received yet.",
            "zh":"⏳ 尚未收到付款。",
        }[lang],show_alert=True)

    paket=VIP_PACKAGES.get(str(tx["code"]),{})
    days=int(paket.get("days",1))
    ptype=str(paket.get("type") or "vip").lower()
    is_vvip=ptype in {"vvip","premium_vvip"} or "vvip" in str(paket.get("name") or "").lower()
    await pool.execute(
        """UPDATE users SET
            vip=TRUE,is_vip=TRUE,
            vvip=CASE WHEN $3 THEN TRUE ELSE vvip END,
            is_vvip=CASE WHEN $3 THEN TRUE ELSE is_vvip END,
            plan=CASE WHEN $3 THEN 'vvip' ELSE 'vip' END,
            vip_until=CASE WHEN vip_until IS NULL OR vip_until<NOW()
                THEN NOW()+($2||' days')::interval
                ELSE vip_until+($2||' days')::interval END,
            updated_at=NOW()
           WHERE user_id=$1""",
        call.from_user.id,days,is_vvip
    )
    lang=await get_user_language(call.from_user.id)
    msg={
        "id":f"🎉 <b>Pembayaran berhasil!</b>\n\n💎 Status akun: <b>{'VVIP' if is_vvip else 'VIP'}</b>\n📅 Durasi: <b>{days} hari</b>",
        "en":f"🎉 <b>Payment successful!</b>\n\n💎 Account status: <b>{'VVIP' if is_vvip else 'VIP'}</b>\n📅 Duration: <b>{days} days</b>",
        "zh":f"🎉 <b>支付成功！</b>\n\n💎 账户状态：<b>{'VVIP' if is_vvip else 'VIP'}</b>\n📅 有效期：<b>{days} 天</b>",
    }[lang]
    try:
        await pool.execute("INSERT INTO user_notifications(user_id,type,title,message) VALUES($1,'payment','VIP Payment',$2)", call.from_user.id, msg)
    except Exception:
        logger.exception("VIP AUTO USER NOTIFICATION INSERT ERROR")
    await send_payment_success_channel(
        call.bot, "vvip" if is_vvip else "vip", call.from_user.id, tx.get("amount"),
        tx.get("provider") or "-", paket.get("name") or ("VVIP" if is_vvip else "VIP"), invoice
    )
    return await call.message.answer(msg,parse_mode="HTML")
