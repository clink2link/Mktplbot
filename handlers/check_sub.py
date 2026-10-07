import logging

from aiogram import Router, F
from aiogram.types import CallbackQuery
from aiogram.exceptions import TelegramBadRequest

from utils.force_sub import check_force_sub, get_missing_channels
from keyboards.join import join_kb
from handlers.start import render_home_fast
from database import get_pool
from utils.user_lang import get_user_language

router = Router()


# =========================================================
# CHECK SUB
# =========================================================

@router.callback_query(F.data == "check_sub")
async def check_sub_callback(call: CallbackQuery):

    user_id = call.from_user.id

    username = (
        f"@{call.from_user.username}"
        if call.from_user.username
        else call.from_user.full_name
    )
    lang = await get_user_language(user_id)

    logging.info(
        f"CHECK SUB CLICKED: {user_id}"
    )

    # =====================================================
    # CEK FORCE SUB
    # =====================================================

    try:

        ok = await check_force_sub(
            call.bot,
            user_id
        )

        logging.info(
            f"FORCE SUB RESULT: {ok}"
        )

    except Exception:

        logging.exception(
            "FORCE SUB CHECK ERROR"
        )

        return await call.answer(
            "❌ Gagal mengecek membership.",
            show_alert=True
        )

    # =====================================================
    # BELUM JOIN
    # =====================================================

    if not ok:

        missing = await get_missing_channels(call.bot, user_id)
        names = "\n".join(f"• <b>{x['name']}</b>" for x in missing)
        text = (
            "❌ <b>WAJIB JOIN CHANNEL</b>\n\n"
            f"Channel yang belum kamu ikuti:\n{names}\n\n"
            "Silakan join lalu tekan <b>✅ Saya Sudah Join</b>."
            if lang == "id" else
            "❌ <b>CHANNEL JOIN REQUIRED</b>\n\n"
            f"Channels you have not joined:\n{names}\n\n"
            "Join them and press <b>✅ I Joined</b>."
            if lang == "en" else
            "❌ <b>需要加入频道</b>\n\n"
            f"尚未加入的频道：\n{names}\n\n"
            "请加入后点击 <b>✅ 我已加入</b>。"
        )
        await call.answer(
            "❌ Masih ada channel yang belum diikuti." if lang == "id" else "❌ Some required channels are still missing." if lang == "en" else "❌ 仍有必需频道未加入。",
            show_alert=True
        )
        try:
            me = await call.bot.get_me()
            await call.message.edit_text(
                text,
                parse_mode="HTML",
                reply_markup=join_kb(me.username, user_id, lang)
            )
        except TelegramBadRequest as e:
            if "message is not modified" not in str(e).lower():
                logging.exception("JOIN MESSAGE EDIT ERROR")
        return

    # =====================================================
    # SUDAH JOIN
    # =====================================================

    pool = await get_pool()

    # =====================================================
    # CREATE / UPDATE USER
    # =====================================================

    try:

        await pool.execute(
            """
            INSERT INTO users (
                user_id,
                username,
                fullname,
                chat_id,
                last_seen
            )
            VALUES (
                $1,
                $2,
                $3,
                $1,
                NOW()
            )

            ON CONFLICT (user_id)
            DO UPDATE SET
                username = EXCLUDED.username,
                fullname = EXCLUDED.fullname,
                chat_id = EXCLUDED.chat_id,
                last_seen = NOW()
            """,

            user_id,
            username,
            call.from_user.full_name
        )

    except Exception:

        logging.exception(
            "CREATE / UPDATE USER ERROR"
        )

        return await call.answer(
            "❌ Gagal memperbarui data user.",
            show_alert=True
        )

    # =====================================================
    # VERIFIKASI BERHASIL
    # =====================================================

    await call.answer(
        "✅ Verifikasi berhasil!"
    )

    # =====================================================
    # LANGSUNG TAMPILKAN HOME
    #
    # Pesan JOIN akan diedit menjadi HOME.
    # Jadi tombol JOIN / CHECK otomatis hilang.
    # =====================================================

    try:

        await render_home_fast(
            call.bot,
            call.message,
            user_id,
            username
        )

    except TelegramBadRequest as e:

        if "message is not modified" not in str(e).lower():

            logging.exception(
                "RENDER HOME AFTER JOIN ERROR"
            )

            try:

                await call.message.answer(
                    "🏠 <b>HOME</b>",
                    parse_mode="HTML"
                )

            except Exception:
                pass

    except Exception:

        logging.exception(
            "RENDER HOME AFTER JOIN ERROR"
        )

        try:

            await call.message.answer(
                "🏠 <b>HOME</b>",
                parse_mode="HTML"
            )

        except Exception:
            pass
