import logging
import os
import re
from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from database import get_pool
from config import ADMIN_IDS, MANUAL_QR_FILE_ID, CASHI_API_KEY, BAYARGG_API_KEY
from utils.user_lang import get_user_language
from utils.payment_methods import payment_methods_enabled, payment_selector_markup, qr_selector_markup
from utils.cashi import Cashi
from utils.bayargg import BayarGG
from utils.payment_channel import send_payment_success_channel
# =========================================================
# CONFIG
# =========================================================
router = Router()
ADMIN_ID = ADMIN_IDS[0] if ADMIN_IDS else 0
# Minimal referral untuk jalur pengajuan gratis
CREATOR_REQUIRED_REFERRAL = 100
# Harga upgrade Creator
CREATOR_UPGRADE_PRICE = int(
    os.getenv("CREATOR_UPGRADE_PRICE", "150000")
)
# Group resmi Kreator
CREATOR_GROUP_URL = "https://t.me/+qo0L89j12hA1NTNl"
# =========================================================
# HELPERS
# =========================================================
def rupiah(value: int) -> str:
    try:
        return f"Rp {int(value):,}".replace(",", ".")
    except (TypeError, ValueError):
        return "Rp 0"
def normalize_username(username: str) -> str:
    """
    Normalisasi username Telegram.
    Contoh:
    username       -> @username
    @username      -> @username
    @@username     -> @username
    """
    username = (username or "").strip()
    while username.startswith("@"):
        username = username[1:]
    return f"@{username}" if username else ""
def valid_telegram_username(username: str) -> bool:
    """
    Telegram username:
    5-32 karakter secara umum,
    huruf/angka/underscore.
    """
    username = normalize_username(username)
    if not username:
        return False
    raw = username[1:]
    if not re.fullmatch(r"[A-Za-z0-9_]{5,32}", raw):
        return False
    return True
def creator_group_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="👥 MASUK GROUP KREATOR",
                    url=CREATOR_GROUP_URL,
                )
            ],
            [
                InlineKeyboardButton(
                    text="🎨 BUKA PROGRAM KREATOR",
                    callback_data="creator",
                )
            ],
        ]
    )
def creator_home_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🎨 Program Kreator",
                    callback_data="creator",
                )
            ],
            [
                InlineKeyboardButton(
                    text="👤 Account",
                    callback_data="account",
                )
            ],
        ]
    )
# =========================================================
# FSM
# =========================================================
class CreatorApplicationState(StatesGroup):
    waiting_telegram = State()
    waiting_contact = State()
    confirming = State()
# =========================================================
# CREATOR INFO
# =========================================================
@router.callback_query(F.data == "creator")
async def creator_info(call: CallbackQuery):
    pool = await get_pool()
    user = await pool.fetchrow(
        """
        SELECT
            referral_count,
            is_creator,
            creator_status
        FROM users
        WHERE user_id = $1
        """,
        call.from_user.id,
    )
    if not user:
        return await call.answer(
            "❌ Data akun tidak ditemukan.",
            show_alert=True,
        )
    count = int(user["referral_count"] or 0)
    approved = (
        bool(user["is_creator"])
        and user["creator_status"] == "approved"
    )
    # =====================================================
    # SUDAH CREATOR
    # =====================================================
    if approved:
        text = (
            "🎨 <b>PROGRAM KREATOR</b>\n"
            "━━━━━━━━━━━━━━━━━━\n\n"
            "✅ Status: <b>Kreator Terverifikasi</b>\n\n"
            "🚀 <b>MANFAAT KREATOR</b>\n"
            "• 📂 Bisa membuka code PAID tanpa membayar\n"
            "• 💰 Bisa upload code dan menentukan harga sendiri\n"
            "• 🛒 Mendapat penghasilan dari setiap penjualan\n"
            "• 💳 Pendapatan masuk ke saldo dan dapat di-WD sesuai ketentuan\n"
            "• 📊 Statistik penjualan, views, suka, tidak suka, favorit, dan rating tercatat di database\n"
            "• 📤 Bisa membagikan code untuk mendapatkan pembeli\n\n"
            "👨‍🏫 <b>BIMBINGAN KREATOR</b>\n"
            "Masuk ke Group Kreator untuk mendapatkan "
            "bimbingan dan informasi langsung dari admin."
        )
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="📤 Upload Code",
                        callback_data="upfile",
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="🛍 Marketplace",
                        callback_data="marketplace",
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="👥 Group Kreator",
                        url=CREATOR_GROUP_URL,
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="⬅️ Home",
                        callback_data="home",
                    )
                ],
            ]
        )
    # =====================================================
    # BELUM CREATOR
    # =====================================================
    else:
        remaining = max(
            0,
            CREATOR_REQUIRED_REFERRAL - count,
        )
        status = user["creator_status"] or "none"
        if status == "pending":
            status_text = (
                "⏳ <b>Pengajuan Kreator sedang menunggu "
                "verifikasi admin.</b>\n\n"
                "Silakan tunggu sampai admin menyelesaikan "
                "proses verifikasi."
            )
        elif status == "rejected":
            status_text = (
                "⚠️ Pengajuan sebelumnya <b>ditolak</b>.\n"
                "Kamu masih dapat mengajukan kembali "
                "jika memenuhi persyaratan."
            )
        else:
            status_text = (
                f"👥 Referral: "
                f"<b>{count}/{CREATOR_REQUIRED_REFERRAL}</b>\n"
                f"📌 Kekurangan: <b>{remaining}</b> referral"
            )
        text = (
            "🎨 <b>PROGRAM KREATOR</b>\n"
            "━━━━━━━━━━━━━━━━━━\n\n"
            "Jadilah Kreator dan dapatkan penghasilan "
            "dari code yang kamu bagikan.\n\n"
            "✨ <b>MANFAAT KREATOR</b>\n"
            "• 📂 Bisa membuka code PAID tanpa bayar setelah terverifikasi\n"
            "• 💰 Bisa upload code PAID dan menentukan harga sendiri\n"
            "• 🛒 Mendapat penghasilan ketika code dibeli\n"
            "• 💳 Saldo dapat di-WD sesuai ketentuan\n"
            "• 📈 Statistik penjualan dan interaksi tersimpan real di database\n"
            "• 📤 Bisa share code untuk mencari pembeli\n\n"
            f"{status_text}\n\n"
            f"💎 <b>Upgrade Creator:</b> "
            f"<b>{rupiah(CREATOR_UPGRADE_PRICE)}</b>"
        )
        rows = []
        # Upgrade selalu tersedia selama belum approved
        rows.append(
            [
                InlineKeyboardButton(
                    text="💎 Upgrade Creator",
                    callback_data="paycreator",
                )
            ]
        )
        # Pengajuan referral hanya jika referral cukup
        if count >= CREATOR_REQUIRED_REFERRAL and status != "pending":
            rows.append(
                [
                    InlineKeyboardButton(
                        text="🎨 Ajukan Kreator",
                        callback_data="creator_apply",
                    )
                ]
            )
        rows.append(
            [
                InlineKeyboardButton(
                    text="⬅️ Home",
                    callback_data="home",
                )
            ]
        )
        kb = InlineKeyboardMarkup(
            inline_keyboard=rows
        )
    try:
        await call.message.edit_text(
            text,
            parse_mode="HTML",
            reply_markup=kb,
        )
    except Exception:
        await call.message.answer(
            text,
            parse_mode="HTML",
            reply_markup=kb,
        )
    await call.answer()
