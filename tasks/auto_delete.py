import asyncio
import logging
from database import get_pool

logger=logging.getLogger(__name__)

async def auto_delete_worker():
    logger.info("🗑 Auto delete worker running...")
    while True:
        try:
            pool=await get_pool()
            rows=await pool.fetch("SELECT code FROM files WHERE expires_at IS NOT NULL AND expires_at < NOW() LIMIT 100")
            for row in rows:
                code=row["code"]
                async with pool.acquire() as conn:
                    async with conn.transaction():
                        await conn.execute("DELETE FROM medias WHERE code=$1",code)
                        await conn.execute("DELETE FROM file_views WHERE file_code=$1",code)
                        await conn.execute("DELETE FROM file_reactions WHERE file_code=$1",code)
                        await conn.execute("DELETE FROM file_favorites WHERE file_code=$1",code)
                        await conn.execute("DELETE FROM file_ratings WHERE file_code=$1",code)
                        await conn.execute("DELETE FROM file_reviews WHERE file_code=$1",code)
                        await conn.execute("DELETE FROM files WHERE code=$1",code)
                logger.info("🗑 Deleted expired file: %s",code)
        except Exception:
            logger.exception("AUTO DELETE ERROR")
        await asyncio.sleep(60)
