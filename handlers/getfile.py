import asyncio
import json
import asyncio
import logging
import re
import time

from typing import Dict
from contextlib import asynccontextmanager

from aiogram.filters import StateFilter
from aiogram import Router, F
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)

from database import get_pool
from utils.user import get_user_status
from utils.user_lang import get_user_language
from utils.language import translate


router = Router()

logger = logging.getLogger(__name__)


# ============================================================
# CONFIG
# ============================================================

UPDATE_DELAY = 0.5

CODE_PREFIX = "Pastelebot_"
CODE_TOTAL_LENGTH = 24
CODE_SUFFIX_LENGTH = 14
CODE_MIN_LENGTH = CODE_TOTAL_LENGTH
CODE_MAX_LENGTH = CODE_TOTAL_LENGTH


# ============================================================
# USER LOCK
# ============================================================

_last_update: Dict[int, float] = {}
_user_locks: Dict[int, asyncio.Lock] = {}


def get_lock(user_id: int) -> asyncio.Lock:
    """
    Satu user tidak boleh menjalankan beberapa proses Get File
    secara bersamaan.
    """

    user_id = int(user_id)

    if user_id not in _user_locks:
        _user_locks[user_id] = asyncio.Lock()

    return _user_locks[user_id]


@asynccontextmanager
async def user_lock(user_id: int):
    async with get_lock(user_id):
        yield


# ============================================================
# FSM
# ============================================================

class GetFileState(StatesGroup):
    waiting_code = State()


# ============================================================
# CALLBACK SAFE ANSWER
# ============================================================

async def safe_callback_answer(
    call: CallbackQuery,
    text: str | None = None,
    show_alert: bool = False,
):
    """
    Menjawab callback Telegram dengan aman.

    CallbackQuery mempunyai batas waktu. Kalau handler terlalu
    lama dan callback sudah expired, Telegram mengembalikan:

    TelegramBadRequest:
    query is too old and response timeout expired

    Error ini tidak boleh membuat bot crash.
    """

    try:
        await call.answer(
            text=text,
            show_alert=show_alert,
        )

    except TelegramBadRequest as exc:

        error_text = str(exc).lower()

        if (
            "query is too old" in error_text
            or "response timeout expired" in error_text
            or "query id is invalid" in error_text
        ):
            logger.warning(
                "CALLBACK EXPIRED | user=%s | data=%s",
                getattr(call.from_user, "id", None),
                getattr(call, "data", None),
            )
            return False

        logger.warning(
            "CALLBACK ANSWER BAD REQUEST | %s",
            exc,
        )
        return False

    except Exception:
        logger.exception(
            "CALLBACK ANSWER ERROR"
        )
        return False

    return True


# ============================================================
# JSON
# ============================================================

def safe_json(data):
    """
    Mengubah media JSON menjadi object Python.
    """

    if isinstance(data, str):

        try:
            return json.loads(data)

        except (json.JSONDecodeError, TypeError, ValueError):
            logger.warning(
                "INVALID MEDIA JSON"
            )
            return []

        except Exception:
            logger.exception(
                "MEDIA JSON PARSE ERROR"
            )
            return []

    return data or []


# ============================================================
# CODE NORMALIZER
# ============================================================

CODE_REGEX = re.compile(
    rf"(?<![A-Za-z0-9]){re.escape(CODE_PREFIX)}[A-Za-z0-9]{{{CODE_SUFFIX_LENGTH}}}(?![A-Za-z0-9])",
    re.IGNORECASE,
)


def normalize_code(code: str) -> str:
    """
    Normalisasi code agar pencarian konsisten.
    """

    if not code:
        return ""

    return (
        str(code)
        .strip()
        .replace(" ", "")
        .replace("\n", "")
        .replace("\r", "")
    )


# ============================================================
# SAFE MESSAGE UPDATE
# ============================================================

async def safe_update(
    bot,
    chat_id: int,
    message_id: int,
    text: str,
    reply_markup=None,
):
    """
    Edit message dengan rate limit sederhana.
    """

    now = time.time()

    previous = _last_update.get(chat_id)

    if (
        previous is not None
        and now - previous < UPDATE_DELAY
    ):
        return False

    _last_update[chat_id] = now

    try:
        await bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text=text,
            parse_mode="HTML",
            reply_markup=reply_markup,
        )

        return True

    except TelegramBadRequest as exc:

        # Message tidak berubah / message sudah tidak ada
        # tidak boleh membuat bot crash.
        logger.debug(
            "GETFILE MESSAGE UPDATE IGNORED | %s",
            exc,
        )

        return False

    except Exception:
        logger.exception(
            "GETFILE UPDATE ERROR"
        )

        return False