# =========================================================
# CREATOR UPGRADE
# =========================================================
# INTERNAL: routed centrally by handlers.pay
async def creator_upgrade(call: CallbackQuery):
    await call.answer()
    pool = await get_pool()
    user_id = call.from_user.id
    user = await pool.fetchrow(
        """
        SELECT
            user_id,
            username,
            fullname,
            is_creator,
            creator_status
        FROM users
        WHERE user_id = $1
        """,
        user_id,
    )
    if not user:
        return await call.message.answer(
            "❌ Data akun tidak ditemukan."
        )
    if (
        bool(user["is_creator"])
        and user["creator_status"] == "approved"
    ):
        return await call.answer(
            "✅ Kamu sudah menjadi Kreator.",
            show_alert=True,
        )
    # =====================================================
    # CEK PEMBAYARAN PENDING
    # =====================================================
    pending = await pool.fetchrow(
        """
        SELECT
            id,
            amount,
            created_at
        FROM creator_upgrade_payments
        WHERE user_id = $1
          AND status = 'pending'
        ORDER BY id DESC
        LIMIT 1
        """,
        user_id,
    )
    if pending:
        return await call.answer(
            "⏳ Masih ada pembayaran Upgrade Creator "
            "yang menunggu verifikasi.\n\n"
            f"ID: CREATOR-{pending['id']}",
            show_alert=True,
        )
    lang = await get_user_language(user_id)
    methods = await payment_methods_enabled()
    labels = {
        "id": "💳 <b>Pilih Metode Pembayaran Creator</b>\n\nPilih metode pembayaran untuk Upgrade Creator.",
        "en": "💳 <b>Choose Creator Payment Method</b>\n\nChoose a payment method for Creator Upgrade.",
        "zh": "💳 <b>选择创作者支付方式</b>\n\n请选择创作者升级的支付方式。",
    }
    await call.message.edit_text(
        labels.get(lang, labels["id"]) + f"\n\n💰 <b>{rupiah(CREATOR_UPGRADE_PRICE)}</b>",
        parse_mode="HTML",
        reply_markup=payment_selector_markup("paycreatorpay", lang, methods),
    )
    return

async def _creator_create_tx(pool, user_id: int, provider: str, payment_id: str | None = None, provider_invoice: str | None = None):
    tx = await pool.fetchrow(
        """INSERT INTO creator_upgrade_payments(user_id,amount,status,payment_id,provider,provider_invoice)
           VALUES($1,$2,'pending',$3,$4,$5) RETURNING *""",
        user_id, CREATOR_UPGRADE_PRICE, payment_id, provider, provider_invoice
    )
    return tx

async def _creator_manual(call: CallbackQuery):
    pool = await get_pool()
    tx = await _creator_create_tx(pool, call.from_user.id, "manual")
    tx_id = tx["id"]
    lang = await get_user_language(call.from_user.id)
    texts = {
        "id": f"💎 <b>UPGRADE CREATOR</b>\n\n💰 Nominal: <b>{rupiah(CREATOR_UPGRADE_PRICE)}</b>\n🧾 ID: <code>CREATOR-{tx_id}</code>\n\nBayar sesuai nominal lalu tekan <b>✅ Saya Sudah Bayar</b>.",
        "en": f"💎 <b>CREATOR UPGRADE</b>\n\n💰 Amount: <b>{rupiah(CREATOR_UPGRADE_PRICE)}</b>\n🧾 ID: <code>CREATOR-{tx_id}</code>\n\nPay the exact amount, then press <b>✅ I Have Paid</b>.",
        "zh": f"💎 <b>创作者升级</b>\n\n💰 金额：<b>{rupiah(CREATOR_UPGRADE_PRICE)}</b>\n🧾 ID：<code>CREATOR-{tx_id}</code>\n\n请支付准确金额，然后点击 <b>✅ 我已付款</b>。",
    }
    buttons={
        "id":("✅ Saya Sudah Bayar","❌ Batal"),
        "en":("✅ I Have Paid","❌ Cancel"),
        "zh":("✅ 我已付款","❌ 取消")
    }[lang]
    kb=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=buttons[0],callback_data=f"creator_upgrade_check:{tx_id}")],[InlineKeyboardButton(text=buttons[1],callback_data=f"creator_upgrade_cancel:{tx_id}")]])
    qr_chat=int(await pool.fetchval("SELECT value FROM settings WHERE key=$1","manual_qr_chat_id") or 0)
    qr_msg=int(await pool.fetchval("SELECT value FROM settings WHERE key=$1","manual_qr_message_id") or 0)
    if not qr_chat or not qr_msg:
        return await call.message.answer("❌ QR Manual belum dikonfigurasi. Gunakan /qrid.")
    try:
        await call.message.delete()
    except Exception: pass
    await call.bot.copy_message(chat_id=call.message.chat.id,from_chat_id=qr_chat,message_id=qr_msg,caption=texts.get(lang,texts["id"]),parse_mode="HTML",reply_markup=kb)

