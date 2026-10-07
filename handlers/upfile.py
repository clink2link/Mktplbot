import asyncio
import json
import logging
import re
import secrets
import string
import time

from contextlib import asynccontextmanager
from html import escape
from typing import Dict, Optional

from aiogram import Router, F
from aiogram.exceptions import TelegramBadRequest, TelegramRetryAfter, TelegramServerError, TelegramNetworkError
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    InputMediaPhoto,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder

from config import CHANNEL_ID
from database import get_pool
from keyboards.join import join_kb
from utils.force_sub import check_force_sub
from utils.share_unlock import telegram_setting, share_url
from utils.user_lang import get_user_language


router = Router()


# =========================================================
# CONFIG
# =========================================================

MAX_MEDIA = 100
MAX_REVIEW_PHOTOS = 5

# Jangan terlalu sering edit message progress.
UPDATE_DELAY = 0.7

# Delay kecil setelah copy berhasil.
# Kecepatan utama didapat dari tidak memakai global copy lock.
COPY_DELAY = 1.5

# Channel review paid file.
REVIEW_CHANNEL_ID = -1003993516320


# =========================================================
# LOGGING
# =========================================================

logger = logging.getLogger(__name__)


# =========================================================
# RUNTIME LOCKS / THROTTLE
# =========================================================

_last_update: Dict[int, float] = {}

_user_locks: Dict[int, asyncio.Lock] = {}
_user_lock_refs: Dict[int, int] = {}

_channel_send_lock = asyncio.Lock()
_storage_ready = False
_last_channel_send = 0.0
CHANNEL_SEND_DELAY = 1.0


async def safe_channel_send(bot, chat_id, text, **kwargs):
    """Serialize update-channel posts and keep a conservative interval."""
    global _last_channel_send
    async with _channel_send_lock:
        configured_delay = await telegram_setting(
            "telegram_channel_delay",
            CHANNEL_SEND_DELAY,
        )
        wait = configured_delay - (time.monotonic() - _last_channel_send)
        if wait > 0:
            await asyncio.sleep(wait)
        while True:
            try:
                msg = await bot.send_message(chat_id=chat_id, text=text, **kwargs)
                _last_channel_send = time.monotonic()
                return msg
            except TelegramRetryAfter as exc:
                await asyncio.sleep(max(float(exc.retry_after), 1.0) + 0.5)



# =========================================================
# USER LOCK
# =========================================================

def get_lock(user_id: int) -> asyncio.Lock:
    """
    Satu user hanya boleh menjalankan satu proses upload
    pada satu waktu.

    User berbeda tetap dapat upload secara bersamaan.
    """

    lock = _user_locks.get(user_id)

    if lock is None:
        lock = asyncio.Lock()
        _user_locks[user_id] = lock

    return lock


@asynccontextmanager
async def user_lock(user_id: int):
    """
    Lock per-user dengan reference counter.

    Setelah user selesai dan lock tidak dipakai lagi,
    lock akan dihapus dari memory.
    """

    lock = get_lock(user_id)

    _user_lock_refs[user_id] = (
        _user_lock_refs.get(user_id, 0) + 1
    )

    try:

        async with lock:
            yield

    finally:

        refs = _user_lock_refs.get(user_id, 1) - 1

        if refs <= 0:

            _user_lock_refs.pop(
                user_id,
                None,
            )

            # Jangan hapus lock yang sedang locked.
            current_lock = _user_locks.get(user_id)

            if (
                current_lock is lock
                and not lock.locked()
            ):
                _user_locks.pop(
                    user_id,
                    None,
                )

        else:

            _user_lock_refs[user_id] = refs


# =========================================================
# SAFE CALLBACK ANSWER
# =========================================================

async def safe_callback_answer(
    call: CallbackQuery,
    text: Optional[str] = None,
    show_alert: bool = False,
):
    """
    Menjawab callback dengan aman.

    Mencegah error:
    - query is too old
    - query ID is invalid
    - callback sudah dijawab
    """

    try:

        await call.answer(
            text=text,
            show_alert=show_alert,
        )

    except TelegramBadRequest as e:

        error = str(e).lower()

        if (
            "query is too old" in error
            or "query id is invalid" in error
            or "query is already answered" in error
        ):
            logger.debug(
                "IGNORED CALLBACK ANSWER ERROR | %s",
                e,
            )
            return

        logger.debug(
            "CALLBACK ANSWER ERROR | %s",
            e,
        )

    except Exception as e:

        logger.debug(
            "CALLBACK ANSWER UNEXPECTED ERROR | %s",
            e,
        )


# =========================================================
# UPLOAD STATE
# =========================================================

class UploadState(StatesGroup):

    upload = State()

    wait_title = State()

    wait_price = State()

    wait_review = State()


# =========================================================
# BAD WORD FILTER
# =========================================================

BAD_WORDS = {
    "bocil",
    "child",
    "underage",
    "minor",
}


def normalize(text: str) -> str:

    return re.sub(
        r"[^a-z0-9]",
        "",
        (text or "").lower(),
    )


def is_bad(text: str) -> bool:

    clean = normalize(text)

    return any(
        word in clean
        for word in BAD_WORDS
    )


# =========================================================
# SAFE UPDATE
# =========================================================

async def safe_update(
    bot,
    chat_id: int,
    message_id: int,
    text: str,
    reply_markup=None,
):
    """
    Edit progress message dengan throttle.

    Menghindari:
    - terlalu banyak edit
    - message is not modified
    - message tidak ditemukan
    """

    now = time.monotonic()

    last = _last_update.get(
        chat_id,
        0,
    )

    if now - last < UPDATE_DELAY:
        return False

    _last_update[chat_id] = now

    try:

        await bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text=text,
            parse_mode="HTML",
            reply_markup=reply_markup,
        )

        return True

    except TelegramBadRequest as e:

        error = str(e).lower()

        if (
            "message is not modified" in error
            or "message to edit not found" in error
            or "message can't be edited" in error
            or "message identifier is not specified" in error
        ):
            return False

        logger.debug(
            "SAFE UPDATE BAD REQUEST | chat=%s | message=%s | error=%s",
            chat_id,
            message_id,
            e,
        )

        return False

    except Exception:

        logger.exception(
            "SAFE UPDATE ERROR | chat=%s | message=%s",
            chat_id,
            message_id,
        )

        return False


