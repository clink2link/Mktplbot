from aiogram import Router, F
from aiogram.types import CallbackQuery
import logging

from database import fetchrow, execute
from utils.redis_client import safe_delete

logger = logging.getLogger(__name__)

router = Router()


@router.callback_query(F.data.startswith("cancel:"))
async def cancel_payment(call: CallbackQuery):
    invoice_id = call.data.split(":")[1]

    logger.info(
        "Cancel payment | invoice=%s | user=%s",
        invoice_id,
        call.from_user.id
    )

    tx = await fetchrow(
        """
        SELECT status
        FROM file_purchases
        WHERE payment_id=$1
        """,
        invoice_id
    )

    if not tx:
        logger.warning(
            "Invoice not found | invoice=%s",
            invoice_id
        )

        return await call.answer(
            "Invoice tidak ditemukan",
            show_alert=True
        )

    if tx["status"] == "paid":
        logger.info(
            "Cancel rejected, already paid | invoice=%s",
            invoice_id
        )

        return await call.answer(
            "Invoice sudah dibayar",
            show_alert=True
        )

    await execute(
        """
        UPDATE file_purchases
        SET status='expired'
        WHERE payment_id=$1
        """,
        invoice_id
    )

    logger.info(
        "Invoice expired | invoice=%s",
        invoice_id
    )

    try:
        await safe_delete(f"invoice:{invoice_id}")
    except Exception:
        logger.exception(
            "Failed delete redis invoice | invoice=%s",
            invoice_id
        )

    try:
        await call.message.delete()
    except Exception:
        logger.exception(
            "Failed delete QR message | invoice=%s",
            invoice_id
        )

    await call.message.answer(
        "❌ Invoice berhasil dibatalkan."
    )

    await call.answer(
        "Invoice dibatalkan",
        show_alert=True
    )
