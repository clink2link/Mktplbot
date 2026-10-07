import asyncio
import base64
import html
import json
import logging
import os
import secrets
from datetime import datetime, timezone
from typing import Any
import aiohttp
from aiogram import Router, F
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    BufferedInputFile,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    Message,
)
from database import fetchrow, fetch, execute
from utils.media_sender import safe_copy_from_storage
from utils.redis_client import safe_set, safe_get
from utils.cashi import Cashi
from utils.bayargg import BayarGG
from utils.user_lang import get_user_language
from utils.payment_methods import payment_methods_enabled
from config import (
    STORAGE_CHANNEL_ID,
    NOTIF_CHANNEL_ID,
    ADMIN_IDS,
    MANUAL_QR_FILE_ID,
    CASHI_API_KEY,
)
logger = logging.getLogger(__name__)
router = Router()
# ============================================================
# CONFIG
# ============================================================
PER_PAGE = 10
MEDIA_TTL = 3600
VERIFY_REQUEST_TTL = 300
CALLBACK_TOKEN_TTL = 900
CHECK_LOCK = 30
CASHI_BASE_URL = os.getenv(
    "CASHI_BASE_URL",
    "https://cashi.id",
).strip().rstrip("/")
CASHI_CREATE_URL = (
    f"{CASHI_BASE_URL}/api/create-order"
)
PAYMENT_MODE = os.getenv(
    "PAYMENT_MODE",
    "both",
).strip().lower()
if PAYMENT_MODE not in {
    "both",
    "cashi",
    "manual",
}:
    PAYMENT_MODE = "both"
CASHI_ENABLED = bool(
    str(CASHI_API_KEY or "").strip()
)
AUTO_PAYMENT_ENABLED = (
    PAYMENT_MODE in {
        "both",
        "cashi",
    }
    and CASHI_ENABLED
)
MANUAL_QR_FILE_ID = str(
    MANUAL_QR_FILE_ID or "AgACAgUAAxkBAAEBrzVqoaVOc_VaY7dIOhqREk9rsUjvWQACIxprG4uvCVUFiwlIIhk8jAEAAwIAA3kAAz0E"
).strip()
MANUAL_PAYMENT_ENABLED = (
    PAYMENT_MODE in {
        "both",
        "manual",
    }
    and bool(MANUAL_QR_FILE_ID)
)
SUCCESS_STATUSES = {
    "paid",
    "success",
    "settled",
    "completed",
    "completed_payment",
    "success_payment",
}
FAILED_STATUSES = {
    "expired",
    "cancel",
    "cancelled",
    "canceled",
    "failed",
    "rejected",
    "void",
}
REUSABLE_PURCHASE_STATUSES = {
    "failed",
    "rejected",
    "expired",
    "cancel",
    "cancelled",
    "canceled",
}
ACTIVE_PURCHASE_STATUSES = {
    "pending",
    "verifying",
}
# ============================================================
# STARTUP LOG
# ============================================================
logger.info(
    "PAYMENT_MODE : %s",
    PAYMENT_MODE,
)
logger.info(
    "MANUAL_PAYMENT : %s",
    "ON" if MANUAL_PAYMENT_ENABLED else "OFF",
)
logger.info(
    "CASHI_ENABLED : %s",
    "ON" if CASHI_ENABLED else "OFF",
)
logger.info(
    "AUTO_PAYMENT : %s",
    "ON" if AUTO_PAYMENT_ENABLED else "OFF",
)
# ============================================================
# FSM
# ============================================================
class RejectPaymentState(StatesGroup):
    waiting_reason = State()
# ============================================================
# BASIC HELPERS
# ============================================================
def mask_user_id(user_id: int) -> str:
    uid = str(user_id)
    if len(uid) <= 4:
        return "****"
    return uid[:2] + "****" + uid[-2:]
def format_rupiah(amount: Any) -> str:
    try:
        return f"Rp {int(amount):,}".replace(",", ".")
    except Exception:
        return f"Rp {amount}"
def normalize_status(value: Any) -> str:
    return str(value or "").strip().lower()
def clean_html(value: Any) -> str:
    return html.escape(str(value or ""))
def safe_int(
    value: Any,
    default: int = 0,
) -> int:
    try:
        return int(value)
    except (
        ValueError,
        TypeError,
    ):
        return default
def get_admin_ids() -> set[int]:
    try:
        raw = ADMIN_IDS
        if raw is None:
            return set()
        if isinstance(raw, str):
            values = raw.replace(
                ";",
                ",",
            ).split(",")
        elif isinstance(
            raw,
            (list, tuple, set),
        ):
            values = raw
        else:
            values = [raw]
        result = set()
        for value in values:
            try:
                value = str(
                    value
                ).strip()
                if value:
                    result.add(
                        int(value)
                    )
            except (
                ValueError,
                TypeError,
            ):
                continue
        return result
    except Exception:
        logger.exception(
            "GET ADMIN IDS ERROR"
        )
        return set()
def is_admin(
    user_id: int,
) -> bool:
    try:
        return int(
            user_id
        ) in get_admin_ids()
    except Exception:
        return False
# ============================================================
# GENERIC CASHI RESPONSE HELPERS
# ============================================================
def recursive_find(
    data: Any,
    keys: set[str],
):
    if isinstance(data, dict):
        for key in keys:
            if (
                key in data
                and data[key]
                not in (
                    None,
                    "",
                )
            ):
                return data[key]
        for value in data.values():
            found = recursive_find(
                value,
                keys,
            )
            if found not in (
                None,
                "",
            ):
                return found
    elif isinstance(data, list):
        for item in data:
            found = recursive_find(
                item,
                keys,
            )
            if found not in (
                None,
                "",
            ):
                return found
    return None
def extract_cashi_status(
    data: Any,
) -> str:
    value = recursive_find(
        data,
        {
            "status",
            "payment_status",
            "paymentStatus",
            "state",
        },
    )
    return normalize_status(
        value
    )
def extract_cashi_order_id(
    data: Any,
    fallback: str | None = None,
) -> str:
    value = recursive_find(
        data,
        {
            "orderId",
            "order_id",
            "orderID",
            "payment_id",
            "paymentId",
            "transaction_id",
            "transactionId",
        },
    )
    if value:
        return str(
            value
        ).strip()
    return str(
        fallback or ""
    ).strip()
def extract_cashi_qr_url(
    data: Any,
) -> str:
    value = recursive_find(
        data,
        {
            "qrUrl",
            "qr_url",
            "qrURL",
            "qris_url",
            "qrisUrl",
            "qr",
            "qr_code",
            "qrCode",
        },
    )
    if not value:
        return ""
    if isinstance(
        value,
        dict,
    ):
        value = (
            value.get("url")
            or value.get("image")
            or value.get("src")
        )
    return str(
        value or ""
    ).strip()
def extract_cashi_payment_url(
    data: Any,
) -> str:
    value = recursive_find(
        data,
        {
            "checkout_url",
            "checkoutUrl",
            "payment_url",
            "paymentUrl",
            "payment_link",
            "paymentLink",
            "url",
        },
    )
    if not value:
        return ""
    return str(
        value or ""
    ).strip()
def parse_cashi_datetime(
    value: Any,
):
    if value is None:
        return None
    # Cashi memakai "0" untuk no expiration.
    if str(value).strip().lower() in {
        "",
        "0",
        "0.0",
        "none",
        "null",
    }:
        return None
    if isinstance(
        value,
        datetime,
    ):
        if value.tzinfo is None:
            return value.replace(
                tzinfo=timezone.utc
            )
        return value
    try:
        if isinstance(
            value,
            (int, float),
        ):
            # Angka 0 sudah ditangani di atas.
            return datetime.fromtimestamp(
                float(value),
                tz=timezone.utc,
            )
        text = str(
            value
        ).strip()
        if not text:
            return None
        if text.endswith("Z"):
            text = (
                text[:-1]
                + "+00:00"
            )
        result = datetime.fromisoformat(
            text
        )
        if result.tzinfo is None:
            result = result.replace(
                tzinfo=timezone.utc
            )
        return result
    except Exception:
        try:
            return Cashi._parse_datetime(
                value
            )
        except Exception:
            logger.warning(
                (
                    "CASHI DATETIME PARSE FAILED "
                    "| value=%r"
                ),
                value,
                exc_info=True,
            )
            return None
def extract_cashi_expires_at(
    data: Any,
):
    value = recursive_find(
        data,
        {
            "expires_at",
            "expiresAt",
            "expired_at",
            "expiredAt",
            "expiry",
            "expiration",
        },
    )
    return parse_cashi_datetime(
        value
    )
# ============================================================
# CALLBACK TOKEN
# ============================================================
async def create_callback_token(
    prefix: str,
    data: dict,
) -> str:
    token = secrets.token_urlsafe(
        12
    )
    await safe_set(
        f"cb:{prefix}:{token}",
        data,
        ex=CALLBACK_TOKEN_TTL,
    )
    return token
async def get_callback_token(
    prefix: str,
    token: str,
):
    if not token:
        return None
    try:
        data = await safe_get(
            f"cb:{prefix}:{token}"
        )
        if isinstance(
            data,
            dict,
        ):
            return data
        if isinstance(
            data,
            bytes,
        ):
            data = data.decode(
                "utf-8",
                errors="ignore",
            )
        if isinstance(
            data,
            str,
        ):
            try:
                return json.loads(
                    data
                )
            except Exception:
                return None
        return None
    except Exception:
        logger.exception(
            (
                "GET CALLBACK TOKEN ERROR "
                "| prefix=%s"
            ),
            prefix,
        )
        return None
# ============================================================
# MEDIA PARSER
# ============================================================
def parse_media(
    media_data: Any,
) -> list[dict]:
    if not media_data:
        return []
    if isinstance(
        media_data,
        str,
    ):
        try:
            media_data = json.loads(
                media_data
            )
        except Exception:
            logger.warning(
                "MEDIA JSON PARSE ERROR"
            )
            return []
    if isinstance(
        media_data,
        dict,
    ):
        media_data = (
            media_data.get("media")
            or media_data.get("items")
            or media_data.get("messages")
            or []
        )
    if not isinstance(
        media_data,
        list,
    ):
        return []
    result = []
    for item in media_data:
        if isinstance(
            item,
            dict,
        ):
            message_id = (
                item.get("message_id")
                or item.get("messageId")
                or item.get("id")
            )
            try:
                message_id = int(
                    message_id
                )
            except (
                ValueError,
                TypeError,
            ):
                continue
            if message_id <= 0:
                continue
            result.append({
                **item,
                "message_id": message_id,
            })
        else:
            try:
                message_id = int(
                    item
                )
            except (
                ValueError,
                TypeError,
            ):
                continue
            if message_id <= 0:
                continue
            result.append({
                "message_id": message_id,
            })
    return result
# ============================================================
# DATABASE
# ============================================================
async def get_file_by_code(
    code: str,
):
    if not code:
        return None
    code = str(
        code
    ).strip()
    if not code:
        return None
    return await fetchrow(
        """
        SELECT *
        FROM files
        WHERE LOWER(TRIM(code)) = LOWER(TRIM($1))
        LIMIT 1
        """,
        code,
    )
async def get_purchase_by_id(
    purchase_id: int,
):
    return await fetchrow(
        """
        SELECT *
        FROM file_purchases
        WHERE id=$1
        LIMIT 1
        """,
        int(purchase_id),
    )
async def get_active_purchase(
    user_id: int,
    code: str,
):
    return await fetchrow(
        """
        SELECT *
        FROM file_purchases
        WHERE user_id=$1
          AND LOWER(TRIM(file_code)) = LOWER(TRIM($2))
          AND status IN ('pending','verifying')
        ORDER BY id DESC
        LIMIT 1
        """,
        int(user_id),
        str(code).strip(),
    )
async def get_active_method_purchase(
    user_id: int,
    code: str,
    payment_prefix: str,
):
    return await fetchrow(
        """
        SELECT *
        FROM file_purchases
        WHERE user_id=$1
          AND LOWER(TRIM(file_code)) = LOWER(TRIM($2))
          AND status IN ('pending','verifying')
          AND payment_id LIKE $3
        ORDER BY id DESC
        LIMIT 1
        """,
        int(user_id),
        str(code).strip(),
        f"{payment_prefix}%",
    )
async def get_paid_purchase(
    user_id: int,
    code: str,
):
    return await fetchrow(
        """
        SELECT *
        FROM file_purchases
        WHERE user_id=$1
          AND (
              LOWER(TRIM(COALESCE(file_code, ''))) = LOWER(TRIM($2))
              OR LOWER(TRIM(COALESCE(code, ''))) = LOWER(TRIM($2))
          )
          AND status='paid'
        ORDER BY id DESC
        LIMIT 1
        """,
        int(user_id),
        str(code).strip(),
    )
# ============================================================
# PAYMENT METHOD DETECTION
# ============================================================
def purchase_method(
    purchase,
) -> str:
    payment_id = str(
        purchase.get("payment_id")
        or ""
    ).strip()
    if payment_id.startswith(
        "CASHI-"
    ):
        return "cashi"
    if payment_id.startswith(
        "BAYARGG-"
    ):
        return "bayargg"
    if payment_id.startswith(
        "MANUAL-"
    ):
        return "manual"
    return ""
# ============================================================
# DELETE OLD PAYMENT MESSAGE
# ============================================================
async def delete_payment_message(
    bot,
    purchase,
):
    """Best-effort deletion of an old payment message.

    Telegram returns 'message to delete not found' when the message was
    already deleted. That is a normal/idempotent condition, not a payment
    failure, so it is intentionally ignored.
    """
    message_id = purchase.get("qr_message_id")
    chat_id = purchase.get("qr_chat_id")
    if not message_id or not chat_id:
        return False
    try:
        await bot.delete_message(
            chat_id=int(chat_id),
            message_id=int(message_id),
        )
        return True
    except TelegramBadRequest as exc:
        if "message to delete not found" in str(exc).lower():
            logger.info(
                "PAYMENT MESSAGE ALREADY GONE | chat=%s | message=%s",
                chat_id,
                message_id,
            )
            return False
        logger.warning(
            "DELETE PAYMENT MESSAGE FAILED | chat=%s | message=%s",
            chat_id,
            message_id,
            exc_info=True,
        )
        return False
    except Exception:
        logger.warning(
            "DELETE PAYMENT MESSAGE FAILED | chat=%s | message=%s",
            chat_id,
            message_id,
            exc_info=True,
        )
        return False
