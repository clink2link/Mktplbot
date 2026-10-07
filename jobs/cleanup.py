import asyncio
from database import get_pool

async def cleanup_expired():
    pool = await get_pool()

    while True:
        await pool.execute(
            """
            UPDATE file_purchases
            SET status='expired'
            WHERE status='pending'
              AND created_at < NOW() - INTERVAL '1 hour'
            """
        )

        await asyncio.sleep(300)  # 5 menit
