import json
import logging
import secrets
import string

from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from aiogram.exceptions import TelegramBadRequest

from database import get_pool

router = Router()
logger = logging.getLogger(__name__)

MAX_REVIEW_PHOTOS = 10


class GetReviewState(StatesGroup):
    waiting_photos = State()


async def ensure_review_codes_table():
    pool = await get_pool()
    await pool.execute(
        """
        CREATE TABLE IF NOT EXISTS review_codes (
            id BIGSERIAL PRIMARY KEY,
            review_code TEXT UNIQUE NOT NULL,
            owner_id BIGINT NOT NULL,
            photo_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )


def review_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ SELESAI / BUAT CODE",
                    callback_data="getreview_finish",
                )
            ],
            [
                InlineKeyboardButton(
                    text="❌ BATAL",
                    callback_data="getreview_cancel",
                )
            ],
        ]
    )


def make_review_code() -> str:
    alphabet = string.ascii_letters + string.digits
    return "PasteleReview_" + "".join(secrets.choice(alphabet) for _ in range(14))


async def update_progress(message: Message, count: int):
    try:
        await message.answer(
            "📸 <b>FOTO REVIEW DITERIMA</b>\n\n"
            f"📷 Foto: <b>{count}/{MAX_REVIEW_PHOTOS}</b>\n\n"
            "Kirim foto lagi atau tekan <b>SELESAI / BUAT CODE</b>.",
            reply_markup=review_keyboard(),
        )
    except Exception:
        pass


@router.message(F.text.func(lambda x: (x or "").strip().lower() == "/getreview"))
async def getreview_start(message: Message, state: FSMContext):
    # Creation happens only in the user's current private chat.
    if message.chat.type != "private":
        return await message.answer(
            "🔒 Silakan gunakan <b>/getreview</b> di chat pribadi dengan bot."
        )

    await ensure_review_codes_table()
    await state.clear()
    await state.update_data(review_photos=[], prompt_message_id=message.message_id)
    await state.set_state(GetReviewState.waiting_photos)

    await message.answer(
        "👀 <b>BUAT CODE REVIEW</b>\n\n"
        "📸 Kirim foto/screenshot review kamu ke sini.\n"
        f"🔢 Maksimal <b>{MAX_REVIEW_PHOTOS} foto</b>.\n\n"
        "Setelah selesai, tekan <b>✅ SELESAI / BUAT CODE</b>.\n"
        "❌ Bisa dibatalkan kapan saja.",
        reply_markup=review_keyboard(),
    )


@router.message(GetReviewState.waiting_photos, F.photo)
async def getreview_photo(message: Message, state: FSMContext):
    data = await state.get_data()
    photos = list(data.get("review_photos") or [])

    if len(photos) >= MAX_REVIEW_PHOTOS:
        return await message.answer(
            f"⚠️ Maksimal {MAX_REVIEW_PHOTOS} foto review sudah tercapai.\n"
            "Tekan <b>✅ SELESAI / BUAT CODE</b>."
        )

    file_id = message.photo[-1].file_id
    if file_id in photos:
        return await message.answer("⚠️ Foto ini sudah ditambahkan.")

    photos.append(file_id)
    await state.update_data(review_photos=photos)
    logger.info("GETREVIEW PHOTO | user=%s | total=%s", message.from_user.id, len(photos))

    await message.answer(
        "📸 <b>REVIEW DITAMBAHKAN</b>\n\n"
        f"📷 Progress: <b>{len(photos)}/{MAX_REVIEW_PHOTOS}</b>\n\n"
        "Kirim foto berikutnya atau tekan <b>SELESAI / BUAT CODE</b>.",
        reply_markup=review_keyboard(),
    )


@router.message(GetReviewState.waiting_photos)
async def getreview_nonphoto(message: Message):
    await message.answer(
        "📸 Silakan kirim <b>foto/screenshot</b> review.\n"
        "Maksimal 10 foto."
    )


@router.callback_query(F.data == "getreview_cancel")
async def getreview_cancel(call: CallbackQuery, state: FSMContext):
    await call.answer()
    await state.clear()
    try:
        await call.message.edit_text("❌ Pembuatan Code Review dibatalkan.")
    except TelegramBadRequest:
        await call.message.answer("❌ Pembuatan Code Review dibatalkan.")


@router.callback_query(F.data == "getreview_finish")
async def getreview_finish(call: CallbackQuery, state: FSMContext):
    await call.answer()

    if call.message and call.message.chat.type != "private":
        return await call.message.answer(
            "🔒 Code Review hanya dapat dibuat melalui chat pribadi dengan bot."
        )

    data = await state.get_data()
    photos = list(data.get("review_photos") or [])

    if not photos:
        return await call.message.answer("⚠️ Kirim minimal 1 foto review terlebih dahulu.")

    if len(photos) > MAX_REVIEW_PHOTOS:
        photos = photos[:MAX_REVIEW_PHOTOS]

    await ensure_review_codes_table()
    pool = await get_pool()

    review_code = None
    for _ in range(10):
        candidate = make_review_code()
        exists = await pool.fetchval(
            "SELECT 1 FROM review_codes WHERE lower(review_code)=lower($1) LIMIT 1",
            candidate,
        )
        if not exists:
            review_code = candidate
            break

    if not review_code:
        return await call.message.answer(
            "❌ Gagal membuat Code Review. Silakan coba lagi."
        )

    await pool.execute(
        """
        INSERT INTO review_codes (review_code, owner_id, photo_ids)
        VALUES ($1, $2, $3::jsonb)
        """,
        review_code,
        call.from_user.id,
        json.dumps(photos),
    )

    await state.clear()

    # IMPORTANT: only send the code to the creator in private chat.
    # Nothing is posted to a group/channel automatically.
    try:
        await call.message.edit_text(
            "✅ <b>CODE REVIEW BERHASIL DIBUAT!</b>\n\n"
            f"📸 Total foto: <b>{len(photos)}</b>\n"
            f"🎟️ Code Review:\n<code>{review_code}</code>\n\n"
            "📌 Code ini hanya dikirim kepada kamu.\n"
            "Kamu bisa menyalinnya dan membagikannya sendiri jika mau."
        )
    except TelegramBadRequest:
        await call.message.answer(
            "✅ <b>CODE REVIEW BERHASIL DIBUAT!</b>\n\n"
            f"📸 Total foto: <b>{len(photos)}</b>\n"
            f"🎟️ Code Review:\n<code>{review_code}</code>\n\n"
            "📌 Code ini hanya dikirim kepada kamu."
        )