# ============================================================
# PAYMENT LOADING UI
# ============================================================
def payment_loading_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="⏳ Memproses pembayaran...",
                    callback_data="none",
                )
            ]
        ]
    )


async def show_payment_loading(
    call: CallbackQuery,
    text: str = "⏳ Memproses pembayaran...",
):
    """Give instant visual feedback before slow DB/API operations."""
    try:
        await call.answer(text)
    except Exception:
        pass
    try:
        await call.message.edit_reply_markup(
            reply_markup=payment_loading_keyboard()
        )
    except Exception:
        # Some source messages (photo/media/etc.) may not be editable.
        pass


# ============================================================
# PAYMENT KEYBOARD
# ============================================================
def paid_unlock_keyboard(code: str, lang: str = "id"):
    labels={
        "id": ("💳 Bayar", "⭐ Gunakan Poin"),
        "en": ("💳 Pay", "⭐ Use Points"),
        "zh": ("💳 支付", "⭐ 使用积分"),
    }
    pay_label, point_label = labels.get(lang, labels["id"])
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=pay_label, callback_data=f"pay:{code}")],
        [InlineKeyboardButton(text=point_label, callback_data=f"paidpoint:{code}")],
        [InlineKeyboardButton(text={"id":"❌ Batal","en":"❌ Cancel","zh":"❌ 取消"}.get(lang,"❌ Batal"), callback_data="close")],
    ])


async def payment_method_keyboard(code: str, user_id: int | None = None):
    """Build payment methods from DB settings so admin can enable/disable them live."""
    lang = await get_user_language(user_id) if user_id else "id"
    pool = await database_pool()
    def on(key, default="on"):
        return True
    async def setting(key, default="on"):
        value = await pool.fetchval("SELECT value FROM settings WHERE key=$1", key)
        return str(value if value is not None else default).lower() in {"on","1","true","yes"}
    cashi_on = await setting("payment_cashi_enabled", "on") and AUTO_PAYMENT_ENABLED
    bayargg_on = await setting("payment_bayargg_enabled", "on") and bool(os.getenv("BAYARGG_API_KEY", "").strip())
    manual_enabled = await setting("payment_manual_enabled", "off")
    manual_qr_chat = await pool.fetchval(
        "SELECT value FROM settings WHERE key=$1", "manual_qr_chat_id"
    )
    manual_qr_message = await pool.fetchval(
        "SELECT value FROM settings WHERE key=$1", "manual_qr_message_id"
    )
    manual_on = (
        manual_enabled
        and bool(safe_int(manual_qr_chat))
        and bool(safe_int(manual_qr_message))
    )
    # Binance/USDT is handled manually by the owner via Telegram @ownergbot.
    binance_on = await setting("payment_binance_enabled", "off")
    L={
      "id":("💳 Pembayaran", "📲 QR Otomatis 1 ", "⚡ QR Otomatis 2 ", "📷 QR Manual", "₿ Binance / USDT", "❌ Batal", "❌ Pembayaran Tidak Tersedia"),
      "en":("💳 Payment", "📲 Automatic QR 1 ", "⚡ Automatic QR 2 ", "📷 Manual QR", "₿ Binance / USDT", "❌ Cancel", "❌ Payment Unavailable"),
      "zh":("💳 支付", "📲 自动二维码 1 ", "⚡ 自动二维码 2 ", "📷 手动二维码", "₿ Binance / USDT", "❌ 取消", "❌ 暂无可用支付方式")
    }[lang]
    buttons=[]
    if cashi_on: buttons.append([InlineKeyboardButton(text=L[1], callback_data=f"cashi:{code}")])
    if bayargg_on: buttons.append([InlineKeyboardButton(text=L[2], callback_data=f"bayargg:{code}")])
    if manual_on: buttons.append([InlineKeyboardButton(text=L[3], callback_data=f"manual:{code}")])
    if binance_on:
        buttons.append([InlineKeyboardButton(text=L[4], url="https://t.me/ownergbot")])
    if not buttons: buttons.append([InlineKeyboardButton(text=L[6], callback_data="none")])
    buttons.append([InlineKeyboardButton(text=L[5], callback_data="close")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

async def database_pool():
    from database import get_pool
    return await get_pool()

# ============================================================
# CENTRAL PAYMENT NOTIFICATIONS
# ============================================================
async def _record_user_notification(pool, user_id: int, title: str, message: str, type_: str = "payment"):
    try:
        await pool.execute(
            """INSERT INTO user_notifications(user_id,type,title,message) VALUES($1,$2,$3,$4)""",
            int(user_id), type_, title, message,
        )
    except Exception:
        logger.exception("USER NOTIFICATION INSERT ERROR user=%s", user_id)

async def _notify_admins(bot, text: str, reply_markup=None):
    sent = 0
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(admin_id, text, parse_mode="HTML", reply_markup=reply_markup)
            sent += 1
        except Exception:
            logger.exception("ADMIN PAYMENT NOTIFY ERROR admin=%s", admin_id)
    return sent

# ============================================================
# POINT PURCHASE PAYMENT
# ============================================================
async def create_points_payment(call: CallbackQuery, points_amount: int, price_amount: int | None = None):
    """Central payment entry for point packages.

    points_amount is the number of points received; price_amount is the
    actual rupiah amount paid. This fixes the old 20-point -> invalid-package
    bug where the point quantity was incorrectly treated as the price.
    """
    points_amount = safe_int(points_amount)
    price_amount = safe_int(price_amount if price_amount is not None else points_amount)
    packages = {
        20: 2000,
        100: 5000,
        200: 10000,
        400: 20000,
        1000: 50000,
    }
    if points_amount not in packages:
        return await call.answer("❌ Paket poin tidak valid.", show_alert=True)
    if price_amount != packages[points_amount]:
        price_amount = packages[points_amount]

    lang = await get_user_language(call.from_user.id)
    methods = await payment_methods_enabled()
    labels = {
        "id": ("💳 <b>PEMBAYARAN POIN</b>", "Pilih metode pembayaran untuk membeli poin."),
        "en": ("💳 <b>POINT PAYMENT</b>", "Choose a payment method to buy points."),
        "zh": ("💳 <b>积分支付</b>", "请选择购买积分的支付方式。"),
    }[lang]
    rows = []
    if methods.get("cashi"):
        rows.append([InlineKeyboardButton(text="📲 QR Otomatis 1 • Cashi", callback_data=f"pointpay:{points_amount}:cashi")])
    if methods.get("bayargg"):
        rows.append([InlineKeyboardButton(text="⚡ QR Otomatis 2 • BayarGG", callback_data=f"pointpay:{points_amount}:bayargg")])
    if methods.get("manual"):
        rows.append([InlineKeyboardButton(text="📷 QR Manual", callback_data=f"pointpay:{points_amount}:manual")])
    if not rows:
        rows.append([InlineKeyboardButton(text="❌ Pembayaran tidak tersedia", callback_data="none")])
    rows.append([InlineKeyboardButton(text={"id":"⬅️ Kembali","en":"⬅️ Back","zh":"⬅️ 返回"}[lang], callback_data="points")])
    text = (
        f"{labels[0]}\n\n⭐ <b>{points_amount:,}</b> poin\n"
        f"💰 <b>Rp {price_amount:,}</b>\n\n{labels[1]}"
    ).replace(",", ".")
    return await call.message.edit_text(
        text, parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows)
    )

@router.callback_query(F.data.startswith("pointpay:"))
async def pointpay_method(call: CallbackQuery):
    try:
        await call.answer()
    except Exception:
        pass
    parts = call.data.split(":")
    if len(parts) != 3:
        return await call.answer("❌ Data tidak valid.", show_alert=True)
    points_amount = safe_int(parts[1])
    method = parts[2].lower()
    packages = {20: 2000, 100: 5000, 200: 10000, 400: 20000, 1000: 50000}
    if points_amount not in packages:
        return await call.answer("❌ Paket tidak valid.", show_alert=True)
    if method in {"cashi", "bayargg"}:
        return await _create_points_provider(
            call, points_amount, packages[points_amount], method
        )
    if method == "manual":
        return await _create_points_manual(call, points_amount, packages[points_amount])
    return await call.answer("❌ Metode tersebut tidak tersedia.", show_alert=True)

async def _create_points_provider(call, points_amount: int, price_amount: int, provider: str):
    import uuid
    uid = int(call.from_user.id)
    pool = await database_pool()
    existing = await pool.fetchrow(
        "SELECT * FROM point_orders WHERE user_id=$1 AND provider=$2 AND status='pending' ORDER BY id DESC LIMIT 1",
        uid, provider,
    )
    if existing and int(existing["points"] or 0) == points_amount:
        return await _send_point_qr(
            call, points_amount, price_amount,
            str(existing["order_id"]), str(existing["qr_url"] or ""), provider
        )
    try:
        if provider == "cashi":
            payment = await Cashi.create_payment(
                amount=price_amount,
                description=f"Buy {points_amount} points",
                customer_name=call.from_user.full_name,
            )
        else:
            payment = await BayarGG.create_payment(
                amount=price_amount,
                description=f"Buy {points_amount} points",
                customer_name=call.from_user.full_name,
                payment_method="qris",
            )
    except Exception:
        logger.exception("POINT %s CREATE ERROR", provider.upper())
        return await call.message.answer(f"❌ Gagal membuat pembayaran {provider.title()}.")
    if not payment:
        return await call.message.answer(f"❌ Gagal membuat pembayaran {provider.title()}.")
    order_id = str(
        payment.get("order_id") or payment.get("invoice_id")
        or payment.get("payment_id") or f"POINT-{uuid.uuid4().hex[:16].upper()}"
    ).strip()
    qr = str(
        payment.get("qr_string") or payment.get("qris_string")
        or payment.get("qr_image") or payment.get("qr_url")
        or payment.get("qrUrl") or ""
    )
    expires = payment.get("expires_at")
    await pool.execute(
        """INSERT INTO point_orders(user_id,points,amount,provider,order_id,status,qr_url,expires_at)
           VALUES($1,$2,$3,$4,$5,'pending',$6,$7)
           ON CONFLICT(order_id) DO NOTHING""",
        uid, points_amount, price_amount, provider, order_id, qr, expires
    )
    return await _send_point_qr(
        call, points_amount, price_amount, order_id, qr, provider
    )

async def _create_points_manual(call: CallbackQuery, points_amount: int, price_amount: int):
    """Manual QR uses the same central point order, but no provider API call."""
    import uuid
    pool = await database_pool()
    uid = int(call.from_user.id)
    order_id = f"POINT-MANUAL-{uuid.uuid4().hex[:16].upper()}"
    qr = str(await pool.fetchval("SELECT value FROM settings WHERE key=$1", "manual_qr_file_id") or MANUAL_QR_FILE_ID or "")
    await pool.execute(
        """INSERT INTO point_orders(user_id,points,amount,provider,order_id,status,qr_url)
           VALUES($1,$2,$3,'manual',$4,'pending',$5)
           ON CONFLICT(order_id) DO NOTHING""",
        uid, points_amount, price_amount, order_id, qr
    )
    return await _send_point_qr(
        call, points_amount, price_amount, order_id, qr, "manual"
    )

async def _send_point_qr(call, points_amount: int, price_amount: int, order_id: str, qr: str, provider: str):
    import qrcode
    from io import BytesIO
    lang=await get_user_language(call.from_user.id)
    name={"cashi":"📲 CASHI","bayargg":"⚡ BAYARGG"}.get(provider,provider.upper())
    text={"id":f"💳 <b>PEMBELIAN POIN • {name}</b>\n\n⭐ Poin: <b>{points_amount:,}</b>\n💰 Harga: <b>Rp {price_amount:,}</b>\n\nScan QR lalu tekan <b>Cek Pembayaran</b>.".replace(",","."),
          "en":f"💳 <b>POINT PURCHASE • {name}</b>\n\n⭐ Points: <b>{points_amount:,}</b>\n💰 Price: <b>Rp {price_amount:,}</b>\n\nScan the QR then press <b>Check Payment</b>.".replace(",","."),
          "zh":f"💳 <b>购买积分 • {name}</b>\n\n⭐ 积分：<b>{points_amount:,}</b>\n💰 价格：<b>Rp {price_amount:,}</b>\n\n请扫描二维码，然后点击<b>检查支付</b>。".replace(",",".")}[lang]
    kb=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text={"id":"🔄 Cek Pembayaran","en":"🔄 Check Payment","zh":"🔄 检查支付"}[lang],callback_data=f"points_check:{order_id}")],
        [InlineKeyboardButton(text={"id":"❌ Tutup","en":"❌ Close","zh":"❌ 关闭"}[lang],callback_data="points")]
    ])
    if qr:
        # Manual QR stores a Telegram file_id. Send the actual QR image
        # instead of turning the file_id into a QR payload.
        if provider == "manual" and not qr.startswith(("http://", "https://", "data:image/")):
            try:
                return await call.message.answer_photo(
                    qr, caption=text, parse_mode="HTML", reply_markup=kb
                )
            except Exception:
                logger.exception("POINT MANUAL QR SEND ERROR")
        if qr.startswith(("http://","https://")):
            try: return await call.message.answer_photo(qr,caption=text,parse_mode="HTML",reply_markup=kb)
            except Exception: logger.exception("POINT QR URL SEND ERROR")
        try:
            buf=BytesIO(); qrcode.make(qr).save(buf,format="PNG")
            return await call.message.answer_photo(BufferedInputFile(buf.getvalue(),"point_qr.png"),caption=text,parse_mode="HTML",reply_markup=kb)
        except Exception: logger.exception("POINT QR RENDER ERROR")
    return await call.message.answer(text+f"\n\n🧾 Order: <code>{html.escape(order_id)}</code>",parse_mode="HTML",reply_markup=kb)