async def _creator_auto(call: CallbackQuery, provider: str):
    pool=await get_pool(); user_id=call.from_user.id
    try:
        if provider=="cashi":
            payment=await Cashi.create_payment(CREATOR_UPGRADE_PRICE,"Creator Upgrade",call.from_user.full_name)
        else:
            payment=await BayarGG.create_payment(CREATOR_UPGRADE_PRICE,"Creator Upgrade",customer_name=call.from_user.full_name)
    except Exception:
        logging.exception("CREATOR %s CREATE ERROR",provider); payment=None
    if not payment: return await call.message.answer("❌ Pembayaran otomatis sedang tidak tersedia.")
    invoice=str(payment.get("invoice_id") or payment.get("order_id") or "").strip()
    if not invoice: return await call.message.answer("❌ Invoice tidak valid.")
    tx=await _creator_create_tx(pool,user_id,provider,invoice,invoice)
    await pool.execute("""INSERT INTO payments(order_id,user_id,code,reference,amount,status,provider,invoice_id,payment_url,expires_at,type) VALUES($1,$2,$3,$4,$5,'pending',$6,$7,$8,$9,'creator') ON CONFLICT(invoice_id) DO NOTHING""",invoice,user_id,"creator",invoice,CREATOR_UPGRADE_PRICE,provider,invoice,payment.get("payment_url"),payment.get("expires_at"))
    lang=await get_user_language(user_id); qr=payment.get("qr_string") or payment.get("qr_image")
    kb=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text={"id":"🔄 Cek Pembayaran","en":"🔄 Check Payment","zh":"🔄 检查支付"}[lang],callback_data=f"creatorpaycheck:{provider}:{invoice}:{tx['id']}")],[InlineKeyboardButton(text={"id":"❌ Batal","en":"❌ Cancel","zh":"❌ 取消"}[lang],callback_data=f"creatorpay:cancel:{tx['id']}")]])
    text={"id":"💳 <b>PEMBAYARAN CREATOR</b>","en":"💳 <b>CREATOR PAYMENT</b>","zh":"💳 <b>创作者付款</b>"}[lang]+f"\n\n💰 <b>{rupiah(CREATOR_UPGRADE_PRICE)}</b>\n🧾 <code>{invoice}</code>"
    if qr:
        try:
            import base64, qrcode
            from io import BytesIO
            if isinstance(qr,str) and qr.startswith("data:image/"): raw=base64.b64decode(qr.split(',',1)[1])
            else:
                buf=BytesIO(); qrcode.make(qr).save(buf,format="PNG"); raw=buf.getvalue()
            await call.message.answer_photo(__import__('aiogram').types.BufferedInputFile(raw,filename="creator-qr.png"),caption=text,parse_mode="HTML",reply_markup=kb); return
        except Exception: logging.exception("CREATOR QR ERROR")
    await call.message.answer(text,parse_mode="HTML",reply_markup=kb)

# INTERNAL: routed centrally by handlers.pay
async def creator_payment_method(call: CallbackQuery):
    await call.answer()
    parts=call.data.split(":")
    if len(parts)==3 and parts[1]=="cancel":
        return await call.message.edit_text("❌ Pembayaran dibatalkan.")
    if len(parts)!=2 or parts[0] not in {"creatorpay", "paycreatorpay"}: return
    method=parts[1]; lang=await get_user_language(call.from_user.id); methods=await payment_methods_enabled()
    if method=="qr": return await call.message.edit_reply_markup(reply_markup=qr_selector_markup("paycreatorpay",lang,methods))
    if method=="back": return await call.message.edit_reply_markup(reply_markup=payment_selector_markup("paycreatorpay",lang,methods))
    if method=="cashi": return await _creator_auto(call,"cashi")
    if method=="bayargg": return await _creator_auto(call,"bayargg")
    if method=="manual": return await _creator_manual(call)

# INTERNAL: routed centrally by handlers.pay
async def creator_payment_check(call: CallbackQuery):
    await call.answer()
    parts=call.data.split(":")
    if len(parts)!=4: return
    provider,invoice,txid=parts[1],parts[2],int(parts[3]); pool=await get_pool()
    tx=await pool.fetchrow("SELECT * FROM creator_upgrade_payments WHERE id=$1 AND user_id=$2 AND status='pending'",txid,call.from_user.id)
    if not tx: return await call.message.answer("❌ Transaksi tidak ditemukan.")
    if provider=="cashi": result=await Cashi.check_payment(invoice); status=str((result or {}).get("status") or "").lower(); paid=status in {"settled","paid","success","completed"}
    else: result=await BayarGG.check_payment(invoice); status=str((result or {}).get("status") or "").lower(); paid=status in {"paid","success","settled","completed"}
    if not paid: return await call.answer("⏳ Pembayaran belum diterima.",show_alert=True)
    await pool.execute("UPDATE creator_upgrade_payments SET status='approved',provider=$1,provider_invoice=$2,paid_at=NOW(),reviewed_at=NOW() WHERE id=$3 AND status='pending'",provider,invoice,txid)
    await pool.execute("UPDATE users SET is_creator=TRUE,creator_status='approved',creator_verified_at=NOW(),plan='creator',updated_at=NOW() WHERE user_id=$1",call.from_user.id)
    await pool.execute("UPDATE payments SET status='paid',paid_at=NOW() WHERE invoice_id=$1",invoice)
    lang=await get_user_language(call.from_user.id); msg={"id":"🎉 <b>Creator berhasil diaktifkan!</b>","en":"🎉 <b>Creator has been activated!</b>","zh":"🎉 <b>创作者已成功激活！</b>"}[lang]
    try:
        await pool.execute("INSERT INTO user_notifications(user_id,type,title,message) VALUES($1,'payment','Creator Payment',$2)", call.from_user.id, msg)
    except Exception:
        logging.exception("CREATOR AUTO USER NOTIFICATION INSERT ERROR")
    await send_payment_success_channel(
        call.bot, "creator", call.from_user.id, CREATOR_UPGRADE_PRICE, provider,
        "Creator Upgrade", invoice
    )
    await call.message.answer(msg,parse_mode="HTML")

    # legacy code below is intentionally unreachable after the method selector.
    caption = (
        "💎 <b>UPGRADE CREATOR</b>\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        f"💰 Nominal: "
        f"<b>{rupiah(CREATOR_UPGRADE_PRICE)}</b>\n"
        f"🧾 ID Pembayaran: "
        f"<code>CREATOR-{tx_id}</code>\n\n"
        "📌 <b>CARA PEMBAYARAN</b>\n"
        "1. Scan QR manual di atas.\n"
        "2. Bayar <b>tepat sesuai nominal</b>.\n"
        "3. Setelah membayar, tekan "
        "<b>✅ Saya Sudah Bayar</b>.\n"
        "4. Admin akan melakukan pengecekan manual.\n\n"
        "🎨 Setelah pembayaran disetujui admin, "
        "akun kamu langsung menjadi "
        "<b>Kreator Terverifikasi</b>.\n\n"
        "⚠️ Jangan pernah mengirim OTP, PIN, "
        "password, atau data rahasia."
    )
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Saya Sudah Bayar",
                    callback_data=(
                        f"creator_upgrade_check:{tx_id}"
                    ),
                )
            ],
            [
                InlineKeyboardButton(
                    text="❌ Batal",
                    callback_data=(
                        f"creator_upgrade_cancel:{tx_id}"
                    ),
                )
            ],
            [
                InlineKeyboardButton(
                    text="⬅️ Kembali",
                    callback_data="creator",
                )
            ],
        ]
    )
    try:
        await call.message.delete()
    except Exception:
        pass
    try:
        qr_chat = int(await pool.fetchval("SELECT value FROM settings WHERE key=$1", "manual_qr_chat_id") or 0)
        qr_msg = int(await pool.fetchval("SELECT value FROM settings WHERE key=$1", "manual_qr_message_id") or 0)
        if not qr_chat or not qr_msg:
            raise RuntimeError("Manual QR belum dikonfigurasi. Gunakan /qrid.")
        await call.bot.copy_message(
            chat_id=call.message.chat.id,
            from_chat_id=qr_chat,
            message_id=qr_msg,
            caption=caption,
            parse_mode="HTML",
            reply_markup=kb,
        )
    except Exception:
        logging.exception(
            "CREATOR MANUAL QR SEND ERROR"
        )
        await call.message.answer(
            caption
            + "\n\n⚠️ QR tidak dapat ditampilkan. "
            "Silakan hubungi admin.",
            parse_mode="HTML",
            reply_markup=kb,
        )