# ============================================================
# BUTTON GET FILE
# ============================================================

@router.callback_query(
    F.data == "getfile"
)
async def getfile_start(
    call: CallbackQuery,
    state: FSMContext,
):
    """
    Membuka mode Get File.

    PENTING:
    Callback langsung di-answer sebelum database/FSM/message
    processing supaya tidak terkena timeout Telegram.
    """

    # ========================================================
    # ACK CALLBACK SECEPAT MUNGKIN
    # ========================================================

    await safe_callback_answer(call)

    user_id = int(call.from_user.id)

    async with user_lock(user_id):

        # ====================================================
        # FSM
        # ====================================================

        await state.clear()

        await state.set_state(
            GetFileState.waiting_code
        )

        # ====================================================
        # TEXT
        # ====================================================

        lang = await get_user_language(user_id)
        text = translate(lang, "send_code").replace("*", "<b>", 1).replace("*", "</b>", 1)

        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="🏠 Home",
                        callback_data="home",
                    )
                ]
            ]
        )

        # ====================================================
        # MESSAGE
        # ====================================================

        progress_id = None

        try:

            await call.message.edit_text(
                text=text,
                parse_mode="HTML",
                reply_markup=keyboard,
            )

            progress_id = call.message.message_id

        except TelegramBadRequest:

            try:

                msg = await call.message.answer(
                    text=text,
                    parse_mode="HTML",
                    reply_markup=keyboard,
                )

                progress_id = msg.message_id

            except Exception:
                logger.exception(
                    "GETFILE START SEND MESSAGE ERROR"
                )

        except Exception:
            logger.exception(
                "GETFILE START EDIT ERROR"
            )

        # ====================================================
        # SAVE FSM DATA
        # ====================================================

        if progress_id:

            await state.update_data(
                getfile_mode=True,
                progress_msg_id=progress_id,
            )


# ============================================================
# OPEN FILE
# ============================================================

