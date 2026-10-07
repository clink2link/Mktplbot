from __future__ import annotations
from aiogram import BaseMiddleware
from aiogram.types import Message, CallbackQuery
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from database import get_pool
from handlers.admin.admins import is_admin
MAINTENANCE_KEY = "maintenance"
MAINTENANCE_TEXT_KEY = "maintenance_text"
DEFAULT_MAINTENANCE_TEXT = "🚧 Bot sedang maintenance."
async def safe_callback_answer(
    callback: CallbackQuery,
) -> bool:
    """
    ACK callback secepat mungkin.
    Telegram callback mempunyai batas waktu yang pendek.
    Jangan melakukan query database sebelum fungsi ini dipanggil.
    """
    try:
        await callback.answer()
        return True
    except TelegramBadRequest as exc:
        error = str(exc).lower()
        # Callback sudah expired / sudah pernah di-answer.
        if (
            "query is too old" in error
            or "query id is invalid" in error
            or "response timeout expired" in error
        ):
            return False
        # Callback sudah di-answer sebelumnya.
        if "query is too old" in error:
            return False
        return False
    except TelegramForbiddenError:
        return False
    except Exception:
        return False
async def safe_send_maintenance(
    event: Message | CallbackQuery,
    text: str,
) -> None:
    """
    Kirim pesan maintenance dengan aman.
    """
    try:
        if isinstance(event, Message):
            await event.answer(text)
            return
        if isinstance(event, CallbackQuery):
            if event.message:
                await event.message.answer(text)
    except (TelegramBadRequest, TelegramForbiddenError):
        pass
    except Exception:
        pass
class MaintenanceMiddleware(BaseMiddleware):
    """
    Global maintenance protection.
    Prinsip:
    1. CallbackQuery di-ACK terlebih dahulu.
    2. Baru melakukan query database.
    3. Admin tetap bisa menggunakan bot saat maintenance.
    4. User biasa diblokir ketika maintenance aktif.
    """
    async def __call__(self, handler, event, data):
        # Event yang bukan Message / CallbackQuery
        # langsung diteruskan.
        if not isinstance(event, (Message, CallbackQuery)):
            return await handler(event, data)
        user = event.from_user
        if not user:
            return await handler(event, data)
        # ---------------------------------------------------------
        # CALLBACK QUERY
        # ---------------------------------------------------------
        #
        # WAJIB ACK SEBELUM DATABASE.
        #
        # Ini mencegah:
        #
        # TelegramBadRequest:
        # query is too old and response timeout expired
        #
        callback_acknowledged = False
        if isinstance(event, CallbackQuery):
            callback_acknowledged = await safe_callback_answer(event)
            # Tandai agar middleware/handler berikutnya tahu
            # callback sudah pernah di-ACK.
            data["callback_acknowledged"] = callback_acknowledged
        # ---------------------------------------------------------
        # DATABASE
        # ---------------------------------------------------------
        try:
            pool = await get_pool()
            status = await pool.fetchval(
                """
                SELECT value
                FROM settings
                WHERE key = $1
                LIMIT 1
                """,
                MAINTENANCE_KEY,
            )
        except Exception:
            # Jika database bermasalah, jangan membuat seluruh bot
            # tidak bisa digunakan.
            #
            # Maintenance middleware fail-open.
            return await handler(event, data)
        # ---------------------------------------------------------
        # NORMAL MODE
        # ---------------------------------------------------------
        maintenance_active = str(status or "").strip().lower() in {
            "on",
            "true",
            "1",
            "yes",
            "enabled",
        }
        if not maintenance_active:
            return await handler(event, data)
        # ---------------------------------------------------------
        # ADMIN BYPASS
        # ---------------------------------------------------------
        try:
            admin = is_admin(user.id)
            # Support jika is_admin merupakan async function.
            if hasattr(admin, "__await__"):
                admin = await admin
        except Exception:
            admin = False
        if admin:
            return await handler(event, data)
        # ---------------------------------------------------------
        # MAINTENANCE TEXT
        # ---------------------------------------------------------
        try:
            text = await pool.fetchval(
                """
                SELECT value
                FROM settings
                WHERE key = $1
                LIMIT 1
                """,
                MAINTENANCE_TEXT_KEY,
            )
        except Exception:
            text = None
        text = str(text or "").strip()
        if not text:
            text = DEFAULT_MAINTENANCE_TEXT
        # ---------------------------------------------------------
        # BLOCK USER
        # ---------------------------------------------------------
        if isinstance(event, Message):
            # Opsional: hapus command/message user.
            try:
                await event.delete()
            except (TelegramBadRequest, TelegramForbiddenError):
                pass
            except Exception:
                pass
            await safe_send_maintenance(event, text)
            return
        if isinstance(event, CallbackQuery):
            # Callback sudah di-ACK di awal.
            #
            # Karena callback sudah dijawab, jangan memanggil
            # event.answer(text, show_alert=True) lagi.
            #
            # Kirim maintenance sebagai pesan biasa.
            await safe_send_maintenance(event, text)
            return
        return await handler(event, data)
