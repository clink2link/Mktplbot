import logging

from aiogram import Router

from database import get_pool
from bot import bot  # pastikan instance bot kamu bisa di-import
from page import send_page  # fungsi dari page.py yang kita buat

router = Router()

ADMIN_CHAT_ID = -1001234567890  # ganti sesuai admin kamu


# =========================
# PAYMENT SUCCESS HANDLER
# =========================
async def process_payment_success(invoice_id: str):
    pool = await get_pool()

    # =========================
    # AMBIL TRANSAKSI
    # =========================
    tx = await pool.fetchrow(
        """
        SELECT *
        FROM file_purchases
        WHERE payment_id=$1
        """,
        invoice_id
    )

    if not tx:
        logging.warning("Invoice not found: %s", invoice_id)
        return

    # =========================
    # CEK SUDAH PAID?
    # =========================
    if tx["status"] == "paid":
        return

    # =========================
    # UPDATE STATUS
    # =========================
    await pool.execute(
        """
        UPDATE file_purchases
        SET status='paid'
        WHERE payment_id=$1
        """,
        invoice_id
    )

    user_id = tx["user_id"]
    file_code = tx["file_code"]

    # =========================
    # NOTIF USER
    # =========================
    try:
        await bot.send_message(
            user_id,
            "✅ <b>Pembayaran Berhasil!</b>\n\nFile kamu sedang dikirim...",
            parse_mode="HTML"
        )
    except Exception:
        logging.exception("user notify failed")

    # =========================
    # AUTO SEND FILE (PAGE 1)
    # =========================
    try:
        await send_page(
            bot=bot,
            chat_id=user_id,
            user_id=user_id,
            code=file_code,
            page=1
        )
    except Exception as e:
        logging.exception("send file failed: %s", e)

        try:
            await bot.send_message(
                user_id,
                "❌ Gagal mengirim file, hubungi admin."
            )
        except:
            pass

    # =========================
    # NOTIF ADMIN
    # =========================
    try:
        await bot.send_message(
            ADMIN_CHAT_ID,
            (
                "💰 <b>PAYMENT SUCCESS</b>\n\n"
                f"🧾 Invoice : <code>{invoice_id}</code>\n"
                f"👤 User : <code>{user_id}</code>\n"
                f"📂 File : <code>{file_code}</code>\n"
                f"💵 Amount : Rp {tx['paid_price']:,}"
            ).replace(",", "."),
            parse_mode="HTML"
        )
    except Exception:
        logging.exception("admin notify failed")

    logging.info("Invoice %s processed successfully", invoice_id)
