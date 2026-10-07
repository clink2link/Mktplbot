import logging

from aiogram import Router, F
from aiogram.filters import CommandStart
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.exceptions import TelegramBadRequest

from utils.force_sub import check_force_sub
from keyboards.menu import home_kb
from keyboards.join import join_kb
from database import get_pool
from utils.user_lang import get_user_language
from utils.force_sub import get_missing_channels
from aiogram.utils.keyboard import InlineKeyboardBuilder
from utils.share_unlock import record_new_member_open


router = Router()


# =========================================================
# CEK KREATOR TERVERIFIKASI
# =========================================================

def creator_verified(user) -> bool:

    if not user:
        return False

    return (
        bool(user["is_creator"])
        and user["creator_status"] == "approved"
    )


# =========================================================
# /START
# =========================================================

@router.message(CommandStart())
async def start_cmd(
    message: Message,
    state: FSMContext
):

    # /start always opens a compact language selector.
    # The original deep-link argument is kept in FSM so referral/code links are not lost.
    payload = message.text.split(maxsplit=1)[1].strip() if len(message.text.split(maxsplit=1)) > 1 else ""
    await state.clear()
    await state.update_data(start_payload=payload)

    user_id = message.from_user.id

    username = (
        f"@{message.from_user.username}"
        if message.from_user.username
        else message.from_user.full_name
    )

    loading = await message.answer(
        "⚡ Loading..."
    )

    try:

        await process_start(
            message,
            loading,
            user_id,
            username,
            state=state,
            force_language=False,
            start_arg=payload,
            from_user=message.from_user
        )

    except Exception as e:

        logging.exception(
            f"START ERROR: {e}"
        )

        try:

            await loading.edit_text(
                "❌ <b>SYSTEM ERROR</b>\n\n"
                "Terjadi kesalahan saat membuka bot.",
                parse_mode="HTML"
            )

        except Exception:
            pass


# =========================================================
# PROCESS START
# =========================================================