# Central payment callbacks for VIP / Creator.
@router.callback_query(F.data.startswith("payvipmethod:"))
async def payvip_method_bridge(call: CallbackQuery):
    try:
        from handlers.vip import vip_method
        # vip_method accepts both central and legacy namespaces.
        return await vip_method(call)
    except Exception:
        logger.exception("PAY VIP METHOD ERROR")
        return await call.message.answer("❌ Gagal memproses metode pembayaran VIP.")

@router.callback_query(F.data.startswith("paycreatorpay:"))
async def paycreator_method_bridge(call: CallbackQuery):
    try:
        from handlers.creator import creator_payment_method
        # creator_payment_method accepts both central and legacy namespaces.
        return await creator_payment_method(call)
    except Exception:
        logger.exception("PAY CREATOR METHOD ERROR")
        return await call.message.answer("❌ Gagal memproses metode pembayaran Creator.")


# ============================================================
# CENTRAL PRODUCT PAYMENT ENTRY / CHECK
# ============================================================
# Semua pembayaran user masuk melalui pay.py. Provider/module handlers
# hanya menyediakan implementasi provider dan helper; router entry tetap
# berada di sini agar tidak ada jalur pembayaran kedua.

def _product_method_rows(lang: str, prefix: str, methods: dict):
    rows = []
    labels = {
        "cashi": {"id":"📲 QR Otomatis 1 ","en":"📲 Automatic QR 1 ","zh":"📲 自动二维码 1 "},
        "bayargg": {"id":"⚡ QR Otomatis 2 ","en":"⚡ Automatic QR 2 ","zh":"⚡ 自动二维码 2 "},
        "manual": {"id":"📷 QR Manual","en":"📷 Manual QR","zh":"📷 手动二维码"},
    }
    for method in ("cashi","bayargg","manual"):
        if methods.get(method):
            rows.append([InlineKeyboardButton(text=labels[method].get(lang, labels[method]["id"]), callback_data=f"{prefix}:{method}")])
    if not rows:
        rows.append([InlineKeyboardButton(text={"id":"❌ Pembayaran tidak tersedia","en":"❌ Payment unavailable","zh":"❌ 暂无可用支付方式"}[lang], callback_data="none")])
    rows.append([InlineKeyboardButton(text={"id":"⬅️ Kembali","en":"⬅️ Back","zh":"⬅️ 返回"}[lang], callback_data="account")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

async def _central_vip_entry(call: CallbackQuery, package_id: str):
    package_id = str(package_id).strip()
    from config_vip import VIP_PACKAGES
    paket = VIP_PACKAGES.get(package_id)
    if not paket:
        return await call.answer("❌ Paket VIP tidak ditemukan.", show_alert=True)
    lang = await get_user_language(call.from_user.id)
    methods = await payment_methods_enabled()
    name = html.escape(str(paket.get("name") or package_id))
    price = int(paket.get("price") or 0)
    text = {
        "id": "💎 <b>PEMBAYARAN VIP</b>\n\nPilih metode pembayaran:",
        "en": "💎 <b>VIP PAYMENT</b>\n\nChoose a payment method:",
        "zh": "💎 <b>VIP 支付</b>\n\n请选择支付方式：",
    }[lang] + f"\n\n📦 <b>{name}</b>\n💰 <b>Rp {price:,}</b>".replace(",", ".")
    await call.answer()
    return await call.message.edit_text(text, parse_mode="HTML", reply_markup=_product_method_rows(lang, f"payvipmethod:{package_id}", methods))

async def _central_creator_entry(call: CallbackQuery):
    lang = await get_user_language(call.from_user.id)
    methods = await payment_methods_enabled()
    from handlers.creator import CREATOR_UPGRADE_PRICE
    text = {
        "id": "🎨 <b>PEMBAYARAN CREATOR</b>\n\nPilih metode pembayaran:",
        "en": "🎨 <b>CREATOR PAYMENT</b>\n\nChoose a payment method:",
        "zh": "🎨 <b>创作者支付</b>\n\n请选择支付方式：",
    }[lang] + f"\n\n💰 <b>Rp {CREATOR_UPGRADE_PRICE:,}</b>".replace(",", ".")
    await call.answer()
    return await call.message.edit_text(text, parse_mode="HTML", reply_markup=_product_method_rows(lang, "paycreatorpay", methods))

# ============================================================
# ONE CENTRAL PRODUCT PAYMENT ENTRY
# ============================================================
@router.callback_query(F.data.startswith("buyvip:"))
async def legacy_buyvip_entry(call: CallbackQuery):
    return await _central_vip_entry(call, call.data.split(":",1)[1])

@router.callback_query(F.data.startswith("payvip:"))
async def payvip_entry(call: CallbackQuery):
    return await _central_vip_entry(call, call.data.split(":",1)[1])

@router.callback_query(F.data == "creator_upgrade")
async def legacy_creator_entry(call: CallbackQuery):
    return await _central_creator_entry(call)

@router.callback_query(F.data == "paycreator")
async def paycreator_entry(call: CallbackQuery):
    return await _central_creator_entry(call)

@router.callback_query(F.data.startswith("pointapprove:"))
async def point_manual_approve(call: CallbackQuery):
    if call.from_user.id not in ADMIN_IDS:
        return await call.answer("❌ Bukan admin.", show_alert=True)
    try: await call.answer()
    except Exception: pass
    try: oid=int(call.data.split(":",1)[1])
    except Exception: return await call.answer("❌ Order tidak valid.", show_alert=True)
    pool=await database_pool()
    row=await pool.fetchrow("SELECT * FROM point_orders WHERE id=$1 AND provider='manual' AND status='verifying' FOR UPDATE",oid)
    if not row: return await call.answer("❌ Order sudah diproses.", show_alert=True)
    ok=await _settle_points_order_by_id(pool, row)
    if not ok: return await call.answer("❌ Gagal menambahkan poin.", show_alert=True)
    lang=await get_user_language(row["user_id"]); pts=await pool.fetchval("SELECT points FROM users WHERE user_id=$1",row["user_id"])
    msg={"id":f"🎉 <b>Poin berhasil masuk!</b>\n\n⭐ +{row['points']} poin\n⭐ Total: <b>{pts}</b>\n\n💳 Pembayaran manual kamu telah disetujui admin.","en":f"🎉 <b>Points added successfully!</b>\n\n⭐ +{row['points']} points\n⭐ Total: <b>{pts}</b>\n\n💳 Your manual payment was approved by admin.","zh":f"🎉 <b>积分已到账！</b>\n\n⭐ +{row['points']} 积分\n⭐ 总计：<b>{pts}</b>\n\n💳 你的手动付款已获管理员批准。"}[lang]
    await _record_user_notification(pool,row["user_id"],"Points Payment",msg)
    await call.bot.send_message(row["user_id"],msg,parse_mode="HTML")
    await call.message.edit_text("✅ <b>PEMBAYARAN POIN DISETUJUI</b>\n\n"+f"👤 <code>{row['user_id']}</code>\n⭐ +{row['points']} poin",parse_mode="HTML")

@router.callback_query(F.data.startswith("pointreject:"))
async def point_manual_reject(call: CallbackQuery):
    if call.from_user.id not in ADMIN_IDS:
        return await call.answer("❌ Bukan admin.", show_alert=True)
    await call.answer()
    try: oid=int(call.data.split(":",1)[1])
    except Exception: return
    pool=await database_pool(); row=await pool.fetchrow("UPDATE point_orders SET status='rejected',updated_at=NOW() WHERE id=$1 AND provider='manual' AND status='verifying' RETURNING *",oid)
    if not row: return await call.answer("❌ Order sudah diproses.",show_alert=True)
    lang=await get_user_language(row['user_id']); msg={"id":"❌ <b>Pembayaran poin ditolak admin.</b>\n\nSilakan periksa pembayaran kamu dan lakukan kembali jika diperlukan.","en":"❌ <b>Point payment was rejected by admin.</b>\n\nPlease check your payment and try again if needed.","zh":"❌ <b>积分付款已被管理员拒绝。</b>\n\n请检查付款后重试。"}[lang]
    await _record_user_notification(pool,row['user_id'],"Points Payment Rejected",msg)
    try: await call.bot.send_message(row['user_id'],msg,parse_mode="HTML")
    except Exception: pass
    await call.message.edit_text("❌ <b>PEMBAYARAN POIN DITOLAK</b>\n\n"+f"👤 <code>{row['user_id']}</code>\n⭐ {row['points']} poin",parse_mode="HTML")

async def _settle_points_order_by_id(pool, row):
    if str(row['status']).lower() == 'paid': return True
    return bool(await pool.fetchval("""SELECT public.add_points($1,$2,'purchase',$3,$4)""", row['user_id'], row['points'], f"points_purchase:{row['id']}", f"Buy {row['points']} points"))

@router.callback_query(F.data.startswith("cashicheck:"))
async def central_cashi_check(call: CallbackQuery):
    try:
        from handlers.cashi import check_cashi
        return await check_cashi(call)
    except Exception:
        logger.exception("CENTRAL CASHI CHECK ERROR")
        return await call.message.answer("❌ Gagal mengecek pembayaran Cashi.")

@router.callback_query(F.data.startswith("bayarggcheck:"))
async def central_bayargg_check(call: CallbackQuery):
    try:
        from handlers.bayargg_payment import bayargg_check
        return await bayargg_check(call)
    except Exception:
        logger.exception("CENTRAL BAYARGG CHECK ERROR")
        return await call.message.answer("❌ Gagal mengecek pembayaran BayarGG.")

@router.callback_query(F.data.startswith("points_check:"))
async def central_points_check(call: CallbackQuery):
    try:
        from handlers.points import points_check
        return await points_check(call)
    except Exception:
        logger.exception("CENTRAL POINT PAYMENT CHECK ERROR")
        return await call.message.answer("❌ Gagal mengecek pembayaran poin.")

@router.callback_query(F.data.startswith("vipcashicheck:"))
async def central_vip_cashi_check(call: CallbackQuery):
    try:
        from handlers.vip import vip_cashi_check
        return await vip_cashi_check(call)
    except Exception:
        logger.exception("CENTRAL VIP CASHI CHECK ERROR")
        return await call.message.answer("❌ Gagal mengecek pembayaran VIP.")

@router.callback_query(F.data.startswith("vipwait:"))
async def central_vip_auto_check(call: CallbackQuery):
    try:
        from handlers.vip import vip_wait
        return await vip_wait(call)
    except Exception:
        logger.exception("CENTRAL VIP AUTO CHECK ERROR")
        return await call.message.answer("❌ Gagal mengecek pembayaran VIP.")

@router.callback_query(F.data.startswith("vipmanualcheck:"))
async def central_vip_manual_check(call: CallbackQuery):
    try:
        from handlers.vip import vip_manual_check
        return await vip_manual_check(call)
    except Exception:
        logger.exception("CENTRAL VIP MANUAL CHECK ERROR")
        return await call.message.answer("❌ Gagal mengecek pembayaran manual VIP.")

@router.callback_query(F.data.startswith("creatorpaycheck:"))
async def central_creator_check(call: CallbackQuery):
    try:
        from handlers.creator import creator_payment_check
        return await creator_payment_check(call)
    except Exception:
        logger.exception("CENTRAL CREATOR PAYMENT CHECK ERROR")
        return await call.message.answer("❌ Gagal mengecek pembayaran Creator.")

# ============================================================
# PAYMENT ENTRY
# ============================================================
@router.callback_query(
    F.data.startswith("pay:")
)
async def choose_payment(
    call: CallbackQuery,
):
    await show_payment_loading(
        call,
        "⏳ Menyiapkan pembayaran...",
    )
    try:
        code = call.data.split(
            ":",
            1,
        )[1].strip()
    except (
        AttributeError,
        IndexError,
    ):
        return await call.message.answer(
            "❌ Code tidak valid."
        )
    if not code:
        return await call.message.answer(
            "❌ Code tidak valid."
        )
    try:
        file = await get_file_by_code(
            code
        )
    except Exception:
        logger.exception(
            "GET FILE ERROR"
        )
        return await call.message.answer(
            "❌ Gagal mengambil data file."
        )
    if not file:
        return await call.message.answer(
            "❌ File tidak ditemukan."
        )
    # Always use the canonical code stored in `files.code` for every
    # downstream payment/purchase operation. User input remains case-insensitive.
    code = str(file.get("code") or code).strip()
    price = safe_int(
        file.get("price")
    )
    if price <= 0:
        return await call.message.answer(
            "❌ Harga file tidak valid."
        )
    user_id = int(
        call.from_user.id
    )
    paid = await get_paid_purchase(
        user_id,
        code,
    )
    if paid:
        from handlers.getfile import process_code
        return await process_code(
            call.message,
            code,
            paid_override=True,
        )
    # --------------------------------------------------------
    # Jika ada satu active, tampilkan transaksi tersebut.
    # Jika Cashi + Manual sama-sama aktif, tampilkan pilihan
    # metode agar user bisa masuk ke transaksi masing-masing.
    # --------------------------------------------------------
    active_rows = await fetch(
        """
        SELECT *
        FROM file_purchases
        WHERE user_id=$1
          AND LOWER(TRIM(file_code)) = LOWER(TRIM($2))
          AND status IN ('pending','verifying')
        ORDER BY id DESC
        LIMIT 10
        """,
        user_id,
        code,
    )
    if active_rows:
        methods = {
            purchase_method(row)
            for row in active_rows
        }
        if methods == {"cashi"}:
            return await show_existing_cashi(
                call,
                active_rows[0],
                file,
            )
        if methods == {"manual"}:
            return await show_existing_manual(
                call,
                active_rows[0],
                file,
            )
        if methods == {"binance"}:
            return await show_existing_binance(call, active_rows[0], file)
        if methods == {"binance"}:
            return await show_existing_binance(call, active_rows[0], file)
        if "cashi" in methods or "manual" in methods or "binance" in methods:
            await call.message.answer(
                (
                    "⏳ <b>Kamu sudah memiliki pembayaran "
                    "yang sedang aktif.</b>\n\n"
                    "Kamu bisa melanjutkan salah satu "
                    "metode pembayaran di bawah."
                ),
                parse_mode="HTML",
                reply_markup=await payment_method_keyboard(
                    code, call.from_user.id
                ),
            )
            return
    lang = await get_user_language(call.from_user.id)
    title = clean_html(file.get("title"))
    price_text = format_rupiah(price)
    chooser = {
      "id": f"🔒 <b>CODE BERBAYAR</b>\n\n💳 <b>Pembayaran diperlukan untuk membuka code ini.</b>\n\n📄 File: <b>{title}</b>\n💰 Harga: <b>{price_text}</b>\n\nSilakan pilih metode pembayaran:",
      "en": f"🔒 <b>PAID CODE</b>\n\n💳 <b>Payment is required to open this code.</b>\n\n📄 File: <b>{title}</b>\n💰 Price: <b>{price_text}</b>\n\nChoose a payment method:",
      "zh": f"🔒 <b>付费代码</b>\n\n💳 <b>打开此代码需要付款。</b>\n\n📄 文件：<b>{title}</b>\n💰 价格：<b>{price_text}</b>\n\n请选择支付方式："
    }[lang]
    await call.message.answer(chooser, parse_mode="HTML", reply_markup=await payment_method_keyboard(code, call.from_user.id))
# ============================================================
# BUY ALIAS
# ============================================================
@router.callback_query(
    F.data.startswith("buy:")
)
async def buy_payment_alias(
    call: CallbackQuery,
):
    code = call.data.split(
        ":",
        1,
    )[1].strip()
    call.data = f"pay:{code}"
    return await choose_payment(
        call
    )
# ============================================================
# CENTRAL PROVIDER ENTRY
# ============================================================
@router.callback_query(F.data.startswith("cashi:"))
async def cashi_payment(call: CallbackQuery):
    try: await call.answer("⏳ Menyiapkan Cashi...")
    except Exception: pass
    code=call.data.split(":",1)[1].strip()
    if not code: return await call.message.answer("❌ Code tidak valid.")
    file=await get_file_by_code(code)
    if not file: return await call.message.answer("❌ File tidak ditemukan.")
    try:
        from handlers.cashi import create_cashi
        return await create_cashi(call)
    except Exception:
        logger.exception("CENTRAL CASHI ROUTE ERROR | code=%s",code)
        return await call.message.answer("❌ Gagal membuat QR Cashi. Silakan coba lagi.")

@router.callback_query(F.data.startswith("bayargg:"))
async def bayargg_payment(call: CallbackQuery):
    try: await call.answer("⏳ Menyiapkan BayarGG...")
    except Exception: pass
    code=call.data.split(":",1)[1].strip()
    if not code: return await call.message.answer("❌ Code tidak valid.")
    file=await get_file_by_code(code)
    if not file: return await call.message.answer("❌ File tidak ditemukan.")
    try:
        from handlers.bayargg_payment import create_bayargg
        return await create_bayargg(call,code,file)
    except Exception:
        logger.exception("CENTRAL BAYARGG ROUTE ERROR | code=%s",code)
        return await call.message.answer("❌ Gagal membuat QR BayarGG. Silakan coba lagi.")

# ============================================================
# BINANCE / USDT ENTRY
# ============================================================
@router.callback_query(F.data.startswith("binance:"))
async def binance_payment(call: CallbackQuery):
    # Kept only for old/stale messages containing the previous callback.
    # New payment keyboards use a direct Telegram URL to @ownergbot.
    lang = await get_user_language(call.from_user.id)
    text = {
        "id": "₿ <b>BINANCE / USDT</b>\n\nSilakan hubungi admin untuk pembayaran Binance / USDT.",
        "en": "₿ <b>BINANCE / USDT</b>\n\nPlease contact the admin for Binance / USDT payment.",
        "zh": "₿ <b>BINANCE / USDT</b>\n\n如需使用 Binance / USDT 付款，请联系管理员。",
    }[lang]
    button = {
        "id": "💬 Hubungi Admin",
        "en": "💬 Contact Admin",
        "zh": "💬 联系管理员",
    }[lang]
    await call.answer()
    return await call.message.answer(
        text, parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=button, url="https://t.me/ownergbot")],
            [InlineKeyboardButton(text={"id":"❌ Batal","en":"❌ Cancel","zh":"❌ 取消"}[lang], callback_data="close")],
        ])
    )

