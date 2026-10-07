import logging
import os
import json

import redis.asyncio as redis


logger = logging.getLogger(__name__)


# ============================================================
# CONFIG
# ============================================================

REDIS_URL = os.getenv("REDIS_URL")

redis_client = None


# ============================================================
# INIT
# ============================================================

async def init_redis():
    global redis_client

    if not REDIS_URL:
        logger.warning(
            "⚠️ REDIS_URL not found, Redis disabled"
        )
        redis_client = None
        return None

    try:

        redis_client = redis.from_url(
            REDIS_URL,
            decode_responses=True,
            socket_connect_timeout=5,
            socket_timeout=5,
            retry_on_timeout=True,
            health_check_interval=30,
        )

        # Test koneksi
        await redis_client.ping()

        logger.info(
            "✅ Redis connected"
        )

        return redis_client

    except Exception:

        logger.exception(
            "❌ Failed to connect Redis"
        )

        redis_client = None

        return None


# ============================================================
# SERIALIZE VALUE
# ============================================================

def serialize_value(value):
    """
    Convert Python values into Redis-compatible values.

    Supported:
    - None
    - bool
    - int
    - float
    - str
    - bytes
    - dict
    - list
    - tuple
    """

    if value is None:
        return ""

    # IMPORTANT:
    # bool harus dicek sebelum int
    # karena bool adalah subclass dari int.
    if isinstance(value, bool):
        return "1" if value else "0"

    if isinstance(value, bytes):
        return value

    if isinstance(
        value,
        (dict, list, tuple),
    ):
        return json.dumps(
            value,
            ensure_ascii=False,
            separators=(",", ":"),
        )

    if isinstance(
        value,
        (int, float),
    ):
        return str(value)

    if isinstance(value, str):
        return value

    # Fallback
    return str(value)


# ============================================================
# SAFE SET
# ============================================================

async def safe_set(
    key: str,
    value,
    ex: int | None = None,
    nx: bool = False,
):
    if redis_client is None:
        return False

    try:

        value = serialize_value(
            value
        )

        return await redis_client.set(
            key,
            value,
            ex=ex,
            nx=nx,
        )

    except Exception:

        logger.exception(
            "Redis SET failed | key=%s",
            key,
        )

        return False


# ============================================================
# SAFE GET
# ============================================================

async def safe_get(
    key: str,
):
    if redis_client is None:
        return None

    try:

        value = await redis_client.get(
            key
        )

        if value is None:
            return None

        # decode_responses=True biasanya
        # sudah menghasilkan str.
        #
        # Tetapi tetap aman jika bytes.
        if isinstance(value, bytes):

            value = value.decode(
                "utf-8",
                errors="ignore",
            )

        # AUTO JSON PARSE
        try:

            return json.loads(value)

        except (
            json.JSONDecodeError,
            TypeError,
            ValueError,
        ):

            return value

    except Exception:

        logger.exception(
            "Redis GET failed | key=%s",
            key,
        )

        return None


# ============================================================
# SAFE DELETE
# ============================================================

async def safe_delete(
    key: str,
):
    if redis_client is None:
        return False

    try:

        return await redis_client.delete(
            key
        )

    except Exception:

        logger.exception(
            "Redis DELETE failed | key=%s",
            key,
        )

        return False


# ============================================================
# SAFE EXISTS
# ============================================================

async def safe_exists(
    key: str,
) -> bool:

    if redis_client is None:
        return False

    try:

        return (
            await redis_client.exists(
                key
            )
            > 0
        )

    except Exception:

        logger.exception(
            "Redis EXISTS failed | key=%s",
            key,
        )

        return False


# ============================================================
# SAFE INCR
# ============================================================

async def safe_incr(
    key: str,
    ex: int | None = None,
) -> int:

    if redis_client is None:
        return 0

    try:

        value = await redis_client.incr(
            key
        )

        if ex:

            await redis_client.expire(
                key,
                ex,
            )

        return int(value)

    except Exception:

        logger.exception(
            "Redis INCR failed | key=%s",
            key,
        )

        return 0


# ============================================================
# SAFE EXPIRE
# ============================================================

async def safe_expire(
    key: str,
    seconds: int,
) -> bool:

    if redis_client is None:
        return False

    try:

        return bool(
            await redis_client.expire(
                key,
                int(seconds),
            )
        )

    except Exception:

        logger.exception(
            "Redis EXPIRE failed | key=%s",
            key,
        )

        return False


# ============================================================
# SAFE TTL
# ============================================================

async def safe_ttl(
    key: str,
) -> int:

    if redis_client is None:
        return -2

    try:

        return int(
            await redis_client.ttl(
                key
            )
        )

    except Exception:

        logger.exception(
            "Redis TTL failed | key=%s",
            key,
        )

        return -2
