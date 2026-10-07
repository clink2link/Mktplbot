from aiogram import Router, F
from aiogram.types import CallbackQuery
from database import fetchrow, execute

router = Router()

async def toggle_reaction(call: CallbackQuery, reaction: str):
    code = call.data.split(":", 1)[1]
    user_id = call.from_user.id

    exists = await fetchrow(
        "SELECT reaction FROM file_reactions WHERE user_id=$1 AND file_code=$2",
        user_id, code
    )
    if not exists:
        await execute(
            "INSERT INTO file_reactions(user_id,file_code,reaction) VALUES($1,$2,$3)",
            user_id, code, reaction
        )
        message = "👍 Kamu menyukai file ini." if reaction == "like" else "👎 Kamu tidak menyukai file ini."
    elif exists["reaction"] == reaction:
        await execute(
            "DELETE FROM file_reactions WHERE user_id=$1 AND file_code=$2",
            user_id, code
        )
        message = "↩️ Reaksi dihapus."
    else:
        await execute(
            "UPDATE file_reactions SET reaction=$1, updated_at=NOW() WHERE user_id=$2 AND file_code=$3",
            reaction, user_id, code
        )
        message = "👍 Suka dipilih." if reaction == "like" else "👎 Tidak suka dipilih."

    await execute(
        """
        UPDATE files f SET
            likes = (SELECT COUNT(*) FROM file_reactions r WHERE r.file_code=f.code AND r.reaction='like'),
            dislikes = (SELECT COUNT(*) FROM file_reactions r WHERE r.file_code=f.code AND r.reaction='dislike')
        WHERE f.code=$1
        """, code
    )
    await call.answer(message)
    # Render ulang detail supaya counter langsung terlihat.
    from handlers.market_detail import market_detail
    await market_detail(call)

@router.callback_query(F.data.startswith("like:"))
async def like_file(call: CallbackQuery):
    await toggle_reaction(call, "like")

@router.callback_query(F.data.startswith("dislike:"))
async def dislike_file(call: CallbackQuery):
    await toggle_reaction(call, "dislike")