# =========================================================
# GENERATE UNIQUE CODE
# =========================================================

async def generate_code() -> str:
    """Generate stable marketplace codes like Pastelebot_A18KA07JAMP1714."""
    pool = await get_pool()
    alphabet = string.ascii_uppercase + string.digits
    while True:
        suffix = "".join(secrets.choice(alphabet) for _ in range(14))
        code = f"Pastelebot_{suffix}"
        exists = await pool.fetchval("SELECT 1 FROM files WHERE LOWER(code)=LOWER($1) LIMIT 1", code)
        if not exists:
            return code


async def generate_review_code() -> str:
    """Generate a separate public code used only for free review/preview."""
    pool = await get_pool()
    alphabet = string.ascii_uppercase + string.digits
    while True:
        suffix = "".join(secrets.choice(alphabet) for _ in range(14))
        code = f"PasteleReview_{suffix}"
        exists = await pool.fetchval(
            "SELECT 1 FROM files WHERE LOWER(review_code)=LOWER($1) LIMIT 1",
            code,
        )
        if not exists:
            return code


# =========================================================
# FORMAT RUPIAH
# =========================================================

def rupiah(amount: int) -> str:

    return f"Rp{amount:,}".replace(
        ",",
        ".",
    )


# =========================================================
# FORMAT USER ID
# =========================================================

def mask_user_id(user_id: int) -> str:

    value = str(user_id)

    if len(value) <= 4:
        return value

    return (
        value[:2]
        + "****"
        + value[-2:]
    )


# =========================================================
# UPLOAD KEYBOARD
# =========================================================

def upload_keyboard():

    kb = InlineKeyboardBuilder()

    kb.button(
        text="⏹ STOP & SAVE",
        callback_data="save_upfile",
    )

    kb.button(
        text="❌ BATAL",
        callback_data="cancel_upfile",
    )

    kb.adjust(1)

    return kb.as_markup()


# =========================================================
# REVIEW KEYBOARD
# =========================================================

def review_keyboard():

    kb = InlineKeyboardBuilder()

    kb.button(
        text="✅ SELESAI REVIEW",
        callback_data="finish_review",
    )

    kb.button(
        text="❌ BATAL",
        callback_data="cancel_upfile",
    )

    kb.adjust(1)

    return kb.as_markup()


# =========================================================
# HOME KEYBOARD
# =========================================================

def home_keyboard():

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🏠 Home",
                    callback_data="home",
                )
            ]
        ]
    )


# =========================================================
# START UPLOAD
# =========================================================

@router.callback_query(
    F.data == "upfile"
)
async def start_upload(
    call: CallbackQuery,
    state: FSMContext,
):

    # ACK SECEPAT MUNGKIN
    await safe_callback_answer(
        call
    )

    user_id = call.from_user.id

    # -----------------------------------------------------
    # FORCE SUB
    # -----------------------------------------------------

    if not await check_force_sub(
        call.bot,
        user_id,
    ):

        return await call.message.answer(
            "❌ Kamu belum join channel.",
            reply_markup=join_kb(),
        )

    # -----------------------------------------------------
    # CHECK CREATOR
    # -----------------------------------------------------

    pool = await get_pool()

    creator = await pool.fetchrow(
        """
        SELECT
            is_creator,
            creator_status
        FROM users
        WHERE user_id = $1
        """,
        user_id,
    )

    is_creator = bool(
        creator
        and creator["is_creator"]
        and creator["creator_status"] == "approved"
    )

    # -----------------------------------------------------
    # RESET STATE
    # -----------------------------------------------------

    await state.clear()

    await state.set_state(
        UploadState.upload
    )

    # -----------------------------------------------------
    # SAVE USER INFO
    # -----------------------------------------------------

    await state.update_data(

        upload_mode=True,

        media=[],

        title=None,

        share_media=True,

        is_paid=False,

        price=0,

        payment_provider=None,

        review_photos=[],

        saving=False,

        progress_msg_id=None,

        saving_msg_id=None,

        is_creator=is_creator,

        creator_id=user_id,

        creator_username=call.from_user.username,

        creator_fullname=(
            call.from_user.full_name
            or "Unknown"
        ),
    )

    # -----------------------------------------------------
    # TEXT
    # -----------------------------------------------------

    text = (
        "📦 <b>UPLOAD MODE</b>\n\n"
        "Silakan kirim file.\n"
        f"Maksimal <b>{MAX_MEDIA}</b> media.\n\n"
    )

    if is_creator:

        text += (
            "🎨 Status : "
            "<b>Kreator Terverifikasi</b> ✅\n\n"
            "🆓 File FREE\n"
            "💰 File PAID\n\n"
        )

    else:

        text += (
            "👤 Status : <b>User</b>\n\n"
            "🆓 File FREE tersedia.\n"
            "🔒 File PAID hanya untuk "
            "Kreator terverifikasi.\n\n"
        )

    text += (
        "Kirim file satu per satu.\n"
        "Jika selesai tekan <b>STOP & SAVE</b>."
    )

    # -----------------------------------------------------
    # EDIT PROGRESS
    # -----------------------------------------------------

    try:

        await call.message.edit_text(
            text,
            parse_mode="HTML",
            reply_markup=upload_keyboard(),
        )

        progress_id = (
            call.message.message_id
        )

    except TelegramBadRequest:

        msg = await call.message.answer(
            text,
            parse_mode="HTML",
            reply_markup=upload_keyboard(),
        )

        progress_id = msg.message_id

    except Exception:

        logger.exception(
            "START UPLOAD MESSAGE ERROR | user=%s",
            user_id,
        )

        msg = await call.message.answer(
            text,
            parse_mode="HTML",
            reply_markup=upload_keyboard(),
        )

        progress_id = msg.message_id

    # -----------------------------------------------------
    # SAVE PROGRESS ID
    # -----------------------------------------------------

    await state.update_data(
        progress_msg_id=progress_id
    )


# =========================================================
# RECEIVE MEDIA
# =========================================================