# ============================================================
# MANUAL ENTRY
# ============================================================
@router.callback_query(
    F.data.startswith("manual:")
)
async def manual_payment(
    call: CallbackQuery,
):
    # ACK callback immediately. Do not replace the payment keyboard with a
    # permanent "processing" button; the manual flow must continue to the QR.
    try:
        await call.answer()
    except Exception:
        pass
    # Baca status QR Manual langsung dari database.
    # Jangan gunakan konstanta MANUAL_PAYMENT_ENABLED karena admin dapat
    # mengaktifkan/nonaktifkan metode pembayaran dari panel secara live.
    pool = await database_pool()
    manual_enabled = str(
        await pool.fetchval(
            "SELECT value FROM settings WHERE key=$1",
            "payment_manual_enabled",
        ) or "off"
    ).lower() in {"on", "1", "true", "yes"}
    qr_chat = safe_int(
        await pool.fetchval(
            "SELECT value FROM settings WHERE key=$1",
            "manual_qr_chat_id",
        )
    )
    qr_msg = safe_int(
        await pool.fetchval(
            "SELECT value FROM settings WHERE key=$1",
            "manual_qr_message_id",
        )
    )
    if not manual_enabled or not qr_chat or not qr_msg:
        return await call.message.answer(
            "❌ Pembayaran manual sedang tidak tersedia."
        )
    try:
        code = call.data.split(
            ":",
            1,
        )[1].strip()
    except (
        AttributeError,
        IndexError,
    ):
        return await call.message.answer(
            "❌ Code tidak valid."
        )
    file = await get_file_by_code(
        code
    )
    if not file:
        return await call.message.answer(
            "❌ File tidak ditemukan."
        )
    # Always use the canonical code stored in `files.code` for every
    # downstream payment/purchase operation. User input remains case-insensitive.
    code = str(file.get("code") or code).strip()
    price = safe_int(
        file.get("price")
    )
    if price <= 0:
        return await call.message.answer(
            "❌ Harga file tidak valid."
        )
    return await create_manual_payment(
        call,
        code,
        file,
    )
# ============================================================
# CREATE / REUSE METHOD PURCHASE
# ============================================================
async def get_or_create_purchase(
    user_id: int,
    code: str,
    file,
    payment_prefix: str,
):
    """Return one active purchase, reusing an existing active row when possible."""
    user_id = int(user_id)
    code = str(code or "").strip()
    payment_prefix = str(payment_prefix or "").strip()

    paid = await get_paid_purchase(user_id, code)
    if paid:
        return {
            "purchase": paid,
            "already_paid": True,
            "existing": True,
        }

    existing = await get_active_method_purchase(
        user_id,
        code,
        payment_prefix,
    )
    if existing:
        return {
            "purchase": existing,
            "already_paid": False,
            "existing": True,
        }

    payment_id = (
        f"{payment_prefix}"
        f"{user_id}-"
        f"{secrets.token_hex(8)}"
    )

    try:
        # Do not require a UNIQUE(user_id, file_code) constraint here.
        # The provider-specific flow already reuses active transactions.
        purchase = await fetchrow(
            """
            INSERT INTO file_purchases
            (
                user_id,
                file_code,
                owner_id,
                paid_price,
                payment_id,
                status,
                created_at,
                paid_at,
                qr_image,
                payment_url,
                expires_at,
                qr_message_id,
                qr_chat_id,
                media_session_id
            )
            VALUES
            (
                $1,
                $2,
                $3,
                $4,
                $5,
                'pending',
                NOW(),
                NULL,
                NULL,
                NULL,
                NULL,
                NULL,
                NULL,
                NULL
            )
            RETURNING *
            """,
            user_id,
            code,
            file.get("owner_id"),
            safe_int(file.get("price")),
            payment_id,
        )
    except Exception:
        logger.exception(
            "CREATE PURCHASE DB ERROR | user=%s | code=%s | method=%s",
            user_id,
            code,
            payment_prefix,
        )
        # Never create another payment after an unexpected DB error.
        # Re-read the existing transaction before reporting failure.
        existing = await get_active_method_purchase(
            user_id,
            code,
            payment_prefix,
        )
        if existing:
            return {
                "purchase": existing,
                "already_paid": False,
                "existing": True,
            }
        paid = await get_paid_purchase(user_id, code)
        if paid:
            return {
                "purchase": paid,
                "already_paid": True,
                "existing": True,
            }
        return None

    if purchase:
        logger.info(
            "PURCHASE CREATED | id=%s | user=%s | code=%s | method=%s",
            purchase.get("id"),
            user_id,
            code,
            payment_prefix,
        )
        return {
            "purchase": purchase,
            "already_paid": False,
            "existing": False,
        }

    paid = await get_paid_purchase(user_id, code)
    if paid:
        return {
            "purchase": paid,
            "already_paid": True,
            "existing": True,
        }

    # If another callback created an active row first, reuse it regardless
    # of provider/method.
    active_any = await fetchrow(
        """
        SELECT *
        FROM file_purchases
        WHERE user_id=$1
          AND LOWER(TRIM(file_code)) = LOWER(TRIM($2))
          AND status IN ('pending','verifying')
        ORDER BY id DESC
        LIMIT 1
        """,
        user_id,
        code,
    )
    if active_any:
        logger.info(
            "PURCHASE REUSED AFTER CONFLICT | id=%s | user=%s | code=%s | method=%s",
            active_any.get("id"),
            user_id,
            code,
            purchase_method(active_any),
        )
        return {
            "purchase": active_any,
            "already_paid": False,
            "existing": True,
        }

    # The unique row exists, but it is not active for this payment method.
    # This can happen when an old row is failed/expired/rejected. Do not
    # blindly INSERT because the unique constraint still protects the pair.
    row = await fetchrow(
        """
        SELECT *
        FROM file_purchases
        WHERE user_id=$1
          AND file_code=$2
        ORDER BY
            CASE
                WHEN status='paid' THEN 0
                WHEN status IN ('pending','verifying') THEN 1
                ELSE 2
            END,
            id DESC
        LIMIT 1
        """,
        user_id,
        code,
    )
    if row:
        status = normalize_status(row.get("status"))
        if status in REUSABLE_PURCHASE_STATUSES:
            try:
                reused = await fetchrow(
                    """
                    UPDATE file_purchases
                    SET
                        owner_id=$1,
                        paid_price=$2,
                        payment_id=$3,
                        status='pending',
                        created_at=NOW(),
                        paid_at=NULL,
                        qr_image=NULL,
                        payment_url=NULL,
                        expires_at=NULL,
                        qr_message_id=NULL,
                        qr_chat_id=NULL,
                        media_session_id=NULL,
                        gateway_order_id=NULL
                    WHERE id=$4
                      AND user_id=$5
                      AND file_code=$6
                      AND status IN (
                          'failed',
                          'rejected',
                          'expired',
                          'cancel',
                          'cancelled',
                          'canceled'
                      )
                    RETURNING *
                    """,
                    file.get("owner_id"),
                    safe_int(file.get("price")),
                    payment_id,
                    row["id"],
                    user_id,
                    code,
                )
                if reused:
                    logger.info(
                        "PURCHASE REACTIVATED | id=%s | user=%s | code=%s | method=%s",
                        reused.get("id"),
                        user_id,
                        code,
                        payment_prefix,
                    )
                    return {
                        "purchase": reused,
                        "already_paid": False,
                        "existing": False,
                    }
            except Exception:
                logger.exception(
                    "REACTIVATE PURCHASE ERROR | id=%s | user=%s | code=%s",
                    row.get("id"),
                    user_id,
                    code,
                )

        if status == "paid":
            return {
                "purchase": row,
                "already_paid": True,
                "existing": True,
            }

    logger.error(
        "PURCHASE CONFLICT UNRESOLVED | user=%s | code=%s | method=%s",
        user_id,
        code,
        payment_prefix,
    )
    return None

# ============================================================
# CASHI HEADERS
# ============================================================
def cashi_headers() -> dict:
    return {
        "x-api-key": str(
            CASHI_API_KEY or ""
        ).strip(),
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": "MKTPLBot/1.0",
    }
