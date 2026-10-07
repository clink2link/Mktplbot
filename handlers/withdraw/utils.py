from datetime import datetime
from zoneinfo import ZoneInfo


__all__ = [
    "WIB",
    "WITHDRAW_OPEN_HOUR",
    "WITHDRAW_CLOSE_HOUR",
    "MIN_WITHDRAW",
    "WITHDRAW_FEE",
    "INSTANT_AMOUNT",
    "INSTANT_FEE",
    "INSTANT_MIN_BALANCE",
    "WITHDRAW_NOMINALS",
    "withdraw_is_open",
    "rupiah",
    "mask_name",
    "mask_account",
    "mask_id",
]


# =========================
# TIMEZONE
# =========================

WIB = ZoneInfo("Asia/Jakarta")


# =========================
# WITHDRAW CONFIG
# =========================

WITHDRAW_OPEN_HOUR = 9
WITHDRAW_CLOSE_HOUR = 19


# =========================
# NOMINAL
# =========================

MIN_WITHDRAW = 100_000
WITHDRAW_FEE = 10_000

INSTANT_AMOUNT = 50_000
INSTANT_FEE = 15_000
INSTANT_MIN_BALANCE = INSTANT_AMOUNT + INSTANT_FEE


WITHDRAW_NOMINALS = (
    100_000,
    150_000,
    200_000,
    250_000,
    300_000,
    500_000,
)


# =========================
# JAM OPERASIONAL
# =========================

def withdraw_is_open() -> bool:

    now = datetime.now(WIB)

    # Sabtu & Minggu tutup
    if now.weekday() >= 5:
        return False

    return (
        WITHDRAW_OPEN_HOUR
        <= now.hour
        <
        WITHDRAW_CLOSE_HOUR
    )


# =========================
# FORMAT RUPIAH
# =========================

def rupiah(amount: int) -> str:
    return f"Rp {int(amount):,}".replace(",", ".")


# =========================
# MASK NAME
# =========================

def mask_name(name: str) -> str:

    if not name:
        return "-"

    result = []

    for word in name.split():

        if len(word) <= 2:
            result.append(word[0] + "*")
        else:
            result.append(
                word[0]
                + "*" * (len(word) - 2)
                + word[-1]
            )

    return " ".join(result)


# =========================
# MASK ACCOUNT
# =========================

def mask_account(number: str) -> str:

    if not number:
        return "-"

    number = str(number)

    if len(number) <= 8:
        return "*" * len(number)

    return (
        number[:4]
        + "*" * (len(number) - 8)
        + number[-4:]
    )


# =========================
# MASK TELEGRAM ID
# =========================

def mask_id(user_id) -> str:

    if not user_id:
        return "-"

    uid = str(user_id)

    if len(uid) <= 6:
        return "*" * len(uid)

    return (
        uid[:3]
        + "*****"
        + uid[-3:]
    )
