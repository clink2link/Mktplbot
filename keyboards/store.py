from aiogram.types import (
    InlineKeyboardMarkup,
    InlineKeyboardButton
)


def store_keyboard():

    return InlineKeyboardMarkup(
        inline_keyboard=[

            [
                InlineKeyboardButton(
                    text="🔥 Top Code",
                    callback_data="store_top"
                ),

                InlineKeyboardButton(
                    text="📈 Terlaris",
                    callback_data="store_best"
                )
            ],


            [
                InlineKeyboardButton(
                    text="🆕 Terbaru",
                    callback_data="store_new"
                ),

                InlineKeyboardButton(
                    text="💎 Premium",
                    callback_data="store_premium"
                )
            ],


            [
                InlineKeyboardButton(
                    text="📂 Kategori",
                    callback_data="store_category"
                ),

                InlineKeyboardButton(
                    text="🔎 Cari",
                    callback_data="store_search"
                )
            ],


            [
                InlineKeyboardButton(
                    text="🆓 Gratis",
                    callback_data="store_free"
                ),

                InlineKeyboardButton(
                    text="❤️ Favorit",
                    callback_data="store_favorite"
                )
            ],


            [
                InlineKeyboardButton(
                    text="🎲 Random",
                    callback_data="store_random"
                )
            ],


            [
                InlineKeyboardButton(
                    text="🔙 Kembali",
                    callback_data="home"
                )
            ]

        ]
    )