@router.message(
    UploadState.upload,
    F.document
    | F.video
    | F.photo,
)
async def receive_media(
    message: Message,
    state: FSMContext,
):

    user_id = message.from_user.id

    async with user_lock(user_id):

        data = await state.get_data()

        # -------------------------------------------------
        # CHECK UPLOAD MODE
        # -------------------------------------------------

        if not data.get(
            "upload_mode",
            False,
        ):
            return

        media = list(
            data.get(
                "media",
                [],
            )
        )

        # -------------------------------------------------
        # MAX MEDIA
        # -------------------------------------------------

        if len(media) >= MAX_MEDIA:

            try:
                await message.delete()
            except Exception:
                pass

            return await message.answer(
                f"❌ Maksimal {MAX_MEDIA} media."
            )

        # -------------------------------------------------
        # CREATOR
        # -------------------------------------------------

        is_creator = bool(
            data.get(
                "is_creator",
                False,
            )
        )

        # -------------------------------------------------
        # FILE DATA
        # -------------------------------------------------

        file_id = None
        file_type = None
        file_name = None
        file_size = 0

        if message.document:

            file_type = "document"

            file_id = (
                message.document.file_id
            )

            file_name = (
                message.document.file_name
            )

            file_size = (
                message.document.file_size
                or 0
            )

        elif message.video:

            file_type = "video"

            file_id = (
                message.video.file_id
            )

            file_name = getattr(
                message.video,
                "file_name",
                None,
            )

            file_size = (
                message.video.file_size
                or 0
            )

        elif message.photo:

            file_type = "photo"

            photo = message.photo[-1]

            file_id = photo.file_id

            file_size = (
                photo.file_size
                or 0
            )

        if not file_id:

            return

        # -------------------------------------------------
        # DUPLICATE
        # -------------------------------------------------

        if any(
            item.get("file_id") == file_id
            for item in media
        ):

            try:
                await message.delete()
            except Exception:
                pass

            return await message.answer(
                "⚠️ File tersebut sudah ditambahkan."
            )

        # -------------------------------------------------
        # FILE_ID STORAGE
        # -------------------------------------------------
        # Media is stored by Telegram file_id only. No storage channel,
        # copy_message, or storage migration is used for uploads.
        # file_id remains reusable by this bot after the original message
        # is deleted, so the user's chat does not become the storage.
        source_chat_id = int(message.chat.id)

        # -------------------------------------------------
        # APPEND
        # -------------------------------------------------

        media.append({
            "message_id": int(message.message_id),
            "source_chat_id": source_chat_id,
            "file_id": file_id,
            "type": file_type,
            "file_name": file_name,
            "file_size": file_size,
            "position": len(media) + 1,
        })

        # -------------------------------------------------
        # SAVE STATE
        # -------------------------------------------------

        await state.update_data(
            media=media
        )

        # -------------------------------------------------
        # PROGRESS
        # -------------------------------------------------

        progress_id = data.get(
            "progress_msg_id"
        )

        if progress_id:

            await safe_update(

                message.bot,

                message.chat.id,

                progress_id,

                (
                    "📦 <b>UPLOAD MODE</b>\n\n"
                    f"📁 Media : "
                    f"<b>{len(media)}/{MAX_MEDIA}</b>\n"
                    "💾 Penyimpanan : <b>Telegram file_id</b>\n\n"
                    "Kirim media lagi atau tekan "
                    "<b>STOP & SAVE</b>."
                ),

                upload_keyboard(),
            )

        # -------------------------------------------------
        # DELETE ORIGINAL MESSAGE
        # -------------------------------------------------
        # The Telegram file_id is already stored, so the original upload
        # message is not needed as storage.
        try:
            await message.delete()
        except Exception:
            pass

        logger.info(
            "MEDIA ADDED | user=%s | type=%s | total=%s | file_id=%s | message_id=%s",
            user_id,
            file_type,
            len(media),
            file_id,
            message.message_id,
        )


# =========================================================
# CANCEL UPLOAD
# =========================================================

@router.callback_query(
    F.data == "cancel_upfile"
)
async def cancel_upload(
    call: CallbackQuery,
    state: FSMContext,
):

    await safe_callback_answer(
        call
    )

    user_id = call.from_user.id

    async with user_lock(user_id):

        data = await state.get_data()

        progress_id = data.get(
            "progress_msg_id"
        )

        saving_id = data.get(
            "saving_msg_id"
        )

        # -------------------------------------------------
        # DELETE OLD MESSAGES
        # -------------------------------------------------

        for message_id in (
            progress_id,
            saving_id,
        ):

            if not message_id:
                continue

            try:

                await call.bot.delete_message(
                    chat_id=call.message.chat.id,
                    message_id=message_id,
                )

            except Exception:
                pass

        # -------------------------------------------------
        # CLEAR
        # -------------------------------------------------

        await state.clear()

        # -------------------------------------------------
        # RESPONSE
        # -------------------------------------------------

        try:

            await call.message.edit_text(
                "❌ <b>Upload dibatalkan.</b>",
                parse_mode="HTML",
                reply_markup=home_keyboard(),
            )

        except Exception:

            await call.message.answer(
                "❌ <b>Upload dibatalkan.</b>",
                parse_mode="HTML",
                reply_markup=home_keyboard(),
            )


# =========================================================
# CHOOSE SHARE MODE
# =========================================================

@router.callback_query(
    F.data == "save_upfile"
)
async def choose_share_mode(
    call: CallbackQuery,
    state: FSMContext,
):

    # ACK SEBELUM DB/STATE
    await safe_callback_answer(
        call
    )

    user_id = call.from_user.id

    async with user_lock(user_id):

        data = await state.get_data()

        if not data.get(
            "upload_mode",
            False,
        ):

            return await call.message.answer(
                "❌ Sesi upload sudah berakhir."
            )

        media = list(
            data.get(
                "media",
                [],
            )
        )

        if not media:

            return await call.message.answer(
                "❌ Belum ada media."
            )

        # -------------------------------------------------
        # KEYBOARD
        # -------------------------------------------------

        kb = InlineKeyboardBuilder()

        kb.button(
            text="🔗 Share Media",
            callback_data="share_yes",
        )

        kb.button(
            text="🔒 Private",
            callback_data="share_no",
        )

        kb.adjust(2)

        await call.message.edit_text(

            "📦 <b>PILIH MODE FILE</b>\n\n"
            "🔗 <b>Share Media</b>\n"
            "File bisa dibuka melalui link.\n\n"
            "🔒 <b>Private</b>\n"
            "File hanya dapat dibuka melalui code.",

            parse_mode="HTML",

            reply_markup=kb.as_markup(),
        )


# =========================================================
# SHARE HANDLER
# =========================================================

