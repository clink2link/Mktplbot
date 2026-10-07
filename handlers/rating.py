from aiogram import Router, F
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton
)

router = Router()


@router.callback_query(F.data.startswith("rating:"))
async def rating_menu(call: CallbackQuery):

    code = call.data.split(":")[1]

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="⭐", callback_data=f"rate:{code}:1"),
                InlineKeyboardButton(text="⭐⭐", callback_data=f"rate:{code}:2"),
                InlineKeyboardButton(text="⭐⭐⭐", callback_data=f"rate:{code}:3"),
            ],
            [
                InlineKeyboardButton(text="⭐⭐⭐⭐", callback_data=f"rate:{code}:4"),
                InlineKeyboardButton(text="⭐⭐⭐⭐⭐", callback_data=f"rate:{code}:5"),
            ],
            [
                InlineKeyboardButton(
                    text="⬅️ Kembali",
                    callback_data=f"market:{code}"
                )
            ]
        ]
    )

    await call.message.edit_text(
        "⭐ <b>Berikan Rating</b>\n\nPilih jumlah bintang.",
        parse_mode="HTML",
        reply_markup=kb
    )

    await call.answer()


from database import fetchrow, execute


@router.callback_query(F.data.startswith("rate:"))
async def save_rating(call: CallbackQuery):

    _, code, star = call.data.split(":")
    star = int(star)

    user_id = call.from_user.id

    row = await fetchrow(
        """
        SELECT id
        FROM file_ratings
        WHERE user_id=$1
        AND file_code=$2
        """,
        user_id,
        code
    )

    if row:

        await execute(
            """
            UPDATE file_ratings
            SET rating=$1
            WHERE id=$2
            """,
            star,
            row["id"]
        )

    else:

        await execute(
            """
            INSERT INTO file_ratings(
                user_id,
                file_code,
                rating
            )
            VALUES($1,$2,$3)
            """,
            user_id,
            code,
            star
        )

    await execute(
        """
        UPDATE files
        SET
            rating = (
                SELECT ROUND(AVG(rating)::numeric,1)
                FROM file_ratings
                WHERE file_code=$1
            ),
            review_count = (
                SELECT COUNT(*)
                FROM file_ratings
                WHERE file_code=$1
            )
        WHERE code=$1
        """,
        code
    )

    await call.answer(
        "⭐ Rating berhasil disimpan.",
        show_alert=True
    )

    await call.message.delete()
