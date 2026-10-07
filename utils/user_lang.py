from database import get_pool


async def get_user_language(user_id):

    pool = await get_pool()

    lang = await pool.fetchval(
        """
        SELECT language
        FROM users
        WHERE user_id=$1
        """,
        user_id
    )

    return lang if lang in ("id", "en", "zh") else "id"
