from __future__ import annotations
import html
import logging
from config import NOTIF_CHANNEL_ID

logger = logging.getLogger(__name__)

def _esc(v) -> str:
    return html.escape(str(v if v is not None else ""))

def _idr(value) -> str:
    try:
        return f"Rp {int(value):,}".replace(",", ".")
    except Exception:
        return "Rp 0"

async def send_payment_success_channel(bot, kind: str, user_id: int, amount=None,
                                       payment: str = "-", item: str = "-", reference: str = "-") -> bool:
    """Send one successful purchase notification to the configured transaction channel."""
    if not NOTIF_CHANNEL_ID:
        return False
    labels = {
        "points": "⭐ POINTS PURCHASE SUCCESS",
        "vip": "💎 VIP PURCHASE SUCCESS",
        "vvip": "💎 VVIP PURCHASE SUCCESS",
        "creator": "🎨 CREATOR PURCHASE SUCCESS",
    }
    title = labels.get(str(kind).lower(), "💳 PAYMENT SUCCESS")
    lines = [
        f"<b>{title}</b>",
        "━━━━━━━━━━━━━━━━━━",
        f"👤 User: <code>{_esc(user_id)}</code>",
    ]
    if item and item != "-":
        lines.append(f"📦 Item: <b>{_esc(item)}</b>")
    if amount is not None:
        lines.append(f"💰 Amount: <b>{_idr(amount)}</b>")
    if payment and payment != "-":
        lines.append(f"💳 Payment: <b>{_esc(str(payment).upper())}</b>")
    if reference and reference != "-":
        lines.append(f"🧾 ID: <code>{_esc(reference)}</code>")
    lines.append("━━━━━━━━━━━━━━━━━━")
    try:
        await bot.send_message(NOTIF_CHANNEL_ID, "\n".join(lines), parse_mode="HTML")
        return True
    except Exception:
        logger.exception("PAYMENT SUCCESS CHANNEL NOTIFY ERROR kind=%s user=%s", kind, user_id)
        return False
