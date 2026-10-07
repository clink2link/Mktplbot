"""Telegram edit helpers.

Telegram treats an edit as invalid when the requested content/markup is
identical to the current message. This is harmless, especially with double
clicks and concurrent workers, so these wrappers suppress only that specific
BadRequest while preserving every other Telegram error.
"""
import logging
from functools import wraps

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import Message

logger = logging.getLogger(__name__)

_ALREADY_PATCHED = "_mektpl_message_not_modified_safe"


def _is_not_modified(exc: BaseException) -> bool:
    return (
        isinstance(exc, TelegramBadRequest)
        and "message is not modified" in str(exc).lower()
    )


def _wrap(method):
    if getattr(method, _ALREADY_PATCHED, False):
        return method

    @wraps(method)
    async def wrapped(*args, **kwargs):
        try:
            return await method(*args, **kwargs)
        except TelegramBadRequest as exc:
            if _is_not_modified(exc):
                logger.debug("Telegram ignored duplicate edit: %s", exc)
                return None
            raise

    setattr(wrapped, _ALREADY_PATCHED, True)
    return wrapped


def install_telegram_edit_guards() -> None:
    """Guard every common aiogram message-edit operation globally.

    This covers direct calls such as message.edit_text(), progress.edit_text(),
    callback.message.edit_reply_markup(), and bot.edit_message_text().
    """
    message_methods = (
        "edit_text",
        "edit_caption",
        "edit_reply_markup",
        "edit_media",
    )
    bot_methods = (
        "edit_message_text",
        "edit_message_caption",
        "edit_message_reply_markup",
        "edit_message_media",
    )

    for name in message_methods:
        method = getattr(Message, name, None)
        if method is not None:
            setattr(Message, name, _wrap(method))

    for name in bot_methods:
        method = getattr(Bot, name, None)
        if method is not None:
            setattr(Bot, name, _wrap(method))


__all__ = ["install_telegram_edit_guards"]
