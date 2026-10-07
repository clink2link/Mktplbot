import logging
from datetime import datetime, timedelta, timezone
from io import BytesIO

import qrcode
from aiogram import Router, F
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, BufferedInputFile

from database import get_pool
from utils.dompetx import DompetX
from config_vip import VIP_PACKAGES
from config import PAYMENT_CHANNEL_ID
from bot import bot

logger = logging.getLogger(__name__)
router = Router()

SUCCESS = {"paid", "success", "successful", "settled", "completed", "settlement", "succeeded"}
FAILED = {"cancelled", "canceled", "expired", "failed", "rejected", "void"}


def rupiah(n):
    return f"Rp {int(n):,}".replace(",", ".")


def db_naive_utc(dt):
    """Convert DompetX aware datetime to naive UTC for legacy TIMESTAMP columns."""
    if not dt:
        return None
    if dt.tzinfo is not None:
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


async def add_user_notification(pool, user_id, title, message, ntype="premium"):
    await pool.execute(
        """INSERT INTO user_notifications(user_id, type, title, message)
           VALUES($1,$2,$3,$4)""",
        user_id, ntype, title, message
    )


async def post_payment_channel(kind, user_id, package, payment_id, amount, status="pending"):
    try:
        status_map = {
            "pending": "⏳ MENUNGGU PEMBAYARAN",
            "paid": "✅ PEMBAYARAN BERHASIL",
            "cancel": "❌ PEMBAYARAN DIBATALKAN",
            "expired": "⌛ PEMBAYARAN KEDALUWARSA",
        }
        await bot.send_message(
            PAYMENT_CHANNEL_ID,
            (
                f"💳 <b>{status_map.get(status, status.upper())}</b>\n\n"
                f"🏷️ Jenis: <b>{kind}</b>\n"
                f"📦 Paket: <b>{package['name']}</b>\n"
                f"💰 Nominal: <b>{rupiah(amount)}</b>\n"
                f"👤 User ID: <code>{user_id}</code>\n"
                f"🧾 Payment ID: <code>{payment_id}</code>"
            ),
            parse_mode="HTML"
        )
    except Exception:
        logger.exception("PREMIUM PAYMENT CHANNEL NOTIFY FAILED")


async def notify_user_and_channel(pool, user_id, package, payment_id, amount, status, title, message):
    try:
        await add_user_notification(pool, user_id, title, message)
    except Exception:
        logger.exception("PREMIUM USER NOTIFICATION DB FAILED")
    await post_payment_channel(package['type'], user_id, package, payment_id, amount, status)