# ============================================================
# CASHI CREATE ORDER
# ============================================================
async def cashi_create_order(
    amount: int,
    order_id: str,
):
    if not CASHI_API_KEY:
        return {
            "ok": False,
            "definitive": True,
            "data": None,
            "error": (
                "CASHI_API_KEY belum dikonfigurasi."
            ),
        }
    payload = {
        "amount": int(amount),
        "order_id": str(order_id),
        "kode_channel": "QRIS_CUSTOM",
    }
    logger.info(
        (
            "CASHI CREATE REQUEST "
            "| order=%s | amount=%s"
        ),
        order_id,
        amount,
    )
    try:
        timeout = aiohttp.ClientTimeout(
            total=35,
            connect=10,
            sock_read=25,
        )
        async with aiohttp.ClientSession(
            timeout=timeout
        ) as session:
            async with session.post(
                CASHI_CREATE_URL,
                headers=cashi_headers(),
                json=payload,
            ) as response:
                raw_text = await response.text()
                logger.info(
                    (
                        "CASHI CREATE RESPONSE "
                        "| HTTP=%s | BODY=%s"
                    ),
                    response.status,
                    raw_text[:3000],
                )
                try:
                    data = json.loads(
                        raw_text
                    )
                except Exception:
                    return {
                        "ok": False,
                        "definitive": (
                            400
                            <= response.status
                            < 500
                        ),
                        "data": None,
                        "error": (
                            "Response Cashi bukan JSON."
                        ),
                    }
                if (
                    response.status < 200
                    or response.status >= 300
                ):
                    definitive = (
                        400
                        <= response.status
                        < 500
                    )
                    returned_order = (
                        extract_cashi_order_id(
                            data
                        )
                    )
                    if returned_order:
                        definitive = False
                    return {
                        "ok": False,
                        "definitive": definitive,
                        "data": data,
                        "error": (
                            f"HTTP {response.status}"
                        ),
                    }
                success = data.get(
                    "success"
                )
                if success is False:
                    returned_order = (
                        extract_cashi_order_id(
                            data
                        )
                    )
                    if returned_order:
                        return {
                            "ok": True,
                            "definitive": False,
                            "data": data,
                            "error": (
                                "Cashi success=false "
                                "tetapi order ID tersedia."
                            ),
                        }
                    return {
                        "ok": False,
                        "definitive": True,
                        "data": data,
                        "error": (
                            data.get("message")
                            or data.get("error")
                            or "Cashi menolak pembayaran."
                        ),
                    }
                return {
                    "ok": True,
                    "definitive": False,
                    "data": data,
                    "error": None,
                }
    except asyncio.CancelledError:
        raise
    except (
        asyncio.TimeoutError,
        aiohttp.ClientConnectionError,
        aiohttp.ClientPayloadError,
        aiohttp.ServerTimeoutError,
    ):
        logger.exception(
            (
                "CASHI CREATE UNKNOWN RESULT "
                "| order=%s"
            ),
            order_id,
        )
        return {
            "ok": False,
            "definitive": False,
            "data": None,
            "error": (
                "Timeout/koneksi Cashi."
            ),
        }
    except Exception:
        logger.exception(
            (
                "CASHI CREATE ORDER EXCEPTION "
                "| order=%s"
            ),
            order_id,
        )
        return {
            "ok": False,
            "definitive": False,
            "data": None,
            "error": (
                "Error koneksi Cashi."
            ),
        }
# ============================================================
# CASHI CHECK STATUS
# ============================================================
async def cashi_check_status(
    order_id: str,
):
    if not CASHI_API_KEY:
        return None
    order_id = str(
        order_id or ""
    ).strip()
    if not order_id:
        return None
    url = (
        f"{CASHI_BASE_URL}"
        f"/api/check-status/"
        f"{order_id}"
    )
    logger.info(
        "CASHI STATUS REQUEST | order=%s",
        order_id,
    )
    try:
        timeout = aiohttp.ClientTimeout(
            total=25,
            connect=10,
            sock_read=20,
        )
        async with aiohttp.ClientSession(
            timeout=timeout
        ) as session:
            async with session.get(
                url,
                headers=cashi_headers(),
            ) as response:
                raw_text = await response.text()
                logger.info(
                    (
                        "CASHI STATUS RESPONSE "
                        "| HTTP=%s | BODY=%s"
                    ),
                    response.status,
                    raw_text[:3000],
                )
                try:
                    data = json.loads(
                        raw_text
                    )
                except Exception:
                    return None
                if (
                    response.status < 200
                    or response.status >= 300
                ):
                    return None
                return data
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.exception(
            "CASHI CHECK STATUS EXCEPTION"
        )
        return None
# ============================================================
# DOWNLOAD CASHI QR
# ============================================================
async def download_qr_from_cashi(
    qr_url: str,
) -> bytes | None:
    if not qr_url:
        return None
    qr_url = str(
        qr_url
    ).strip()
    # ========================================================
    # DATA URI
    # ========================================================
    if qr_url.startswith(
        "data:image/"
    ):
        try:
            header, encoded = (
                qr_url.split(
                    ",",
                    1,
                )
            )
            if ";base64" not in (
                header.lower()
            ):
                logger.error(
                    "CASHI QR DATA URI BUKAN BASE64"
                )
                return None
            content = base64.b64decode(
                encoded,
                validate=True,
            )
            if not content:
                logger.error(
                    "CASHI QR DATA URI KOSONG"
                )
                return None
            is_png = content.startswith(
                b"\x89PNG\r\n\x1a\n"
            )
            is_jpeg = content.startswith(
                b"\xff\xd8\xff"
            )
            is_webp = (
                len(content) >= 12
                and content[:4] == b"RIFF"
                and content[8:12] == b"WEBP"
            )
            if not (
                is_png
                or is_jpeg
                or is_webp
            ):
                logger.error(
                    "CASHI QR DATA URI BUKAN IMAGE VALID"
                )
                return None
            logger.info(
                (
                    "CASHI QR DATA URI DECODED "
                    "| size=%s"
                ),
                len(content),
            )
            return content
        except Exception:
            logger.exception(
                "DECODE CASHI QR DATA URI ERROR"
            )
            return None
    # ========================================================
    # HTTP / HTTPS
    # ========================================================
    if not qr_url.startswith(
        (
            "http://",
            "https://",
        )
    ):
        logger.error(
            "INVALID CASHI QR URL | %s",
            qr_url[:200],
        )
        return None
    logger.info(
        "DOWNLOAD CASHI QR | URL=%s",
        qr_url,
    )
    try:
        timeout = aiohttp.ClientTimeout(
            total=30,
            connect=10,
            sock_read=20,
        )
        headers = {
            "User-Agent": (
                "Mozilla/5.0 "
                "(Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 "
                "(KHTML, like Gecko) "
                "Chrome/131.0 Safari/537.36"
            ),
            "Accept": (
                "image/png,"
                "image/jpeg,"
                "image/webp,"
                "image/*,"
                "*/*;q=0.8"
            ),
        }
        async with aiohttp.ClientSession(
            timeout=timeout
        ) as session:
            async with session.get(
                qr_url,
                headers=headers,
                allow_redirects=True,
            ) as response:
                content = await response.read()
                content_type = (
                    response.headers.get(
                        "Content-Type",
                        "",
                    )
                    .lower()
                    .strip()
                )
                logger.info(
                    (
                        "CASHI QR RESPONSE "
                        "| HTTP=%s | TYPE=%s "
                        "| SIZE=%s | FINAL_URL=%s"
                    ),
                    response.status,
                    content_type,
                    len(content),
                    str(response.url),
                )
                if response.status != 200:
                    logger.error(
                        (
                            "CASHI QR DOWNLOAD FAILED "
                            "| HTTP=%s"
                        ),
                        response.status,
                    )
                    return None
                if not content:
                    return None
                is_png = content.startswith(
                    b"\x89PNG"
                )
                is_jpeg = content.startswith(
                    b"\xff\xd8\xff"
                )
                is_webp = (
                    content.startswith(
                        b"RIFF"
                    )
                    and content[8:12]
                    == b"WEBP"
                )
                if (
                    "image/" not in content_type
                    and not is_png
                    and not is_jpeg
                    and not is_webp
                ):
                    logger.error(
                        (
                            "CASHI QR RESPONSE "
                            "BUKAN IMAGE | TYPE=%s"
                        ),
                        content_type,
                    )
                    return None
                return content
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.exception(
            "DOWNLOAD CASHI QR EXCEPTION"
        )
        return None
# ============================================================
# SEND CASHI QR
# ============================================================
async def send_cashi_qr(
    message: Message,
    qr_url: str,
    caption: str,
    reply_markup=None,
):
    qr_bytes = await download_qr_from_cashi(
        qr_url
    )
    if not qr_bytes:
        return None
    try:
        photo = BufferedInputFile(
            qr_bytes,
            filename="cashi_qris.png",
        )
        sent = await message.answer_photo(
            photo=photo,
            caption=caption,
            parse_mode="HTML",
            reply_markup=reply_markup,
        )
        logger.info(
            (
                "CASHI QR SENT "
                "| message_id=%s"
            ),
            sent.message_id,
        )
        return sent
    except Exception:
        logger.exception(
            "TELEGRAM SEND CASHI QR ERROR"
        )
        return None
# ============================================================
# CASHI PAYMENT KEYBOARD
# ============================================================
async def payment_check_keyboard(
    code: str,
    purchase_id: int,
):
    token = await create_callback_token(
        "paymentcheck",
        {
            "code": str(code).strip(),
            "purchase_id": int(
                purchase_id
            ),
        },
    )
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🔄 Cek Pembayaran",
                    callback_data=(
                        f"paymentcheck:{token}"
                    ),
                )
            ],
            [
                InlineKeyboardButton(
                    text="❌ Tutup",
                    callback_data="close",
                )
            ],
        ]
    )
# ============================================================
# MANUAL KEYBOARD
# ============================================================
async def manual_payment_keyboard(
    code: str,
):
    token = await create_callback_token(
        "manualcheck",
        {
            "code": str(code).strip(),
        },
    )
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Saya Sudah Bayar",
                    callback_data=(
                        f"manualcheck:{token}"
                    ),
                )
            ],
            [
                InlineKeyboardButton(
                    text="❌ Tutup",
                    callback_data="close",
                )
            ],
        ]
    )
# ============================================================
# SHOW EXISTING CASHI
# ============================================================
async def show_existing_cashi(
    call: CallbackQuery,
    purchase,
    file,
):
    purchase_id = safe_int(
        purchase.get("id")
    )
    if purchase_id <= 0:
        return await call.message.answer(
            "❌ ID transaksi tidak valid."
        )
    gateway_order_id = str(
        purchase.get(
            "gateway_order_id"
        )
        or ""
    ).strip()
    # Compatibility dengan transaksi lama:
    # sebelum gateway_order_id ditambahkan, payment_id
    # bisa saja berisi order Cashi.
    if not gateway_order_id:
        payment_id = str(
            purchase.get(
                "payment_id"
            )
            or ""
        ).strip()
        if (
            not payment_id.startswith(
                "CASHI-"
            )
            and payment_id
        ):
            gateway_order_id = payment_id
    if not gateway_order_id:
        return await call.message.answer(
            "❌ ID pembayaran Cashi tidak valid."
        )
    status_data = await cashi_check_status(
        gateway_order_id
    )
    if status_data:
        status = extract_cashi_status(
            status_data
        )
        if status in SUCCESS_STATUSES:
            return await process_existing_success(
                call,
                purchase,
                file,
            )
        if status in FAILED_STATUSES:
            changed = await fetchrow(
                """
                UPDATE file_purchases
                SET status=$1
                WHERE id=$2
                  AND status='pending'
                RETURNING *
                """,
                status,
                purchase_id,
            )
            if changed:
                return await call.message.answer(
                    (
                        "⚠️ <b>Pembayaran Cashi sebelumnya "
                        "gagal/expired.</b>\n\n"
                        "Silakan pilih metode pembayaran baru."
                    ),
                    parse_mode="HTML",
                    reply_markup=await payment_method_keyboard(
                        file["code"], call.from_user.id
                    ),
                )
    qr_url = str(
        purchase.get("qr_image")
        or ""
    ).strip()
    payment_url = str(
        purchase.get("payment_url")
        or ""
    ).strip()
    keyboard = await payment_check_keyboard(
        file["code"],
        purchase_id,
    )
    price = safe_int(
        file.get("price")
    )
    caption = (
        "💳 <b>PEMBAYARAN CASHI</b>\n\n"
        f"📄 <b>{clean_html(file.get('title'))}</b>\n\n"
        f"🔑 Code:\n"
        f"<code>{clean_html(file['code'])}</code>\n\n"
        f"💰 <b>{format_rupiah(price)}</b>\n\n"
        "Scan QR di atas.\n"
        "Setelah membayar, tekan "
        "<b>🔄 Cek Pembayaran</b>.\n\n"
        "⚠️ Jangan melakukan pembayaran dua kali."
    )
    if qr_url:
        sent = await send_cashi_qr(
            call.message,
            qr_url,
            caption,
            keyboard,
        )
        if sent:
            await execute(
                """
                UPDATE file_purchases
                SET
                    qr_message_id=$1,
                    qr_chat_id=$2
                WHERE id=$3
                  AND status='pending'
                """,
                sent.message_id,
                sent.chat.id,
                purchase_id,
            )
            return
        if payment_url:
            await call.message.answer(
                (
                    "⚠️ <b>QR tidak dapat ditampilkan.</b>\n\n"
                    "Pembayaran Cashi tetap aktif."
                ),
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(
                    inline_keyboard=[
                        [
                            InlineKeyboardButton(
                                text="💳 Buka Pembayaran",
                                url=payment_url,
                            )
                        ],
                        [
                            keyboard.inline_keyboard[0][0]
                        ],
                    ]
                ),
            )
            return
    if payment_url:
        await call.message.answer(
            (
                "💳 <b>PEMBAYARAN CASHI</b>\n\n"
                f"📄 <b>{clean_html(file.get('title'))}</b>\n\n"
                f"💰 <b>{format_rupiah(price)}</b>\n\n"
                "Silakan lanjutkan pembayaran."
            ),
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="💳 Bayar Sekarang",
                            url=payment_url,
                        )
                    ],
                    [
                        keyboard.inline_keyboard[0][0]
                    ],
                    [
                        InlineKeyboardButton(
                            text="❌ Tutup",
                            callback_data="close",
                        )
                    ],
                ]
            ),
        )
        return
    await call.message.answer(
        (
            "⚠️ <b>Pembayaran Cashi sudah dibuat.</b>\n\n"
            "QR/link pembayaran belum tersedia.\n\n"
            "❗ Jangan membuat transaksi baru.\n"
            "Silakan coba cek kembali beberapa saat lagi."
        ),
        parse_mode="HTML",
        reply_markup=keyboard,
    )
