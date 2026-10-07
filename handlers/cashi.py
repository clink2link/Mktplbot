import logging
import base64
import binascii
import qrcode
from io import BytesIO
from typing import Set

from aiogram import Router, F
from aiogram.types import (
    CallbackQuery,
    BufferedInputFile,
)

from database import fetchrow, execute
from utils.cashi import Cashi

from .pay import (
    finish_payment,
    SUCCESS_STATUSES,
    FAILED_STATUSES,
    normalize_status,
    format_rupiah,
)

logger = logging.getLogger(__name__)

router = Router()

# ============================================================
# CASHI PAYMENT CHECK LOCK
# ============================================================
CHECK_LOCK: Set[str] = set()
# ============================================================
# KEYBOARD
# ============================================================
def cashi_keyboard(payment_id: str):
    """Keyboard dedicated to CASHI orders.

    Keep the provider order ID opaque and route it to the CASHI-specific
    handlers below. The handler performs ownership checks before any action.
    """
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

    payment_id = str(payment_id).strip()

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🔄 Cek Pembayaran",
                    callback_data=f"cashicheck:{payment_id}",
                )
            ],
            [
                InlineKeyboardButton(
                    text="❌ Batal",
                    callback_data=f"cashicancel:{payment_id}",
                )
            ],
        ]
    )
# ============================================================
# GENERATE QR
# ============================================================
def generate_qr(qr_string: str) -> bytes:
    if not qr_string:
        raise ValueError(
            "QR string kosong"
        )
    qr_string = str(
        qr_string
    ).strip()
    # ========================================================
    # CASHI DAPAT MEMBERIKAN:
    #
    # 1. QR string biasa
    # 2. data:image/png;base64,...
    #
    # Jika sudah berupa gambar base64, jangan encode ulang.
    # ========================================================
    if qr_string.startswith(
        "data:image/"
    ):
        try:
            header, encoded = qr_string.split(
                ",",
                1,
            )
            image_data = base64.b64decode(
                encoded,
                validate=True,
            )
            if not image_data:
                raise ValueError(
                    "Data QR image kosong"
                )
            return image_data
        except (
            ValueError,
            binascii.Error,
        ):
            logger.exception(
                "CASHI INVALID QR IMAGE DATA"
            )
            raise ValueError(
                "Format QR image Cashi tidak valid"
            )
    # ========================================================
    # QR STRING NORMAL
    # ========================================================
    qr = qrcode.make(
        qr_string
    )
    buffer = BytesIO()
    qr.save(
        buffer,
        format="PNG",
    )
    buffer.seek(0)
    return buffer.getvalue()
# ============================================================
# GET PURCHASE
# ============================================================
async def get_cashi_purchase(
    payment_id: str,
):
    return await fetchrow(
        """
        SELECT *
        FROM file_purchases
        WHERE payment_id=$1
        LIMIT 1
        """,
        str(payment_id),
    )
# ============================================================
# CHECK USER OWNERSHIP
# ============================================================
def purchase_belongs_to_user(
    purchase,
    user_id: int,
) -> bool:
    try:
        return int(
            purchase["user_id"]
        ) == int(user_id)
    except Exception:
        return False
# ============================================================
# CANCEL DATABASE PURCHASE
# ============================================================
async def cancel_cashi_database(
    payment_id: str,
):
    try:
        await execute(
            """
            UPDATE file_purchases
            SET status='cancel'
            WHERE payment_id=$1
              AND status='pending'
            """,
            str(payment_id),
        )
    except Exception:
        logger.exception(
            "CASHI DATABASE CANCEL ERROR | "
            "payment_id=%s",
            payment_id,
        )