# =========================================================
# USER CONFIRM PAYMENT
# =========================================================
@router.callback_query(
    F.data.startswith("creator_upgrade_check:")
)
async def creator_upgrade_check(
    call: CallbackQuery
):
    try:
        tx_id = int(
            call.data.split(":", 1)[1]
        )
    except (ValueError, IndexError):
        return await call.answer(
            "❌ ID pembayaran tidak valid.",
            show_alert=True,
        )
    await call.answer()
    pool = await get_pool()
    tx = await pool.fetchrow(
        """
        SELECT *
        FROM creator_upgrade_payments
        WHERE id = $1
          AND user_id = $2
          AND status = 'pending'
        """,
        tx_id,
        call.from_user.id,
    )
    if not tx:
        return await call.answer(
            "❌ Pembayaran tidak ditemukan "
            "atau sudah diproses.",
            show_alert=True,
        )
    user = await pool.fetchrow(
        """
        SELECT
            username,
            fullname
        FROM users
        WHERE user_id = $1
        """,
        tx["user_id"],
    )
    username = (
        normalize_username(user["username"])
        if user and user["username"]
        else "-"
    )
    fullname = (
        user["fullname"]
        if user and user["fullname"]
        else "-"
    )
    admin_text = (
        "💎 <b>UPGRADE CREATOR — PEMBAYARAN MASUK</b>\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        f"👤 Nama: <b>{fullname}</b>\n"
        f"🆔 User ID: <code>{tx['user_id']}</code>\n"
        f"🔗 Username: <b>{username}</b>\n\n"
        f"💰 Nominal: "
        f"<b>{rupiah(tx['amount'])}</b>\n"
        f"🧾 ID: "
        f"<code>CREATOR-{tx['id']}</code>\n"
        f"📅 Dibuat: "
        f"<code>{tx['created_at']}</code>\n\n"
        "🔎 Silakan cek mutasi/pembayaran "
        "sebelum melakukan approval."
    )
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ APPROVE & UPGRADE",
                    callback_data=(
                        f"creator_upgrade_approve:{tx_id}"
                    ),
                )
            ],
            [
                InlineKeyboardButton(
                    text="❌ FAILED / TOLAK",
                    callback_data=(
                        f"creator_upgrade_failed:{tx_id}"
                    ),
                )
            ],
        ]
    )
    sent = 0
    for admin_id in ADMIN_IDS:
        try:
            await call.bot.send_message(
                chat_id=admin_id,
                text=admin_text,
                parse_mode="HTML",
                reply_markup=kb,
            )
            sent += 1
        except Exception:
            logging.exception(
                "CREATOR UPGRADE ADMIN NOTIFY ERROR "
                "admin=%s",
                admin_id,
            )
    if sent:
        try:
            await call.message.edit_caption(
                caption=(
                    "⏳ <b>MENUNGGU VERIFIKASI ADMIN</b>\n"
                    "━━━━━━━━━━━━━━━━━━\n\n"
                    f"🧾 ID: "
                    f"<code>CREATOR-{tx_id}</code>\n"
                    f"💰 Nominal: "
                    f"<b>{rupiah(tx['amount'])}</b>\n\n"
                    "✅ Pembayaran sudah dilaporkan "
                    "kepada admin.\n\n"
                    "Mohon tunggu sampai admin "
                    "menyelesaikan verifikasi."
                ),
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(
                    inline_keyboard=[
                        [
                            InlineKeyboardButton(
                                text="⬅️ Kreator",
                                callback_data="creator",
                            )
                        ]
                    ]
                ),
            )
        except Exception:
            logging.exception(
                "CREATOR PAYMENT MESSAGE UPDATE ERROR"
            )
        return
    await call.message.answer(
        "❌ Admin tidak dapat menerima notifikasi.\n\n"
        "Silakan coba lagi."
    )
# =========================================================
# CANCEL PAYMENT
# =========================================================
@router.callback_query(
    F.data.startswith("creator_upgrade_cancel:")
)
async def creator_upgrade_cancel(
    call: CallbackQuery
):
    try:
        tx_id = int(
            call.data.split(":", 1)[1]
        )
    except (ValueError, IndexError):
        return await call.answer(
            "❌ ID pembayaran tidak valid.",
            show_alert=True,
        )
    await call.answer()
    pool = await get_pool()
    result = await pool.execute(
        """
        UPDATE creator_upgrade_payments
        SET
            status = 'cancelled',
            reviewed_at = NOW()
        WHERE id = $1
          AND user_id = $2
          AND status = 'pending'
        """,
        tx_id,
        call.from_user.id,
    )
    await call.message.edit_text(
        "❌ <b>PEMBAYARAN DIBATALKAN</b>\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "Pembayaran Upgrade Creator telah dibatalkan.\n\n"
        "Kamu dapat membuat pembayaran baru "
        "kapan saja.",
        parse_mode="HTML",
        reply_markup=creator_home_keyboard(),
    )
