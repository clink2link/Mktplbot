from aiogram.exceptions import TelegramBadRequest
import traceback

async def safe_edit(
    message,
    text,
    reply_markup=None,
    parse_mode="HTML"
):
    try:
        await message.edit_text(
            text,
            reply_markup=reply_markup,
            parse_mode=parse_mode
        )

    except TelegramBadRequest as e:

        error = str(e)

        if "message is not modified" in error:
            return

        print("EDIT ERROR:", error)

        try:
            await message.answer(
                text,
                reply_markup=reply_markup,
                parse_mode=parse_mode
            )

        except Exception as e:
            print("ANSWER ERROR:", repr(e))
            traceback.print_exc()