# ============================================================
# CREATE CASHI PAYMENT
# ============================================================
# INTERNAL: routed centrally by handlers.pay
async def create_cashi(
    call: CallbackQuery,
):
    code = call.data.split(
        ":",
        1,
    )[1].strip()
    user_id = call.from_user.id
    if not code:
        return await call.answer(
            "❌ Kode file tidak valid.",
            show_alert=True,
        )
    # ========================================================
    # FILE
    # ========================================================
    try:
        file = await fetchrow(
            """
            SELECT *
            FROM files
            WHERE code=$1
            LIMIT 1
            """,
            code,
        )
    except Exception:
        logger.exception(
            "CASHI FILE QUERY ERROR | code=%s",
            code,
        )
        return await call.answer(
            "❌ Gagal mengambil data file.",
            show_alert=True,
        )
    if not file:
        return await call.answer(
            "❌ File tidak ditemukan.",
            show_alert=True,
        )
    # ========================================================
    # PRICE
    # ========================================================
    try:
        price = int(
            file["price"] or 0
        )
    except Exception:
        price = 0
    # Cashi minimum = Rp2.000
    if price < 2000:
        return await call.answer(
            "❌ Harga file minimal Rp2.000.",
            show_alert=True,
        )
    # Cashi maximum = Rp10.000.000
    if price > 10_000_000:
        return await call.answer(
            "❌ Harga file maksimal Rp10.000.000.",
            show_alert=True,
        )
    # ========================================================
    # OWNER
    # ========================================================
    owner_id = file.get(
        "owner_id"
    )
    if owner_id is None:
        logger.error(
            "CASHI OWNER ID KOSONG | code=%s",
            code,
        )
        return await call.answer(
            "❌ Pemilik file tidak ditemukan.",
            show_alert=True,
        )
    # ========================================================
    # CEK PURCHASE TERAKHIR
    # ========================================================
    try:
        existing = await fetchrow(
            """
            SELECT *
            FROM file_purchases
            WHERE user_id=$1
              AND file_code=$2
            ORDER BY created_at DESC
            LIMIT 1
            """,
            user_id,
            code,
        )
    except Exception:
        logger.exception(
            "CASHI PURCHASE QUERY ERROR | "
            "user=%s | code=%s",
            user_id,
            code,
        )
        return await call.answer(
            "❌ Gagal mengecek transaksi.",
            show_alert=True,
        )
    # ========================================================
    # SUDAH PAID
    # ========================================================
    if existing:
        existing_status = normalize_status(
            existing["status"]
        )
        if existing_status == "paid":
            return await call.answer(
                "✅ File ini sudah kamu beli.",
                show_alert=True,
            )
    # ========================================================
    # PAYMENT LAMA PENDING
    # ========================================================
    if existing:
        existing_status = normalize_status(
            existing["status"]
        )
        if existing_status == "pending":
            old_payment_id = existing.get(
                "payment_id"
            )
            if old_payment_id:
                await call.answer(
                    "🔄 Mengecek pembayaran sebelumnya..."
                )
                old_result = None
                try:
                    old_result = (
                        await Cashi.check_payment(
                            str(old_payment_id)
                        )
                    )
                except Exception:
                    logger.exception(
                        "CASHI CHECK OLD PAYMENT ERROR | "
                        "payment_id=%s",
                        old_payment_id,
                    )
                if old_result:
                    old_status = normalize_status(
                        old_result.get(
                            "status"
                        )
                    )
                    logger.info(
                        "CASHI OLD PAYMENT | "
                        "payment_id=%s | status=%s",
                        old_payment_id,
                        old_status,
                    )
                    # ==========================================
                    # OLD PAYMENT SUCCESS
                    # ==========================================
                    if old_status in SUCCESS_STATUSES:
                        purchase = await get_cashi_purchase(
                            old_payment_id
                        )
                        if not purchase:
                            return await call.answer(
                                "❌ Data transaksi tidak ditemukan.",
                                show_alert=True,
                            )
                        old_file = await fetchrow(
                            """
                            SELECT *
                            FROM files
                            WHERE code=$1
                            LIMIT 1
                            """,
                            purchase["file_code"],
                        )
                        if not old_file:
                            return await call.answer(
                                "❌ File tidak ditemukan.",
                                show_alert=True,
                            )
                        # ======================================
                        # NOMINAL VALIDATION
                        # ======================================
                        try:
                            provider_amount = int(
                                old_result.get(
                                    "amount"
                                ) or 0
                            )
                            purchase_amount = int(
                                purchase["paid_price"] or 0
                            )
                        except Exception:
                            provider_amount = 0
                            purchase_amount = 0
                        if (
                            provider_amount
                            and purchase_amount
                            and provider_amount
                            != purchase_amount
                        ):
                            logger.error(
                                "CASHI AMOUNT MISMATCH | "
                                "payment=%s | provider=%s | db=%s",
                                old_payment_id,
                                provider_amount,
                                purchase_amount,
                            )
                            return await call.answer(
                                "❌ Nominal pembayaran tidak sesuai.",
                                show_alert=True,
                            )
                        success = await finish_payment(
                            call.bot,
                            purchase,
                            old_file,
                            str(old_payment_id),
                            call.message,
                        )
                        if success:
                            return
                        return await call.answer(
                            "⚠️ Pembayaran sudah diproses atau gagal diproses.",
                            show_alert=True,
                        )
                    # ==========================================
                    # OLD PAYMENT STILL ACTIVE
                    # ==========================================
                    if old_status in {
                        "pending",
                        "processing",
                        "unpaid",
                        "created",
                    }:
                        old_qr_string = existing.get(
                            "qr_string"
                        )
                        if old_qr_string:
                            try:
                                qr_data = generate_qr(
                                    old_qr_string
                                )
                                await call.message.answer_photo(
                                    BufferedInputFile(
                                        qr_data,
                                        filename="cashi_qris.png",
                                    ),
                                    caption=(
                                        "💳 <b>PEMBAYARAN MASIH BERJALAN</b>\n\n"
                                        f"📄 File:\n"
                                        f"<b>{file['title']}</b>\n\n"
                                        f"🧾 Invoice:\n"
                                        f"<code>{old_payment_id}</code>\n\n"
                                        f"💰 Total:\n"
                                        f"<b>{format_rupiah(price)}</b>\n\n"
                                        "📷 Silakan scan QRIS di atas.\n\n"
                                        "Jika sudah membayar, "
                                        "tekan <b>🔄 Cek Pembayaran</b>."
                                    ),
                                    parse_mode="HTML",
                                    reply_markup=cashi_keyboard(
                                        str(old_payment_id)
                                    ),
                                )
                                return
                            except Exception:
                                logger.exception(
                                    "CASHI RESEND OLD QR ERROR | "
                                    "payment_id=%s",
                                    old_payment_id,
                                )
                        return await call.answer(
                            "⏳ Pembayaran sebelumnya masih aktif.",
                            show_alert=True,
                        )
                    # ==========================================
                    # OLD PAYMENT FAILED
                    # ==========================================
                    if old_status in FAILED_STATUSES:
                        logger.info(
                            "CASHI OLD PAYMENT CLOSED | "
                            "payment_id=%s | status=%s",
                            old_payment_id,
                            old_status,
                        )
                        try:
                            await execute(
                                """
                                UPDATE file_purchases
                                SET status='cancel'
                                WHERE payment_id=$1
                                  AND status='pending'
                                """,
                                str(old_payment_id),
                            )
                        except Exception:
                            logger.exception(
                                "CASHI CLOSE OLD PAYMENT ERROR"
                            )
                    # ==========================================
                    # UNKNOWN
                    # ==========================================
                    else:
                        logger.warning(
                            "CASHI UNKNOWN STATUS | "
                            "payment_id=%s | status=%s",
                            old_payment_id,
                            old_status,
                        )
                        return await call.answer(
                            f"⏳ Status pembayaran: {old_status}",
                            show_alert=True,
                        )
    # ========================================================
    # CREATE NEW PAYMENT
    # ========================================================
    await call.answer(
        "⏳ Membuat QRIS Cashi..."
    )
    try:
        payment = await Cashi.create_payment(
            amount=price,
            description=f"File {code}",
            customer_name=call.from_user.full_name,
        )
    except Exception:
        logger.exception(
            "CASHI CREATE PAYMENT ERROR | "
            "user=%s | code=%s | amount=%s",
            user_id,
            code,
            price,
        )
        return await call.message.answer(
            "❌ Cashi sedang mengalami gangguan."
        )
    if not payment:
        logger.error(
            "CASHI EMPTY PAYMENT RESPONSE"
        )
        return await call.message.answer(
            "❌ Gagal membuat pembayaran Cashi."
        )
    # ========================================================
    # PAYMENT ID / ORDER ID
    # ========================================================
    payment_id = (
        payment.get("order_id")
        or payment.get("payment_id")
        or payment.get("invoice_id")
    )
    if not payment_id:
        logger.error(
            "CASHI PAYMENT ID KOSONG: %s",
            payment,
        )
        return await call.message.answer(
            "❌ Order ID Cashi tidak ditemukan."
        )
    payment_id = str(
        payment_id
    )
    # ========================================================
    # QR
    # ========================================================
    qr_string = (
        payment.get("qr_string")
        or payment.get("qr_image")
    )
    if not qr_string:
        logger.error(
            "CASHI QR KOSONG | "
            "payment_id=%s | response=%s",
            payment_id,
            payment,
        )
        # Tidak ada cancel API Cashi.
        # Transaksi belum disimpan ke DB sehingga
        # tidak perlu melakukan request cancel.
        return await call.message.answer(
            "❌ QRIS Cashi tidak tersedia."
        )
    # ========================================================
    # EXPIRES
    # ========================================================
    # Always pass a real datetime to asyncpg for timestamptz columns.
    expires_at = Cashi._parse_datetime(
        payment.get("expires_at")
    )
    # ========================================================
    # OPTIONAL DATA
    # ========================================================
    qr_image = payment.get(
        "qr_image"
    )
    payment_url = (
        payment.get("checkout_url")
        or payment.get("payment_url")
    )
    # ========================================================
    # SAVE PURCHASE
    # ========================================================
    try:
        if existing:
            saved_purchase = await fetchrow(
                """
                UPDATE file_purchases
                SET
                    owner_id=$1,
                    paid_price=$2,
                    payment_id=$3,
                    status='pending',
                    qr_string=$4,
                    qr_image=$5,
                    payment_url=$6,
                    expires_at=$7,
                    qr_message_id=NULL,
                    qr_chat_id=NULL,
                    paid_at=NULL,
                    created_at=NOW()
                WHERE id=$8
                RETURNING *
                """,
                owner_id,
                price,
                payment_id,
                qr_string,
                qr_image,
                payment_url,
                expires_at,
                existing["id"],
            )
        else:
            saved_purchase = await fetchrow(
                """
                INSERT INTO file_purchases
                (
                    user_id,
                    file_code,
                    owner_id,
                    paid_price,
                    payment_id,
                    status,
                    qr_string,
                    qr_image,
                    payment_url,
                    expires_at,
                    created_at,
                    provider,
                    payment_method,
                    code
                )
                VALUES
                (
                    $1,
                    $2,
                    $3,
                    $4,
                    $5,
                    'pending',
                    $6,
                    $7,
                    $8,
                    $9,
                    NOW(),
                    'CASHI',
                    'qris',
                    $2
                )
                RETURNING *
                """,
                user_id,
                code,
                owner_id,
                price,
                payment_id,
                qr_string,
                qr_image,
                payment_url,
                expires_at,
            )
    except Exception:
        logger.exception(
            "CASHI SAVE PURCHASE ERROR | "
            "payment_id=%s",
            payment_id,
        )
        # Cashi tidak mempunyai cancel API
        # pada dokumentasi yang diberikan.
        # Jadi cukup jangan proses transaksi lebih lanjut.
        return await call.message.answer(
            "❌ Gagal menyimpan transaksi."
        )
    if not saved_purchase:
        logger.error(
            "CASHI PURCHASE NOT SAVED | "
            "payment_id=%s",
            payment_id,
        )
        return await call.message.answer(
            "❌ Transaksi gagal dibuat."
        )
    # ========================================================
    # GENERATE QR
    # ========================================================
    try:
        qr_data = generate_qr(
            qr_string
        )
    except Exception:
        logger.exception(
            "CASHI QR GENERATE ERROR | "
            "payment_id=%s",
            payment_id,
        )
        await cancel_cashi_database(
            payment_id
        )
        return await call.message.answer(
            "❌ Gagal membuat QRIS."
        )
    # ========================================================
    # CAPTION
    # ========================================================
    caption = (
        "💳 <b>PEMBAYARAN FILE</b>\n\n"
        f"📄 File:\n"
        f"<b>{file['title']}</b>\n\n"
        f"🧾 Invoice:\n"
        f"<code>{payment_id}</code>\n\n"
        f"💰 Total:\n"
        f"<b>{format_rupiah(price)}</b>\n\n"
        "📷 Silakan scan QRIS di atas.\n\n"
        "Setelah pembayaran berhasil, "
        "tekan <b>🔄 Cek Pembayaran</b>."
    )
    if expires_at:
        try:
            caption += (
                "\n\n⏰ Expired:\n"
                f"<code>"
                f"{expires_at.strftime('%d-%m-%Y %H:%M:%S %z')}"
                f"</code>"
            )
        except Exception:
            logger.warning(
                "CASHI EXPIRES FORMAT ERROR",
                exc_info=True,
            )
    # ========================================================
    # SEND QR
    # ========================================================
    try:
        msg = await call.message.answer_photo(
            BufferedInputFile(
                qr_data,
                filename="cashi_qris.png",
            ),
            caption=caption,
            parse_mode="HTML",
            reply_markup=cashi_keyboard(
                payment_id
            ),
        )
    except Exception:
        logger.exception(
            "CASHI SEND QR ERROR | "
            "payment_id=%s",
            payment_id,
        )
        await cancel_cashi_database(
            payment_id
        )
        return await call.message.answer(
            "❌ Gagal mengirim QRIS."
        )
    # ========================================================
    # SAVE QR MESSAGE
    # ========================================================
    try:
        await execute(
            """
            UPDATE file_purchases
            SET
                qr_message_id=$1,
                qr_chat_id=$2
            WHERE payment_id=$3
            """,
            msg.message_id,
            msg.chat.id,
            payment_id,
        )
    except Exception:
        logger.exception(
            "CASHI SAVE QR MESSAGE ERROR | "
            "payment_id=%s",
            payment_id,
        )
    logger.info(
        "CASHI PAYMENT CREATED | "
        "payment_id=%s | user=%s | code=%s | "
        "amount=%s | expires=%s",
        payment_id,
        user_id,
        code,
        price,
        expires_at,
    )
