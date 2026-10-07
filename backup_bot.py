import json
import logging
import asyncio
import re

from aiogram import Bot, Dispatcher, Router, F
from aiogram.types import Message
from aiogram.filters import CommandStart
from aiogram.client.default import DefaultBotProperties

from config import (
    BACKUP_BOT_TOKEN,
    STORAGE_CHANNEL_ID,
    BOT_URL
)

from database import get_pool


# =========================
# LOG
# =========================
logging.basicConfig(level=logging.INFO)

logger = logging.getLogger(__name__)


# =========================
# BOT
# =========================
backup_bot = Bot(
    token=BACKUP_BOT_TOKEN,
    default=DefaultBotProperties(
        parse_mode="HTML"
    )
)


backup_dp = Dispatcher()

router = Router()

backup_dp.include_router(router)



# =========================
# NORMALIZE CODE
# =========================
def clean_code(text: str):

    text = text.strip()

    # buang link kalau user paste full link
    if "getFile_" in text:
        text = text.split("getFile_")[-1]

    # hapus karakter aneh
    text = re.sub(
        r"[^a-zA-Z0-9]",
        "",
        text
    )

    return text



# =========================
# START LINK
# =========================
@router.message(CommandStart())
async def start_handler(message: Message):

    args = message.text.split(maxsplit=1)

    if len(args) < 2:
        return await message.answer(
            "🤖 Backup Bot Aktif\n\nTempel kode file."
        )

    payload = args[1]

    if payload.startswith("getFile_"):

        code = payload.replace(
            "getFile_",
            "",
            1
        )

        return await send_file(
            message,
            code
        )

    return await message.answer(
        "❌ Link tidak valid."
    )



# =========================
# CODE HANDLER
# =========================
@router.message(F.text)
async def code_handler(message: Message):

    raw = message.text.strip()

    if not raw:
        return


    # =========================
    # AMBIL CODE DARI LINK
    # =========================
    if "getFile_" in raw:
        text = raw.split("getFile_")[-1]

    else:
        text = raw


    # =========================
    # CLEAN CODE
    # =========================
    text = re.sub(
        r"[^a-zA-Z0-9]",
        "",
        text
    )


    if not text:
        return


    pool = await get_pool()


    # =========================
    # CARI EXACT CODE
    # =========================
    row = await pool.fetchrow(
        """
        SELECT code
        FROM files
        WHERE LOWER(code)=LOWER($1)
        LIMIT 1
        """,
        text
    )


    if not row:

        # fallback kalau ada typo kecil
        row = await pool.fetchrow(
            """
            SELECT code
            FROM files
            WHERE LOWER(code) LIKE LOWER($1)
            LIMIT 1
            """,
            f"%{text}%"
        )


    if row:

        return await send_file(
            message,
            row["code"]
        )


    # =========================
    # TIDAK DITEMUKAN
    # =========================
    await message.answer(
        "❌ <b>File tidak ditemukan.</b>\n\n"
        "Pastikan kode benar atau gunakan link asli."
    )



# =========================
# SEND FILE
# =========================
async def send_file(
    message: Message,
    code: str
):

    pool = await get_pool()


    row = await pool.fetchrow(
        """
        SELECT
            title,
            media,
            is_paid,
            price
        FROM files
        WHERE LOWER(code)=LOWER($1)
        LIMIT 1
        """,
        code
    )


    if not row:

        return await message.answer(
            "❌ File tidak ditemukan."
        )



    if row["is_paid"]:

        return await message.answer(
            "🔒 File berbayar.\n"
            f"Harga: Rp {row['price']:,}".replace(",", ".")
        )



    try:

        media = json.loads(
            row["media"]
        )

    except Exception as e:

        logger.error(
            f"JSON ERROR: {e}"
        )

        return await message.answer(
            "❌ Data file rusak."
        )



    if not media:

        return await message.answer(
            "❌ File kosong."
        )



    await message.answer(
        f"📦 <b>{row['title']}</b>\n"
        f"📁 Total: {len(media)} file"
    )


    # =========================
    # SEND MEDIA
    # =========================

    success = 0

    for item in media:

        try:

            msg_id = item.get("message_id")
            file_id = item.get("file_id")
            file_type = (item.get("type") or "document").lower()


            # =========================
            # PRIORITAS STORAGE CHANNEL
            # =========================
            if msg_id:

                await backup_bot.copy_message(
                    chat_id=message.chat.id,
                    from_chat_id=STORAGE_CHANNEL_ID,
                    message_id=msg_id
                )

                success += 1


            # =========================
            # FALLBACK FILE_ID
            # =========================
            elif file_id:


                if file_type == "video":

                    await backup_bot.send_video(
                        chat_id=message.chat.id,
                        video=file_id
                    )


                elif file_type == "photo":

                    await backup_bot.send_photo(
                        chat_id=message.chat.id,
                        photo=file_id
                    )


                elif file_type == "audio":

                    await backup_bot.send_audio(
                        chat_id=message.chat.id,
                        audio=file_id
                    )


                else:

                    await backup_bot.send_document(
                        chat_id=message.chat.id,
                        document=file_id
                    )


                success += 1


            else:

                logger.warning(
                    f"MEDIA INVALID: {item}"
                )


            await asyncio.sleep(0.3)


        except Exception as e:

            logger.exception(
                f"SEND MEDIA ERROR: {e}"
            )


    if success == 0:

        await message.answer(
            "❌ Semua file gagal dikirim."
        )
