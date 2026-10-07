"""CASHI webhook integration.

Security:
- Verifies X-GATEWAY-SIGNATURE against the raw request body.
- Never trusts a client supplied status/order without a matching local order.
- Uses finish_payment() which atomically changes a pending purchase to paid,
  preventing duplicate webhook deliveries from paying a seller twice.
"""

import hashlib
import hmac
import json
import logging
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import PlainTextResponse

from config import CASHI_SECRET_KEY
from database import fetchrow
from handlers.pay import finish_payment
from bot import bot

logger = logging.getLogger(__name__)

router = APIRouter(tags=["CASHI"])


def _signature_valid(payload: bytes, signature: str) -> bool:
    secret = str(CASHI_SECRET_KEY or "").strip()
    signature = str(signature or "").strip()

    if not secret or not signature:
        return False

    expected = hmac.new(
        secret.encode("utf-8"),
        payload,
        hashlib.sha256,
    ).hexdigest()

    # Accept the two common representations of the same HMAC:
    #   <hex>
    #   sha256=<hex>
    # Cashi documentation for this integration uses the raw hex digest.
    supplied = signature.lower()
    if supplied.startswith("sha256="):
        supplied = supplied[7:].strip()

    return hmac.compare_digest(expected, supplied)


class _WebhookMessage:
    """Small aiogram-compatible message facade used by finish_payment()."""

    def __init__(self, chat_id: int):
        self.chat = type("Chat", (), {"id": int(chat_id)})()
        self.from_user = None

    async def answer(self, text: str, **kwargs: Any):
        return await bot.send_message(
            chat_id=int(self.chat.id),
            text=text,
            **kwargs,
        )