# =========================================================
# ADMIN APPROVE PAYMENT
# =========================================================
@router.callback_query(
    F.data.startswith("creator_upgrade_approve:")
)
async def creator_upgrade_approve(
    call: CallbackQuery
):
    if call.from_user.id not in ADMIN_IDS:
        return await call.answer(
            "❌ Kamu tidak memiliki akses.",
            show_alert=True,
        )
    try:
        tx_id = int(
            call.data.split(":", 1)[1]
        )
    except (ValueError, IndexError):
        return await call.answer(
            "❌ ID pembayaran tidak valid.",
            show_alert=True,
        )
    await call.answer()
    pool = await get_pool()
    # Atomic:
    # hanya transaksi pending yang dapat diapprove.
    tx = await pool.fetchrow(
        """
        UPDATE creator_upgrade_payments
        SET
            status = 'approved',
            admin_id = $1,
            reviewed_at = NOW(),
            paid_at = NOW()
        WHERE id = $2
          AND status = 'pending'
        RETURNING *
        """,
        call.from_user.id,
        tx_id,
    )
    if not tx:
        return await call.answer(
            "❌ Pembayaran sudah diproses "
            "atau tidak ditemukan.",
            show_alert=True,
        )
    # =====================================================
    # AKTIFKAN CREATOR
    # =====================================================
    await pool.execute(
        """
        UPDATE users
        SET
            is_creator = TRUE,
            creator_status = 'approved',
            creator_verified_at = NOW(),
            plan = 'creator',
            updated_at = NOW()
        WHERE user_id = $1
        """,
        tx["user_id"],
    )
    # =====================================================
    # NOTIFIKASI USER
    # =====================================================
    try:
        user_lang = await get_user_language(tx["user_id"])
        notify = {
            "id": (
                "🎉 <b>SELAMAT!</b>\n━━━━━━━━━━━━━━━━━━\n\n"
                "✅ Pembayaran Upgrade Creator kamu telah <b>DISETUJUI</b>.\n\n"
                f"💰 Pembayaran: <b>{rupiah(tx['amount'])}</b>\n"
                f"🧾 ID: <code>CREATOR-{tx['id']}</code>\n\n"
                "🎨 Akun kamu sekarang resmi menjadi <b>Kreator Terverifikasi</b>."
            ),
            "en": (
                "🎉 <b>CONGRATULATIONS!</b>\n━━━━━━━━━━━━━━━━━━\n\n"
                "✅ Your Creator upgrade payment has been <b>APPROVED</b>.\n\n"
                f"💰 Payment: <b>{rupiah(tx['amount'])}</b>\n"
                f"🧾 ID: <code>CREATOR-{tx['id']}</code>\n\n"
                "🎨 Your account is now a <b>Verified Creator</b>."
            ),
            "zh": (
                "🎉 <b>恭喜！</b>\n━━━━━━━━━━━━━━━━━━\n\n"
                "✅ 你的创作者升级付款已被<b>批准</b>。\n\n"
                f"💰 付款：<b>{rupiah(tx['amount'])}</b>\n"
                f"🧾 ID：<code>CREATOR-{tx['id']}</code>\n\n"
                "🎨 你的账户现在已成为<b>认证创作者</b>。"
            ),
        }[user_lang]
        await call.bot.send_message(
            chat_id=tx["user_id"],
            text=notify,
            parse_mode="HTML",
            reply_markup=creator_group_keyboard(),
        )
    except Exception:
        logging.exception(
            "CREATOR UPGRADE USER NOTIFY ERROR"
        )
    await send_payment_success_channel(
        call.bot, "creator", tx["user_id"], tx.get("amount"),
        tx.get("provider") or "manual", "Creator Upgrade", f"CREATOR-{tx['id']}"
    )
    # =====================================================
    # UPDATE PESAN ADMIN
    # =====================================================
    try:
        await call.message.edit_text(
            "✅ <b>UPGRADE CREATOR DISETUJUI</b>\n"
            "━━━━━━━━━━━━━━━━━━\n\n"
            f"👤 User: "
            f"<code>{tx['user_id']}</code>\n"
            f"💰 Nominal: "
            f"<b>{rupiah(tx['amount'])}</b>\n"
            f"🧾 ID: "
            f"<code>CREATOR-{tx['id']}</code>\n"
            f"👮 Admin: "
            f"<code>{call.from_user.id}</code>\n\n"
            "🎨 Status user: "
            "<b>Kreator Terverifikasi</b>"
        )
    except Exception:
        pass
# =========================================================
# ADMIN FAILED PAYMENT
# =========================================================
@router.callback_query(
    F.data.startswith("creator_upgrade_failed:")
)
async def creator_upgrade_failed(
    call: CallbackQuery
):
    if call.from_user.id not in ADMIN_IDS:
        return await call.answer(
            "❌ Kamu tidak memiliki akses.",
            show_alert=True,
        )
    try:
        tx_id = int(
            call.data.split(":", 1)[1]
        )
    except (ValueError, IndexError):
        return await call.answer(
            "❌ ID pembayaran tidak valid.",
            show_alert=True,
        )
    await call.answer()
    pool = await get_pool()
    tx = await pool.fetchrow(
        """
        UPDATE creator_upgrade_payments
        SET
            status = 'failed',
            admin_id = $1,
            reviewed_at = NOW()
        WHERE id = $2
          AND status = 'pending'
        RETURNING *
        """,
        call.from_user.id,
        tx_id,
    )
    if not tx:
        return await call.answer(
            "❌ Pembayaran sudah diproses "
            "atau tidak ditemukan.",
            show_alert=True,
        )
    try:
        await call.bot.send_message(
            chat_id=tx["user_id"],
            text=(
                "⚠️ <b>PEMBAYARAN UPGRADE CREATOR</b>\n"
                "━━━━━━━━━━━━━━━━━━\n\n"
                f"🧾 ID: "
                f"<code>CREATOR-{tx['id']}</code>\n\n"
                "❌ Pembayaran belum dapat disetujui.\n\n"
                "Admin tidak menemukan pembayaran "
                "yang sesuai atau pembayaran belum masuk.\n\n"
                "Jika kamu yakin sudah melakukan pembayaran, "
                "silakan hubungi admin."
            ),
            parse_mode="HTML",
        )
    except Exception:
        logging.exception(
            "CREATOR UPGRADE FAILED USER NOTIFY ERROR"
        )
    try:
        await call.message.edit_text(
            "❌ <b>UPGRADE CREATOR DITOLAK</b>\n"
            "━━━━━━━━━━━━━━━━━━\n\n"
            f"👤 User: "
            f"<code>{tx['user_id']}</code>\n"
            f"💰 Nominal: "
            f"<b>{rupiah(tx['amount'])}</b>\n"
            f"🧾 ID: "
            f"<code>CREATOR-{tx['id']}</code>\n"
            f"👮 Admin: "
            f"<code>{call.from_user.id}</code>"
        )
    except Exception:
        pass