async def open_file_by_code(
    message: Message,
    code: str,
    state: FSMContext,
    paid_override: bool = False,
    user_id: int | None = None,
):
    """
    Membuka file berdasarkan code.
    """

    code = normalize_code(code)
    opener_id = int(user_id if user_id is not None else message.from_user.id)

    if not code:
        await state.clear()

        lang = await get_user_language(opener_id)
        return await message.answer({"id":"❌ CODE tidak valid.","en":"❌ Invalid code.","zh":"❌ 代码无效。"}.get(lang,"❌ CODE tidak valid."))

    pool = await get_pool()

    # ========================================================
    # DATABASE FILE
    # ========================================================

    file = await pool.fetchrow(
        """
        SELECT
            code,
            title,
            media,
            owner_id,
            expires_at,
            is_paid,
            price,
            views
        FROM files
        WHERE LOWER(TRIM(code)) = LOWER(TRIM($1))
        LIMIT 1
        """,
        code,
    )

    # ========================================================
    # FILE TIDAK DITEMUKAN
    # ========================================================

    if not file:

        await state.clear()

        lang = await get_user_language(opener_id)
        return await message.answer(translate(lang, "code_not_found").replace("*", "", 2))

    # ========================================================
    # MEDIA
    # ========================================================

    media = safe_json(
        file["media"]
    )

    if not isinstance(media, list) or not media:

        await state.clear()

        lang = await get_user_language(opener_id)
        return await message.answer(translate(lang, "file_empty").replace("*", "", 2))

    # ========================================================
    # EXPIRED
    # ========================================================

    expires_at = file["expires_at"]

    if expires_at:

        try:

            if expires_at.timestamp() < time.time():

                await state.clear()

                lang = await get_user_language(opener_id)
                return await message.answer({"id":"❌ File sudah kadaluarsa.","en":"❌ File has expired.","zh":"❌ 文件已过期。"}.get(lang,"❌ File sudah kadaluarsa."))

        except Exception:
            logger.warning(
                "INVALID EXPIRES_AT | code=%s",
                code,
                exc_info=True,
            )

    # ========================================================
    # OWNER
    # ========================================================

    owner_id = file["owner_id"]

    owner = False

    try:

        owner = (
            int(opener_id)
            == int(owner_id)
        )

    except (ValueError, TypeError):

        owner = False

    # ========================================================
    # PAYMENT
    # ========================================================

    is_paid = bool(
        file["is_paid"]
    )

    price = file["price"] or 0

    try:
        price = int(price)

    except (ValueError, TypeError):
        price = 0

    # ========================================================
    # USER STATUS
    # ========================================================

    try:

        user_level = await get_user_status(
            pool,
            opener_id,
        )

    except Exception:

        logger.exception(
            "GET USER STATUS ERROR | user=%s",
            opener_id,
        )

        user_level = None

    # ========================================================
    # CREATOR ACCESS
    # ========================================================

    creator_access = False

    try:

        creator_access = await pool.fetchval(
            """
            SELECT
                COALESCE(is_creator, FALSE)
                AND COALESCE(
                    creator_status,
                    'none'
                ) = 'approved'
            FROM users
            WHERE chat_id = $1
            LIMIT 1
            """,
            opener_id,
        ) or False

    except Exception:

        logger.exception(
            "CREATOR ACCESS CHECK ERROR | user=%s",
            opener_id,
        )

        creator_access = False

    # ========================================================
    # PURCHASE
    # ========================================================

    access = False

    try:

        access = await pool.fetchval(
            """
            SELECT EXISTS(
                SELECT 1
                FROM file_purchases
                WHERE user_id = $1
                  AND (
                      LOWER(TRIM(COALESCE(file_code, ''))) = LOWER(TRIM($2))
                      OR LOWER(TRIM(COALESCE(code, ''))) = LOWER(TRIM($2))
                  )
                  AND status = 'paid'
            )
            """,
            opener_id,
            code,
        )

    except Exception:

        logger.exception(
            "PURCHASE ACCESS CHECK ERROR | "
            "user=%s | code=%s",
            opener_id,
            code,
        )

        access = False

    # ========================================================
    # FINAL ACCESS
    # ========================================================

    # Single access policy: paid files are never bypassed by VIP/VVIP/Creator.
    has_access = owner or bool(access)

    # ========================================================
    # VIEW COUNT
    # ========================================================

    if not is_paid or has_access:

        try:

            viewed = await pool.fetchrow(
                """
                INSERT INTO file_views
                (
                    user_id,
                    file_code
                )
                VALUES
                (
                    $1,
                    $2
                )
                ON CONFLICT
                (
                    user_id,
                    file_code
                )
                DO NOTHING
                RETURNING user_id
                """,
                opener_id,
                file["code"],
            )

            if viewed:

                await pool.execute(
                    """
                    UPDATE files
                    SET
                        views =
                            COALESCE(views, 0) + 1,
                        view_count =
                            COALESCE(view_count, 0) + 1
                    WHERE code = $1
                    """,
                    file["code"],
                )

        except Exception:

            # Statistik gagal tidak boleh membuat
            # user kehilangan akses ke file.
            logger.exception(
                "FILE VIEW UPDATE ERROR | code=%s",
                file["code"],
            )

    # ========================================================
    # CLEAR FSM
    # ========================================================

    await state.clear()

    # ========================================================
    # CANONICAL ACCESS / POINT GATE
    # ========================================================
    lang = await get_user_language(opener_id)
    from utils.media_access import can_open_media, reward_owner_for_open
    access_file = dict(file)
    access_file["media_count"] = len(media)
    allowed, reason = await can_open_media(opener_id, access_file, paid_override=paid_override)

    if not allowed:
        if reason == "payment_required":
            from handlers.pay import paid_unlock_keyboard
            txt = {
                "id": f"🔒 <b>FILE BERBAYAR</b>\n\n🔑 CODE: <code>{file['code']}</code>\n💰 Harga: <b>Rp {int(price):,}</b>\n📦 Media: <b>{len(media)}</b>\n\nPilih cara membuka file:",
                "en": f"🔒 <b>PAID FILE</b>\n\n🔑 CODE: <code>{file['code']}</code>\n💰 Price: <b>Rp {int(price):,}</b>\n📦 Media: <b>{len(media)}</b>\n\nChoose how to unlock this file:",
                "zh": f"🔒 <b>付费文件</b>\n\n🔑 代码：<code>{file['code']}</code>\n💰 价格：<b>Rp {int(price):,}</b>\n📦 媒体：<b>{len(media)}</b>\n\n请选择解锁方式：",
            }
            return await message.answer(txt.get(lang, txt["id"]), parse_mode="HTML", reply_markup=paid_unlock_keyboard(file["code"], lang))
        from utils.points import get_points, fmt_points
        points = await get_points(pool, opener_id)
        required = len(media)
        txt = {
            "id": f"⭐ <b>POIN TIDAK CUKUP</b>\n\nCode ini berisi <b>{required} media</b> dan membutuhkan <b>{required} poin</b>.\nPoin kamu: <b>{fmt_points(points)}</b>.",
            "en": f"⭐ <b>NOT ENOUGH POINTS</b>\n\nThis code contains <b>{required} media</b> and requires <b>{required} points</b>.\nYour points: <b>{fmt_points(points)}</b>.",
            "zh": f"⭐ <b>积分不足</b>\n\n此代码包含 <b>{required} 个媒体</b>，需要 <b>{required} 积分</b>。\n你的积分：<b>{fmt_points(points)}</b>。",
        }
        kb=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text={"id":"⭐ Cek Poin","en":"⭐ Points","zh":"⭐ 积分"}.get(lang,"⭐ Cek Poin"),callback_data="points")]])
        return await message.answer(txt.get(lang,txt["id"]),parse_mode="HTML",reply_markup=kb)

    # A successful non-owner open is recorded once and rewards the owner.
    if reason != "owner":
        await reward_owner_for_open(opener_id, access_file)

    # ========================================================
    # OPEN FILE
    # ========================================================

    try:

        from handlers.open_menu import open_keyboard

    except Exception:

        logger.exception(
            "OPEN MENU IMPORT ERROR"
        )

        return await message.answer(
            "❌ Menu file sedang mengalami masalah."
        )

    title = str(
        file["title"] or "Tanpa Judul"
    )

    lang = await get_user_language(opener_id)
    found_text = {
        "id": f"✅ <b>FILE DITEMUKAN</b>\n\n📝 Judul: <b>{title}</b>\n📦 Total Media: <b>{len(media)}</b>\n\nPilih metode pengiriman:",
        "en": f"✅ <b>FILE FOUND</b>\n\n📝 Title: <b>{title}</b>\n📦 Total Media: <b>{len(media)}</b>\n\nChoose a delivery method:",
        "zh": f"✅ <b>找到文件</b>\n\n📝 标题：<b>{title}</b>\n📦 媒体总数：<b>{len(media)}</b>\n\n请选择发送方式：",
    }
    return await message.answer(found_text.get(lang, found_text["id"]), parse_mode="HTML", reply_markup=open_keyboard(code, lang))


