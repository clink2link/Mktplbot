import asyncio
import json
from aiogram import Router, F
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton

from database import get_pool
from utils.media_sender import deliver_one

router = Router()

BATCH_SIZE = 10
SEND_INTERVAL = 2.0

_sessions = {}


def _caption(code, index, total, media):
    watermark = media.get("caption") or media.get("watermark")
    if watermark:
        return str(watermark)
    return (
        f"🔑 {code}-M{index:03d}\n"
        f"🤖 @Telecodrobot\n"
        f"📦 Media {index}/{total}"
    )


def _control_kb(code, session_id, has_more):
    if has_more:
        return InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="▶️ Lanjut Kirim",
                        callback_data=f"allnext:{session_id}",
                    ),
                    InlineKeyboardButton(
                        text="⛔ Batal Kirim",
                        callback_data=f"allstop:{session_id}",
                    ),
                ]
            ]
        )

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="👍 Like", callback_data=f"like:{code}"),
                InlineKeyboardButton(text="👎 No Like", callback_data=f"dislike:{code}"),
            ],
            [
                InlineKeyboardButton(text="🛍 Marketplace", callback_data="marketplace"),
                InlineKeyboardButton(text="🔎 Cari Code", callback_data="search_code"),
            ],
        ]
    )


async def _load(code):
    pool = await get_pool()
    row = await pool.fetchrow(
        "SELECT * FROM files WHERE lower(code)=lower($1) LIMIT 1",
        code,
    )
    if not row:
        return None, []

    data = dict(row)
    raw = data.get("media") or data.get("medias") or []
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except Exception:
            raw = []
    return data, raw if isinstance(raw, list) else []


async def _send_batch(bot, chat_id, session):
    code = session["code"]
    medias = session["medias"]
    total = len(medias)
    start = session["index"]
    end = min(start + BATCH_SIZE, total)

    sent = 0
    for pos in range(start, end):
        result = await deliver_one(
            bot,
            chat_id,
            dict(medias[pos]),
            caption=_caption(code, pos + 1, total, dict(medias[pos])),
        )
        if result:
            sent += 1
        session["index"] = pos + 1
        if pos + 1 < end:
            await asyncio.sleep(SEND_INTERVAL)

    session["running"] = False
    remaining = total - session["index"]

    if remaining > 0:
        text = (
            f"⏸️ <b>Pengiriman dijeda</b>\n\n"
            f"✅ Terkirim: {session['index']}/{total}\n"
            f"📦 Tersisa: {remaining} media\n\n"
            f"Tekan <b>Lanjut Kirim</b> untuk melanjutkan."
        )
        await bot.send_message(
            chat_id,
            text,
            parse_mode="HTML",
            reply_markup=_control_kb(code, session["id"], True),
        )
    else:
        await bot.send_message(
            chat_id,
            f"✅ <b>Semua media selesai dikirim</b>\n"
            f"📦 Total: {total} media",
            parse_mode="HTML",
            reply_markup=_control_kb(code, session["id"], False),
        )

    return sent


async def send_all(message, code: str, user_id: int | None = None, lang: str | None = None):
    data, medias = await _load(code)
    if not data:
        await message.answer("❌ Code tidak ditemukan.")
        return

    if not medias:
        await message.answer("❌ Tidak ada media pada Code ini.")
        return

    from utils.media_access import can_open_media
    opener_id = int(user_id or message.from_user.id)
    data["media_count"] = len(medias)
    allowed, reason = await can_open_media(opener_id, data)
    if not allowed:
        if reason == "payment_required":
            from handlers.pay import paid_unlock_keyboard
            price = int(data.get("price") or 0)
            await message.answer(
                f"🔒 <b>CODE MEDIA BERBAYAR</b>\n\n📦 Total Media: <b>{int(data.get('media_count') or len(medias))}</b>\n💰 Harga: <b>Rp{price:,}</b>\n\nSilakan bayar untuk membuka media.",
                parse_mode="HTML", reply_markup=paid_unlock_keyboard(str(data.get("code")), "id")
            )
        else:
            await message.answer("⭐ <b>Poin tidak cukup untuk membuka code ini.</b>", parse_mode="HTML")
        return

    if reason != "owner":
        try:
            from utils.media_access import reward_owner_for_open
            await reward_owner_for_open(opener_id, data)
        except Exception:
            pass

    session_id = f"{message.chat.id}:{code}:{id(medias)}"
    session = {
        "id": session_id,
        "code": code,
        "medias": medias,
        "index": 0,
        "running": True,
    }
    _sessions[session_id] = session
    await _send_batch(message.bot, message.chat.id, session)


@router.callback_query(F.data.startswith("allnext:"))
async def all_next(call: CallbackQuery):
    sid = call.data.split(":", 1)[1]
    session = _sessions.get(sid)
    if not session:
        await call.answer("❌ Sesi sudah tidak tersedia.", show_alert=True)
        return
    if session["running"]:
        await call.answer("⏳ Pengiriman masih berjalan.", show_alert=True)
        return

    session["running"] = True
    await call.answer("▶️ Melanjutkan...")
    await _send_batch(call.message.bot, call.message.chat.id, session)


@router.callback_query(F.data.startswith("allstop:"))
async def all_stop(call: CallbackQuery):
    sid = call.data.split(":", 1)[1]
    session = _sessions.pop(sid, None)
    await call.answer("⛔ Pengiriman dibatalkan.")
    try:
        await call.message.edit_text(
            "⛔ <b>Pengiriman dibatalkan.</b>",
            parse_mode="HTML",
        )
    except Exception:
        pass