@router.callback_query(
    F.data.startswith("share_")
)
async def share_handler(
    call: CallbackQuery,
    state: FSMContext,
):

    await safe_callback_answer(
        call
    )

    user_id = call.from_user.id

    async with user_lock(user_id):

        data = await state.get_data()

        if not data.get(
            "upload_mode",
            False,
        ):

            return await call.message.answer(
                "❌ Sesi upload sudah berakhir."
            )

        share = (
            call.data == "share_yes"
        )

        await state.update_data(
            share_media=share
        )

        await state.set_state(
            UploadState.wait_title
        )

        await call.message.edit_text(

            "📝 <b>MASUKKAN JUDUL FILE</b>\n\n"
            "Kirim judul file.\n"
            "Ketik <code>/skip</code> "
            "untuk menggunakan judul otomatis.",

            parse_mode="HTML",
        )


# =========================================================
# INPUT TITLE
# =========================================================

@router.message(
    UploadState.wait_title
)
async def input_title(
    message: Message,
    state: FSMContext,
):

    user_id = message.from_user.id

    async with user_lock(user_id):

        title = (
            message.text or ""
        ).strip()

        # -------------------------------------------------
        # SKIP
        # -------------------------------------------------

        if title.lower() == "/skip":

            title = "Untitled"

        else:

            if len(title) < 3:

                return await message.answer(
                    "❌ Judul minimal 3 karakter."
                )

            if len(title) > 150:

                return await message.answer(
                    "❌ Judul maksimal 150 karakter."
                )

            if is_bad(title):

                return await message.answer(
                    "❌ Judul tidak diperbolehkan."
                )

        # -------------------------------------------------
        # SAVE TITLE
        # -------------------------------------------------

        await state.update_data(
            title=title
        )

        # -------------------------------------------------
        # FILE TYPE
        # -------------------------------------------------

        kb = InlineKeyboardBuilder()

        kb.button(
            text="🆓 FREE",
            callback_data="file_free",
        )

        kb.button(
            text="💰 PAID",
            callback_data="file_paid",
        )

        kb.adjust(2)

        await message.answer(

            "💎 <b>PILIH TIPE FILE</b>\n\n"
            "🆓 <b>FREE</b>\n"
            "File dapat diakses gratis.\n\n"
            "💰 <b>PAID</b>\n"
            "File harus dibayar terlebih dahulu.\n\n"
            "🔒 PAID hanya tersedia untuk "
            "Kreator terverifikasi.",

            parse_mode="HTML",

            reply_markup=kb.as_markup(),
        )


# =========================================================
# FREE FILE
# =========================================================

@router.callback_query(
    F.data == "file_free"
)
async def file_free(
    call: CallbackQuery,
    state: FSMContext,
):

    await safe_callback_answer(
        call
    )

    user_id = call.from_user.id

    async with user_lock(user_id):

        data = await state.get_data()

        if not data.get(
            "upload_mode",
            False,
        ):

            return await call.message.answer(
                "❌ Sesi upload sudah berakhir."
            )

        if not data.get("media"):

            return await call.message.answer(
                "❌ Tidak ada media."
            )

        await state.update_data(

            is_paid=False,

            price=0,

            payment_provider=None,

            review_photos=[],

            saving_msg_id=call.message.message_id,
        )

        try:

            await call.message.edit_text(
                "⏳ <b>Menyimpan file...</b>",
                parse_mode="HTML",
            )

        except Exception:
            pass

        await finalize_save(
            message=call.message,
            state=state,
            user_id=user_id,
        )


# =========================================================
# PAID FILE
# =========================================================

@router.callback_query(
    F.data == "file_paid"
)
async def file_paid(
    call: CallbackQuery,
    state: FSMContext,
):

    # ACK PALING AWAL
    await safe_callback_answer(
        call
    )

    user_id = call.from_user.id

    async with user_lock(user_id):

        data = await state.get_data()

        if not data.get(
            "upload_mode",
            False,
        ):

            return await call.message.answer(
                "❌ Sesi upload sudah berakhir."
            )

        is_creator = bool(
            data.get(
                "is_creator",
                False,
            )
        )

        if not is_creator:

            return await call.message.answer(
                "🔒 <b>PAID TERKUNCI</b>\n\n"
                "Fitur PAID hanya tersedia "
                "untuk Kreator terverifikasi.",
                parse_mode="HTML",
            )

        await state.set_state(
            UploadState.wait_price
        )

        await call.message.edit_text(

            "💰 <b>MASUKKAN HARGA FILE</b>\n\n"
            "Minimal : <b>Rp1.000</b>\n\n"
            "🎨 Status : "
            "<b>Kreator Terverifikasi</b> ✅\n\n"
            "Contoh:\n"
            "<code>1000</code>\n"
            "<code>5000</code>\n"
            "<code>10000</code>",

            parse_mode="HTML",
        )


# =========================================================
# INPUT PRICE
# =========================================================

@router.message(
    UploadState.wait_price
)
async def input_price(
    message: Message,
    state: FSMContext,
):

    user_id = message.from_user.id

    async with user_lock(user_id):

        data = await state.get_data()

        if not data.get(
            "is_creator",
            False,
        ):

            await state.set_state(
                UploadState.wait_title
            )

            return await message.answer(
                "🔒 <b>PAID TERKUNCI</b>\n\n"
                "Hanya Kreator terverifikasi "
                "yang dapat membuat file PAID.",
                parse_mode="HTML",
            )

        # -------------------------------------------------
        # PRICE
        # -------------------------------------------------

        raw = (
            message.text or ""
        ).strip()

        raw = (
            raw
            .replace(".", "")
            .replace(",", "")
            .replace(" ", "")
        )

        if not raw.isdigit():

            return await message.answer(

                "❌ Harga harus berupa angka.\n\n"
                "Contoh:\n"
                "<code>1000</code>\n"
                "<code>5000</code>\n"
                "<code>10000</code>",

                parse_mode="HTML",
            )

        price = int(raw)

        if price < 1000:

            return await message.answer(
                "❌ Harga minimal <b>Rp1.000</b>.",
                parse_mode="HTML",
            )

        # -------------------------------------------------
        # SAVE
        # -------------------------------------------------

        await state.update_data(

            is_paid=True,

            price=price,

            payment_provider="bayargg",

            review_photos=[],
        )

        await state.set_state(
            UploadState.wait_review
        )

        await message.answer(

            "💰 <b>HARGA FILE</b>\n\n"
            f"Harga : <b>{rupiah(price)}</b>\n\n"
            "🖼 <b>UPLOAD REVIEW FILE</b>\n\n"
            "File PAID wajib mempunyai "
            "foto review.\n\n"
            "📸 Minimal : <b>1 foto</b>\n"
            "📸 Maksimal : <b>5 foto</b>\n\n"
            "Contoh review:\n"
            "• Screenshot isi file\n"
            "• Preview produk\n"
            "• Contoh hasil\n"
            "• Screenshot materi\n\n"
            "Kirim foto review sekarang.\n\n"
            "Setelah selesai tekan:\n"
            "✅ <b>SELESAI REVIEW</b>",

            parse_mode="HTML",

            reply_markup=review_keyboard(),
        )