# ============================================================
@router.callback_query(F.data.startswith("paidpoint:"))
async def paid_point_unlock(call: CallbackQuery):
    code=normalize_code(call.data.split(":",1)[1])
    pool=await get_pool()
    file=await pool.fetchrow("SELECT * FROM files WHERE LOWER(TRIM(code))=LOWER(TRIM($1)) LIMIT 1",code)
    if not file: return await call.answer("❌ Code tidak ditemukan.", show_alert=True)
    if not bool(file.get("is_paid")): return await call.answer("❌ Code ini gratis.", show_alert=True)
    user_id=int(call.from_user.id)
    if int(file.get("owner_id") or 0)==user_id: return await call.answer("✅ Kamu adalah pemilik file.", show_alert=False)
    paid=bool(await pool.fetchval("SELECT EXISTS(SELECT 1 FROM file_purchases WHERE user_id=$1 AND (LOWER(TRIM(COALESCE(file_code,'')))=LOWER(TRIM($2)) OR LOWER(TRIM(COALESCE(code,'')))=LOWER(TRIM($2))) AND status='paid')",user_id,file["code"]))
    if paid: return await call.answer("✅ File sudah dibuka.", show_alert=False)
    from utils.points import unlock_paid_code, fmt_points
    price=int(file.get("price") or 0); ok,balance=await unlock_paid_code(pool,user_id,file["code"],price)
    lang=await get_user_language(user_id)
    if not ok:
        text={"id":f"⭐ <b>POIN TIDAK CUKUP</b>\n\nDibutuhkan: <b>{fmt_points(price)} poin</b>\nPoin kamu: <b>{fmt_points(balance)}</b>","en":f"⭐ <b>NOT ENOUGH POINTS</b>\n\nRequired: <b>{fmt_points(price)} points</b>\nYour points: <b>{fmt_points(balance)}</b>","zh":f"⭐ <b>积分不足</b>\n\n需要：<b>{fmt_points(price)} 积分</b>\n你的积分：<b>{fmt_points(balance)}</b>"}
        kb=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text={"id":"⭐ Buy Poin","en":"⭐ Buy Points","zh":"⭐ 购买积分"}.get(lang,"⭐ Buy Poin"),callback_data="points")],[InlineKeyboardButton(text={"id":"💳 Bayar","en":"💳 Pay","zh":"💳 支付"}.get(lang,"💳 Bayar"),callback_data=f"pay:{file['code']}")]])
        return await call.message.answer(text.get(lang,text["id"]),parse_mode="HTML",reply_markup=kb)
    await call.answer("✅ Unlock berhasil!", show_alert=False)
    from handlers.open_menu import open_keyboard
    title=str(file.get("title") or "Tanpa Judul")
    try:
        media=file.get("media"); media=json.loads(media) if isinstance(media,str) else media; count=len(media or [])
    except Exception: count=int(file.get("media_count") or 0)
    txt={"id":f"✅ <b>FILE DITEMUKAN</b>\n\n📝 Judul: <b>{title}</b>\n📦 Total Media: <b>{count}</b>\n\nPilih metode pengiriman:","en":f"✅ <b>FILE FOUND</b>\n\n📝 Title: <b>{title}</b>\n📦 Total Media: <b>{count}</b>\n\nChoose a delivery method:","zh":f"✅ <b>找到文件</b>\n\n📝 标题：<b>{title}</b>\n📦 媒体总数：<b>{count}</b>\n\n请选择发送方式："}
    return await call.message.answer(txt.get(lang,txt["id"]),parse_mode="HTML",reply_markup=open_keyboard(file["code"],lang))