async def process_start(
    message: Message,
    loading: Message,
    user_id: int,
    username: str,
    state: FSMContext | None = None,
    force_language: bool = False,
    start_arg: str = "",
    from_user=None
):

    bot = message.bot
    tg_user = from_user or message.from_user

    # =====================================================
    # SAVE / UPDATE MEMBER PADA SETIAP /START
    # =====================================================
    # Member tetap dicatat walaupun force-sub belum terpenuhi.
    # Ini membuat daftar member/admin selalu terisi.
    pool = await get_pool()

    existing_user = await pool.fetchval(
        "SELECT 1 FROM users WHERE user_id=$1",
        user_id
    )
    is_new_user = existing_user is None

    await pool.execute(
        """
        INSERT INTO users(
            user_id,
            chat_id,
            username,
            full_name,
            fullname,
            language,
            last_seen
        )
        VALUES($1, $1, $2, $3, $3, NULL, NOW())
        ON CONFLICT(user_id)
        DO UPDATE SET
            chat_id = EXCLUDED.chat_id,
            username = EXCLUDED.username,
            full_name = EXCLUDED.full_name,
            fullname = EXCLUDED.fullname,
            last_seen = NOW()
        """,
        user_id,
        tg_user.username,
        tg_user.full_name
    )

    # =====================================================
    # CODE SHARE DEEP-LINK
    # Format: s_<owner_id>_<code>. Sharing itself never awards points.
    # The +1 is recorded only when the shared code is actually opened.
    # =====================================================
    pending_share_owner = None
    pending_share_code = None
    if start_arg.startswith("s_"):
        try:
            parts = start_arg.split("_", 2)
            if len(parts)==3 and parts[1].isdigit():
                pending_share_owner=int(parts[1]); pending_share_code=parts[2].strip()
                shared_file=await pool.fetchrow("SELECT code,owner_id FROM files WHERE LOWER(TRIM(code))=LOWER(TRIM($1)) LIMIT 1",pending_share_code)
                if shared_file and int(shared_file["owner_id"] or 0)==pending_share_owner:
                    start_arg=shared_file["code"]
                    if state is not None: await state.update_data(start_payload=start_arg)
                else:
                    pending_share_owner=None; pending_share_code=None
        except Exception:
            logging.exception("SHARE DEEPLINK PARSE ERROR | user=%s | payload=%s",user_id,start_arg)

    # Language is selected once; /start reuses the saved language.
    # The selector is shown only when no language has been saved (or when explicitly forced).
    current_lang = await pool.fetchval(
        "SELECT language FROM users WHERE user_id=$1",
        user_id
    )
    if force_language or not current_lang:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="🇮🇩 Indonesia", callback_data="lang:id"),
                InlineKeyboardButton(text="🇬🇧 English", callback_data="lang:en"),
                InlineKeyboardButton(text="🇨🇳 中文", callback_data="lang:zh"),
            ]
        ])
        await loading.edit_text(
            "🌐 <b>Pilih Bahasa / Choose Language / 选择语言</b>\n\n"
            "🇮🇩 Indonesia\n🇬🇧 English\n🇨🇳 中文",
            parse_mode="HTML", reply_markup=kb
        )
        return

    # =====================================================
    # FORCE SUB
    # =====================================================

    try:

        subscribed = await check_force_sub(
            bot,
            user_id
        )

    except Exception:

        logging.exception(
            "FORCE SUB CHECK ERROR"
        )

        # Fail closed: a membership check error must never unlock the dashboard.
        subscribed = False

    if not subscribed:

        try:

            bot_username = (
                await bot.me()
            ).username

        except Exception:

            bot_username = None

        lang = current_lang or "id"
        missing = await get_missing_channels(bot, user_id)
        names = "\n".join(f"• <b>{x['name']}</b>" for x in missing)
        text = (
            "❌ <b>WAJIB JOIN CHANNEL</b>\n\nSilakan join channel yang belum kamu ikuti:\n" + names + "\n\nSetelah itu tekan <b>✅ Saya Sudah Join</b>."
            if lang == "id" else
            "❌ <b>CHANNEL JOIN REQUIRED</b>\n\nPlease join the channel(s) you have not joined:\n" + names + "\n\nThen press <b>✅ I Joined</b>."
            if lang == "en" else
            "❌ <b>需要加入频道</b>\n\n请加入尚未加入的频道：\n" + names + "\n\n完成后点击 <b>✅ 我已加入</b>。"
        )
        await loading.edit_text(
            text,
            reply_markup=join_kb(bot_username, user_id, lang),
            parse_mode="HTML"
        )

        return

    # User sudah disimpan di awal process_start.

    # =====================================================
    # AMBIL PARAMETER /START
    # =====================================================

    args = ["/start"] + ([start_arg] if start_arg else [])

    # =====================================================
    # REFERRAL
    #
    # /start ref_123456
    # =====================================================

    if (
        len(args) > 1
        and args[1].startswith("ref_")
    ):

        if is_new_user:

            ref_id_text = args[1].replace(
                "ref_",
                "",
                1
            )

            if ref_id_text.isdigit():

                ref_id = int(
                    ref_id_text
                )

                # Tidak boleh referral diri sendiri
                if ref_id != user_id:

                    # Pastikan referral user ada
                    ref_exists = await pool.fetchval(
                        """
                        SELECT 1
                        FROM users
                        WHERE user_id = $1
                        """,
                        ref_id
                    )

                    if ref_exists:

                        # Cek apakah sudah punya referral
                        existing_referral = await pool.fetchval(
                            """
                            SELECT referred_by
                            FROM users
                            WHERE user_id = $1
                            """,
                            user_id
                        )

                        if not existing_referral:

                            # Simpan pemilik referral
                            await pool.execute(
                                """
                                UPDATE users
                                SET referred_by = $1
                                WHERE user_id = $2
                                """,
                                ref_id,
                                user_id
                            )

                            # Tambahkan referral + bonus secara atomic.
                            # referral_count adalah counter utama yang dipakai
                            # Account, Reward, dan Creator.
                            await pool.execute(
                                """
                                UPDATE users
                                SET
                                    referral_count = COALESCE(referral_count, 0) + 1,
                                    total_referral = COALESCE(total_referral, 0) + 1,
                                    balance = COALESCE(balance, 0) + 200,
                                    updated_at = NOW()
                                WHERE user_id = $1
                                """,
                                ref_id
                            )

                            # Notifikasi pemilik referral
                            try:

                                await bot.send_message(
                                    ref_id,

                                    "🎉 <b>Referral Berhasil!</b>\n\n"
                                    "👤 Pengguna baru bergabung.\n"
                                    "💰 Bonus: <b>Rp200</b>\n\n"
                                    "Saldo otomatis bertambah.",

                                    parse_mode="HTML"
                                )

                            except Exception:

                                logging.exception(
                                    "REFERRAL NOTIFICATION ERROR"
                                )

                            try:
                                from utils.referral import check_referral_reward
                                reward = await check_referral_reward(pool, ref_id)
                                if reward:
                                    await bot.send_message(
                                        ref_id,
                                        f"🎁 <b>Referral Reward</b>\n\n{reward}\n\nTerima kasih sudah mengajak member baru!",
                                        parse_mode="HTML"
                                    )
                            except Exception:
                                logging.exception("REFERRAL REWARD ERROR")

    # =====================================================
    # /START DENGAN CODE
    #
    # Contoh:
    # /start abc123
    # =====================================================

    elif len(args) > 1:

        code = args[1].strip()

        if not code:

            return await render_home_fast(
                bot,
                loading,
                user_id,
                username
            )

        # Hapus loading
        try:

            await loading.delete()

        except Exception:
            pass

        # Review codes are public preview codes and never enter the paid media
        # access flow. Media codes continue through the canonical payment gate.
        if code.lower().startswith("pastelereview_"):
            from handlers.review_code import send_review
            result = await send_review(message, code)
        else:
            # Import setelah diperlukan.
            # IMPORTANT: reward is granted only AFTER the code is actually
            # opened through the canonical Get File flow.
            from handlers.getfile import process_code
            result = await process_code(message, code)

        if pending_share_owner and pending_share_code:
            try:
                shared_file = await pool.fetchrow(
                    "SELECT code, owner_id, is_paid FROM files "
                    "WHERE LOWER(TRIM(code))=LOWER(TRIM($1)) LIMIT 1",
                    pending_share_code,
                )
                # A share-open reward is for a real free-code open. Paid
                # codes are rewarded only through their normal purchase flow.
                if (
                    shared_file
                    and not bool(shared_file["is_paid"])
                    and int(shared_file["owner_id"] or 0) != user_id
                ):
                    media_count = await pool.fetchval(
                        "SELECT COALESCE(media_count,0) FROM files WHERE code=$1",
                        shared_file["code"],
                    )
                    opener_points = await pool.fetchval(
                        "SELECT COALESCE(points,0) FROM users WHERE user_id=$1",
                        user_id,
                    )
                    # Get File only opens a FREE code when the opener has
                    # enough points for the entry gate. Reward only then.
                    if float(opener_points or 0) >= int(media_count or 0):
                        from utils.share_unlock import record_new_member_open
                        awarded = await record_new_member_open(
                            pool,
                            shared_file["code"],
                            pending_share_owner,
                            user_id,
                        )
                    else:
                        awarded = False
                    if awarded:
                        owner_points = await pool.fetchval(
                            "SELECT points FROM users WHERE user_id=$1",
                            pending_share_owner,
                        )
                        owner_lang = await pool.fetchval(
                            "SELECT language FROM users WHERE user_id=$1",
                            pending_share_owner,
                        ) or "id"
                        notify = {
                            "id": (
                                "🎉 <b>+1 POIN</b>\n\n"
                                f"Code <code>{shared_file['code']}</code> "
                                "berhasil dibuka oleh 1 pengguna unik.\n"
                                f"⭐ Poin kamu sekarang: <b>{owner_points}</b>"
                            ),
                            "en": (
                                "🎉 <b>+1 POINT</b>\n\n"
                                f"Code <code>{shared_file['code']}</code> "
                                "was opened by 1 unique user.\n"
                                f"⭐ Your points: <b>{owner_points}</b>"
                            ),
                            "zh": (
                                "🎉 <b>+1 积分</b>\n\n"
                                f"代码 <code>{shared_file['code']}</code> "
                                "已被 1 位独立用户打开。\n"
                                f"⭐ 当前积分：<b>{owner_points}</b>"
                            ),
                        }.get(owner_lang, None)
                        if notify:
                            try:
                                await bot.send_message(
                                    pending_share_owner,
                                    notify,
                                    parse_mode="HTML",
                                )
                            except Exception:
                                logging.exception(
                                    "SHARE OWNER NOTIFY ERROR | owner=%s",
                                    pending_share_owner,
                                )
            except Exception:
                logging.exception(
                    "SHARE POINT AWARD ERROR | owner=%s code=%s opener=%s",
                    pending_share_owner,
                    pending_share_code,
                    user_id,
                )

        return result

    # =====================================================
    # HOME
    # =====================================================

    user = await pool.fetchrow(
        """
        SELECT
            username,
            fullname,
            balance,
            points,
            total_referral,
            is_creator,
            creator_status
        FROM users
        WHERE user_id = $1
        """,
        user_id
    )

    display_username = (
        user["username"]
        if user and user["username"]
        else username
    )

    await render_home_fast(
        bot,
        loading,
        user_id,
        display_username
    )


