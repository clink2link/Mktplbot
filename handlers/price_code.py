from aiogram import Router, F
from aiogram.types import CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder

from database import get_pool


router = Router()


@router.callback_query(F.data == "price_code")
async def price_menu(call: CallbackQuery):

    kb = InlineKeyboardBuilder()

    prices = [
        ("🆓 Gratis", "0"),
        ("💵 Rp2.000", "2000"),
        ("💵 Rp5.000", "5000"),
        ("💵 Rp7.000", "7000"),
        ("💵 Rp10.000", "10000"),
        ("💰 Rp13.000", "13000"),
        ("💰 Rp15.000", "15000"),
        ("🔥 Rp17.000", "17000"),
    ]

    for text, price in prices:
        kb.button(
            text=text,
            callback_data=f"price:{price}"
        )


    kb.button(
        text="⬅️ Kembali",
        callback_data="marketplace"
    )

    kb.adjust(1)


    await call.message.edit_text(
        "<b>💰 HARGA CODE</b>\n\n"
        "Pilih harga code yang ingin dilihat:",
        parse_mode="HTML",
        reply_markup=kb.as_markup()
    )

    await call.answer()



@router.callback_query(F.data.startswith("price:"))
async def price_result(call: CallbackQuery):

    price = int(
        call.data.split(":")[1]
    )

    pool = await get_pool()


    rows = await pool.fetch(
        """
        SELECT
            code,
            title,
            price,
            view_count
        FROM files
        WHERE price=$1
        ORDER BY
            view_count DESC,
            created_at DESC
        LIMIT 10
        """,
        price
    )


    if not rows:

        return await call.answer(
            "❌ Belum ada code dengan harga tersebut.",
            show_alert=True
        )


    text = (
        "💰 <b>LIST CODE</b>\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
    )


    for i,row in enumerate(rows,1):

        harga = (
            "Gratis"
            if row["price"] == 0
            else f"Rp{row['price']:,}"
        )

        text += (
            f"{i}. 📌 <b>{row['title']}</b>\n"
            f"🔑 <code>{row['code']}</code>\n"
            f"💰 Harga : {harga}\n"
            f"👁 Dibuka : {row['view_count']}x\n\n"
        )


    kb = InlineKeyboardBuilder()

    kb.button(
        text="⬅️ Kembali Harga",
        callback_data="price_code"
    )

    kb.button(
        text="🏠 Home",
        callback_data="home"
    )

    kb.adjust(1)


    await call.message.edit_text(
        text,
        parse_mode="HTML",
        reply_markup=kb.as_markup()
    )

    await call.answer()
