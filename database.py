import asyncio
import logging
from pathlib import Path

import asyncpg

from config import DATABASE_URL

_pool = None
_lock = asyncio.Lock()


# ========================
# CONNECTION
# ========================
async def get_pool():
    global _pool

    if _pool is not None:
        return _pool

    async with _lock:
        if _pool is not None:
            return _pool

        while True:
            try:
                logging.info("🔌 Connecting to PostgreSQL...")

                _pool = await asyncpg.create_pool(
                    dsn=DATABASE_URL,
                    min_size=1,
                    max_size=10,
                    command_timeout=60,
                    max_inactive_connection_lifetime=300,
                    statement_cache_size=0,
                    ssl="require",
                )

                # DEBUG DATABASE
                async with _pool.acquire() as conn:
                    db = await conn.fetchval(
                        "SELECT current_database()"
                    )

                    schema = await conn.fetch("""
                        SELECT column_name
                        FROM information_schema.columns
                        WHERE table_name='file_purchases'
                        ORDER BY ordinal_position
                    """)

                    logging.info(f"DATABASE = {db}")
                    logging.info(
                        f"COLUMNS = {[r['column_name'] for r in schema]}"
                    )

                logging.info("✅ PostgreSQL connected")
                break

            except Exception:
                logging.exception(
                    "❌ Failed connecting to PostgreSQL. Retrying in 3 seconds..."
                )
                await asyncio.sleep(3)

    return _pool

# ========================
# CLOSE DATABASE
# ========================
async def close_db():
    global _pool

    if _pool is not None:
        await _pool.close()
        _pool = None
        logging.info("🔌 Database closed")

# ========================
# INIT DATABASE (AUTO FIX)
# ========================
async def init_db():
    """Initialize the database from database.sql.

    database.sql is the single source of truth for the application schema.
    Keeping startup initialization in sync with that file prevents the bot
    from silently creating a different schema in production.
    """
    pool = await get_pool()
    schema_path = Path(__file__).with_name("database.sql")
    sql = schema_path.read_text(encoding="utf-8")
    async with pool.acquire() as conn:
        await conn.execute(sql)
        logging.info("✅ Database initialized from %s", schema_path.name)


# ========================
# QUERY HELPERS
# ========================
async def execute(query, *args, retry=1):
    for attempt in range(retry + 1):
        try:
            pool = await get_pool()

            async with pool.acquire() as conn:
                return await conn.execute(query, *args)

        except Exception:
            logging.exception("EXECUTE ERROR")

            if attempt >= retry:
                raise

            await asyncio.sleep(1)


async def fetch(query, *args, retry=1):
    for attempt in range(retry + 1):
        try:
            pool = await get_pool()

            async with pool.acquire() as conn:
                return await conn.fetch(query, *args)

        except Exception:
            logging.exception("FETCH ERROR")

            if attempt >= retry:
                raise

            await asyncio.sleep(1)


async def fetchrow(query, *args, retry=1):
    for attempt in range(retry + 1):
        try:
            pool = await get_pool()

            async with pool.acquire() as conn:
                return await conn.fetchrow(query, *args)

        except Exception:
            logging.exception("FETCHROW ERROR")

            if attempt >= retry:
                raise

            await asyncio.sleep(1)


async def fetchval(query, *args, retry=1):
    for attempt in range(retry + 1):
        try:
            pool = await get_pool()

            async with pool.acquire() as conn:
                return await conn.fetchval(query, *args)

        except Exception:
            logging.exception("FETCHVAL ERROR")

            if attempt >= retry:
                raise

            await asyncio.sleep(1)


# ========================
# TRANSACTION
# ========================
async def transaction(queries: list):
    pool = await get_pool()

    async with pool.acquire() as conn:
        async with conn.transaction():
            results = []

            for q in queries:
                query = q[0]
                args = q[1:]

                results.append(
                    await conn.execute(query, *args)
                )

            return results
