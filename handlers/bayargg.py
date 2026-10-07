import hmac
import hashlib
import logging
import asyncio

from datetime import datetime, timedelta

from fastapi import APIRouter, Request

from bot import bot
from config import BAYARGG_WEBHOOK_SECRET
from config_vip import VIP_PACKAGES
from database import get_pool
from utils.redis_client import redis_client
from handlers.page import send_page

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/bayargg", tags=["BayarGG"])


def secure_compare(a: str, b: str):
    return hmac.compare_digest(a or "", b or "")


@router.post("/webhook")
async def bayargg_webhook(request: Request):

    signature = request.headers.get("X-Webhook-Signature", "")
    timestamp = request.headers.get("X-Webhook-Timestamp", "")

    try:
        data = await request.json()
    except Exception:
        logger.exception("INVALID JSON")
        return {"success": False}

    # ==========================
    # VERIFY SIGNATURE
    # ==========================
    signature_data = (
        f"{data['invoice_id']}|"
        f"{data['status']}|"
        f"{data['final_amount']}|"
        f"{timestamp}"
    )

    expected = hmac.new(
        BAYARGG_WEBHOOK_SECRET.encode(),
        signature_data.encode(),
        hashlib.sha256
    ).hexdigest()

    if not secure_compare(signature, expected):
        logger.warning("INVALID SIGNATURE")
        return {"success": False}

    invoice_id = data.get("invoice_id")
    status = (data.get("status") or "").lower()

    if not invoice_id:
        return {"success": False}

    if status != "paid":
        return {"success": True}

    pool = await get_pool()

    # ==========================
    # LOCK (ANTI DOUBLE WEBHOOK)
    # ==========================
    lock_key = f"payment_processing:{invoice_id}"

    if await redis_client.get(lock_key):
        return {"success": True}

    await redis_client.set(lock_key, "1", ex=300)

    try:

        # =================================
        # FILE PAYMENT
        # =================================

        purchase = await pool.fetchrow(
            """
            SELECT *
            FROM file_purchases
            WHERE payment_id=$1
            """,
            invoice_id
        )


        if purchase:

            if purchase["status"] == "paid":
                return {"success": True}


            file = await pool.fetchrow(
                """
                SELECT *
                FROM files
                WHERE code=$1
                """,
                purchase["file_code"]
            )


            if not file:
                return {"success": False}



            # UPDATE STATUS PEMBAYARAN
            claimed = await pool.fetchrow(
                """UPDATE file_purchases SET status='paid', paid_at=COALESCE(paid_at,NOW())
                   WHERE payment_id=$1 AND status='pending' RETURNING id""", invoice_id
            )
            if not claimed:
                return {"success": True}

            # Each successful purchase advances the seller's 3-step marketplace progress.
            await pool.execute(
                "UPDATE files SET buy_count=COALESCE(buy_count,0)+1, sold=COALESCE(sold,0)+1, free_progress=LEAST(3,COALESCE(free_progress,0)+1) WHERE code=$1",
                purchase["file_code"]
            )
            await pool.execute(
                """UPDATE free_code_progress
                   SET purchase_count=LEAST(3,COALESCE(purchase_count,0)+1),
                       completed=(LEAST(3,COALESCE(purchase_count,0)+1)>=3),
                       completed_at=CASE WHEN LEAST(3,COALESCE(purchase_count,0)+1)>=3 THEN COALESCE(completed_at,NOW()) ELSE completed_at END
                   WHERE code=$1 AND completed=FALSE""",
                purchase["file_code"]
            )



            # HAPUS QR PAYMENT
            try:

                if (
                    purchase["qr_chat_id"]
                    and purchase["qr_message_id"]
                ):

                    await bot.delete_message(
                        chat_id=purchase["qr_chat_id"],
                        message_id=purchase["qr_message_id"]
                    )

            except Exception:
                pass



            # KIRIM FILE
            success = False


            for _ in range(3):

                try:

                    await send_page(
                        bot=bot,
                        chat_id=purchase["user_id"],
                        user_id=purchase["user_id"],
                        code=purchase["file_code"],
                        page=1
                    )

                    success = True
                    break


                except Exception as e:

                    logger.warning(
                        f"SEND FILE RETRY ERROR: {e}"
                    )

                    await asyncio.sleep(1)



            if success:

                await bot.send_message(
                    purchase["user_id"],
                    "✅ Pembayaran berhasil!\n\n📦 File sudah dikirim."
                )

            else:

                await bot.send_message(
                    purchase["user_id"],
                    "⚠️ Pembayaran berhasil, tapi file gagal dikirim. Hubungi admin."
                )


            return {
                "success": True
            }

        # =================================
        # VIP / VVIP PAYMENT
        # =================================

        trx = await pool.fetchrow(
            "SELECT * FROM payments WHERE invoice_id=$1",
            invoice_id
        )

        if not trx:
            return {"success": False}

        # ✅ ANTI DOUBLE
        if trx["status"] == "paid":
            return {"success": True}

        paket = VIP_PACKAGES.get(trx["code"])
        if not paket:
            return {"success": False}

        paket_type = paket.get("type", "vip")

        now = datetime.utcnow()

        user = await pool.fetchrow(
            """
            SELECT 
                vip_expired,
                vvip_expired
            FROM users
            WHERE user_id=$1
            """,
            trx["user_id"]
        )

        # =========================
        # HITUNG EXPIRED
        # =========================
        if paket_type == "vvip":
            base_time = (
                user["vvip_expired"]
                if user and user["vvip_expired"] and user["vvip_expired"] > now
                else now
            )
        else:
            base_time = (
                user["vip_expired"]
                if user and user["vip_expired"] and user["vip_expired"] > now
                else now
            )

        expired = base_time + timedelta(days=paket["days"])

        # =========================
        # UPDATE DB
        # =========================
        async with pool.acquire() as conn:
            async with conn.transaction():

                await conn.execute(
                    "UPDATE payments SET status='paid' WHERE invoice_id=$1",
                    invoice_id
                )

                if paket_type == "vvip":
                    await conn.execute(
                        """
                        UPDATE users
                        SET is_vvip=TRUE,
                            is_vip=TRUE,
                            vvip_expired=$1,
                            vip=TRUE,
                            vip_expired=$1
                        WHERE user_id=$2
                        """,
                        expired,
                        trx["user_id"]
                    )
                else:
                    await conn.execute(
                        """
                        UPDATE users
                        SET vip=TRUE,
                            is_vip=TRUE,
                            vip_expired=$1
                        WHERE user_id=$2
                        """,
                        expired,
                        trx["user_id"]
                    )

        # =========================
        # 🔥 SYNC REDIS (WAJIB)
        # =========================
        await redis_client.delete(
            f"user:{trx['user_id']}"
        )

        # optional: clear cache lain
        await redis_client.delete(f"user_cache:{trx['user_id']}")

        # =========================
        # NOTIF USER
        # =========================
        if paket_type == "vvip":
            await bot.send_message(
                trx["user_id"],
                (
                    "💎 <b>VVIP AKTIF</b>\n\n"
                    "✅ Upload file\n"
                    "✅ Akses premium\n"
                    f"⏳ Sampai {expired:%d-%m-%Y %H:%M}"
                ),
                parse_mode="HTML"
            )
        else:
            await bot.send_message(
                trx["user_id"],
                (
                    "💠 <b>VIP AKTIF</b>\n\n"
                    "✅ Akses premium\n"
                    f"⏳ Sampai {expired:%d-%m-%Y %H:%M}"
                ),
                parse_mode="HTML"
            )

        return {"success": True}

    except Exception as e:
        logger.exception(f"WEBHOOK ERROR: {e}")
        return {"success": False}
