from aiogram import Router, F

router = Router()


@router.message(F.photo | F.document)
async def get_file_id(message):

    if message.photo:
        file_id = message.photo[-1].file_id

    elif message.document:
        file_id = message.document.file_id

    else:
        return

    print("FILE ID:", file_id)

    await message.answer(
        f"FILE ID:\n<code>{file_id}</code>",
        parse_mode="HTML"
    )
