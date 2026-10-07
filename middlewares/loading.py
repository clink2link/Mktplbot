"""Lightweight Telegram-native loading feedback for callback buttons."""
from __future__ import annotations

from aiogram import BaseMiddleware
from aiogram.enums import ChatAction
from aiogram.types import CallbackQuery


class CallbackLoadingMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        if isinstance(event, CallbackQuery):
            try:
                await event.bot.send_chat_action(
                    chat_id=event.from_user.id,
                    action=ChatAction.TYPING,
                )
            except Exception:
                pass
            try:
                await event.answer(cache_time=0)
            except Exception:
                pass
        return await handler(event, data)