# ============================================================
# SHOW EXISTING MANUAL
# ============================================================
async def show_existing_manual(
    call: CallbackQuery,
    purchase,
    file,
):
    """Resend the manual QR for an existing pending manual purchase."""
    pool = await database_pool()
    enabled = str(
        await pool.fetchval(
            "SELECT value FROM settings WHERE key=$1",
            "payment_manual_enabled",
        ) or "off"
    ).lower() in {"on", "1", "true", "yes"}
    qr_file_id = str(
        await pool.fetchval(
            "SELECT value FROM settings WHERE key=$1",
            "manual_qr_file_id",
        ) or MANUAL_QR_FILE_ID or ""
    ).strip()
    if not enabled or not qr_file_id:
        return await call.message.answer(
            "❌ QR manual belum tersedia. Admin perlu menjalankan /qrid dan mengatur QR Manual terlebih dahulu."
        )

    keyboard = await manual_payment_keyboard(file["code"])
    price = safe_int(file.get("price"))
    caption = (
        "📷 <b>PEMBAYARAN MANUAL</b>\n\n"
        f"📄 File: <b>{clean_html(file.get('title'))}</b>\n"
        f"🔑 Code: <code>{clean_html(file['code'])}</code>\n"
        f"💰 Harga: <b>{format_rupiah(price)}</b>\n\n"
        "Scan QR manual di atas, bayar sesuai nominal, lalu tekan "
        "<b>✅ Saya Sudah Bayar</b>."
    )
    msg = None
    try:
        msg = await call.bot.send_photo(
            chat_id=call.from_user.id, photo=qr_file_id,
            caption=caption, parse_mode="HTML", reply_markup=keyboard,
        )
    except Exception:
        logger.exception("MANUAL QR existing send_photo failed")
        try:
            msg = await call.bot.send_document(
                chat_id=call.from_user.id, document=qr_file_id,
                caption=caption, parse_mode="HTML", reply_markup=keyboard,
            )
        except Exception:
            logger.exception("MANUAL QR existing send_document failed")
    if not msg:
        return await call.message.answer(
            "❌ QR Manual gagal dikirim. Admin perlu set QR Manual ulang dengan /qrid."
        )
    try:
        await execute(
            "UPDATE file_purchases SET qr_message_id=$1, qr_chat_id=$2 WHERE id=$3 AND status='pending'",
            msg.message_id, msg.chat.id, purchase["id"],
        )
    except Exception:
        logger.exception("Failed updating manual QR message metadata")

# ============================================================
# CREATE MANUAL PAYMENT
# ============================================================
async def create_manual_payment(
    call: CallbackQuery,
    code: str,
    file,
):
    pool = await database_pool()

    enabled = str(
        await pool.fetchval(
            "SELECT value FROM settings WHERE key=$1",
            "payment_manual_enabled",
        ) or "off"
    ).lower() in {"on", "1", "true", "yes"}

    qr_file_id = str(
        await pool.fetchval(
            "SELECT value FROM settings WHERE key=$1",
            "manual_qr_file_id",
        ) or ""
    ).strip()

    if not enabled or not qr_file_id:
        return await call.message.answer(
            "❌ QR manual belum tersedia. Admin perlu mengatur QR Manual terlebih dahulu."
        )

    user_id = int(call.from_user.id)
    code = str(file.get("code") or code).strip()

    paid = await get_paid_purchase(user_id, code)
    if paid:
        from handlers.getfile import process_code
        return await process_code(call.message, code, paid_override=True, user_id=call.from_user.id)

    # Reuse an existing pending manual transaction if one exists.
    existing = await get_active_method_purchase(user_id, code, "MANUAL-")
    if existing:
        return await show_existing_manual(call, existing, file)

    result = await get_or_create_purchase(
        user_id=user_id,
        code=code,
        file=file,
        payment_prefix="MANUAL-",
    )

    if not result:
        return await call.message.answer("❌ Gagal membuat transaksi.")

    purchase = result["purchase"]

    if result.get("already_paid"):
        from handlers.getfile import process_code
        return await process_code(call.message, code, paid_override=True, user_id=call.from_user.id)

    if result.get("existing"):
        existing_method = purchase_method(purchase)
        if existing_method == "manual":
            return await show_existing_manual(call, purchase, file)
        if existing_method == "cashi":
            return await show_existing_cashi(call, purchase, file)
        return await call.message.answer(
            "⚠️ Transaksi pembayaran sudah ada. Silakan gunakan transaksi tersebut."
        )

    return await send_manual_payment(call, purchase, file)

# ============================================================
# SEND MANUAL PAYMENT
# ============================================================
async def send_manual_payment(
    call: CallbackQuery,
    purchase,
    file,
):
    pool = await database_pool()

    enabled = str(
        await pool.fetchval(
            "SELECT value FROM settings WHERE key=$1",
            "payment_manual_enabled",
        ) or "off"
    ).lower() in {"on", "1", "true", "yes"}

    qr_file_id = str(
        await pool.fetchval(
            "SELECT value FROM settings WHERE key=$1",
            "manual_qr_file_id",
        ) or ""
    ).strip()

    if not enabled or not qr_file_id:
        return await call.message.answer(
            "❌ QR manual belum tersedia. Admin perlu mengatur QR Manual terlebih dahulu."
        )

    code = str(file.get("code") or "").strip()
    price = safe_int(file.get("price"))
    keyboard = await manual_payment_keyboard(code)

    caption = (
        "📷 <b>PEMBAYARAN MANUAL</b>\n\n"
        f"📄 File:\n<b>{clean_html(file.get('title'))}</b>\n\n"
        f"🔑 Code:\n<code>{clean_html(code)}</code>\n\n"
        f"💰 Harga:\n<b>{format_rupiah(price)}</b>\n\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "📌 <b>Cara Pembayaran</b>\n\n"
        "1️⃣ Scan QR manual\n"
        "2️⃣ Bayar sesuai nominal\n"
        "3️⃣ Pastikan pembayaran berhasil\n"
        "4️⃣ Tekan <b>✅ Saya Sudah Bayar</b>\n\n"
        "⚠️ Setelah menekan tombol, admin akan memverifikasi pembayaran."
    )

    msg = None

    # QR from admin is stored as a Telegram file_id. Send it directly.
    try:
        msg = await call.bot.send_photo(
            chat_id=call.from_user.id,
            photo=qr_file_id,
            caption=caption,
            parse_mode="HTML",
            reply_markup=keyboard,
        )
    except Exception:
        logger.exception("MANUAL QR send_photo failed; trying document fallback")
        try:
            msg = await call.bot.send_document(
                chat_id=call.from_user.id,
                document=qr_file_id,
                caption=caption,
                parse_mode="HTML",
                reply_markup=keyboard,
            )
        except Exception:
            logger.exception("MANUAL QR send_document failed")

    if not msg:
        return await call.message.answer(
            "❌ QR Manual gagal dikirim. Silakan admin Set QR Manual ulang dengan mengirim QR sebagai foto."
        )

    await execute(
        """
        UPDATE file_purchases
        SET qr_message_id=$1, qr_chat_id=$2
        WHERE id=$3 AND status='pending'
        """,
        msg.message_id,
        msg.chat.id,
        purchase["id"],
    )

# ============================================================
# CLAIM PURCHASE PAID
# ============================================================
async def claim_purchase_paid(
    purchase_id: int,
    user_id: int,
    file_code: str,
    allowed_statuses: tuple = (
        "pending",
        "verifying",
    ),
):
    purchase_id = int(
        purchase_id
    )
    user_id = int(
        user_id
    )
    file_code = str(
        file_code
    ).strip()
    if not purchase_id:
        return None
    placeholders = ",".join(
        f"'{status}'"
        for status in allowed_statuses
    )
    query = f"""
        UPDATE file_purchases
        SET
            status='paid',
            code=$3,
            file_code=$3,
            paid_at=COALESCE(
                paid_at,
                NOW()
            )
        WHERE id=$1
          AND user_id=$2
          AND (
              LOWER(TRIM(COALESCE(file_code, ''))) = LOWER(TRIM($3))
              OR LOWER(TRIM(COALESCE(code, ''))) = LOWER(TRIM($3))
          )
          AND status IN ({placeholders})
          AND NOT EXISTS (
              SELECT 1
              FROM file_purchases p2
              WHERE p2.user_id=$2
                AND p2.file_code=$3
                AND p2.status='paid'
                AND p2.id<>$1
          )
        RETURNING *
    """
    try:
        updated = await fetchrow(
            query,
            purchase_id,
            user_id,
            file_code,
        )
        if updated:
            return updated
        logger.info(
            (
                "PAYMENT CLAIM LOST "
                "| purchase=%s | user=%s | code=%s"
            ),
            purchase_id,
            user_id,
            file_code,
        )
        return None
    except Exception as exc:
        error_text = str(
            exc
        ).lower()
        if (
            "uq_file_purchases_one_paid"
            in error_text
        ) or (
            "duplicate key"
            in error_text
        ):
            logger.warning(
                (
                    "PAYMENT ALREADY WON "
                    "| purchase=%s"
                ),
                purchase_id,
            )
            return None
        logger.exception(
            "CLAIM PAYMENT ERROR"
        )
        raise
# ============================================================
# CANCEL OTHER PAYMENT ATTEMPTS
# ============================================================
async def cancel_other_active_payments(
    user_id: int,
    file_code: str,
    winner_id: int,
):
    try:
        await execute(
            """
            UPDATE file_purchases
            SET status='cancelled'
            WHERE user_id=$1
              AND file_code=$2
              AND id<>$3
              AND status IN (
                  'pending',
                  'verifying'
              )
            """,
            int(user_id),
            str(file_code).strip(),
            int(winner_id),
        )
    except Exception:
        logger.exception(
            (
                "CANCEL OTHER PAYMENTS ERROR "
                "| winner=%s"
            ),
            winner_id,
        )
# ============================================================
# CASHI PAYMENT CHECK
# ============================================================
@router.callback_query(
    F.data.startswith("paymentcheck:")
)
async def check_cashi_payment(
    call: CallbackQuery,
):
    await call.answer(
        "🔄 Mengecek pembayaran..."
    )
    try:
        token = call.data.split(
            ":",
            1,
        )[1].strip()
    except (
        AttributeError,
        IndexError,
    ):
        return await call.message.answer(
            "❌ Permintaan tidak valid."
        )
    data = await get_callback_token(
        "paymentcheck",
        token,
    )
    if not data:
        return await call.message.answer(
            "❌ Tombol pembayaran sudah expired."
        )
    code = str(
        data.get("code")
        or ""
    ).strip()
    purchase_id = safe_int(
        data.get("purchase_id")
    )
    if not code or purchase_id <= 0:
        return await call.message.answer(
            "❌ Data pembayaran tidak valid."
        )
    user_id = int(
        call.from_user.id
    )
    lock_key = (
        f"cashi-check:"
        f"{user_id}:"
        f"{purchase_id}"
    )
    try:
        if await safe_get(
            lock_key
        ):
            return await call.message.answer(
                "⏳ Pembayaran sedang dicek..."
            )
        await safe_set(
            lock_key,
            True,
            ex=CHECK_LOCK,
        )
    except Exception:
        logger.warning(
            "CASHI CHECK LOCK ERROR",
            exc_info=True,
        )
    purchase = await fetchrow(
        """
        SELECT *
        FROM file_purchases
        WHERE id=$1
          AND user_id=$2
          AND file_code=$3
        LIMIT 1
        """,
        purchase_id,
        user_id,
        code,
    )
    if not purchase:
        return await call.message.answer(
            "❌ Transaksi tidak ditemukan."
        )
    method = purchase_method(
        purchase
    )
    if method != "cashi":
        return await call.message.answer(
            "❌ Ini bukan transaksi Cashi."
        )
    current_status = normalize_status(
        purchase.get("status")
    )
    if current_status == "paid":
        return await call.message.answer(
            "✅ Pembayaran ini sudah berhasil diproses."
        )
    if current_status not in {
        "pending",
        "verifying",
    }:
        return await call.message.answer(
            (
                "ℹ️ Transaksi sudah tidak berada "
                "dalam status pembayaran aktif."
            )
        )
    gateway_order_id = str(
        purchase.get(
            "gateway_order_id"
        )
        or ""
    ).strip()
    # Compatibility transaksi lama.
    if not gateway_order_id:
        old_payment_id = str(
            purchase.get(
                "payment_id"
            )
            or ""
        ).strip()
        if old_payment_id:
            gateway_order_id = old_payment_id
    if not gateway_order_id:
        return await call.message.answer(
            "❌ Gateway order ID tidak ditemukan."
        )
    status_data = await cashi_check_status(
        gateway_order_id
    )
    if not status_data:
        return await call.message.answer(
            (
                "⚠️ <b>Cashi belum dapat dihubungi.</b>\n\n"
                "Transaksi tetap aktif.\n"
                "Silakan coba lagi beberapa saat."
            ),
            parse_mode="HTML",
        )
    status = extract_cashi_status(
        status_data
    )
    logger.info(
        (
            "CASHI STATUS PARSED "
            "| purchase=%s | gateway=%s "
            "| status=%s"
        ),
        purchase["id"],
        gateway_order_id,
        status,
    )
    if status in SUCCESS_STATUSES:
        file = await get_file_by_code(
            code
        )
        if not file:
            return await call.message.answer(
                "❌ File transaksi tidak ditemukan."
            )
        return await process_existing_success(
            call,
            purchase,
            file,
        )
    if status in FAILED_STATUSES:
        changed = await fetchrow(
            """
            UPDATE file_purchases
            SET status=$1
            WHERE id=$2
              AND status IN ('pending','verifying')
            RETURNING *
            """,
            status,
            purchase_id,
        )
        if not changed:
            return await call.message.answer(
                "⚠️ Transaksi sudah diproses."
            )
        return await call.message.answer(
            (
                "❌ <b>Pembayaran tidak berhasil.</b>\n\n"
                f"Status Cashi: "
                f"<code>{clean_html(status.upper())}</code>\n\n"
                "Silakan melakukan pembayaran baru."
            ),
            parse_mode="HTML",
            reply_markup=await payment_method_keyboard(
                code, call.from_user.id
            ),
        )
    return await call.message.answer(
        (
            "⏳ <b>Pembayaran belum terkonfirmasi.</b>\n\n"
            "Cashi belum memberikan status berhasil.\n\n"
            "Jika kamu sudah membayar, tunggu beberapa detik "
            "kemudian tekan <b>🔄 Cek Pembayaran</b> lagi.\n\n"
            "⚠️ Jangan membayar ulang."
        ),
        parse_mode="HTML",
    )