# =========================================================
# START CREATOR APPLICATION
# =========================================================
@router.callback_query(F.data == "creator_apply")
async def creator_apply(
    call: CallbackQuery,
    state: FSMContext,
):
    pool = await get_pool()
    user = await pool.fetchrow(
        """
        SELECT
            user_id,
            username,
            fullname,
            referral_count,
            is_creator,
            creator_status
        FROM users
        WHERE user_id = $1
        """,
        call.from_user.id,
    )
    if not user:
        return await call.answer(
            "❌ Data akun tidak ditemukan.",
            show_alert=True,
        )
    referral_count = int(
        user["referral_count"] or 0
    )
    is_creator = bool(
        user["is_creator"]
    )
    status = (
        user["creator_status"]
        or "none"
    )
    if is_creator and status == "approved":
        return await call.answer(
            "✅ Kamu sudah menjadi Kreator.",
            show_alert=True,
        )
    if status == "pending":
        return await call.answer(
            "⏳ Pengajuan kamu masih menunggu "
            "verifikasi admin.",
            show_alert=True,
        )
    if referral_count < CREATOR_REQUIRED_REFERRAL:
        remaining = (
            CREATOR_REQUIRED_REFERRAL
            - referral_count
        )
        return await call.answer(
            f"❌ Referral belum cukup.\n\n"
            f"Referral: "
            f"{referral_count}/{CREATOR_REQUIRED_REFERRAL}\n"
            f"Kekurangan: {remaining}",
            show_alert=True,
        )
    await state.clear()
    await state.set_state(
        CreatorApplicationState.waiting_telegram
    )
    text = (
        "🎨 <b>VERIFIKASI KREATOR</b>\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "Kamu sudah memenuhi syarat minimal "
        f"<b>{CREATOR_REQUIRED_REFERRAL} referral</b>. ✅\n\n"
        "Silakan isi data verifikasi berikut.\n\n"
        "📱 <b>LANGKAH 1 — TELEGRAM</b>\n\n"
        "Kirim username Telegram yang aktif.\n\n"
        "Contoh:\n"
        "<code>@username</code>\n\n"
        "⚠️ Jangan kirim password, OTP, PIN, "
        "atau informasi rahasia lainnya."
    )
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="❌ Batal",
                    callback_data="creator_cancel",
                )
            ]
        ]
    )
    try:
        await call.message.edit_text(
            text,
            parse_mode="HTML",
            reply_markup=keyboard,
        )
    except Exception:
        await call.message.answer(
            text,
            parse_mode="HTML",
            reply_markup=keyboard,
        )
    await call.answer()
# =========================================================
# TELEGRAM USERNAME
# =========================================================
@router.message(
    CreatorApplicationState.waiting_telegram,
    F.text,
)
async def creator_telegram(
    message: Message,
    state: FSMContext,
):
    username = normalize_username(
        message.text
    )
    if not valid_telegram_username(username):
        return await message.answer(
            "❌ <b>Username Telegram tidak valid.</b>\n\n"
            "Gunakan username Telegram yang valid.\n\n"
            "Contoh:\n"
            "<code>@username</code>",
            parse_mode="HTML",
        )
    await state.update_data(
        telegram_username=username
    )
    await state.set_state(
        CreatorApplicationState.waiting_contact
    )
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="❌ Batal",
                    callback_data="creator_cancel",
                )
            ]
        ]
    )
    await message.answer(
        "📞 <b>LANGKAH 2 — KONTAK</b>\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "Kirim nomor WhatsApp/telepon yang aktif "
        "untuk keperluan verifikasi.\n\n"
        "Contoh:\n"
        "<code>628123456789</code>\n\n"
        "⚠️ Nomor hanya digunakan untuk proses "
        "verifikasi Kreator.",
        parse_mode="HTML",
        reply_markup=keyboard,
    )
# =========================================================
# CONTACT
# =========================================================
@router.message(
    CreatorApplicationState.waiting_contact,
    F.contact,
)
async def creator_contact(
    message: Message,
    state: FSMContext,
):
    contact = message.contact
    if not contact or not contact.phone_number:
        return await message.answer(
            "❌ Nomor kontak tidak ditemukan."
        )
    await save_creator_contact(
        message,
        state,
        contact.phone_number,
    )
@router.message(
    CreatorApplicationState.waiting_contact,
    F.text,
)
async def creator_contact_text(
    message: Message,
    state: FSMContext,
):
    phone = message.text.strip()
    # Bersihkan format nomor
    clean_phone = re.sub(
        r"[^\d+]",
        "",
        phone,
    )
    digits = clean_phone.replace(
        "+",
        "",
        1,
    )
    if not digits.isdigit() or len(digits) < 8:
        return await message.answer(
            "❌ Nomor tidak valid.\n\n"
            "Contoh:\n"
            "<code>628123456789</code>",
            parse_mode="HTML",
        )
    await save_creator_contact(
        message,
        state,
        clean_phone,
    )
