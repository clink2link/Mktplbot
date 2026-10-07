# utils/cashi.py
import logging
import uuid
from datetime import datetime, timezone
import httpx
from config import (
    CASHI_API_KEY,
    CASHI_BASE_URL,
    CASHI_PAYMENT_CHANNEL,
    CASHI_MIN_AMOUNT,
    CASHI_MAX_AMOUNT,
)
logger = logging.getLogger(__name__)
BASE_URL = CASHI_BASE_URL.rstrip("/")
class Cashi:
    # ==================================================
    # PARSE DATETIME
    # ==================================================
    @staticmethod
    def _parse_datetime(value):
        """Normalize provider timestamps for asyncpg/PostgreSQL.

        Cashi may return ISO-8601 values, values with a space separator,
        or a zero-like value.  PostgreSQL ``timestamptz`` parameters must
        receive a real ``datetime`` object, not the original JSON string.
        Naive provider timestamps are treated as UTC.
        """
        if value is None or value == "":
            return None

        if isinstance(value, datetime):
            if value.tzinfo is None:
                return value.replace(tzinfo=timezone.utc)
            return value

        if not isinstance(value, str):
            logger.warning(
                "CASHI INVALID DATETIME TYPE: %s",
                type(value),
            )
            return None

        value = value.strip()
        if not value or value == "0":
            return None

        try:
            # Python's fromisoformat handles both 'T' and space separators.
            normalized = value.replace("Z", "+00:00")
            parsed = datetime.fromisoformat(normalized)

            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)

            return parsed
        except (ValueError, TypeError):
            logger.warning(
                "CASHI INVALID DATETIME: %s",
                value,
            )
            return None
    # ==================================================
    # HEADERS
    # ==================================================
    @staticmethod
    def _headers():
        return {
            "x-api-key": CASHI_API_KEY,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
    # ==================================================
    # CREATE PAYMENT
    # ==================================================
    @staticmethod
    async def create_payment(
        amount: int,
        description: str,
        customer_name: str = "Customer",
    ):
        try:
            amount = int(amount)
        except (TypeError, ValueError):
            logger.error(
                "CASHI INVALID AMOUNT: %r",
                amount,
            )
            return None
        # Cashi minimum amount according to documentation
        if amount < CASHI_MIN_AMOUNT:
            logger.error(
                "CASHI AMOUNT BELOW MINIMUM: %s",
                amount,
            )
            return None
        # Cashi maximum amount according to documentation
        if amount > CASHI_MAX_AMOUNT:
            logger.error(
                "CASHI AMOUNT ABOVE MAXIMUM: %s",
                amount,
            )
            return None
        # Unique order ID
        order_id = (
            f"FILE-{uuid.uuid4().hex[:16]}"
        )
        body = {
            "amount": amount,
            "order_id": order_id,
            "kode_channel": CASHI_PAYMENT_CHANNEL,
        }
        logger.info(
            "CASHI CREATE | order_id=%s | amount=%s",
            order_id,
            amount,
        )
        try:
            async with httpx.AsyncClient(
                timeout=30
            ) as client:
                response = await client.post(
                    f"{BASE_URL}/api/create-order",
                    json=body,
                    headers=Cashi._headers(),
                )
            logger.info(
                "CASHI CREATE HTTP %s | %s",
                response.status_code,
                response.text,
            )
            response.raise_for_status()
            data = response.json()
            if not isinstance(data, dict):
                logger.error(
                    "CASHI INVALID RESPONSE: %r",
                    data,
                )
                return None
            if not data.get("success"):
                logger.error(
                    "CASHI CREATE FAILED: %s",
                    data,
                )
                return None
            # ==================================================
            # ORDER ID
            # ==================================================
            returned_order_id = (
                data.get("orderId")
                or data.get("order_id")
                or order_id
            )
            if not returned_order_id:
                logger.error(
                    "CASHI ORDER ID KOSONG | data=%s",
                    data,
                )
                return None
            returned_order_id = str(
                returned_order_id
            )
            # ==================================================
            # QR
            # ==================================================
            qr_url = data.get("qrUrl")
            if not qr_url:
                logger.error(
                    "CASHI QR URL KOSONG | "
                    "order_id=%s | data=%s",
                    returned_order_id,
                    data,
                )
                return None
            # ==================================================
            # AMOUNT
            # ==================================================
            try:
                response_amount = int(
                    data.get(
                        "amount",
                        amount,
                    )
                    or amount
                )
            except (
                TypeError,
                ValueError,
            ):
                response_amount = amount
            # ==================================================
            # FEE
            # ==================================================
            try:
                fee = float(
                    data.get("fee", 0) or 0
                )
            except (
                TypeError,
                ValueError,
            ):
                fee = 0
            # ==================================================
            # EXPIRES
            # ==================================================
            expires_at = Cashi._parse_datetime(
                data.get("expires_at")
            )
            # ==================================================
            # STATUS
            # ==================================================
            status = str(
                data.get(
                    "status",
                    "pending",
                )
                or "pending"
            ).lower()
            # ==================================================
            # RETURN NORMALIZED RESPONSE
            # ==================================================
            return {
                # Compatible with existing payment handler
                "payment_id": returned_order_id,
                "invoice_id": returned_order_id,
                "order_id": returned_order_id,
                "reference": returned_order_id,
                "provider_payment_id":
                    returned_order_id,
                "status": status,
                "amount": response_amount,
                "fee": fee,
                "additional_fee": 0,
                "total_amount": response_amount,
                "currency": "IDR",
                # Cashi gives a QR URL.
                # It may be a data:image/png;base64,... URL.
                "qr_string": qr_url,
                "qr_image": qr_url,
                "payment_url":
                    data.get("checkout_url"),
                "checkout_url":
                    data.get("checkout_url"),
                "expires_at":
                    expires_at,
                "provider": data.get(
                    "provider",
                    "CASHI",
                ),
                "raw": data,
            }
        except httpx.HTTPStatusError as e:
            logger.error(
                "CASHI CREATE HTTP ERROR | "
                "status=%s | response=%s",
                (
                    e.response.status_code
                    if e.response
                    else None
                ),
                (
                    e.response.text
                    if e.response
                    else ""
                ),
            )
            return None
        except httpx.RequestError as e:
            logger.error(
                "CASHI CREATE REQUEST ERROR: %s",
                e,
            )
            return None
        except Exception:
            logger.exception(
                "CASHI CREATE PAYMENT ERROR"
            )
            return None
    # ==================================================
    # CHECK PAYMENT
    # ==================================================
    @staticmethod
    async def check_payment(
        payment_id: str,
    ):
        if not payment_id:
            logger.error(
                "CASHI CHECK: payment_id kosong"
            )
            return None
        payment_id = str(
            payment_id
        ).strip()
        try:
            async with httpx.AsyncClient(
                timeout=30
            ) as client:
                response = await client.get(
                    f"{BASE_URL}/api/check-status/"
                    f"{payment_id}",
                    headers=Cashi._headers(),
                )
            logger.info(
                "CASHI CHECK HTTP %s | %s",
                response.status_code,
                response.text,
            )
            response.raise_for_status()
            data = response.json()
            if not isinstance(data, dict):
                logger.error(
                    "CASHI CHECK INVALID RESPONSE: %r",
                    data,
                )
                return None
            if not data.get("success"):
                logger.warning(
                    "CASHI CHECK FAILED: %s",
                    data,
                )
                return None
            status = str(
                data.get(
                    "status",
                    "",
                )
                or ""
            ).lower()
            try:
                amount = int(
                    data.get("amount")
                    or 0
                )
            except (
                TypeError,
                ValueError,
            ):
                amount = 0
            return {
                "payment_id": str(
                    data.get(
                        "order_id",
                        payment_id,
                    )
                ),
                "order_id": str(
                    data.get(
                        "order_id",
                        payment_id,
                    )
                ),
                "status": status,
                "amount": amount,
                "currency": "IDR",
                "settle": (
                    status == "settled"
                ),
                "is_cancellable": (
                    status
                    not in {
                        "settled",
                        "paid",
                        "success",
                        "completed",
                    }
                ),
                "expires_at": None,
                "qr_data": None,
                "raw": data,
            }
        except httpx.HTTPStatusError as e:
            logger.error(
                "CASHI CHECK HTTP ERROR | "
                "status=%s | response=%s",
                (
                    e.response.status_code
                    if e.response
                    else None
                ),
                (
                    e.response.text
                    if e.response
                    else ""
                ),
            )
            return None
        except httpx.RequestError as e:
            logger.error(
                "CASHI CHECK REQUEST ERROR: %s",
                e,
            )
            return None
        except Exception:
            logger.exception(
                "CASHI CHECK PAYMENT ERROR"
            )
            return None
    # ==================================================
    # CANCEL PAYMENT
    # ==================================================
    #
    # Dokumentasi Cashi yang diberikan belum menyediakan
    # endpoint cancel order.
    #
    # Karena itu JANGAN melakukan request palsu ke Cashi.
    # Pembatalan transaksi cukup dilakukan di database
    # oleh handler:
    #
    #     status='cancel'
    #
    # ==================================================
    @staticmethod
    async def cancel_payment(
        payment_id: str,
    ):
        if not payment_id:
            logger.error(
                "CASHI CANCEL: payment_id kosong"
            )
            return None
        logger.info(
            "CASHI CANCEL LOCAL ONLY | "
            "order_id=%s",
            payment_id,
        )
        return {
            "success": True,
            "order_id": str(payment_id),
            "status": "cancel",
            "provider": "CASHI",
            "local_only": True,
        }