# ============================================================
# PROCESS SUCCESS
# ============================================================
async def process_existing_success(
    call: CallbackQuery,
    purchase,
    file,
):
    user_id = safe_int(
        purchase.get("user_id")
    )
    # Jangan kirim "berhasil" sebelum transaksi benar-benar
    # memenangkan claim paid.
    return await finish_payment(
        call.bot,
        purchase,
        file,
        purchase.get("payment_id"),
        call.message,
    )
# ============================================================
# COMMON SUCCESS SIDE EFFECTS
# ============================================================
async def complete_success_side_effects(
    bot,
    purchase,
    file,
    invoice,
    message,
    media_list,
):
    purchase_id = safe_int(
        purchase.get("id")
    )
    user_id = safe_int(
        purchase.get("user_id")
    )
    code = str(
        file.get("code")
        or ""
    ).strip()
    # ========================================================
    # MEDIA SESSION
    # ========================================================
    media_id = secrets.token_hex(
        16
    )
    session_data = {
        "user_id": user_id,
        "media": media_list,
        "share_media": bool(
            file.get(
                "share_media",
                False,
            )
        ),
        "invoice": invoice,
        "purchase_id": purchase_id,
    }
    try:
        await safe_set(
            f"paidmedia:{media_id}",
            session_data,
            ex=MEDIA_TTL,
        )
        await execute(
            """
            UPDATE file_purchases
            SET media_session_id=$1
            WHERE id=$2
              AND status='paid'
            """,
            media_id,
            purchase_id,
        )
    except Exception:
        logger.exception(
            "MEDIA SESSION CREATE ERROR"
        )
        return False
    # ========================================================
    # BUY COUNT
    # ========================================================
    try:
        await execute(
            """
            UPDATE files
            SET
                buy_count=COALESCE(
                    buy_count,
                    0
                ) + 1,
                sold=COALESCE(
                    sold,
                    0
                ) + 1
            WHERE code=$1
            """,
            code,
        )
    except Exception:
        logger.exception(
            "BUY COUNT UPDATE ERROR"
        )
    # ========================================================
    # FREE CODE PROGRESS
    # ========================================================
    try:
        completed_rows = await fetch(
            """
            UPDATE free_code_progress
            SET
                purchase_count=LEAST(
                    3,
                    COALESCE(
                        purchase_count,
                        0
                    ) + 1
                ),
                completed=(
                    LEAST(
                        3,
                        COALESCE(
                            purchase_count,
                            0
                        ) + 1
                    ) >= 3
                ),
                completed_at=CASE
                    WHEN LEAST(
                        3,
                        COALESCE(
                            purchase_count,
                            0
                        ) + 1
                    ) >= 3
                    THEN COALESCE(
                        completed_at,
                        NOW()
                    )
                    ELSE completed_at
                END
            WHERE code=$1
              AND user_id=$2
              AND completed=FALSE
            RETURNING
                user_id,
                purchase_count,
                completed
            """,
            code,
            user_id,
        )
        for row in completed_rows:
            if row["completed"]:
                try:
                    await bot.send_message(
                        row["user_id"],
                        (
                            "🎉 <b>Progress Code Free 3/3!</b>\n\n"
                            f"Code "
                            f"<code>{clean_html(code)}</code>\n"
                            "sudah mencapai 3 pembelian berhasil.\n\n"
                            "🔓 Code sekarang bisa dibuka gratis."
                        ),
                        parse_mode="HTML",
                    )
                except Exception:
                    logger.exception(
                        "FREE PROGRESS NOTIFY ERROR"
                    )
    except Exception:
        logger.exception(
            "FREE CODE PROGRESS ERROR"
        )
    # ========================================================
    # SELLER PROFIT
    # ========================================================
    try:
        price = safe_int(
            file.get("price")
        )
        income = int(
            price * 0.5
        )
        owner_id = file.get(
            "owner_id"
        )
        if owner_id and income > 0:
            await execute(
                """
                UPDATE users
                SET
                    balance=COALESCE(
                        balance,
                        0
                    ) + $1,
                    total_earn=COALESCE(
                        total_earn,
                        0
                    ) + $1
                WHERE chat_id=$2
                """,
                income,
                owner_id,
            )
            await execute(
                """
                INSERT INTO transactions
                (
                    user_id,
                    type,
                    amount,
                    description
                )
                VALUES
                ($1,$2,$3,$4)
                """,
                owner_id,
                "file_sale",
                income,
                f"Pendapatan file {code}",
            )
    except Exception:
        logger.exception(
            "SELLER PROFIT ERROR"
        )
    # ========================================================
    # NOTIFICATION CHANNEL
    # ========================================================
    try:
        if NOTIF_CHANNEL_ID:
            masked = mask_user_id(
                user_id
            )
            buy_url = (
                "https://t.me/mktplbot"
                f"?start={code}"
            )
            keyboard = InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="🛒 Buy Now",
                            url=buy_url,
                        )
                    ]
                ]
            )
            payment_name = (
                "CASHI"
                if purchase_method(
                    purchase
                ) == "cashi"
                else "MANUAL"
            )
            await bot.send_message(
                NOTIF_CHANNEL_ID,
                (
                    "💸 <b>FILE PAYMENT SUCCESS</b>\n\n"
                    f"📄 Judul: "
                    f"<b>{clean_html(file.get('title'))}</b>\n"
                    f"📁 Code: "
                    f"<code>{clean_html(code)}</code>\n"
                    f"👤 User: "
                    f"<code>{masked}</code>\n"
                    f"💰 Harga: "
                    f"<b>{format_rupiah(purchase.get('paid_price'))}</b>"
                ),
                parse_mode="HTML",
                reply_markup=keyboard,
            )
    except Exception:
        logger.exception(
            "PAYMENT NOTIFICATION ERROR"
        )
    # ========================================================
    # DELETE PAYMENT QR
    # ========================================================
    await delete_payment_message(
        bot,
        purchase,
    )
    # ========================================================
    # USER SUCCESS -> GET FILE / OPEN MENU
    # ========================================================
    # Setelah pembayaran sukses, jangan membuat menu pengiriman
    # kedua di pay.py. Gunakan satu-satunya flow resmi:
    # getfile.py -> open_menu.py -> page.py / sendall.py
    try:
        from handlers.getfile import process_code
        await process_code(
            message,
            code,
            paid_override=True,
        )
    except Exception:
        logger.exception(
            "REDIRECT TO OPEN MENU ERROR | code=%s user=%s",
            code,
            user_id,
        )
        try:
            await message.answer(
                "❌ File berhasil dibayar, tetapi menu file gagal dibuka. Silakan kirim CODE kembali."
            )
        except Exception:
            pass
    return True
# ============================================================
# FINISH CASHI PAYMENT
# ============================================================
async def finish_payment(
    bot,
    purchase,
    file,
    invoice,
    message,
):
    purchase_id = safe_int(
        purchase.get("id")
    )
    user_id = safe_int(
        purchase.get("user_id")
    )
    code = str(
        file.get("code")
        or purchase.get("file_code")
        or ""
    ).strip()
    if (
        purchase_id <= 0
        or user_id <= 0
        or not code
    ):
        return False
    try:
        media_list = parse_media(
            file.get("media")
        )
        if not media_list:
            await message.answer(
                "❌ Media file kosong."
            )
            return False
        # ----------------------------------------------------
        # CLAIM PAYMENT
        # ----------------------------------------------------
        updated = await claim_purchase_paid(
            purchase_id,
            user_id,
            code,
            allowed_statuses=(
                "pending",
                "verifying",
            ),
        )
        if not updated:
            paid = await get_paid_purchase(
                user_id,
                code,
            )
            if paid:
                try:
                    from handlers.getfile import process_code
                    await process_code(message, code, paid_override=True)
                    return True
                except Exception:
                    logger.exception("REOPEN PAID FILE ERROR | code=%s user=%s", code, user_id)
                    return False
            return False
        purchase = updated
        # ----------------------------------------------------
        # CANCEL OTHER PAYMENT METHODS
        # ----------------------------------------------------
        await cancel_other_active_payments(
            user_id,
            code,
            purchase_id,
        )
        # ----------------------------------------------------
        # SUCCESS MESSAGE
        # ----------------------------------------------------
        try:
            lang = await get_user_language(user_id)
            success_notice = {
                "id": "⏳ <b>Pembayaran berhasil terdeteksi.</b>\n\nSedang membuka file...",
                "en": "⏳ <b>Payment confirmed.</b>\n\nOpening your file...",
                "zh": "⏳ <b>支付已确认。</b>\n\n正在打开文件……",
            }[lang]
            await message.answer(success_notice, parse_mode="HTML")
        except Exception:
            pass
        return await complete_success_side_effects(
            bot,
            purchase,
            file,
            invoice,
            message,
            media_list,
        )
    except Exception:
        logger.exception(
            (
                "FINISH PAYMENT ERROR "
                "| purchase=%s"
            ),
            purchase_id,
        )
        return False
# ============================================================
# MANUAL PAYMENT CHECK
# ============================================================
@router.callback_query(
    F.data.startswith("manualcheck:")
)
async def manual_check(
    call: CallbackQuery,
):
    lang = await get_user_language(call.from_user.id)
    verify_ack = {
        "id": "⏳ Menunggu persetujuan admin...",
        "en": "⏳ Waiting for admin approval...",
        "zh": "⏳ 等待管理员审核……",
    }.get(lang, "⏳ Menunggu persetujuan admin...")
    await call.answer(verify_ack)
    try:
        token = call.data.split(
            ":",
            1,
        )[1].strip()
    except (
        AttributeError,
        IndexError,
    ):
        return await call.message.answer(
            "❌ Permintaan tidak valid."
        )
    callback_data = await get_callback_token(
        "manualcheck",
        token,
    )
    if not callback_data:
        return await call.message.answer(
            "❌ Tombol sudah expired."
        )
    code = str(
        callback_data.get("code")
        or ""
    ).strip()
    user_id = int(
        call.from_user.id
    )
    purchase = await get_active_method_purchase(
        user_id,
        code,
        "MANUAL-",
    )
    if not purchase:
        paid = await get_paid_purchase(
            user_id,
            code,
        )
        if paid:
            return await call.message.answer(
                "✅ Pembayaran sudah diverifikasi."
            )
        return await call.message.answer(
            "❌ Transaksi manual tidak ditemukan."
        )
    payment_id = str(
        purchase.get("payment_id")
        or ""
    ).strip()
    if not payment_id.startswith(
        "MANUAL-"
    ):
        return await call.message.answer(
            "❌ Transaksi ini bukan pembayaran manual."
        )
    purchase_id = safe_int(
        purchase.get("id")
    )
    lock_key = (
        f"manualverify:{purchase_id}"
    )
    try:
        if await safe_get(
            lock_key
        ):
            return await call.message.answer(
                (
                    "⏳ Permintaan verifikasi sudah "
                    "dikirim ke admin."
                )
            )
        await safe_set(
            lock_key,
            True,
            ex=VERIFY_REQUEST_TTL,
        )
    except Exception:
        logger.warning(
            "MANUAL VERIFY LOCK ERROR",
            exc_info=True,
        )
    file = await get_file_by_code(
        code
    )
    if not file:
        return await call.message.answer(
            "❌ File tidak ditemukan."
        )
    text = (
        "📥 <b>MANUAL PAYMENT CHECK</b>\n\n"
        f"👤 User: <code>{user_id}</code>\n"
        f"📄 File: <b>{clean_html(file.get('title'))}</b>\n"
        f"🔑 Code: <code>{clean_html(code)}</code>\n"
        f"💰 Harga: "
        f"<b>{format_rupiah(purchase.get('paid_price'))}</b>\n"
        f"🧾 ID: <code>{purchase_id}</code>\n"
        f"💳 Payment: "
        f"<code>{clean_html(payment_id)}</code>"
    )
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Approve",
                    callback_data=(
                        f"approve:{purchase_id}"
                    ),
                ),
                InlineKeyboardButton(
                    text="❌ Reject",
                    callback_data=(
                        f"reject:{purchase_id}"
                    ),
                ),
            ]
        ]
    )
    sent = 0
    for admin_id in get_admin_ids():
        try:
            await call.bot.send_message(
                admin_id,
                text,
                parse_mode="HTML",
                reply_markup=keyboard,
            )
            sent += 1
        except Exception:
            logger.exception(
                (
                    "SEND MANUAL ADMIN ERROR "
                    "| admin=%s"
                ),
                admin_id,
            )
    if sent == 0:
        return await call.message.answer(
            (
                "❌ Tidak ada admin yang dapat "
                "menerima permintaan."
            )
        )
    await call.message.answer(
        {
            "id": "✅ <b>Permintaan pembayaran terkirim.</b>\n\n⏳ Silakan tunggu persetujuan admin. File akan terbuka setelah admin menyetujui pembayaran.",
            "en": "✅ <b>Payment verification request sent.</b>\n\n⏳ Please wait for admin approval. The file will open after approval.",
            "zh": "✅ <b>付款审核请求已发送。</b>\n\n⏳ 请等待管理员批准。管理员批准后文件将自动打开。",
        }.get(lang, "✅ <b>Permintaan pembayaran terkirim.</b>\n\n⏳ Silakan tunggu persetujuan admin."),
        parse_mode="HTML",
    )