# ============================================================
# CHECK CASHI PAYMENT
# ============================================================
# INTERNAL: routed centrally by handlers.pay
async def check_cashi(
    call: CallbackQuery,
):
    payment_id = call.data.split(
        ":",
        1,
    )[1].strip()
    if not payment_id:
        return await call.answer(
            "❌ Order ID tidak valid.",
            show_alert=True,
        )
    # ========================================================
    # LOCK
    # ========================================================
    if payment_id in CHECK_LOCK:
        return await call.answer(
            "⏳ Sedang diproses...",
            show_alert=True,
        )
    CHECK_LOCK.add(
        payment_id
    )
    try:
        await call.answer(
            "🔄 Mengecek pembayaran..."
        )
        # ====================================================
        # PURCHASE
        # ====================================================
        purchase = await get_cashi_purchase(
            payment_id
        )
        if not purchase:
            return await call.message.answer(
                "❌ Data pembayaran tidak ditemukan."
            )
        # ====================================================
        # SECURITY
        # ====================================================
        if not purchase_belongs_to_user(
            purchase,
            call.from_user.id,
        ):
            logger.warning(
                "UNAUTHORIZED CASHI CHECK | "
                "payment_id=%s | owner=%s | caller=%s",
                payment_id,
                purchase["user_id"],
                call.from_user.id,
            )
            return await call.message.answer(
                "❌ Pembayaran ini bukan milik kamu."
            )
        # ====================================================
        # ALREADY PAID
        # ====================================================
        if normalize_status(
            purchase["status"]
        ) == "paid":
            return await call.message.answer(
                "✅ Pembayaran sudah diproses."
            )
        # ====================================================
        # PROVIDER CHECK
        # ====================================================
        try:
            result = await Cashi.check_payment(
                payment_id
            )
        except Exception:
            logger.exception(
                "CASHI CHECK PROVIDER ERROR | "
                "payment_id=%s",
                payment_id,
            )
            return await call.message.answer(
                "❌ Gagal terhubung ke Cashi."
            )
        if not result:
            return await call.message.answer(
                "❌ Gagal mengecek pembayaran."
            )
        # ====================================================
        # STATUS
        # ====================================================
        status = normalize_status(
            result.get("status")
        )
        logger.info(
            "CASHI CHECK | "
            "payment_id=%s | status=%s",
            payment_id,
            status,
        )
        # ====================================================
        # FAILED
        # ========================================================
        if status in FAILED_STATUSES:
            await execute(
                """
                UPDATE file_purchases
                SET status='cancel'
                WHERE payment_id=$1
                  AND status='pending'
                """,
                payment_id,
            )
            return await call.message.answer(
                f"❌ Pembayaran {status}."
            )
        # ====================================================
        # NOT PAID
        # ====================================================
        if status not in SUCCESS_STATUSES:
            return await call.message.answer(
                "⏳ Pembayaran belum diterima."
            )
        # ====================================================
        # AMOUNT VALIDATION
        # ========================================================
        try:
            provider_amount = int(
                result.get("amount") or 0
            )
            purchase_amount = int(
                purchase["paid_price"] or 0
            )
        except Exception:
            provider_amount = 0
            purchase_amount = 0
        if (
            provider_amount
            and purchase_amount
            and provider_amount != purchase_amount
        ):
            logger.error(
                "CASHI AMOUNT MISMATCH | "
                "payment=%s | provider=%s | db=%s",
                payment_id,
                provider_amount,
                purchase_amount,
            )
            return await call.message.answer(
                "❌ Nominal pembayaran tidak sesuai."
            )
        # ====================================================
        # FILE
        # ====================================================
        file = await fetchrow(
            """
            SELECT *
            FROM files
            WHERE code=$1
            LIMIT 1
            """,
            purchase["file_code"],
        )
        if not file:
            logger.error(
                "CASHI FILE NOT FOUND | "
                "payment_id=%s | code=%s",
                payment_id,
                purchase["file_code"],
            )
            return await call.message.answer(
                "❌ File tidak ditemukan."
            )
        # ====================================================
        # FINISH PAYMENT
        # ====================================================
        success = await finish_payment(
            call.bot,
            purchase,
            file,
            payment_id,
            call.message,
        )
        if not success:
            return await call.message.answer(
                "⚠️ Pembayaran sudah diproses atau gagal diproses."
            )
    except Exception:
        logger.exception(
            "CASHI CHECK ERROR | payment_id=%s",
            payment_id,
        )
        try:
            await call.message.answer(
                "❌ Terjadi kesalahan saat memproses pembayaran."
            )
        except Exception:
            pass
    finally:
        CHECK_LOCK.discard(
            payment_id
        )
