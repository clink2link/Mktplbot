from aiogram import BaseMiddleware
from aiogram.types import Message, CallbackQuery
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from database import get_pool
class BanMiddleware(BaseMiddleware):
    """
    Middleware untuk mengecek apakah user sedang dibanned.
    Optimasi:
    - CallbackQuery di-answer secepat mungkin.
    - Tidak membiarkan callback expired menjatuhkan handler.
    - Error database ditangani dengan aman.
    - Tidak melakukan operasi yang tidak perlu.
    """
    async def __call__(self, handler, event, data):
        # ====================================================================
        # ONLY HANDLE MESSAGE / CALLBACK QUERY
        # ====================================================================
        if not isinstance(event, (Message, CallbackQuery)):
            return await handler(event, data)
        # ====================================================================
        # GET USER
        # ====================================================================
        user = event.from_user
        if not user:
            return await handler(event, data)
        user_id = user.id
        # ====================================================================
        # CALLBACK QUERY
        # ====================================================================
        #
        # Telegram callback query harus di-ACK dengan cepat.
        #
        # Jangan menunggu database sebelum call.answer().
        #
        if isinstance(event, CallbackQuery):
            try:
                await event.answer()
            except TelegramBadRequest as e:
                error_text = str(e).lower()
                # Callback sudah expired.
                # Jangan membuat polling crash.
                if not (
                    "query is too old" in error_text
                    or "query id is invalid" in error_text
                    or "response timeout expired" in error_text
                ):
                    raise
            except TelegramForbiddenError:
                # User/bot interaction sudah tidak memungkinkan.
                return
        # ====================================================================
        # DATABASE
        # ====================================================================
        try:
            pool = await get_pool()
            # ----------------------------------------------------------------
            # IMPORTANT
            # ----------------------------------------------------------------
            #
            # Gunakan user_id karena kolom users.user_id digunakan oleh
            # sistem bot.
            #
            # Kalau database kamu ternyata menggunakan "id" sebagai primary
            # Telegram user ID, query ini bisa disesuaikan.
            #
            user_row = await pool.fetchrow(
                """
                SELECT is_banned
                FROM users
                WHERE user_id = $1
                LIMIT 1
                """,
                user_id,
            )
        except Exception:
            # Jangan sampai masalah database membuat seluruh update bot
            # gagal/crash.
            #
            # Dalam kondisi DB error, kita lanjutkan handler.
            return await handler(event, data)
        # ====================================================================
        # CHECK BAN
        # ====================================================================
        if user_row and user_row["is_banned"]:
            # ----------------------------------------------------------------
            # MESSAGE
            # ----------------------------------------------------------------
            if isinstance(event, Message):
                try:
                    await event.answer(
                        "🚫 Akun Anda telah diblokir."
                    )
                except (
                    TelegramBadRequest,
                    TelegramForbiddenError,
                ):
                    pass
            # ----------------------------------------------------------------
            # CALLBACK
            # ----------------------------------------------------------------
            else:
                # Callback sudah di-ACK di awal.
                #
                # Jangan panggil event.answer() lagi tanpa kebutuhan karena
                # callback ID sudah selesai.
                #
                # Gunakan message.answer/edit jika ingin memberi informasi.
                #
                try:
                    if event.message:
                        await event.message.answer(
                            "🚫 Akun Anda diblokir."
                        )
                except (
                    TelegramBadRequest,
                    TelegramForbiddenError,
                ):
                    pass
            return
        # ====================================================================
        # USER NOT BANNED
        # ====================================================================
        return await handler(event, data)
