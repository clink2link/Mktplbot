import hmac
import hashlib
import logging

logger = logging.getLogger(__name__)

from fastapi import APIRouter, Request

from config_vip import VIP_PACKAGES
from bot import bot
from database import fetchrow, execute
from utils.redis_client import redis_client
from handlers.page import send_page
from config import BAYARGG_SECRET

router = APIRouter(prefix="/bayargg", tags=["BayarGG"])

SECRET_KEY = BAYARGG_SECRET.encode()
ADMIN_CHAT_ID = -1004437365690


def secure_compare(a: str, b: str) -> bool:
    return hmac.compare_digest(a or "", b or "")


@router.post("/webhook")
async def webhook(request: Request):
    body = await request.body()
    signature = request.headers.get("X-Callback-Signature", "")

    expected = hmac.new(
        SECRET_KEY,
        body,
        hashlib.sha256
    ).hexdigest()

    if not secure_compare(signature, expected):
        return {"success": False, "message": "invalid signature"}

    try:
        data = await request.json()
    except Exception:
        return {"success": False, "message": "invalid json"}

    invoice_id = str(data.get("invoice_id", "")).strip()
    status = str(data.get("status", "")).strip().lower()

    if not invoice_id:
        return {
            "success": False,
            "message": "missing invoice"
        }

    logger.info(
        "BayarGG webhook | invoice=%s | status=%s",
        invoice_id,
        status
    )

    if status != "paid":
        return {"success": True, "message": "ignored"}

    redis_key = f"webhook:bayargg:{invoice_id}"

    try:
        locked = await redis_client.set(
            redis_key,
            "1",
            ex=86400,
            nx=True
        )

        if not locked:
            return {
                "success": True,
                "message": "already processed"
            }

    except Exception:
        logger.exception("Redis lock failed")

    # =========================
    # CEK VIP PAYMENT
    # =========================

    vip_tx = await fetchrow(
        """
        SELECT
            user_id,
            amount,
            code,
            status
        FROM payments
        WHERE invoice_id=$1
          AND type='vip'
        """,
        invoice_id
    )

    if vip_tx:

        updated = await execute(
            """
            UPDATE payments
            SET
                status='paid'
            WHERE invoice_id=$1
              AND type='vip'
              AND status!='paid'
            """,
            invoice_id
        )

        if updated == "UPDATE 0":
            return {
                "success": True,
                "message": "vip already processed"
            }

        paket = vip_tx["code"]

        paket_data = VIP_PACKAGES.get(paket)

        if not paket_data:
            days = 1
        else:
            days = paket_data["days"]

        await execute(
            """
            UPDATE users
            SET
                vip = TRUE,
                vip_until =
                CASE
                    WHEN vip_until IS NULL
                         OR vip_until < NOW()
                    THEN NOW() + ($2 || ' days')::interval
                    ELSE vip_until + ($2 || ' days')::interval
                END
            WHERE user_id = $1
            """,
            vip_tx["user_id"],
            days
        )

        logger.info(
            "VIP activated | user=%s | package=%s | days=%s",
            vip_tx["user_id"],
            paket,
            days
        )

        try:
            await bot.send_message(
                vip_tx["user_id"],
                (
                    "💎 <b>VIP BERHASIL DIAKTIFKAN</b>\n\n"
                    f"Durasi : {days} hari"
                ),
                parse_mode="HTML"
            )
        except Exception:
            logger.exception("vip notify failed")

        try:
            await bot.send_message(
                ADMIN_CHAT_ID,
                (
                    "💎 <b>VIP PURCHASE</b>\n\n"
                    f"👤 User : <code>{vip_tx['user_id']}</code>\n"
                    f"📦 Paket : <code>{paket}</code>\n"
                    f"🧾 Invoice : <code>{invoice_id}</code>\n"
                    f"💰 Amount : Rp {vip_tx['amount']:,}"
                ).replace(",", "."),
                parse_mode="HTML"
            )
        except Exception:
            logger.exception("vip admin notify failed")

        return {
            "success": True,
            "message": "vip activated"
        }

    # =========================
    # CEK CREATOR PAYMENT
    # =========================
    creator_tx = await fetchrow(
        """SELECT * FROM creator_upgrade_payments
           WHERE provider_invoice=$1 AND provider='bayargg' AND status='pending'
           LIMIT 1""", invoice_id
    )
    if creator_tx:
        updated = await execute(
            """UPDATE creator_upgrade_payments
               SET status='approved', paid_at=NOW(), reviewed_at=NOW()
               WHERE id=$1 AND status='pending'""", creator_tx["id"]
        )
        if updated != "UPDATE 0":
            await execute(
                """UPDATE users SET is_creator=TRUE, creator_status='approved', creator_verified_at=NOW(), updated_at=NOW()
                   WHERE user_id=$1""", creator_tx["user_id"]
            )
            try:
                await bot.send_message(
                    creator_tx["user_id"],
                    "🎉 <b>Creator berhasil diaktifkan!</b>",
                    parse_mode="HTML",
                )
            except Exception:
                logger.exception("creator notify failed")
        return {"success": True, "message": "creator activated"}

    # =========================
    # CEK FILE PAYMENT
    # =========================

    file_tx = await fetchrow(
        """
        SELECT
            user_id,
            owner_id,
            paid_price,
            file_code,
            status,
            qr_message_id,
            qr_chat_id
        FROM file_purchases
        WHERE payment_id=$1
        """,
        invoice_id
    )

    if not file_tx:
        logger.warning(
            "Invoice %s tidak ditemukan",
            invoice_id
        )

        return {
            "success": False,
            "message": "transaction not found"
        }

    if file_tx["status"] == "paid":
        return {
            "success": True,
            "message": "already paid"
        }

    updated = await execute(
        """
        UPDATE file_purchases
        SET
            status='paid',
            paid_at=NOW()
        WHERE payment_id=$1
          AND status='pending'
        """,
        invoice_id
    )

    if updated == "UPDATE 0":
        return {
            "success": True,
            "message": "already processed"
        }

    try:
        if file_tx["qr_message_id"]:
            await bot.delete_message(
                chat_id=file_tx["qr_chat_id"],
                message_id=file_tx["qr_message_id"]
            )
    except Exception:
        logger.exception("Failed delete QR message")

    try:
        updated = await execute(
            """
            UPDATE users
            SET balance = balance + $1
            WHERE user_id = $2
            """,
            file_tx["paid_price"],
            file_tx["owner_id"]
        )

        if updated == "UPDATE 0":
            logger.warning(
                "Owner %s tidak ditemukan",
                file_tx["owner_id"]
            )

    except Exception:
        logger.exception("failed update owner balance")

    try:
        await bot.send_message(
            file_tx["user_id"],
            "✅ <b>Pembayaran Berhasil!</b>\n\nFile kamu sudah aktif.",
            parse_mode="HTML"
        )
    except Exception:
        logger.exception("user notify failed")


    # =========================
    # SEND FILE OTOMATIS
    # =========================
    try:
        sent = await send_page(
            bot=bot,
            chat_id=file_tx["user_id"],
            user_id=file_tx["user_id"],
            code=file_tx["file_code"],
            page=1
        )
        if not sent:
            raise Exception("send_page returned False")

        logger.info(
            "File delivered | user=%s | code=%s",
            file_tx["user_id"],
            file_tx["file_code"]
        )

    except Exception:
        logger.exception(
            "Failed deliver file | user=%s | code=%s",
            file_tx["user_id"],
            file_tx["file_code"]
        )

        await bot.send_message(
            file_tx["user_id"],
            "⚠️ Pembayaran berhasil, tetapi file gagal dikirim otomatis.\nSilakan hubungi admin."
        )


    # =========================
    # ADMIN NOTIFY
    # =========================
    try:
        await bot.send_message(
            ADMIN_CHAT_ID,
            (
                "💰 <b>PAYMENT SUCCESS</b>\n\n"
                f"🧾 Invoice : <code>{invoice_id}</code>\n"
                f"👤 User : <code>{file_tx['user_id']}</code>\n"
                f"📂 File : <code>{file_tx['file_code']}</code>\n"
                f"💵 Amount : Rp {file_tx['paid_price']:,}"
            ).replace(",", "."),
            parse_mode="HTML"
        )

    except Exception:
        logger.exception("admin notify failed")


    logger.info(
        "Invoice %s processed successfully",
        invoice_id
    )

    return {
        "success": True
    }