# =========================================================
# RENDER HOME
# =========================================================

async def render_home_fast(
    bot,
    message,
    user_id: int,
    username: str
):

    pool = await get_pool()

    # =====================================================
    # BOT USERNAME
    # =====================================================

    try:

        bot_username = (
            await bot.me()
        ).username

    except Exception:

        bot_username = None

    # =====================================================
    # REFERRAL LINK
    # =====================================================

    if bot_username:

        ref_link = (
            f"https://t.me/"
            f"{bot_username}"
            f"?start=ref_{user_id}"
        )

    else:

        ref_link = "-"

    # =====================================================
    # USER DATA
    # =====================================================

    user = await pool.fetchrow(
        """
        SELECT
            balance,
            points,
            total_referral,
            is_creator,
            creator_status,
            language
        FROM users
        WHERE user_id = $1
        """,
        user_id
    )

    lang = (user["language"] or "id") if user else "id"

    if user:

        balance = (
            user["balance"] or 0
        )

        points = user["points"] or 0

        referral = (
            user["total_referral"] or 0
        )

        is_creator = creator_verified(
            user
        )

    else:

        balance = 0
        points = 0
        referral = 0
        is_creator = False

    # =====================================================
    # CLEAN MARKET DASHBOARD
    # =====================================================
    status = "TERVERIFIKASI ✅" if is_creator else "BELUM TERVERIFIKASI 🔒"
    balance_text = f"Rp {int(balance):,}".replace(",", ".")
    points_text = str(points)
    if lang == "en":
        text = (
            "<b>✨ MARKET DASHBOARD ✨</b>\n"
            "━━━━━━━━━━━━━━\n"
            f"🆔 ID : <code>{user_id}</code>\n"
            f"🎨 Status : <b>{'VERIFIED ✅' if is_creator else 'NOT VERIFIED 🔒'}</b>\n"
            f"💰 Balance : <b>{balance_text}</b>\n"
            f"⭐ Points : <b>{points_text}</b>\n"
            f"👥 Referral : <b>{referral}</b>\n"
            "━━━━━━━━━━━━━━\n"
            "🔗 Referral Link :\n"
            f"<code>{ref_link}</code>"
        )
    elif lang == "zh":
        text = (
            "<b>✨ 市场控制面板 ✨</b>\n"
            "━━━━━━━━━━━━━━\n"
            f"🆔 ID：<code>{user_id}</code>\n"
            f"🎨 状态：<b>{'已认证 ✅' if is_creator else '未认证 🔒'}</b>\n"
            f"💰 余额：<b>{balance_text}</b>\n"
            f"⭐ 积分：<b>{points_text}</b>\n"
            f"👥 推荐：<b>{referral}</b>\n"
            "━━━━━━━━━━━━━━\n"
            "🔗 推荐链接：\n"
            f"<code>{ref_link}</code>"
        )
    else:
        text = (
            "<b>✨ MARKET DASHBOARD ✨</b>\n"
            "━━━━━━━━━━━━━━\n"
            f"🆔 ID : <code>{user_id}</code>\n"
            f"🎨 Status : <b>{status}</b>\n"
            f"💰 Saldo : <b>{balance_text}</b>\n"
            f"⭐ Poin : <b>{points_text}</b>\n"
            f"👥 Referral : <b>{referral}</b>\n"
            "━━━━━━━━━━━━━━\n"
            "🔗 Link Referral :\n"
            f"<code>{ref_link}</code>"
        )

    # =====================================================
    # EDIT LOADING
    # =====================================================

    try:

        await message.edit_text(
            text,
            parse_mode="HTML",
            reply_markup=home_kb(user_id, lang),
            disable_web_page_preview=True
        )

    except TelegramBadRequest as e:

        if "message is not modified" in str(e).lower():
            return

        raise

    except Exception:

        try:

            await bot.send_message(
                user_id,
                text,
                parse_mode="HTML",
                reply_markup=home_kb(user_id, lang),
                disable_web_page_preview=True
            )

        except Exception:

            logging.exception(
                "RENDER HOME ERROR"
            )


