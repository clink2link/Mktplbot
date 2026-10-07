from aiogram import Router, F
from aiogram.types import CallbackQuery

from database import fetchrow, execute

router = Router()


@router.callback_query(F.data.startswith("favorite:"))
async def favorite_toggle(call: CallbackQuery):

    code = call.data.split(":", 1)[1]
    user_id = call.from_user.id

    # =========================
    # CEK FILE
    # =========================

    file = await fetchrow(
        """
        SELECT code
        FROM files
        WHERE code=$1
        LIMIT 1
        """,
        code
    )

    if not file:
        return await call.answer(
            "❌ File tidak ditemukan.",
            show_alert=True
        )

    # =========================
    # CEK FAVORIT
    # =========================

    exists = await fetchrow(
        """
        SELECT 1
        FROM file_favorites
        WHERE user_id=$1
          AND file_code=$2
        LIMIT 1
        """,
        user_id,
        code
    )

    # =========================
    # HAPUS FAVORIT
    # =========================

    if exists:

        await execute(
            """
            DELETE FROM file_favorites
            WHERE user_id=$1
              AND file_code=$2
            """,
            user_id,
            code
        )

        await execute(
            """
            UPDATE files
            SET favorite_count = GREATEST(
                COALESCE(favorite_count, 0) - 1,
                0
            )
            WHERE code=$1
            """,
            code
        )

        await call.answer(
            "💔 Favorit dihapus.",
            show_alert=True
        )

        return

    # =========================
    # TAMBAH FAVORIT
    # =========================

    await execute(
        """
        INSERT INTO file_favorites (
            user_id,
            file_code
        )
        VALUES ($1, $2)
        ON CONFLICT (user_id, file_code)
        DO NOTHING
        """,
        user_id,
        code
    )

    await execute(
        """
        UPDATE files
        SET favorite_count =
            COALESCE(favorite_count, 0) + 1
        WHERE code=$1
        """,
        code
    )

    await call.answer(
        "❤️ Ditambahkan ke favorit.",
        show_alert=True
    )