# =========================================================
# RECEIVE REVIEW PHOTO
# =========================================================

@router.message(
    UploadState.wait_review,
    F.photo,
)
async def receive_review_photo(
    message: Message,
    state: FSMContext,
):

    user_id = message.from_user.id

    async with user_lock(user_id):

        data = await state.get_data()

        reviews = list(
            data.get(
                "review_photos",
                [],
            )
            or []
        )

        # -------------------------------------------------
        # MAX
        # -------------------------------------------------

        if len(reviews) >= MAX_REVIEW_PHOTOS:

            try:
                await message.delete()
            except Exception:
                pass

            return await message.answer(
                f"❌ Maksimal {MAX_REVIEW_PHOTOS} foto review."
            )

        # -------------------------------------------------
        # FILE ID
        # -------------------------------------------------

        photo = message.photo[-1]

        file_id = photo.file_id

        # -------------------------------------------------
        # DUPLICATE
        # -------------------------------------------------

        if file_id in reviews:

            try:
                await message.delete()
            except Exception:
                pass

            return await message.answer(
                "⚠️ Foto review tersebut sudah ditambahkan."
            )

        # -------------------------------------------------
        # APPEND
        # -------------------------------------------------

        reviews.append(
            file_id
        )

        # -------------------------------------------------
        # SAVE
        # -------------------------------------------------

        await state.update_data(
            review_photos=reviews
        )

        logger.info(
            "REVIEW PHOTO SAVED | user=%s | total=%s",
            user_id,
            len(reviews),
        )

        # -------------------------------------------------
        # CONFIRM
        # -------------------------------------------------

        await message.answer(

            "🖼 <b>REVIEW DITAMBAHKAN</b>\n\n"
            f"Foto : "
            f"<b>{len(reviews)}/{MAX_REVIEW_PHOTOS}</b>\n\n"
            "Kirim foto review lagi atau tekan:\n"
            "✅ <b>SELESAI REVIEW</b>",

            parse_mode="HTML",

            reply_markup=review_keyboard(),
        )

        # -------------------------------------------------
        # DELETE USER PHOTO
        # -------------------------------------------------

        try:
            await message.delete()
        except Exception:
            pass


# =========================================================
# FINISH REVIEW
# =========================================================

@router.callback_query(
    F.data == "finish_review"
)
async def finish_review(
    call: CallbackQuery,
    state: FSMContext,
):

    # =====================================================
    # ACK DULU
    # =====================================================

    await safe_callback_answer(
        call
    )

    user_id = call.from_user.id

    async with user_lock(user_id):

        # -------------------------------------------------
        # STATE
        # -------------------------------------------------

        current_state = (
            await state.get_state()
        )

        logger.info(
            "FINISH REVIEW | user=%s | state=%s",
            user_id,
            current_state,
        )

        if (
            current_state
            != UploadState.wait_review.state
        ):

            return await call.message.answer(
                "❌ Sesi review sudah berakhir."
            )

        # -------------------------------------------------
        # DATA
        # -------------------------------------------------

        data = await state.get_data()

        reviews = list(
            data.get(
                "review_photos",
                [],
            )
            or []
        )

        # -------------------------------------------------
        # VALIDATE
        # -------------------------------------------------

        if len(reviews) < 1:

            return await call.message.answer(
                "❌ Minimal 1 foto review."
            )

        if len(reviews) > MAX_REVIEW_PHOTOS:

            return await call.message.answer(
                f"❌ Maksimal {MAX_REVIEW_PHOTOS} foto review."
            )

        # -------------------------------------------------
        # SAVING MESSAGE
        # -------------------------------------------------

        try:

            await call.message.edit_text(

                "⏳ <b>MENYIMPAN FILE...</b>\n\n"
                f"🖼 Review : "
                f"<b>{len(reviews)} foto</b>\n\n"
                "Mohon tunggu...",

                parse_mode="HTML",
            )

        except Exception:
            pass

        await state.update_data(
            saving_msg_id=call.message.message_id
        )

        # -------------------------------------------------
        # FINAL SAVE
        # -------------------------------------------------

        await finalize_save(

            message=call.message,

            state=state,

            user_id=user_id,
        )


# =========================================================
# SEND PAID REVIEW
# =========================================================