# ============================================================
# CANCEL CASHI PAYMENT
# ============================================================
@router.callback_query(
    F.data.startswith("cashicancel:")
)
async def cancel_cashi(
    call: CallbackQuery,
):
    payment_id = call.data.split(
        ":",
        1,
    )[1].strip()
    payment = await get_cashi_purchase(
        payment_id
    )
    if not payment:
        return await call.answer(
            "❌ Data pembayaran tidak ditemukan.",
            show_alert=True,
        )
    # ========================================================
    # SECURITY
    # ========================================================
    if not purchase_belongs_to_user(
        payment,
        call.from_user.id,
    ):
        logger.warning(
            "UNAUTHORIZED CASHI CANCEL | "
            "payment_id=%s | owner=%s | caller=%s",
            payment_id,
            payment["user_id"],
            call.from_user.id,
        )
        return await call.answer(
            "❌ Pembayaran ini bukan milik kamu.",
            show_alert=True,
        )
    # ========================================================
    # STATUS
    # ========================================================
    status = normalize_status(
        payment["status"]
    )
    if status == "paid":
        return await call.answer(
            "❌ Pembayaran sudah dibayar.",
            show_alert=True,
        )
    if status != "pending":
        return await call.answer(
            f"⚠️ Pembayaran sudah berstatus {status}.",
            show_alert=True,
        )
    # ========================================================
    # CASHI TIDAK MENYEDIAKAN CANCEL ENDPOINT
    #
    # Sesuai dokumentasi Cashi yang diberikan:
    # hanya create-order dan check-status yang tersedia.
    #
    # Jadi pembatalan dilakukan secara LOCAL DATABASE.
    # ========================================================
    logger.info(
        "CASHI LOCAL CANCEL | "
        "payment_id=%s | user=%s",
        payment_id,
        call.from_user.id,
    )
    # ========================================================
    # DATABASE
    # ========================================================
    try:
        await execute(
            """
            UPDATE file_purchases
            SET status='cancel'
            WHERE payment_id=$1
              AND status='pending'
            """,
            payment_id,
        )
    except Exception:
        logger.exception(
            "CASHI DATABASE CANCEL ERROR | "
            "payment_id=%s",
            payment_id,
        )
        return await call.answer(
            "❌ Gagal membatalkan transaksi.",
            show_alert=True,
        )
    # ========================================================
    # DELETE QR
    # ========================================================
    try:
        qr_chat_id = payment.get(
            "qr_chat_id"
        )
        qr_message_id = payment.get(
            "qr_message_id"
        )
        if (
            qr_chat_id
            and qr_message_id
        ):
            await call.bot.delete_message(
                chat_id=qr_chat_id,
                message_id=qr_message_id,
            )
    except Exception:
        logger.warning(
            "CASHI DELETE QR MESSAGE FAILED | "
            "payment_id=%s",
            payment_id,
            exc_info=True,
        )
    # ========================================================
    # FEEDBACK
    # ========================================================
    await call.answer(
        "✅ Pembayaran dibatalkan."
    )
    try:
        await call.message.edit_reply_markup(
            reply_markup=None
        )
    except Exception:
        pass
    logger.info(
        "CASHI PAYMENT CANCELLED | "
        "payment_id=%s | user=%s",
        payment_id,
        call.from_user.id,
    )
