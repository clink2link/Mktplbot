"""Legacy payment-channel hook.

Transaction notification channels are intentionally disabled in the current
Pastele architecture. Payment processing remains independent from Telegram
notification channels.
"""

async def send_payment_success_channel(
    bot,
    kind: str,
    user_id: int,
    amount=None,
    payment: str = "-",
    item: str = "-",
    reference: str = "-",
) -> bool:
    return False