async def send_paid_review(
    bot,
    *,
    user_id: int,
    username: Optional[str],
    title: str,
    code: str,
    review_code: str,
    price: int,
    media_count: int,
    review_photos: list,
):

    if not review_photos:
        return

    # -----------------------------------------------------
    # BOT INFO
    # -----------------------------------------------------

    me = await bot.get_me()

    bot_username = (
        me.username
        or "Unknown"
    )

    # -----------------------------------------------------
    # ESCAPE HTML
    # -----------------------------------------------------

    safe_title = escape(
        title or "Untitled"
    )

    safe_bot_username = escape(
        bot_username
    )

    safe_code = escape(
        code
    )

    # -----------------------------------------------------
    # CLEAN REVIEW CAPTION
    # -----------------------------------------------------

    caption = (
        "💰 <b>PAID FILE</b>\n"
        "━━━━━━━━━━━━━━\n"
        f"🤖 Bot: @{safe_bot_username}\n"
        f"📝 Judul: {safe_title}\n"
        f"📦 Total media: {media_count}\n"
        f"💎 Media: <b>{'PAID' if price > 0 else 'FREE'}</b>\n"
        f"👀 Code review: <code>{escape(review_code)}</code>\n"
        f"📦 Code media: <code>{safe_code}</code>\n"
        f"💵 Harga: <b>{rupiah(price)}</b>\n"
        "🛒 Code media digunakan untuk membuka media; code review gratis untuk melihat review."
    )

    # -----------------------------------------------------
    # BUILD ALBUM
    # -----------------------------------------------------

    media_group = []

    for index, photo_id in enumerate(
        review_photos
    ):

        if index == 0:

            media_group.append(
                InputMediaPhoto(
                    media=photo_id,
                    caption=caption,
                    parse_mode="HTML",
                )
            )

        else:

            media_group.append(
                InputMediaPhoto(
                    media=photo_id,
                )
            )

    # -----------------------------------------------------
    # SEND
    # -----------------------------------------------------

    try:

        await bot.send_media_group(
            chat_id=REVIEW_CHANNEL_ID,
            media=media_group,
        )
        await bot.send_message(
            chat_id=REVIEW_CHANNEL_ID,
            text=(
                f"📝 <b>{safe_title}</b>\n"
                f"👀 Code review: <code>{escape(review_code)}</code>\n"
                f"📦 Code media: <code>{safe_code}</code>\n"
                f"📦 Total media: <b>{media_count}</b>\n"
                f"💎 Media: <b>{'PAID' if price > 0 else 'FREE'}</b>\n"
                f"🤖 Bot: @{safe_bot_username}"
            ),
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="👀 Buka Review", url=f"https://t.me/{bot_username}?start={review_code}")],
                [InlineKeyboardButton(text="📦 Buka Code Media", url=f"https://t.me/{bot_username}?start={safe_code}")],
            ]),
        )

        logger.info(
            "PAID REVIEW SENT | code=%s | photos=%s",
            code,
            len(review_photos),
        )

    except TelegramRetryAfter as e:

        retry_after = max(
            float(e.retry_after),
            0.5,
        )

        logger.warning(
            "REVIEW RATE LIMIT | retry_after=%.2fs | code=%s",
            retry_after,
            code,
        )

        await asyncio.sleep(
            retry_after + 0.2
        )

        await bot.send_media_group(
            chat_id=REVIEW_CHANNEL_ID,
            media=media_group,
        )

    except Exception:

        logger.exception(
            "PAID REVIEW ERROR | code=%s",
            code,
        )

        raise


# =========================================================
# SEND UPLOAD LOG
# =========================================================

async def send_upload_log(
    bot,
    *,
    user_id: int,
    title: str,
    code: str,
    review_code: Optional[str],
    media_count: int,
    is_paid: bool,
    price: int,
):

    try:

        me = await bot.get_me()

        bot_username = (
            me.username
            or "Unknown"
        )

        # -------------------------------------------------
        # ESCAPE HTML
        # -------------------------------------------------

        safe_title = escape(
            title or "Untitled"
        )

        safe_bot_username = escape(
            bot_username
        )

        safe_code = escape(
            code
        )

        mode = (
            f"💰 PAID {rupiah(price)}"
            if is_paid
            else "🆓 FREE"
        )

        # -------------------------------------------------
        # CLEAN UPDATE MESSAGE
        # -------------------------------------------------

        text = (
            "📤 <b>UPLOAD BARU</b>\n"
            "━━━━━━━━━━━━━━\n"
            f"🤖 Bot: @{safe_bot_username}\n"
            f"🆔 ID: <code>{mask_user_id(user_id)}</code>\n"
            f"📝 Judul: {safe_title}\n"
            f"👀 Code review: <code>{escape(review_code or '-')}</code>\n"
            f"📦 Code media: <code>{safe_code}</code>\n"
            f"📦 Total media: {media_count}\n"
            f"💎 Media: <b>{'PAID' if is_paid else 'FREE'}</b>\n"
            f"💰 Harga: {rupiah(price) if is_paid else 'Gratis'}"
        )

        await bot.send_message(

            chat_id=CHANNEL_ID,

            text=text,

            parse_mode="HTML",
        )

        logger.info(
            "UPLOAD LOG SENT | code=%s",
            code,
        )

    except Exception:

        logger.exception(
            "UPLOAD LOG ERROR | code=%s",
            code,
        )


# =========================================================
# FINAL SAVE
# =========================================================