# =========================================================
# HOME BUTTON
# =========================================================

@router.callback_query(
    F.data == "home"
)
async def back_home(
    call: CallbackQuery,
    state: FSMContext
):

    await state.clear()

    user_id = call.from_user.id

    # =====================================================
    # FORCE SUB
    # =====================================================

    try:

        subscribed = await check_force_sub(
            call.bot,
            user_id
        )

    except Exception:

        logging.exception(
            "HOME FORCE SUB ERROR"
        )

        subscribed = True

    if not subscribed:

        try:

            bot_username = (
                await call.bot.me()
            ).username

        except Exception:

            bot_username = None

        await call.message.answer(
            "❌ <b>JOIN REQUIRED</b>\n\n"
            "Silakan join semua channel terlebih dahulu.",

            parse_mode="HTML",

            reply_markup=join_kb(
                bot_username,
                user_id
            )
        )

        return await call.answer()

    # =====================================================
    # USER
    # =====================================================

    pool = await get_pool()

    user = await pool.fetchrow(
        """
        SELECT
            username,
            fullname
        FROM users
        WHERE user_id = $1
        """,
        user_id
    )

    if user:

        username = (
            user["username"]
            or user["fullname"]
            or "unknown"
        )

    else:

        username = "unknown"

    # =====================================================
    # RENDER HOME
    # =====================================================

    await render_home_fast(
        call.bot,
        call.message,
        user_id,
        username
    )

    await call.answer()