# PROCESS CODE
# ============================================================

async def process_code(
    message: Message,
    code: str,
    paid_override: bool = False,
    user_id: int | None = None,
):
    """
    Compatibility helper untuk pemanggilan dari handler lain.
    """

    code = normalize_code(code)
    if user_id is None:
        user_id = int(message.from_user.id)

    class DummyState:

        async def clear(self):
            return None

        async def get_data(self):
            return {}

        async def update_data(self, **kwargs):
            return None

    return await open_file_by_code(
        message=message,
        code=code,
        state=DummyState(),
        paid_override=paid_override,
        user_id=user_id,
    )


# ============================================================
# GLOBAL CODE ENTRY
# ============================================================
# A CODE can arrive from anywhere in the chat, not only after pressing
# Get File. It always enters the same process_code() pipeline.
@router.message(
    F.text.regexp(CODE_REGEX)
    | F.text.regexp(
        re.compile(
            r"(?<![A-Za-z0-9])Jsshowbot_[A-Za-z0-9]{14}(?![A-Za-z0-9])",
            re.IGNORECASE,
        )
    )
)
async def receive_code_global(
    message: Message,
    state: FSMContext,
):
    """
    Direct CODE entry.

    A CODE typed/sent directly in chat must behave exactly like
    entering the CODE through the Get File menu.  It must NOT enter
    the Open Page/Open All loading flow and must never show
    "Mencari Media Code..." merely because the CODE was sent directly.

    We accept the configured Pastelebot_ format and the legacy
    Jsshowbot_ format so existing shared codes are handled too.
    """
    text = (message.text or "").strip()
    if not text:
        return

    patterns = [
        CODE_REGEX,
        re.compile(
            r"(?<![A-Za-z0-9])Jsshowbot_[A-Za-z0-9]{14}(?![A-Za-z0-9])",
            re.IGNORECASE,
        ),
    ]

    match = None
    for pattern in patterns:
        match = pattern.search(text)
        if match:
            break

    if not match:
        return

    code = normalize_code(match.group())

    user_id = int(message.from_user.id)
    async with user_lock(user_id):
        try:
            await message.delete()
        except Exception:
            pass

        try:
            await state.clear()
        except Exception:
            pass

        # EXACTLY the same canonical Get File pipeline used by the
        # Get File -> enter CODE flow.
        return await process_code(message, code)


# ============================================================
# RECEIVE CODE
# ============================================================