# =========================================================
# SAVE CONTACT
# =========================================================
async def save_creator_contact(
    message: Message,
    state: FSMContext,
    phone: str,
):
    await state.update_data(
        contact=phone
    )
    data = await state.get_data()
    telegram_username = data.get(
        "telegram_username",
        "-",
    )
    await state.set_state(
        CreatorApplicationState.confirming
    )
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Kirim Verifikasi",
                    callback_data="creator_submit",
                )
            ],
            [
                InlineKeyboardButton(
                    text="✏️ Ubah",
                    callback_data="creator_restart",
                ),
                InlineKeyboardButton(
                    text="❌ Batal",
                    callback_data="creator_cancel",
                ),
            ],
        ]
    )
    await message.answer(
        "🔎 <b>KONFIRMASI DATA KREATOR</b>\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        f"📱 Telegram: "
        f"<b>{telegram_username}</b>\n"
        f"📞 Kontak: "
        f"<code>{phone}</code>\n\n"
        f"👥 Syarat referral: "
        f"<b>{CREATOR_REQUIRED_REFERRAL}+</b>\n\n"
        "Pastikan data di atas benar sebelum "
        "mengirim pengajuan.\n\n"
        "⚠️ Jangan mengirim password, OTP, PIN, "
        "atau data pembayaran.",
        parse_mode="HTML",
        reply_markup=keyboard,
    )
# =========================================================
# SUBMIT CREATOR APPLICATION
# =========================================================
@router.callback_query(
    CreatorApplicationState.confirming,
    F.data == "creator_submit",
)
async def creator_submit(
    call: CallbackQuery,
    state: FSMContext,
):
    pool = await get_pool()
    data = await state.get_data()
    telegram_username = data.get(
        "telegram_username"
    )
    contact = data.get(
        "contact"
    )
    if not telegram_username or not contact:
        return await call.answer(
            "❌ Data verifikasi belum lengkap.",
            show_alert=True,
        )
    user = await pool.fetchrow(
        """
        SELECT
            user_id,
            username,
            fullname,
            referral_count,
            is_creator,
            creator_status
        FROM users
        WHERE user_id = $1
        """,
        call.from_user.id,
    )
    if not user:
        return await call.answer(
            "❌ Data akun tidak ditemukan.",
            show_alert=True,
        )
    referral_count = int(
        user["referral_count"] or 0
    )
    if referral_count < CREATOR_REQUIRED_REFERRAL:
        await state.clear()
        return await call.answer(
            "❌ Syarat referral sudah tidak terpenuhi.",
            show_alert=True,
        )
    if (
        bool(user["is_creator"])
        and user["creator_status"] == "approved"
    ):
        await state.clear()
        return await call.answer(
            "✅ Kamu sudah menjadi Kreator.",
            show_alert=True,
        )
    if user["creator_status"] == "pending":
        await state.clear()
        return await call.answer(
            "⏳ Pengajuan kamu sudah menunggu "
            "verifikasi admin.",
            show_alert=True,
        )
    # =====================================================
    # SAVE
    # =====================================================
    await pool.execute(
        """
        UPDATE users
        SET
            creator_status = 'pending',
            is_creator = FALSE,
            phone = $2,
            creator_telegram = $3,
            updated_at = NOW()
        WHERE user_id = $1
        """,
        call.from_user.id,
        contact,
        telegram_username,
    )
    username = (
        user["username"]
        if user["username"]
        else "-"
    )
    fullname = (
        user["fullname"]
        if user["fullname"]
        else "-"
    )
    admin_text = (
        "🎨 <b>PENGAJUAN KREATOR BARU</b>\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        f"👤 Nama: <b>{fullname}</b>\n"
        f"🆔 ID: <code>{user['user_id']}</code>\n"
        f"🔗 Username: <b>{username}</b>\n\n"
        f"👥 Referral: "
        f"<b>{referral_count}</b>\n\n"
        f"📱 Telegram: "
        f"<b>{telegram_username}</b>\n"
        f"📞 Kontak: "
        f"<code>{contact}</code>\n\n"
        "⏳ Status: <b>PENDING</b>"
    )
    admin_keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ TERIMA",
                    callback_data=(
                        f"creator_approve:{user['user_id']}"
                    ),
                ),
                InlineKeyboardButton(
                    text="❌ TOLAK",
                    callback_data=(
                        f"creator_reject:{user['user_id']}"
                    ),
                ),
            ]
        ]
    )
    # =====================================================
    # SEND ADMIN
    # =====================================================
    sent = 0
    for admin_id in ADMIN_IDS:
        try:
            await call.bot.send_message(
                chat_id=admin_id,
                text=admin_text,
                parse_mode="HTML",
                reply_markup=admin_keyboard,
            )
            sent += 1
        except Exception:
            logging.exception(
                "CREATOR APPLICATION ADMIN NOTIFY ERROR "
                "admin=%s",
                admin_id,
            )
    if not sent:
        await pool.execute(
            """
            UPDATE users
            SET
                creator_status = 'none',
                is_creator = FALSE,
                updated_at = NOW()
            WHERE user_id = $1
            """,
            call.from_user.id,
        )
        return await call.answer(
            "❌ Gagal mengirim pengajuan ke admin.",
            show_alert=True,
        )
    await state.clear()
    try:
        await call.message.edit_text(
            "🎨 <b>PENGAJUAN TERKIRIM</b>\n"
            "━━━━━━━━━━━━━━━━━━\n\n"
            "✅ Data verifikasi berhasil dikirim.\n\n"
            "⏳ Status: <b>Menunggu Verifikasi</b>\n\n"
            "Admin akan memeriksa data kamu terlebih "
            "dahulu sebelum memberikan status Kreator.\n\n"
            "Mohon tunggu sampai proses verifikasi selesai.",
            parse_mode="HTML",
        )
    except Exception:
        pass
    await call.answer(
        "✅ Pengajuan berhasil dikirim."
    )
# =========================================================
# RESTART APPLICATION
# =========================================================
@router.callback_query(
    F.data == "creator_restart"
)
async def creator_restart(
    call: CallbackQuery,
    state: FSMContext,
):
    await state.clear()
    await state.set_state(
        CreatorApplicationState.waiting_telegram
    )
    await call.message.edit_text(
        "📱 <b>ULANGI VERIFIKASI</b>\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "Kirim username Telegram kamu.\n\n"
        "Contoh:\n"
        "<code>@username</code>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="❌ Batal",
                        callback_data="creator_cancel",
                    )
                ]
            ]
        ),
    )
    await call.answer()
# =========================================================
# CANCEL APPLICATION
# =========================================================
@router.callback_query(
    F.data == "creator_cancel"
)
async def creator_cancel(
    call: CallbackQuery,
    state: FSMContext,
):
    await state.clear()
    await call.message.edit_text(
        "❌ <b>VERIFIKASI KREATOR DIBATALKAN</b>\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "Proses verifikasi telah dibatalkan.\n\n"
        "Kamu dapat mengajukan kembali kapan saja "
        "jika sudah memenuhi persyaratan.",
        parse_mode="HTML",
        reply_markup=creator_home_keyboard(),
    )
    await call.answer()
