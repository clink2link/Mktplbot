import json
import logging
import httpx
import re
import unicodedata

from config import BAYARGG_API_KEY

logger = logging.getLogger(__name__)

BASE_URL = "https://www.bayar.gg/api"


def clean_customer_name(name: str) -> str:
    if not name:
        return "Customer"

    # Ubah font Unicode menjadi huruf biasa
    name = unicodedata.normalize("NFKC", name)

    # Hapus emoji & karakter non-ASCII
    name = name.encode("ascii", "ignore").decode("ascii")

    # Sisakan huruf, angka, spasi, titik, koma, strip, underscore
    name = re.sub(r"[^A-Za-z0-9 .,_-]", "", name)

    # Rapikan spasi
    name = re.sub(r"\s+", " ", name).strip()

    # Maksimal 50 karakter
    return name[:50] or "Customer"


class BayarGG:

    @staticmethod
    async def get_payment_methods(self):
        """Return BayarGG payment methods and availability for this API key."""
        headers = {
            "X-API-Key": BAYARGG_API_KEY,
            "Content-Type": "application/json",
        }
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(
                f"{BASE_URL}/get-payment-methods.php",
                headers=headers,
            )
        logger.info(f"PAYMENT METHODS STATUS: {response.status_code}")
        logger.info(f"PAYMENT METHODS BODY: {response.text}")
        response.raise_for_status()
        raw = response.json()
        if not raw.get("success"):
            raise Exception(raw.get("error") or "Gagal mengambil metode pembayaran BayarGG")
        data = raw.get("data") or {}
        methods = data.get("payment_methods") or []
        return {
            "methods": methods,
            "user_status": data.get("user_status") or {},
            "feature_status": data.get("feature_status") or {},
        }

    async def choose_payment_method(self, preferred=None):
        """Choose the first usable QR/payment method exposed by BayarGG."""
        preferred = preferred or [
            "qris",
            "qris_bayar_gg",
            "gopay_qris",
            "qris_livin",
            "qris_user",
            "ovo",
        ]
        info = await self.get_payment_methods()
        methods = {str(m.get("id")): m for m in info["methods"] if m.get("id")}
        for method_id in preferred:
            item = methods.get(method_id)
            if item and item.get("available") is True and item.get("enabled", True) is not False:
                logger.info(f"BAYARGG SELECTED PAYMENT METHOD: {method_id}")
                return method_id
        raise Exception("Tidak ada metode pembayaran BayarGG yang tersedia untuk akun ini.")

    async def create_payment(
        amount: int,
        description: str,
        payment_url: str = "https://www.bayar.gg/pay",
        callback_url: str | None = None,
        redirect_url: str | None = None,
        customer_name: str | None = None,
        customer_phone: str | None = None,
        payment_method: str | None = None,
    ):

        headers = {
            "X-API-Key": BAYARGG_API_KEY,
            "Content-Type": "application/json"
        }

        logger.info(
            f"API KEY LENGTH: {len(BAYARGG_API_KEY)}"
        )

        logger.info(
            f"HEADERS: {headers.keys()}"
        )

        if not payment_method:
            payment_method = await self.choose_payment_method()

        payload = {
            "amount": amount,
            "description": description,
            "payment_url": payment_url,
            "payment_method": payment_method,
        }

        if callback_url:
            payload["callback_url"] = callback_url

        if redirect_url:
            payload["redirect_url"] = redirect_url

        # Selalu bersihkan customer_name
        original_name = customer_name or "Customer"
        customer_name = clean_customer_name(original_name)

        if original_name != customer_name:
            logger.warning(
                "Customer name sanitized: '%s' -> '%s'",
                original_name,
                customer_name,
            )

        payload["customer_name"] = customer_name

        if customer_phone:
            payload["customer_phone"] = customer_phone

        try:
            logger.info("🚀 CREATE PAYMENT")
            logger.info(json.dumps(payload, indent=2, ensure_ascii=False))

            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.post(
                    f"{BASE_URL}/create-payment.php",
                    headers=headers,
                    json=payload
                )

            logger.info(f"STATUS: {response.status_code}")
            logger.info(f"BODY: {response.text}")

            if response.status_code >= 400:
                logger.error(
                    "BAYARGG ERROR JSON: %s",
                    response.text
                )
                return None

            raw = response.json()

            if not raw.get("success"):
                raise Exception(
                    raw.get("error")
                    or raw.get("message")
                    or str(raw)
                )

            data = raw.get("data", raw)

            # =========================
            # NORMALISASI DATA (PENTING)
            # =========================
            invoice_id = (
                data.get("invoice_id")
                or data.get("id")
                or data.get("invoice")
            )

            qr_string = (
                data.get("qris_string")
                or data.get("qris")
                or data.get("qr_string")
                or data.get("qr")
            )

            final_amount = (
                data.get("final_amount")
                or data.get("amount")
                or amount
            )

            if not invoice_id:
                raise Exception("Invoice ID tidak ditemukan")

            if not qr_string:
                raise Exception("QR string tidak ditemukan")

            return {
                "invoice_id": invoice_id,
                "qris_string": qr_string,
                "payment_url": data.get("payment_url"),
                "expires_at": data.get("expires_at"),
                "final_amount": final_amount,
                "status": data.get("status"),
            }

        except Exception as e:
            logger.exception(f"❌ CREATE PAYMENT ERROR: {e}")
            return None

    @staticmethod
    async def check_payment(invoice_id: str):

        headers = {
            "X-API-Key": BAYARGG_API_KEY
        }

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.get(
                    f"{BASE_URL}/check-payment.php",
                    headers=headers,
                    params={"invoice": invoice_id}
                )

            logger.info(f"CHECK STATUS: {response.status_code}")
            logger.info(f"CHECK BODY: {response.text}")

            response.raise_for_status()

            raw = response.json()

            if not raw.get("success"):
                raise Exception(
                    raw.get("error")
                    or raw.get("message")
                    or str(raw)
                )

            data = raw.get("data", raw)

            status = str(
                data.get("status")
                or data.get("payment_status")
                or ""
            ).lower()

            return {
                "invoice_id": invoice_id,
                "status": status,
                "raw": data
            }

        except Exception as e:
            logger.exception(f"❌ CHECK PAYMENT ERROR: {e}")
            return None