# =========================================================
# LANGUAGE SELECTION
# =========================================================
@router.callback_query(F.data.startswith("lang:"))
async def choose_language(call: CallbackQuery, state: FSMContext):
    lang = call.data.split(":", 1)[1]
    if lang not in ("id", "en", "zh"):
        return await call.answer("Invalid language.", show_alert=True)
    pool = await get_pool()
    await pool.execute("UPDATE users SET language=$1 WHERE user_id=$2", lang, call.from_user.id)
    try:
        await call.answer({"id": "Bahasa disimpan.", "en": "Language saved.", "zh": "语言已保存。"}.get(lang, "Bahasa disimpan."))
    except Exception:
        pass

    data = await state.get_data()
    start_arg = (data.get("start_payload") or "").strip()
    await state.clear()

    missing = await get_missing_channels(call.bot, call.from_user.id)
    if missing:
        lines = (
            ["❌ <b>Kamu harus bergabung ke semua channel.</b>",
             "Masuk ke channel yang belum kamu ikuti, lalu tekan <b>✅ Saya Sudah Join</b>."]
            if lang == "id" else
            ["❌ <b>You must join all required channels.</b>",
             "Join every channel you left, then press <b>✅ I Joined</b>."]
        )
        for ch in missing:
            lines.append(f"• <b>{ch['name']}</b>")
        me = await call.bot.get_me()
        await call.message.edit_text(
            "\n\n".join(lines),
            parse_mode="HTML",
            reply_markup=join_kb(me.username, call.from_user.id, lang)
        )
        return

    user = await pool.fetchrow("SELECT username, fullname FROM users WHERE user_id=$1", call.from_user.id)
    display = (user["username"] or user["fullname"] or "unknown") if user else "unknown"
    # Preserve /start deep-links (including referral links) after language selection.
    await process_start(
        call.message,
        call.message,
        call.from_user.id,
        display,
        force_language=False,
        start_arg=start_arg,
        from_user=call.from_user
    )
