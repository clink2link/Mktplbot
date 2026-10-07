from math import ceil

from aiogram import Router, F
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton
)

from database import get_pool


router = Router()


LIMIT = 10


def mask_code(code: str):

    if len(code) <= 8:
        return "*" * len(code)

    return code[:4] + "****" + code[-4:]


# =====================================
# MY CODE
# =====================================

@router.callback_query(F.data.startswith("my_code"))
async def my_code(call: CallbackQuery):

    page = 1

    if ":" in call.data:

        try:
            page = int(
                call.data.split(":")[1]
            )

        except:
            page = 1


    pool = await get_pool()


    total = await pool.fetchval(
        """
        SELECT COUNT(*)
        FROM files
        WHERE owner_id=$1
        """,
        call.from_user.id
    )


    if not total:

        return await call.message.edit_text(
            "📦 <b>MY CODE</b>\n\n"
            "❌ Kamu belum memiliki file.",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="⬅️ Kembali",
                            callback_data="account"
                        )
                    ]
                ]
            )
        )


    max_page = ceil(
        total / LIMIT
    )


    page = max(
        1,
        min(page, max_page)
    )


    offset = (
        page - 1
    ) * LIMIT



    files = await pool.fetch(
        """
        SELECT

            f.code,
            f.title,
            f.price,
            f.is_paid,
            f.media_count,

            (
                SELECT COUNT(*)
                FROM file_purchases p
                WHERE p.file_code=f.code
                AND p.status='paid'
            ) AS sold,


            (
                SELECT COALESCE(
                    SUM(p.paid_price),
                    0
                )
                FROM file_purchases p
                WHERE p.file_code=f.code
                AND p.status='paid'
            ) AS income


        FROM files f


        WHERE f.owner_id=$1


        ORDER BY f.id DESC


        LIMIT $2 OFFSET $3

        """,
        call.from_user.id,
        LIMIT,
        offset
    )



    text = (
        "📦 <b>MY CODE</b>\n"
        "━━━━━━━━━━━━━━━━━━\n\n"

        f"📄 Total File : <b>{total}</b>\n"
        f"📑 Halaman : <b>{page}/{max_page}</b>\n\n"
    )



    keyboard = []



    for i, f in enumerate(
        files,
        start=offset+1
    ):


        harga = (
            "🆓 FREE"
            if not f["is_paid"]
            else
            f"💰 Rp {f['price']:,}".replace(",",".")
        )


        text += (
            f"<b>{i}. {f['title']}</b>\n"
            f"🔑 <code>{mask_code(f['code'])}</code>\n"
            f"{harga}\n"
            f"📦 Media : {f['media_count']}\n"
            f"🛒 Terjual : {f['sold']}x\n"
            f"💵 Pendapatan : Rp {f['income']:,}\n"
            "━━━━━━━━━━━━━━\n\n"
        )


        keyboard.append(
            [
                InlineKeyboardButton(
                    text=f"📦 {f['title'][:20]}",
                    callback_data=f"myfile:{f['code']}"
                )
            ]
        )



    nav=[]


    if page > 1:

        nav.append(
            InlineKeyboardButton(
                text="⬅️",
                callback_data=f"my_code:{page-1}"
            )
        )


    nav.append(
        InlineKeyboardButton(
            text=f"{page}/{max_page}",
            callback_data="noop"
        )
    )


    if page < max_page:

        nav.append(
            InlineKeyboardButton(
                text="➡️",
                callback_data=f"my_code:{page+1}"
            )
        )


    keyboard.append(nav)


    keyboard.append(
        [
            InlineKeyboardButton(
                text="🏠 Home",
                callback_data="home"
            )
        ]
    )



    await call.message.edit_text(
        text,
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=keyboard
        )
    )


    await call.answer()



@router.callback_query(F.data=="noop")
async def noop(call: CallbackQuery):

    await call.answer()