async def finalize_save(
    message: Message,
    state: FSMContext,
    user_id: int,
):

    data = await state.get_data()

    # -----------------------------------------------------
    # PREVENT DOUBLE SAVE
    # -----------------------------------------------------

    if data.get(
        "saving",
        False,
    ):
        return

    await state.update_data(
        saving=True
    )

    try:

        # =================================================
        # MEDIA
        # =================================================

        media = [

            item

            for item in (
                data.get(
                    "media",
                    [],
                )
                or []
            )

            if item.get("file_id")
        ]

        if not media:

            await state.update_data(
                saving=False
            )

            return await message.answer(
                "❌ Tidak ada media."
            )

        # =================================================
        # BASIC DATA
        # =================================================

        title = (
            data.get("title")
            or "Untitled"
        )

        share_media = bool(
            data.get(
                "share_media",
                True,
            )
        )

        is_paid = bool(
            data.get(
                "is_paid",
                False,
            )
        )

        price = int(
            data.get(
                "price",
                0,
            )
            or 0
        )

        payment_provider = (
            data.get(
                "payment_provider"
            )
        )

        review_photos = list(
            data.get(
                "review_photos",
                [],
            )
            or []
        )

        # =================================================
        # PAID VALIDATION
        # =================================================

        if is_paid:

            if not data.get(
                "is_creator",
                False,
            ):

                await state.update_data(
                    saving=False
                )

                return await message.answer(
                    "❌ Hanya Kreator "
                    "terverifikasi yang dapat "
                    "membuat file PAID."
                )

            if price < 1000:

                await state.update_data(
                    saving=False
                )

                return await message.answer(
                    "❌ Harga PAID minimal Rp1.000."
                )

            if not review_photos:

                await state.update_data(
                    saving=False
                )

                await state.set_state(
                    UploadState.wait_review
                )

                return await message.answer(
                    "❌ File PAID wajib "
                    "memiliki minimal 1 foto review."
                )

        else:

            price = 0

            payment_provider = None

            review_photos = []

        # =================================================
        # USER DATA
        # =================================================

        username = data.get(
            "creator_username"
        )

        fullname = (
            data.get(
                "creator_fullname"
            )
            or "Unknown"
        )

        # =================================================
        # GENERATE CODE
        # =================================================

        code = await generate_code()
        review_code = await generate_review_code() if review_photos else None

        media_count = len(media)

        # =================================================
        # JSON
        # =================================================

        media_json = json.dumps(
            media,
            ensure_ascii=False,
            separators=(
                ",",
                ":",
            ),
        )

        review_json = json.dumps(
            review_photos,
            ensure_ascii=False,
            separators=(
                ",",
                ":",
            ),
        )

        # =================================================
        # MEDIA VALUES
        # =================================================

        media_values = []

        for item in media:

            media_values.append(

                (

                    code,

                    item.get(
                        "message_id"
                    ),

                    item.get("source_chat_id"),

                    item.get(
                        "file_id"
                    ),

                    item.get(
                        "type"
                    ),

                    item.get(
                        "file_size",
                        0,
                    ),

                    title,

                    item.get(
                        "position",
                        0,
                    ),
                )
            )

        # =================================================
        # DATABASE
        # =================================================

        pool = await get_pool()

        # FREE upload economy: 1 point/media cost, 20% returned as reward.
        # Charge atomically before creating the file so a failed upload cannot
        # silently create a debt. Paid/VIP/creator uploads keep existing flow.
        try:
            from utils.user import get_user_status
            current_level = await get_user_status(pool, user_id)
        except Exception:
            current_level = "free"
        free_uploader = (current_level == "free" and not is_paid)
        # FREE uploads never consume points.
        # Reward is granted only for completed blocks of 50 media:
        # 1-49 => 0, 50-99 => +10, 100 => +20.

        async with pool.acquire() as conn:

            async with conn.transaction():

                # =========================================
                # USER
                # =========================================

                await conn.execute(

                    """
                    INSERT INTO users (
                        user_id,
                        username,
                        fullname
                    )
                    VALUES (
                        $1,
                        $2,
                        $3
                    )
                    ON CONFLICT (user_id)
                    DO UPDATE SET
                        username = EXCLUDED.username,
                        fullname = EXCLUDED.fullname
                    """,

                    user_id,

                    username,

                    fullname,
                )

                # =========================================
                # FILE
                # =========================================

                await conn.execute(
                    """
                    INSERT INTO files (
                        code,
                        review_code,
                        title,
                        creator,
                        media,
                        share_media,
                        is_share,
                        owner_id,
                        seller_id,
                        media_count,
                        expires_at,
                        is_paid,
                        price,
                        payment_provider,
                        review_photos,
                        view_count,
                        download_count,
                        favorite_count
                    )
                    VALUES (
                        $1, $2, $3, $4, $5, $6, $7, $8, $9, $10,
                        NULL, $11, $12, $13, $14, 0, 0, 0
                    )
                    """,
                    code,
                    review_code,
                    title,
                    fullname,
                    media_json,
                    share_media,
                    share_media,
                    user_id,
                    user_id,
                    media_count,
                    is_paid,
                    price,
                    payment_provider,
                    review_json,
                )

                # =========================================
                # MEDIA TABLE
                # =========================================

                if media_values:

                    await conn.executemany(

                        """
                        INSERT INTO medias (
                            code,
                            message_id,
                            source_chat_id,
                            file_id,
                            file_type,
                            file_size,
                            title,
                            position
                        )
                        VALUES (
                            $1,
                            $2,
                            $3,
                            $4,
                            $5,
                            $6,
                            $7,
                            $8
                        )
                        """,

                        media_values,
                    )

                # Stable address for every media inside the code.
                me = await message.bot.get_me()
                media_code_rows = [
                    (f"{code}-m{int(item.get('position') or i):03d}", code,
                     None, int(item.get('position') or i), me.username or "")
                    for i, item in enumerate(media, 1)
                ]
                await conn.executemany(
                    """INSERT INTO media_codes(media_code,file_code,media_id,position,bot_username)
                       VALUES($1,$2,$3,$4,$5)
                       ON CONFLICT(file_code,position) DO UPDATE SET media_code=EXCLUDED.media_code, bot_username=EXCLUDED.bot_username""",
                    media_code_rows,
                )

                # =================================================
                # UPLOAD POINT REWARD
                # =================================================
                # Uploading never costs points.
                # Reward is granted only for completed blocks of 50:
                # 1-49 media = 0 points
                # 50-99 media = +10 points
                # 100 media = +20 points.
                from decimal import Decimal
                upload_reward = Decimal(media_count // 50) * Decimal("10")
                if upload_reward > 0:
                    row_points = await conn.fetchrow(
                        "SELECT points FROM users WHERE user_id=$1 FOR UPDATE",
                        user_id,
                    )
                    if row_points:
                        current_points = Decimal(str(row_points["points"] or 0))
                        new_points = current_points + upload_reward
                        reward_ref = f"upload_reward:{user_id}:{code}"
                        await conn.execute(
                            "UPDATE users SET points=$1, updated_at=NOW() WHERE user_id=$2",
                            new_points,
                            user_id,
                        )
                        await conn.execute(
                            """INSERT INTO point_transactions(
                                user_id, amount, balance_after, type, reference, description
                            ) VALUES($1,$2,$3,'upload_reward',$4,$5)
                            ON CONFLICT(reference) DO NOTHING""",
                            user_id,
                            upload_reward,
                            new_points,
                            reward_ref,
                            f"Upload reward: {media_count} media = +{upload_reward} points",
                        )

        # =================================================
        # DATABASE SUCCESS
        # =================================================

        logger.info(
            "FILE SAVED | user=%s | code=%s | media=%s | paid=%s",
            user_id,
            code,
            media_count,
            is_paid,
        )

        # =================================================
        # SAVE OLD MESSAGE IDS
        # =================================================

        progress_id = data.get(
            "progress_msg_id"
        )

        saving_msg_id = data.get(
            "saving_msg_id"
        )

        # =================================================
        # DELETE OLD PROGRESS
        # =================================================

        for message_id in (
            progress_id,
            saving_msg_id,
        ):

            if not message_id:
                continue

            try:

                await message.bot.delete_message(

                    chat_id=message.chat.id,

                    message_id=message_id,
                )

            except Exception:
                pass

        # =================================================
        # CLEAR STATE
        # =================================================

        await state.clear()

        # =================================================
        # MEDIA SUMMARY
        # =================================================

        video_count = sum(
            1
            for item in media
            if item.get("type") == "video"
        )

        photo_count = sum(
            1
            for item in media
            if item.get("type") == "photo"
        )

        document_count = sum(
            1
            for item in media
            if item.get("type") == "document"
        )

        info = []

        if video_count:

            info.append(
                f"{video_count} Video"
            )

        if photo_count:

            info.append(
                f"{photo_count} Photo"
            )

        if document_count:

            info.append(
                f"{document_count} Document"
            )

        files_info = (
            " • ".join(info)
            if info
            else "0 File"
        )

        # =================================================
        # STATUS
        # =================================================

        if is_paid:

            mode = (
                f"💰 PAID "
                f"{rupiah(price)}"
            )

        else:

            mode = "🆓 FREE"

        # =================================================
        # ESCAPE OUTPUT
        # =================================================

        safe_title = escape(
            title
        )

        safe_code = escape(
            code
        )

        # =================================================
        # SUCCESS
        # =================================================

        lang = await get_user_language(user_id)
        review_line_id = f"\n👀 <b>Code Review</b>: <code>{escape(review_code)}</code>" if review_code else ""
        review_line_en = f"\n👀 <b>Review Code</b>: <code>{escape(review_code)}</code>" if review_code else ""
        review_line_zh = f"\n👀 <b>Review Code</b>：<code>{escape(review_code)}</code>" if review_code else ""
        success_text = {
            "id": (f"✅ <b>FILE BERHASIL DISIMPAN</b>\n\n📝 <b>Judul</b>: {safe_title}\n📦 <b>Total Media</b>: {media_count}\n📁 <b>Isi</b>: {escape(files_info)}\n💎 <b>Status</b>: {mode}{review_line_id}\n📦 <b>Code Media</b>: <code>{safe_code}</code>"),
            "en": (f"✅ <b>FILE SAVED SUCCESSFULLY</b>\n\n📝 <b>Title</b>: {safe_title}\n📦 <b>Total Media</b>: {media_count}\n📁 <b>Content</b>: {escape(files_info)}\n💎 <b>Status</b>: {mode}{review_line_en}\n📦 <b>Media Code</b>: <code>{safe_code}</code>"),
            "zh": (f"✅ <b>文件保存成功</b>\n\n📝 <b>标题</b>：{safe_title}\n📦 <b>媒体数量</b>：{media_count}\n📁 <b>内容</b>：{escape(files_info)}\n💎 <b>状态</b>：{mode}{review_line_zh}\n📦 <b>媒体代码</b>：<code>{safe_code}</code>"),
        }
        await message.answer(success_text.get(lang, success_text["id"]), parse_mode="HTML")

        # =================================================
        # PAID REVIEW CHANNEL
        # =================================================

        if is_paid and review_photos:

            try:

                await send_paid_review(

                    message.bot,

                    user_id=user_id,

                    username=username,

                    title=title,

                    code=code,

                    review_code=review_code,

                    price=price,

                    media_count=media_count,

                    review_photos=review_photos,
                )

            except Exception:

                # File database tetap aman.
                logger.exception(
                    "PAID REVIEW FAILED AFTER FILE SAVE | code=%s",
                    code,
                )

        # =================================================
        # UPDATE CHANNEL
        # =================================================
        # FREE uploader: never auto-post the code/upload to any channel.
        # Paid/non-free uploads keep the existing channel log behaviour.
        if not free_uploader:
            await send_upload_log(
                message.bot,
                user_id=user_id,
                title=title,
                code=code,
                review_code=review_code,
                media_count=media_count,
                is_paid=is_paid,
                price=price,
            )

        # =================================================
        # FREE SHARE REWARD NOTICE
        # =================================================
        # Sharing itself gives ZERO points. The owner gets +1 point only
        # after a unique other user actually opens the shared code.
        if free_uploader:
            try:
                me = await message.bot.get_me()
                share_link = share_url(
                    me.username or "",
                    code,
                    user_id,
                    title,
                )
                share_text = {
                    "id": (
                        "🔗 <b>SHARE CODE & DAPATKAN POIN</b>\n\n"
                        f"🔑 Code: <code>{safe_code}</code>\n"
                        "Bagikan link ini. Setiap <b>1 pengguna unik</b> "
                        "yang benar-benar membuka code memberi kamu <b>+1 poin</b>.\n\n"
                        "⚠️ Membagikan link saja tidak memberikan poin."
                    ),
                    "en": (
                        "🔗 <b>SHARE CODE & EARN POINTS</b>\n\n"
                        f"🔑 Code: <code>{safe_code}</code>\n"
                        "Share this link. Every <b>unique user</b> who actually opens "
                        "the code gives you <b>+1 point</b>.\n\n"
                        "⚠️ Sharing the link alone does not give points."
                    ),
                    "zh": (
                        "🔗 <b>分享代码并赚取积分</b>\n\n"
                        f"🔑 代码：<code>{safe_code}</code>\n"
                        "每一位<b>真正打开代码的独立用户</b>可为你增加 <b>+1 积分</b>。\n\n"
                        "⚠️ 仅分享链接不会获得积分。"
                    ),
                }[lang]
                share_button = {
                    "id": "🔗 Bagikan Code",
                    "en": "🔗 Share Code",
                    "zh": "🔗 分享代码",
                }[lang]
                await message.answer(
                    share_text,
                    parse_mode="HTML",
                    reply_markup=InlineKeyboardMarkup(
                        inline_keyboard=[[
                            InlineKeyboardButton(
                                text=share_button,
                                url=share_link,
                            )
                        ]]
                    ),
                )
            except Exception:
                logger.exception("FREE SHARE NOTICE ERROR | code=%s", code)

    # =====================================================
    # FINAL ERROR
    # =====================================================

    except Exception:

        logger.exception(
            "FINAL SAVE ERROR | user=%s",
            user_id,
        )

        try:

            await state.update_data(
                saving=False
            )

        except Exception:
            pass

        try:

            await message.answer(

                "❌ <b>GAGAL MENYIMPAN FILE</b>\n\n"
                "Terjadi kesalahan saat "
                "menyimpan file ke database.\n\n"
                "Silakan coba lagi.",

                parse_mode="HTML",
            )

        except Exception:

            logger.exception(
                "ERROR MESSAGE FAILED | user=%s",
                user_id,
            )