def package_keyboard():
    rows = []
    for key in ("vip1h", "vip2h", "vip3h", "vip1d", "vip3d", "vip7d", "creator"):
        p = VIP_PACKAGES[key]
        rows.append([InlineKeyboardButton(
            text=f"💎 {p['name']} • {rupiah(p['price'])}",
            callback_data=f"premium_buy:{key}"
        )])
    rows.append([InlineKeyboardButton(text="🏠 Home", callback_data="home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def premium_text():
    return (
        "💎 <b>VIP / KREATOR PAS TELE</b>\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "Dengan VIP aktif, kamu dapat membuka <b>code media berbayar tanpa membayar tiap code</b>.\n\n"
        "💠 <b>VIP 1/2/3 Jam</b>\n"
        "• Masa aktif 1, 2, atau 3 jam\n"
        "• Maksimal <b>3 code paid unik</b> selama paket aktif\n"
        "• Semua media di code yang sudah dibuka tidak perlu bayar lagi\n\n"
        "💎 <b>VIP 1/3/7 Hari</b>\n"
        "• Bisa membuka <b>semua code paid</b> selama masa aktif\n"
        "• Tidak perlu bayar per code lagi\n"
        "• Setelah habis, akses premium berhenti dan pembayaran per code berlaku lagi\n\n"
        "🎨 <b>Kreator</b>\n"
        "• <b>Rp 200.000</b> sekali bayar\n"
        "• Aktivasi permanen, tanpa masa kedaluwarsa\n"
        "• Bisa membuka semua code paid tanpa bayar lagi\n"
        "• Fitur upload/penghasilan kreator tetap tersedia sesuai sistem bot\n\n"
        "⚠️ <b>Catatan:</b> VIP jam dibatasi 3 code unik. VIP hari dan Kreator unlimited.\n\n"
        "👇 Pilih paket:"
    )


@router.callback_query(F.data == "premium")
async def premium_menu(call: CallbackQuery):
    await call.answer()
    await call.message.edit_text(
        premium_text(), parse_mode="HTML", reply_markup=package_keyboard()
    )


@router.callback_query(F.data.startswith("premium_buy:"))
async def premium_buy(call: CallbackQuery):
    key = call.data.split(":", 1)[1]
    package = VIP_PACKAGES.get(key)
    if not package:
        return await call.answer("❌ Paket tidak ditemukan.", show_alert=True)

    pool = await get_pool()
    uid = call.from_user.id

    pending = await pool.fetchrow(
        """SELECT payment_id FROM premium_payments
           WHERE user_id=$1 AND status='pending'
           AND (expires_at IS NULL OR expires_at > NOW())
           ORDER BY id DESC LIMIT 1""", uid
    )
    if pending:
        return await call.answer(
            "⚠️ Masih ada pembayaran VIP/Kreator yang belum selesai.",
            show_alert=True
        )

    await call.answer("⏳ Membuat QR DompetX...")
    payment = await DompetX.create_payment(
        amount=package["price"],
        description=f"PasTele {package['name']}",
        customer_name=call.from_user.full_name
    )
    if not payment:
        return await call.message.edit_text(
            "❌ Gagal membuat pembayaran DompetX. Silakan coba lagi.",
            parse_mode="HTML", reply_markup=package_keyboard()
        )

    payment_id = str(payment.get("payment_id") or "")
    qr_string = payment.get("qr_string")
    if not payment_id or not qr_string:
        return await call.message.edit_text(
            "❌ QR DompetX tidak tersedia. Silakan coba lagi.",
            parse_mode="HTML", reply_markup=package_keyboard()
        )

    await pool.execute(
        """INSERT INTO premium_payments
           (user_id, package_id, amount, payment_id, status, qr_string,
            payment_url, expires_at, created_at)
           VALUES ($1,$2,$3,$4,'pending',$5,$6,$7,NOW())""",
        uid, key, package["price"], payment_id, qr_string,
        payment.get("payment_url"), db_naive_utc(payment.get("expires_at"))
    )

    await notify_user_and_channel(
        pool, uid, package, payment_id, package["price"], "pending",
        "Pembayaran VIP dibuat",
        f"{package['name']} senilai {rupiah(package['price'])} dibuat. Silakan selesaikan pembayaran melalui QR DompetX."
    )

    if package["type"] == "vip_clock":
        benefit = f"⏱️ Aktif {package['hours']} jam • maksimal 3 code paid"
    elif package["type"] == "vip_day":
        benefit = f"📅 Aktif {package['days']} hari • semua code paid"
    else:
        benefit = "🎨 Permanen • semua code paid"

    text = (
        "💳 <b>PEMBAYARAN VIP / KREATOR</b>\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        f"📦 Paket: <b>{package['name']}</b>\n"
        f"💰 Total: <b>{rupiah(package['price'])}</b>\n"
        f"✨ Benefit: <b>{benefit}</b>\n\n"
        f"🧾 ID Pembayaran: <code>{payment_id}</code>\n\n"
        "📷 Scan QR DompetX di atas untuk membayar.\n"
        "Setelah membayar, tekan <b>🔄 Cek Pembayaran</b>.\n"
        "Tekan <b>❌ Batal</b> jika ingin membatalkan."
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="🔄 Cek Pembayaran",
            callback_data=f"premium_check:{payment_id}"
        )],
        [InlineKeyboardButton(
            text="❌ Batal",
            callback_data=f"premium_cancel:{payment_id}"
        )]
    ])

    try:
        await call.message.delete()
    except Exception:
        pass

    qr = qrcode.make(qr_string)
    buf = BytesIO()
    qr.save(buf, format="PNG")
    buf.seek(0)
    await call.message.answer_photo(
        BufferedInputFile(buf.getvalue(), filename="dompetx_vip.png"),
        caption=text, parse_mode="HTML", reply_markup=kb
    )


async def activate_package(pool, uid, package_id, payment_id):
    p = VIP_PACKAGES[package_id]
    now = datetime.utcnow()

    if p["type"] == "creator":
        await pool.execute(
            """UPDATE users SET
               is_creator=TRUE, creator_status='approved',
               creator_verified_at=COALESCE(creator_verified_at,NOW()),
               plan='creator', updated_at=NOW()
               WHERE user_id=$1""", uid
        )
        return "🎨 <b>Kreator aktif permanen.</b> Semua code paid bisa dibuka tanpa bayar lagi."

    if p["type"] == "vip_clock":
        until = now + timedelta(hours=p["hours"])
        await pool.execute(
            """UPDATE users SET
               vip=TRUE, is_vip=TRUE, vip_until=$1, vip_expired=$1,
               plan='vip', expired_at=$1, updated_at=NOW()
               WHERE user_id=$2""", until, uid
        )
        await pool.execute(
            "DELETE FROM premium_code_usage WHERE user_id=$1", uid
        )
        await pool.execute(
            "UPDATE premium_payments SET access_until=$1, code_limit=3 WHERE payment_id=$2",
            until, payment_id
        )
        return f"⏱️ <b>VIP {p['hours']} jam aktif.</b> Maksimal 3 code paid unik."

    until = now + timedelta(days=p["days"])
    await pool.execute(
        """UPDATE users SET
           vip=TRUE, is_vip=TRUE, vip_until=$1, vip_expired=$1,
           plan='vip', expired_at=$1, updated_at=NOW()
           WHERE user_id=$2""", until, uid
    )
    await pool.execute(
        "UPDATE premium_payments SET access_until=$1, code_limit=0 WHERE payment_id=$2",
        until, payment_id
    )
    return f"📅 <b>VIP aktif sampai {until.strftime('%d-%m-%Y %H:%M')} WIB.</b> Semua code paid bisa dibuka tanpa bayar lagi."


