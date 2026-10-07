from fastapi import Request
import logging
import asyncio

from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from database import fetchrow, execute
from bot import bot
from handlers.page import send_page

logger = logging.getLogger(__name__)

BUY_CHANNEL_ID = -1004413314849
BOT_USERNAME = "botmarketRobot"


async def bayar_webhook(request: Request):
    data = await request.json()

    logger.info(f"🔥 WEBHOOK MASUK: {data}")

    invoice_id = data.get("invoice_id")
    status = str(data.get("status", "")).lower()

    if not invoice_id:
        return {"ok": False}

    if status not in ["paid", "success"]:
        return {"ok": True}

    # =========================
    # AMBIL TRANSAKSI
    # =========================
    tx = await fetchrow(
        """
        SELECT user_id, file_code, status
        FROM file_purchases
        WHERE payment_id=$1
        """,
        invoice_id
    )

    if not tx:
        return {"ok": True}

    if tx["status"] == "paid":
        logger.info(f"Duplicate webhook: {invoice_id}")
        return {"ok": True}

    # =========================
    # UPDATE STATUS
    # =========================
    await execute(
        """
        UPDATE file_purchases
        SET status='paid',
            paid_at=NOW()
        WHERE payment_id=$1
        AND status!='paid'
        """,
        invoice_id
    )

    # =========================
    # EDIT QR MESSAGE
    # =========================
    purchase = await fetchrow(
        """
        SELECT qr_chat_id, qr_message_id
        FROM file_purchases
        WHERE payment_id=$1
        """,
        invoice_id
    )

    if purchase and purchase["qr_message_id"]:
        try:
            await bot.edit_message_caption(
                chat_id=purchase["qr_chat_id"],
                message_id=purchase["qr_message_id"],
                caption=(
                    "✅ <b>PEMBAYARAN BERHASIL</b>\n\n"
                    f"🧾 Invoice: <code>{invoice_id}</code>\n"
                    "📦 File sudah dikirim ke kamu."
                ),
                parse_mode="HTML"
            )
        except Exception as e:
            logger.warning(f"Gagal edit QR: {e}")

    # =========================
    # KIRIM FILE
    # =========================
    sent = False

    for _ in range(3):
        try:
            await send_page(
                bot=bot,
                chat_id=tx["user_id"],
                user_id=tx["user_id"],
                code=tx["file_code"],
                page=1
            )
            sent = True
            break

        except Exception as e:
            logger.error(f"Retry send gagal: {e}")
            await asyncio.sleep(1)

    if sent:

        await bot.send_message(
            tx["user_id"],
            "✅ Pembayaran berhasil! File sudah dikirim."
        )

        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="🛒 Buy Now",
                        url=f"https://t.me/{BOT_USERNAME}"
                    )
                ]
            ]
        )

        try:
            await bot.send_message(
                chat_id=BUY_CHANNEL_ID,
                text=(
                    "💸 <b>FILE PAID SUCCESS</b>\n\n"
                    f"📦 <b>Code:</b> <code>{tx['file_code']}</code>\n"
                    f"👤 <b>User:</b> <code>{tx['user_id']}</code>"
                ),
                parse_mode="HTML",
                reply_markup=kb
            )
        except Exception as e:
            logger.warning(f"Gagal kirim notif channel: {e}")

        logger.info(f"FILE TERKIRIM: {invoice_id}")

    else:
        await bot.send_message(
            tx["user_id"],
            "⚠️ Pembayaran berhasil, tapi file gagal dikirim.\nHubungi admin."
        )

    return {"ok": True}