async def _handle(request: Request):
    payload = await request.body()
    signature = request.headers.get("x-gateway-signature", "")

    # Signature verification MUST happen before JSON parsing/processing.
    if not signature:
        logger.warning("CASHI WEBHOOK REJECTED: missing signature")
        return PlainTextResponse("Missing signature", status_code=401)

    if not _signature_valid(payload, signature):
        logger.warning("CASHI WEBHOOK REJECTED: invalid signature")
        return PlainTextResponse("Invalid signature", status_code=401)

    try:
        data = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        logger.warning("CASHI WEBHOOK REJECTED: invalid JSON")
        return PlainTextResponse("Invalid JSON", status_code=400)

    if not isinstance(data, dict):
        return PlainTextResponse("Invalid payload", status_code=400)

    event = str(data.get("event") or "").strip().upper()
    event_data = data.get("data")

    if not isinstance(event_data, dict):
        event_data = data

    order_id = str(
        event_data.get("order_id")
        or data.get("order_id")
        or data.get("orderId")
        or ""
    ).strip()

    status = str(
        event_data.get("status")
        or data.get("status")
        or ""
    ).strip().upper()

    # Cashi test connection described in their docs.
    if order_id.startswith("TEST-"):
        logger.info("CASHI webhook test connection accepted")
        return PlainTextResponse("Test connection successful", status_code=200)

    # We only fulfill settled payments. Other legitimate events are acknowledged
    # without changing the local purchase.
    if event and event != "PAYMENT_SETTLED":
        logger.info(
            "CASHI webhook ignored event=%s order=%s",
            event,
            order_id,
        )
        return PlainTextResponse("OK", status_code=200)

    if status != "SETTLED":
        logger.info(
            "CASHI webhook ignored status=%s order=%s",
            status,
            order_id,
        )
        return PlainTextResponse("OK", status_code=200)

    if not order_id:
        logger.warning("CASHI webhook settled without order_id")
        return PlainTextResponse("Missing order_id", status_code=400)

    purchase = await fetchrow(
        """
        SELECT * FROM file_purchases WHERE payment_id=$1 LIMIT 1
        """, order_id)

    # Point purchase uses the same Cashi webhook. It is settled atomically
    # and independently from file_purchases.
    if not purchase:
        point_order = await fetchrow("SELECT * FROM point_orders WHERE order_id=$1 LIMIT 1", order_id)
        if point_order:
            provider_amount_raw = event_data.get("amount")
            if provider_amount_raw is not None:
                try:
                    provider_amount = int(float(provider_amount_raw))
                except (TypeError, ValueError):
                    return PlainTextResponse("Invalid amount", status_code=400)
                if provider_amount < int(point_order.get("amount") or 0):
                    logger.error("CASHI POINT AMOUNT MISMATCH order=%s local=%s provider=%s",order_id,point_order.get("amount"),provider_amount)
                    return PlainTextResponse("Amount mismatch", status_code=400)
            try:
                from handlers.points import settle
                ok = await settle(order_id)
                if ok:
                    try:
                        refreshed = await fetchrow("SELECT * FROM point_orders WHERE order_id=$1 LIMIT 1", order_id)
                        if refreshed and str(refreshed.get("status") or "").lower() == "paid":
                            from database import get_pool
                            ppool = await get_pool()
                            lang = await __import__("utils.user_lang", fromlist=["get_user_language"]).get_user_language(refreshed["user_id"])
                            pts = await ppool.fetchval("SELECT points FROM users WHERE user_id=$1", refreshed["user_id"])
                            text = {"id":f"🎉 <b>Pembelian poin berhasil!</b>\n\n⭐ +{refreshed['points']} poin\n⭐ Total: <b>{pts}</b>","en":f"🎉 <b>Point purchase successful!</b>\n\n⭐ +{refreshed['points']} points\n⭐ Total: <b>{pts}</b>","zh":f"🎉 <b>积分购买成功！</b>\n\n⭐ +{refreshed['points']} 积分\n⭐ 总计：<b>{pts}</b>"}[lang]
                            await ppool.execute("INSERT INTO user_notifications(user_id,type,title,message) VALUES($1,'payment','Points Purchase',$2)", refreshed["user_id"], text)
                            await bot.send_message(refreshed["user_id"], text, parse_mode="HTML")
                    except Exception:
                        logger.exception("CASHI POINT USER NOTIFY ERROR order=%s", order_id)
                return PlainTextResponse("OK" if ok else "Processing failed", status_code=200 if ok else 500)
            except Exception:
                logger.exception("CASHI POINT SETTLEMENT ERROR order=%s", order_id)
                return PlainTextResponse("Processing failed", status_code=500)

    if not purchase:
        logger.warning(
            "CASHI webhook order not found locally: %s",
            order_id,
        )
        # Acknowledge so Cashi does not retry forever for an order that does not
        # belong to this application.
        return PlainTextResponse("OK", status_code=200)

    current_status = str(purchase.get("status") or "").strip().lower()

    if current_status == "paid":
        logger.info(
            "CASHI duplicate webhook ignored: %s",
            order_id,
        )
        return PlainTextResponse("OK", status_code=200)

    if current_status != "pending":
        logger.info(
            "CASHI webhook ignored local status=%s order=%s",
            current_status,
            order_id,
        )
        return PlainTextResponse("OK", status_code=200)

    # The provider may report the settled amount including a gateway fee
    # (e.g. check-status can return an amount different from the original
    # purchase price). Never accept an amount lower than our local order.
    local_amount = int(purchase.get("paid_price") or 0)
    provider_amount_raw = event_data.get("amount")

    if provider_amount_raw is not None:
        try:
            provider_amount = int(float(provider_amount_raw))
        except (TypeError, ValueError):
            logger.warning(
                "CASHI invalid webhook amount order=%s amount=%r",
                order_id,
                provider_amount_raw,
            )
            return PlainTextResponse("Invalid amount", status_code=400)

        if local_amount > 0 and provider_amount < local_amount:
            logger.error(
                "CASHI AMOUNT MISMATCH order=%s local=%s provider=%s",
                order_id,
                local_amount,
                provider_amount,
            )
            return PlainTextResponse("Amount mismatch", status_code=400)

    file_code = str(
        purchase.get("file_code")
        or purchase.get("code")
        or ""
    ).strip()

    if not file_code:
        logger.error(
            "CASHI purchase has no file code order=%s",
            order_id,
        )
        return PlainTextResponse("Invalid local order", status_code=500)

    file = await fetchrow(
        """
        SELECT *
        FROM files
        WHERE code=$1
        LIMIT 1
        """,
        file_code,
    )

    if not file:
        logger.error(
            "CASHI file not found order=%s code=%s",
            order_id,
            file_code,
        )
        return PlainTextResponse("File not found", status_code=500)

    # finish_payment performs the atomic pending -> paid transition and all
    # existing delivery/seller-credit logic.
    message = _WebhookMessage(int(purchase["user_id"]))
    success = await finish_payment(
        bot=bot,
        purchase=purchase,
        file=file,
        invoice=order_id,
        message=message,
    )

    if success:
        logger.info(
            "CASHI PAYMENT SETTLED | order=%s | user=%s | code=%s",
            order_id,
            purchase["user_id"],
            file_code,
        )
    else:
        # If another worker/webhook won the atomic update, still acknowledge.
        latest = await fetchrow(
            """
            SELECT status
            FROM file_purchases
            WHERE payment_id=$1
            LIMIT 1
            """,
            order_id,
        )
        if latest and str(latest.get("status") or "").lower() == "paid":
            logger.info(
                "CASHI webhook already finalized by another worker: %s",
                order_id,
            )
        else:
            logger.error(
                "CASHI settlement processing failed: %s",
                order_id,
            )
            return PlainTextResponse("Processing failed", status_code=500)

    return PlainTextResponse("OK", status_code=200)


@router.get("/api/webhook/cashi")
async def cashi_webhook_health():
    # Cashi/dashboard connectivity checks may use GET.  Never process a
    # payment on GET; simply report that the endpoint is reachable.
    return PlainTextResponse("OK", status_code=200)


@router.post("/api/webhook/cashi")
async def cashi_webhook(request: Request):
    return await _handle(request)


# Optional alias for deployments that prefer /webhook/cashi.
@router.get("/webhook/cashi")
async def cashi_webhook_alias_health():
    return PlainTextResponse("OK", status_code=200)


@router.post("/webhook/cashi")
async def cashi_webhook_alias(request: Request):
    return await _handle(request)