@router.callback_query(F.data.startswith("premium_check:"))
async def premium_check(call: CallbackQuery):
    payment_id = call.data.split(":", 1)[1]
    pool = await get_pool()
    payment = await pool.fetchrow(
        "SELECT * FROM premium_payments WHERE payment_id=$1 AND user_id=$2 LIMIT 1",
        payment_id, call.from_user.id
    )
    if not payment:
        return await call.answer("❌ Pembayaran tidak ditemukan.", show_alert=True)
    if payment["status"] == "paid":
        return await call.answer(
            "✅ Pembayaran sudah berhasil dan paket sudah aktif.",
            show_alert=True
        )

    result = await DompetX.check_payment(payment_id)
    if not result:
        return await call.answer(
            "⚠️ Gagal mengecek DompetX. Coba lagi.", show_alert=True
        )

    status = str(result.get("status") or "").lower()
    if status in SUCCESS:
        provider_amount = int(result.get("amount") or 0)
        if provider_amount != int(payment["amount"]):
            logger.error(
                "PREMIUM AMOUNT MISMATCH payment=%s provider=%s db=%s",
                payment_id, provider_amount, payment["amount"]
            )
            return await call.answer(
                "❌ Nominal pembayaran tidak sesuai.", show_alert=True
            )

        updated = await pool.fetchrow(
            """UPDATE premium_payments
               SET status='paid', paid_at=NOW()
               WHERE payment_id=$1 AND status='pending'
               RETURNING *""", payment_id
        )
        if updated:
            msg = await activate_package(
                pool, call.from_user.id, payment["package_id"], payment_id
            )
            await notify_user_and_channel(
                pool, call.from_user.id, VIP_PACKAGES[payment["package_id"]], payment_id,
                payment["amount"], "paid",
                "VIP / Kreator aktif", msg.replace("<b>", "").replace("</b>", "")
            )
            try:
                await call.message.edit_caption(
                    caption=f"✅ <b>PEMBAYARAN BERHASIL</b>\n\n{msg}\n\nID: <code>{payment_id}</code>",
                    parse_mode="HTML",
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(
                            text="💎 VIP / Kreator", callback_data="premium"
                        )],
                        [InlineKeyboardButton(
                            text="🏠 Home", callback_data="home"
                        )]
                    ])
                )
            except Exception:
                await call.message.answer(
                    f"✅ <b>PEMBAYARAN BERHASIL</b>\n\n{msg}",
                    parse_mode="HTML"
                )
        return await call.answer("✅ Pembayaran berhasil.", show_alert=True)

    if status in FAILED:
        await pool.execute(
            "UPDATE premium_payments SET status='cancel' WHERE payment_id=$1 AND status='pending'",
            payment_id
        )
        await notify_user_and_channel(
            pool, call.from_user.id, VIP_PACKAGES[payment["package_id"]], payment_id,
            payment["amount"], "cancel",
            "Pembayaran gagal / kedaluwarsa",
            f"Pembayaran {VIP_PACKAGES[payment['package_id']]['name']} belum berhasil dan tidak mengaktifkan akses premium."
        )
        return await call.answer(
            "❌ Pembayaran batal/kedaluwarsa.", show_alert=True
        )

    return await call.answer(
        f"⏳ Status: {status or 'pending'}. Silakan cek lagi.", show_alert=True
    )


@router.callback_query(F.data.startswith("premium_cancel:"))
async def premium_cancel(call: CallbackQuery):
    payment_id = call.data.split(":", 1)[1]
    pool = await get_pool()
    payment = await pool.fetchrow(
        "SELECT * FROM premium_payments WHERE payment_id=$1 AND user_id=$2 LIMIT 1",
        payment_id, call.from_user.id
    )
    if not payment:
        return await call.answer("❌ Pembayaran tidak ditemukan.", show_alert=True)

    if payment["status"] == "pending":
        try:
            await DompetX.cancel_payment(payment_id)
        except Exception:
            logger.exception("PREMIUM CANCEL PROVIDER ERROR")
        await pool.execute(
            "UPDATE premium_payments SET status='cancel' WHERE payment_id=$1 AND status='pending'",
            payment_id
        )
        await notify_user_and_channel(
            pool, call.from_user.id, VIP_PACKAGES[payment["package_id"]], payment_id,
            payment["amount"], "cancel",
            "Pembayaran dibatalkan",
            f"Pembayaran {VIP_PACKAGES[payment['package_id']]['name']} dibatalkan. Tidak ada akses premium yang diberikan."
        )

    await call.answer("❌ Pembayaran dibatalkan.")
    await call.message.edit_text(
        premium_text(), parse_mode="HTML", reply_markup=package_keyboard()
    )