# ============================================================
# APPROVE MANUAL
# ============================================================
@router.callback_query(
    F.data.startswith("approve:")
)
async def approve_manual(
    call: CallbackQuery,
    state: FSMContext,
):
    if not is_admin(
        call.from_user.id
    ):
        return await call.answer(
            "❌ Kamu bukan admin.",
            show_alert=True,
        )
    await call.answer(
        "⏳ Memproses pembayaran..."
    )
    await state.clear()
    try:
        purchase_id = int(
            call.data.split(
                ":",
                1,
            )[1]
        )
    except (
        ValueError,
        IndexError,
    ):
        return await call.message.answer(
            "❌ ID transaksi tidak valid."
        )
    # --------------------------------------------------------
    # VERIFY MANUAL
    # --------------------------------------------------------
    purchase = await fetchrow(
        """
        UPDATE file_purchases
        SET status='verifying'
        WHERE id=$1
          AND status='pending'
          AND (payment_id LIKE 'MANUAL-%' OR payment_id LIKE 'BINANCE-%')
        RETURNING *
        """,
        purchase_id,
    )
    if not purchase:
        current = await get_purchase_by_id(
            purchase_id
        )
        if current and current.get(
            "status"
        ) == "paid":
            return await call.message.answer(
                "✅ Pembayaran sudah diproses admin lain."
            )
        if current and current.get(
            "status"
        ) == "rejected":
            return await call.message.answer(
                "❌ Pembayaran sudah ditolak."
            )
        if current and current.get(
            "status"
        ) == "cancelled":
            return await call.message.answer(
                (
                    "ℹ️ Pembayaran ini dibatalkan karena "
                    "metode pembayaran lain sudah berhasil."
                )
            )
        return await call.message.answer(
            "❌ Transaksi sudah diproses / tidak valid."
        )
    file = await get_file_by_code(
        purchase["file_code"]
    )
    if not file:
        await execute(
            """
            UPDATE file_purchases
            SET status='pending'
            WHERE id=$1
              AND status='verifying'
            """,
            purchase_id,
        )
        return await call.message.answer(
            "❌ File tidak ditemukan."
        )
    user_id = safe_int(
        purchase.get("user_id")
    )
    try:
        lang = await get_user_language(user_id)
        user_message = await call.bot.send_message(
            user_id,
            {
                "id": "✅ <b>Pembayaran manual disetujui admin.</b>\n\n📂 Membuka menu file...",
                "en": "✅ <b>Manual payment approved by admin.</b>\n\n📂 Opening file menu...",
                "zh": "✅ <b>管理员已批准手动付款。</b>\n\n📂 正在打开文件菜单……",
            }.get(lang, "✅ <b>Pembayaran manual disetujui admin.</b>\n\n📂 Membuka menu file..."),
            parse_mode="HTML",
        )
    except Exception:
        await execute(
            """
            UPDATE file_purchases
            SET status='pending'
            WHERE id=$1
              AND status='verifying'
            """,
            purchase_id,
        )
        return await call.message.answer(
            "❌ User tidak dapat dihubungi."
        )
    success = await finish_manual_payment(
        call.bot,
        purchase,
        file,
        purchase.get("payment_id"),
        user_message,
    )
    if not success:
        current = await get_purchase_by_id(
            purchase_id
        )
        if current and current.get(
            "status"
        ) == "paid":
            return await call.message.answer(
                (
                    "ℹ️ Pembayaran sudah dimenangkan "
                    "oleh transaksi lain."
                )
            )
        return await call.message.answer(
            "❌ Pembayaran gagal diproses."
        )
    try:
        await call.message.edit_text(
            (
                "✅ <b>PEMBAYARAN DISETUJUI</b>\n\n"
                f"🧾 ID: <code>{purchase_id}</code>\n"
                f"👤 User: <code>{user_id}</code>\n"
                f"📦 File: "
                f"<b>{clean_html(file.get('title'))}</b>\n"
                f"🔑 Code: "
                f"<code>{clean_html(file.get('code'))}</code>\n"
                f"💰 Harga: "
                f"<b>{format_rupiah(purchase.get('paid_price'))}</b>\n\n"
                "📦 Media sudah diproses."
            ),
            parse_mode="HTML",
            reply_markup=None,
        )
    except Exception:
        logger.warning(
            "EDIT APPROVE MESSAGE FAILED",
            exc_info=True,
        )
# ============================================================
# FINISH MANUAL PAYMENT
# ============================================================
async def finish_manual_payment(
    bot,
    purchase,
    file,
    invoice,
    message,
):
    purchase_id = safe_int(
        purchase.get("id")
    )
    user_id = safe_int(
        purchase.get("user_id")
    )
    code = str(
        file.get("code")
        or purchase.get("file_code")
        or ""
    ).strip()
    if (
        purchase_id <= 0
        or user_id <= 0
        or not code
    ):
        return False
    try:
        media_list = parse_media(
            file.get("media")
        )
        if not media_list:
            await execute(
                """
                UPDATE file_purchases
                SET status='pending'
                WHERE id=$1
                  AND status='verifying'
                """,
                purchase_id,
            )
            await message.answer(
                "❌ Media file kosong."
            )
            return False
        # ----------------------------------------------------
        # CLAIM
        # ----------------------------------------------------
        updated = await claim_purchase_paid(
            purchase_id,
            user_id,
            code,
            allowed_statuses=(
                "verifying",
                "pending",
            ),
        )
        if not updated:
            paid = await get_paid_purchase(
                user_id,
                code,
            )
            if paid:
                try:
                    from handlers.getfile import process_code
                    await process_code(message, code, paid_override=True)
                    return True
                except Exception:
                    logger.exception("REOPEN MANUAL PAID FILE ERROR | code=%s user=%s", code, user_id)
                    return False
            logger.warning(
                (
                    "MANUAL PAYMENT CLAIM LOST "
                    "| purchase=%s"
                ),
                purchase_id,
            )
            return False
        purchase = updated
        # ----------------------------------------------------
        # CANCEL CASHI / OTHER ACTIVE
        # ----------------------------------------------------
        await cancel_other_active_payments(
            user_id,
            code,
            purchase_id,
        )
        return await complete_success_side_effects(
            bot,
            purchase,
            file,
            invoice,
            message,
            media_list,
        )
    except Exception:
        logger.exception(
            (
                "FINISH MANUAL PAYMENT ERROR "
                "| purchase=%s"
            ),
            purchase_id,
        )
        return False
# ============================================================
# REJECT
# ============================================================
@router.callback_query(
    F.data.startswith("reject:")
)
async def reject_manual(
    call: CallbackQuery,
    state: FSMContext,
):
    if not is_admin(
        call.from_user.id
    ):
        return await call.answer(
            "❌ Kamu bukan admin.",
            show_alert=True,
        )
    try:
        purchase_id = int(
            call.data.split(
                ":",
                1,
            )[1]
        )
    except (
        ValueError,
        IndexError,
    ):
        return await call.answer(
            "❌ ID transaksi tidak valid.",
            show_alert=True,
        )
    purchase = await fetchrow(
        """
        SELECT *
        FROM file_purchases
        WHERE id=$1
          AND status='pending'
          AND (payment_id LIKE 'MANUAL-%' OR payment_id LIKE 'BINANCE-%')
        LIMIT 1
        """,
        purchase_id,
    )
    if not purchase:
        return await call.answer(
            (
                "❌ Transaksi tidak ditemukan "
                "atau sudah diproses."
            ),
            show_alert=True,
        )
    await state.set_state(
        RejectPaymentState.waiting_reason
    )
    await state.update_data(
        purchase_id=purchase_id,
        admin_id=int(
            call.from_user.id
        ),
        admin_chat_id=int(
            call.message.chat.id
        ),
        admin_message_id=int(
            call.message.message_id
        ),
    )
    await call.message.reply(
        (
            "❌ <b>REJECT PEMBAYARAN</b>\n\n"
            f"🧾 ID: <code>{purchase_id}</code>\n"
            f"👤 User: <code>{purchase['user_id']}</code>\n"
            f"📦 Code: "
            f"<code>{clean_html(purchase['file_code'])}</code>\n\n"
            "📝 Kirim alasan penolakan.\n\n"
            "Ketik <code>/cancelreject</code> untuk membatalkan."
        ),
        parse_mode="HTML",
    )
    await call.answer()
# ============================================================
# CANCEL REJECT
# ============================================================
@router.message(
    RejectPaymentState.waiting_reason,
    F.text == "/cancelreject",
)
async def cancel_reject_reason(
    message: Message,
    state: FSMContext,
):
    if not is_admin(
        message.from_user.id
    ):
        return
    data = await state.get_data()
    purchase_id = data.get(
        "purchase_id"
    )
    await state.clear()
    await message.answer(
        (
            "↩️ <b>Reject dibatalkan.</b>\n\n"
            f"Transaksi <code>{purchase_id}</code> "
            "tetap pending."
        ),
        parse_mode="HTML",
    )
# ============================================================
# RECEIVE REJECT
# ============================================================
@router.message(
    RejectPaymentState.waiting_reason,
    F.text,
)
async def receive_reject_reason(
    message: Message,
    state: FSMContext,
):
    if not is_admin(
        message.from_user.id
    ):
        return await message.answer(
            "❌ Kamu bukan admin."
        )
    data = await state.get_data()
    purchase_id = data.get(
        "purchase_id"
    )
    admin_id = data.get(
        "admin_id"
    )
    if (
        admin_id
        and int(message.from_user.id)
        != int(admin_id)
    ):
        return await message.answer(
            "❌ Permintaan ini milik admin lain."
        )
    if not purchase_id:
        await state.clear()
        return await message.answer(
            "❌ Data transaksi tidak ditemukan."
        )
    reason = str(
        message.text or ""
    ).strip()
    if not reason:
        return await message.answer(
            "❌ Alasan tidak boleh kosong."
        )
    if len(reason) > 1000:
        return await message.answer(
            "❌ Maksimal 1000 karakter."
        )
    rejected = await fetchrow(
        """
        UPDATE file_purchases
        SET status='rejected'
        WHERE id=$1
          AND status='pending'
          AND (payment_id LIKE 'MANUAL-%' OR payment_id LIKE 'BINANCE-%')
        RETURNING *
        """,
        purchase_id,
    )
    if not rejected:
        await state.clear()
        return await message.answer(
            "❌ Transaksi sudah diproses admin lain."
        )
    user_id = safe_int(
        rejected.get("user_id")
    )
    code = str(
        rejected.get("file_code")
        or ""
    )
    safe_reason = clean_html(
        reason
    )
    # --------------------------------------------------------
    # USER
    # --------------------------------------------------------
    user_notified = False
    try:
        await message.bot.send_message(
            user_id,
            (
                "❌ <b>Pembayaran Ditolak</b>\n\n"
                f"📦 Code: <code>{clean_html(code)}</code>\n\n"
                "📝 <b>Alasan Admin:</b>\n"
                f"{safe_reason}\n\n"
                "💡 Silakan lakukan pembayaran ulang."
            ),
            parse_mode="HTML",
        )
        user_notified = True
    except Exception:
        logger.exception(
            "REJECT USER NOTIFICATION ERROR"
        )
    # --------------------------------------------------------
    # DELETE QR
    # --------------------------------------------------------
    qr_deleted = False
    try:
        qr_message_id = rejected.get(
            "qr_message_id"
        )
        qr_chat_id = rejected.get(
            "qr_chat_id"
        )
        if qr_message_id and qr_chat_id:
            await message.bot.delete_message(
                chat_id=int(
                    qr_chat_id
                ),
                message_id=int(
                    qr_message_id
                ),
            )
            qr_deleted = True
    except Exception:
        logger.warning(
            "DELETE REJECT QR FAILED",
            exc_info=True,
        )
    # --------------------------------------------------------
    # ADMIN MESSAGE
    # --------------------------------------------------------
    if (
        data.get("admin_chat_id")
        and data.get("admin_message_id")
    ):
        try:
            await message.bot.edit_message_text(
                chat_id=int(
                    data["admin_chat_id"]
                ),
                message_id=int(
                    data["admin_message_id"]
                ),
                text=(
                    "❌ <b>PEMBAYARAN DITOLAK</b>\n\n"
                    f"🧾 ID: <code>{purchase_id}</code>\n"
                    f"👤 User: <code>{user_id}</code>\n"
                    f"📦 Code: "
                    f"<code>{clean_html(code)}</code>\n\n"
                    "📝 <b>Alasan:</b>\n"
                    f"{safe_reason}"
                ),
                parse_mode="HTML",
                reply_markup=None,
            )
        except Exception:
            logger.warning(
                "EDIT REJECT ADMIN MESSAGE ERROR",
                exc_info=True,
            )
    await message.answer(
        (
            "❌ <b>PEMBAYARAN DITOLAK</b>\n\n"
            f"🧾 ID: <code>{purchase_id}</code>\n"
            f"👤 User: <code>{user_id}</code>\n"
            f"📦 Code: "
            f"<code>{clean_html(code)}</code>\n\n"
            f"📝 Alasan:\n{safe_reason}\n\n"
            f"👤 Notifikasi user: "
            f"{'✅' if user_notified else '❌'}\n"
            f"🗑 QR dihapus: "
            f"{'✅' if qr_deleted else '⚠️'}"
        ),
        parse_mode="HTML",
    )
    await state.clear()
# ============================================================
# CLOSE
# ============================================================
@router.callback_query(
    F.data == "close"
)
async def close_payment(
    call: CallbackQuery,
    state: FSMContext,
):
    await state.clear()
    try:
        await call.message.delete()
    except Exception:
        pass
    await call.answer(
        "Ditutup."
    )
# ============================================================
# PAYMENT MEDIA CALLBACKS REMOVED
# ============================================================
# mp:/sp:/sa: sengaja tidak lagi ditangani di pay.py.
# Semua pengiriman setelah user memiliki akses harus melalui
# handlers/open_menu.py -> page.py / sendall.py.
# ============================================================
# NONE CALLBACK
# ============================================================
@router.callback_query(
    F.data == "none"
)
async def none_callback(
    call: CallbackQuery,
):
    await call.answer()