# =========================================================
# ADMIN APPROVE CREATOR
# =========================================================
@router.callback_query(
    F.data.startswith("creator_approve:")
)
async def creator_approve(
    call: CallbackQuery,
):
    if call.from_user.id not in ADMIN_IDS:
        return await call.answer(
            "❌ Kamu tidak memiliki akses.",
            show_alert=True,
        )
    try:
        user_id = int(
            call.data.split(":", 1)[1]
        )
    except (ValueError, IndexError):
        return await call.answer(
            "❌ Data user tidak valid.",
            show_alert=True,
        )
    pool = await get_pool()
    # Ambil user
    user = await pool.fetchrow(
        """
        SELECT
            user_id,
            username,
            fullname,
            referral_count,
            creator_status
        FROM users
        WHERE user_id = $1
        """,
        user_id,
    )
    if not user:
        return await call.answer(
            "❌ User tidak ditemukan.",
            show_alert=True,
        )
    if user["creator_status"] == "approved":
        return await call.answer(
            "✅ User ini sudah menjadi Kreator.",
            show_alert=True,
        )
    # =====================================================
    # APPROVE
    # =====================================================
    updated = await pool.fetchrow(
        """
        UPDATE users
        SET
            is_creator = TRUE,
            creator_status = 'approved',
            creator_verified_at = NOW(),
            plan = 'creator',
            updated_at = NOW()
        WHERE user_id = $1
          AND creator_status IN ('pending', 'rejected', 'none')
        RETURNING user_id
        """,
        user_id,
    )
    if not updated:
        return await call.answer(
            "❌ User gagal diproses.",
            show_alert=True,
        )
    # =====================================================
    # UPDATE ADMIN MESSAGE
    # =====================================================
    try:
        await call.message.edit_text(
            call.message.text
            + "\n\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "✅ <b>DITERIMA</b>\n"
            f"👮 Admin: "
            f"<code>{call.from_user.id}</code>",
            parse_mode="HTML",
        )
    except Exception:
        pass
    # =====================================================
    # NOTIFY USER
    # =====================================================
    try:
        await call.bot.send_message(
            chat_id=user_id,
            text=(
                "🎉 <b>SELAMAT!</b>\n"
                "━━━━━━━━━━━━━━━━━━\n\n"
                "✅ Pengajuan Kreator kamu telah "
                "<b>DISETUJUI</b> oleh admin.\n\n"
                "🎨 Sekarang akun kamu resmi menjadi "
                "<b>Kreator Terverifikasi</b>.\n\n"
                "✨ <b>FITUR KREATOR</b>\n"
                "📤 Upload code berbayar\n"
                "💰 Mendapatkan penghasilan dari penjualan\n"
                "📊 Mengelola file Marketplace\n"
                "🛒 Menjual code kepada pengguna\n\n"
                "👨‍🏫 <b>GROUP BIMBINGAN KREATOR</b>\n\n"
                "Silakan masuk ke <b>Group Kreator</b> "
                "untuk mendapatkan bimbingan, panduan, "
                "informasi, dan bantuan langsung dari admin.\n\n"
                "👇 <b>Silakan bergabung sekarang.</b>"
            ),
            parse_mode="HTML",
            reply_markup=creator_group_keyboard(),
        )
    except Exception:
        logging.exception(
            "CREATOR APPROVAL USER NOTIFY ERROR"
        )
    await call.answer(
        "✅ User berhasil menjadi Kreator.",
        show_alert=True,
    )
# =========================================================
# ADMIN REJECT CREATOR
# =========================================================
@router.callback_query(
    F.data.startswith("creator_reject:")
)
async def creator_reject(
    call: CallbackQuery,
):
    if call.from_user.id not in ADMIN_IDS:
        return await call.answer(
            "❌ Kamu tidak memiliki akses.",
            show_alert=True,
        )
    try:
        user_id = int(
            call.data.split(":", 1)[1]
        )
    except (ValueError, IndexError):
        return await call.answer(
            "❌ Data user tidak valid.",
            show_alert=True,
        )
    pool = await get_pool()
    user = await pool.fetchrow(
        """
        SELECT
            user_id,
            username,
            fullname,
            creator_status
        FROM users
        WHERE user_id = $1
        """,
        user_id,
    )
    if not user:
        return await call.answer(
            "❌ User tidak ditemukan.",
            show_alert=True,
        )
    if user["creator_status"] == "approved":
        return await call.answer(
            "❌ User sudah menjadi Kreator. "
            "Tidak dapat ditolak.",
            show_alert=True,
        )
    # =====================================================
    # REJECT
    # =====================================================
    updated = await pool.fetchrow(
        """
        UPDATE users
        SET
            is_creator = FALSE,
            creator_status = 'rejected',
            updated_at = NOW()
        WHERE user_id = $1
          AND creator_status = 'pending'
        RETURNING user_id
        """,
        user_id,
    )
    if not updated:
        return await call.answer(
            "❌ Pengajuan sudah diproses "
            "atau bukan status pending.",
            show_alert=True,
        )
    # =====================================================
    # UPDATE ADMIN MESSAGE
    # =====================================================
    try:
        await call.message.edit_text(
            call.message.text
            + "\n\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "❌ <b>DITOLAK</b>\n"
            f"👮 Admin: "
            f"<code>{call.from_user.id}</code>",
            parse_mode="HTML",
        )
    except Exception:
        pass
    # =====================================================
    # NOTIFY USER
    # =====================================================
    try:
        await call.bot.send_message(
            chat_id=user_id,
            text=(
                "⚠️ <b>PENGAJUAN KREATOR</b>\n"
                "━━━━━━━━━━━━━━━━━━\n\n"
                "❌ Pengajuan Kreator kamu "
                "<b>belum disetujui</b> oleh admin.\n\n"
                "Kamu dapat memperbaiki data atau "
                "mengajukan kembali setelah memenuhi "
                "persyaratan yang diperlukan."
            ),
            parse_mode="HTML",
            reply_markup=creator_home_keyboard(),
        )
    except Exception:
        logging.exception(
            "CREATOR REJECT USER NOTIFY ERROR"
        )
    await call.answer(
        "❌ Pengajuan ditolak.",
        show_alert=True,
    )
