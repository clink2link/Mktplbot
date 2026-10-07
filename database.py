import asyncio
import logging
from pathlib import Path

import asyncpg

from config import DATABASE_URL, SHOWJS_DATABASE_URL

_pool = None
_showjs_pool = None
_lock = asyncio.Lock()
_showjs_lock = asyncio.Lock()


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


async def get_showjs_pool():
    """Read-only connection pool for the legacy Showjs database."""
    global _showjs_pool
    if _showjs_pool is not None:
        return _showjs_pool
    if not SHOWJS_DATABASE_URL:
        raise RuntimeError("SHOWJS_DATABASE_URL belum di-set")
    async with _showjs_lock:
        if _showjs_pool is not None:
            return _showjs_pool
        async def _showjs_connection_init(conn):
            # Defense in depth: the bridge must never mutate Showjs.
            await conn.execute("SET default_transaction_read_only = on")

        _showjs_pool = await asyncpg.create_pool(
            dsn=SHOWJS_DATABASE_URL,
            min_size=1,
            max_size=5,
            command_timeout=60,
            max_inactive_connection_lifetime=300,
            statement_cache_size=0,
            ssl="require",
            init=_showjs_connection_init,
        )
        logging.info("✅ Showjs PostgreSQL connected (read-only bridge)")
    return _showjs_pool

# ========================
# CLOSE DATABASE
# ========================
async def close_db():
    global _pool, _showjs_pool

    if _pool is not None:
        await _pool.close()
        _pool = None
        logging.info("🔌 Database closed")

    if _showjs_pool is not None:
        await _showjs_pool.close()
        _showjs_pool = None
        logging.info("🔌 Showjs database closed")

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

    # Encrypt legacy plaintext B2 credentials after the schema exists.
    try:
        from utils.b2_storage import migrate_b2_credentials, log_b2_credential_key_status
        log_b2_credential_key_status()
        await migrate_b2_credentials()
    except Exception:
        # Do not prevent the bot from starting because an optional B2
        # credential migration failed; B2 operations will report the error.
        logging.exception("⚠️ B2 credential migration failed")


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
