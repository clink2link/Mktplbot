import asyncio
import logging

from database import execute

logger = logging.getLogger(__name__)


async def vip_expired_worker():

    logger.info("👑 VIP expired worker running...")

    while True:

        try:

            result = await execute(
                """
                UPDATE vip_users
                SET
                    plan = 'FREE'
                WHERE expired_at IS NOT NULL
                AND expired_at < NOW()
                """
            )

            if result != "UPDATE 0":
                logger.info(
                    "VIP expired cleaned: %s",
                    result
                )

        except Exception:
            logger.exception(
                "VIP expired worker error"
            )

        await asyncio.sleep(3600)