@router.callback_query(F.data.startswith("grantopen:"))
async def grant_open_code(call: CallbackQuery):
    code = call.data.split(":", 1)[1].strip()
    await safe_callback_answer(call, "⏳")
    await process_code(call.message, code)


@router.message(
    StateFilter(
        GetFileState.waiting_code
    ),
    F.text,
)
async def receive_code(
    message: Message,
    state: FSMContext,
):
    """
    Menerima code dari user.
    """

    user_id = int(
        message.from_user.id
    )

    async with user_lock(user_id):

        text = (
            message.text or ""
        ).strip()

        match = CODE_REGEX.search(text)
        if not match:
            match = re.search(r"(?<![A-Za-z0-9])Jsshowbot_[A-Za-z0-9]{14}(?![A-Za-z0-9])", text, re.IGNORECASE)

        # ====================================================
        # INVALID CODE
        # ====================================================

        if not match:

            try:
                await message.delete()

            except Exception:
                pass

            lang = await get_user_language(user_id)
            invalid = {
                "id": "❌ Itu bukan CODE bot saya.\n\nSilakan kirim CODE yang benar atau tekan Batal.",
                "en": "❌ That is not a valid bot code.\n\nSend a valid code or press Cancel.",
                "zh": "❌ 这不是有效的机器人代码。\n\n请发送正确的代码或点击取消。",
            }
            return await message.answer(invalid.get(lang, invalid["id"]))

        # ====================================================
        # NORMALIZE
        # ====================================================

        code = normalize_code(
            match.group()
        )

        # ====================================================
        # DELETE USER MESSAGE
        # ====================================================

        try:

            await message.delete()

        except Exception:
            pass

        # ====================================================
        # DELETE PROGRESS MESSAGE
        # ====================================================

        try:

            data = await state.get_data()

            progress_id = data.get(
                "progress_msg_id"
            )

            if progress_id:

                try:

                    await message.bot.delete_message(
                        chat_id=message.chat.id,
                        message_id=int(
                            progress_id
                        ),
                    )

                except Exception:
                    pass

        except Exception:

            logger.exception(
                "GETFILE PROGRESS DELETE ERROR"
            )

        # ====================================================
        # OPEN
        # ====================================================

        # SINGLE CODE ENTRY POINT:
        # The FSM only collects the code. The actual lookup/access
        # logic always goes through process_code(), exactly like
        # Marketplace, Search, deep-links and successful payments.
        await state.clear()
        return await process_code(message, code)


# ============================================================
# CANCEL GET FILE
# ============================================================

@router.callback_query(
    F.data == "cancel_getfile"
)
async def cancel_getfile(
    call: CallbackQuery,
    state: FSMContext,
):
    """
    Membatalkan mode Get File.
    """

    # ACK SECEPAT MUNGKIN
    await safe_callback_answer(call)

    user_id = int(
        call.from_user.id
    )

    async with user_lock(user_id):

        await state.clear()

        lang = await get_user_language(user_id)
        text = {"id":"❌ <b>Get File dibatalkan.</b>","en":"❌ <b>Get File cancelled.</b>","zh":"❌ <b>获取文件已取消。</b>"}.get(lang,"❌ <b>Get File dibatalkan.</b>")

        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="🏠 Home",
                        callback_data="home",
                    )
                ]
            ]
        )

        try:

            await call.message.edit_text(
                text,
                parse_mode="HTML",
                reply_markup=keyboard,
            )

        except TelegramBadRequest:

            try:

                await call.message.answer(
                    text,
                    parse_mode="HTML",
                    reply_markup=keyboard,
                )

            except Exception:
                logger.exception(
                    "CANCEL GETFILE SEND ERROR"
                )

        except Exception:

            logger.exception(
                "CANCEL GETFILE EDIT ERROR"
            )


async def canonical_open_menu(message, code: str, lang: str = "id"):
    """Single post-access destination for every successful Code lookup."""
    await message.answer(
        "📂 <b>OPEN MENU</b>\n\nPilih cara membuka media:"
        if lang == "id"
        else (
            "📂 <b>OPEN MENU</b>\n\nChoose how to open the media."
            if lang == "en"
            else "📂 <b>打开菜单</b>\n\n请选择打开媒体的方式。"
        ),
        parse_mode="HTML",
        reply_markup=open_keyboard(code, lang),
    )
