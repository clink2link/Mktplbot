from math import ceil

from aiogram import Router, F
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton
)

from database import fetch, fetchval

router = Router()

LIMIT = 10


def nav(page, max_page):

    row = []

    if page > 1:
        row.append(
            InlineKeyboardButton(
                text="⬅️",
                callback_data=f"market_all:{page-1}"
            )
        )

    row.append(
        InlineKeyboardButton(
            text=f"{page}/{max_page}",
            callback_data="ignore"
        )
    )

    if page < max_page:
        row.append(
            InlineKeyboardButton(
                text="➡️",
                callback_data=f"market_all:{page+1}"
            )
        )

    return row


async def show_market(call: CallbackQuery, page: int):

    total = await fetchval(
        """
        SELECT COUNT(*)
        FROM files
        WHERE is_paid=true
        """
    )

    if total == 0:

        return await call.message.edit_text(
            "🛒 <b>SEMUA FILE</b>\n\nBelum ada file.",
            parse_mode="HTML"
        )

    max_page = ceil(total / LIMIT)

    page = max(1, min(page, max_page))

    offset = (page - 1) * LIMIT

    rows = await fetch(
        """
        SELECT
            code,
            title,
            price,
            media_count,
            sold,
            views,
            rating
        FROM files
        WHERE is_paid=true
        ORDER BY created_at DESC
        LIMIT $1 OFFSET $2
        """,
        LIMIT,
        offset
    )

    text = (
        "🏷 <b>SEMUA FILE MARKET</b>\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
    )

    keyboard = []

    for i, row in enumerate(rows, start=offset + 1):

        text += (
            f"{i}. <b>{row['title']}</b>\n"
            f"💰 Rp {row['price']:,}\n"
            f"📁 {row['media_count']} Media\n"
            f"❤️ {row['sold']} | 👁 {row['views']} | ⭐ {float(row['rating']):.1f}\n\n"
        ).replace(",", ".")

        keyboard.append([
            InlineKeyboardButton(
                text=f"📦 {row['title'][:30]}",
                callback_data=f"market:{row['code']}"
            )
        ])

    keyboard.append(nav(page, max_page))

    keyboard.append([
        InlineKeyboardButton(
            text="⬅️ Marketplace",
            callback_data="marketplace"
        )
    ])

    await call.message.edit_text(
        text,
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=keyboard
        )
    )


@router.callback_query(F.data == "market_all")
async def market_all(call: CallbackQuery):

    await call.answer()

    await show_market(call, 1)


@router.callback_query(F.data.startswith("market_all:"))
async def market_all_page(call: CallbackQuery):

    await call.answer()

    page = int(call.data.split(":")[1])

    await show_market(call, page)


@router.callback_query(F.data == "ignore")
async def ignore(call: CallbackQuery):

    await call.answer()
