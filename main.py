import asyncio
import logging
import os
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI

from utils.redis_client import init_redis
from config import TIMEZONE
from bot import bot, dp
from database import get_pool, close_db, init_db

from tasks.auto_delete import auto_delete_worker
from tasks.payment_worker import payment_worker
from tasks.vip_expired import vip_expired_worker
from handlers.bayargg import router as bayargg_webhook_router
from handlers.cashi_webhook import router as cashi_webhook_router


os.environ["TZ"] = TIMEZONE

if hasattr(time, "tzset"):
    time.tzset()


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)


tasks = {}


def create_task(name, coro):

    async def runner():
        try:
            await coro
        except asyncio.CancelledError:
            logging.warning(f"{name} cancelled")
            raise
        except Exception:
            logging.exception(f"{name} crashed")
            raise

    tasks[name] = asyncio.create_task(runner())
    logging.info(f"{name} started")


async def stop_task(name):
    task = tasks.get(name)

    if task:
        task.cancel()

        try:
            await task
        except asyncio.CancelledError:
            logging.info(f"{name} stopped")


async def start_workers():

    create_task(
        "AUTO_DELETE",
        auto_delete_worker()
    )

    create_task(
        "PAYMENT",
        payment_worker()
    )

    create_task(
        "VIP_EXPIRED",
        vip_expired_worker()
    )

    create_task(
        "MAIN_BOT",
        dp.start_polling(bot)
    )

    logging.info("MAIN BOT STARTED")


@asynccontextmanager
async def lifespan(app: FastAPI):

    logging.info("APP STARTING")

    await get_pool()
    await init_db()
    await init_redis()

    logging.info("Skipping Telegram startup check...")

    # Langsung jalankan worker dan bot
    await start_workers()

    yield

    logging.info("SHUTDOWN")

    for name in list(tasks.keys()):
        await stop_task(name)

    await close_db()
    await bot.session.close()

    logging.info("BOT STOPPED")


app = FastAPI(
    lifespan=lifespan
)

# BayarGG callback for automatic VIP/VVIP and file payments.
app.include_router(bayargg_webhook_router)
app.include_router(cashi_webhook_router)


@app.get("/")
async def root():
    return {
        "status": "running"
    }


@app.get("/health")
async def health():
    return {
        "status": "ok"
    }
