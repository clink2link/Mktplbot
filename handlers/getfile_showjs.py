"""
Get File bridge for legacy Showjs codes.

This handler is intentionally separate from Pastele's native getfile.py.
Showjs codes are looked up in SHOWJS_DATABASE_URL, access is charged through
Pastele's existing point economy, and media is downloaded from the B2 account
configured in Pastele Admin -> B2 Storage.

No Showjs bot token is required.
"""
import asyncio
import json
import logging
import os
import re
import tempfile
from contextlib import asynccontextmanager

from aiogram import Router, F
from aiogram.exceptions import TelegramBadRequest, TelegramRetryAfter
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery, FSInputFile

from database import get_showjs_pool, get_pool
from utils.b2_storage import download_file_from_b2, get_b2_account
from utils.points import unlock_free_code, unlock_paid_code, get_points, fmt_points
from utils.user_lang import get_user_language

router = Router()
logger = logging.getLogger(__name__)

SHOWJS_CODE_RE = re.compile(
    r"(?<![A-Za-z0-9])Jsshowbot_[A-Za-z0-9]{14}(?![A-Za-z0-9])",
    re.IGNORECASE,
)

_locks = {}


def _lock(user_id: int):
    uid = int(user_id)
    if uid not in _locks:
        _locks[uid] = asyncio.Lock()
    return _locks[uid]


def _parse_media(value):
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except Exception:
            return []
    if isinstance(value, dict):
        # Some legacy rows may store one media object instead of a list.
        return [value]
    return value if isinstance(value, list) else []


def _field(row, name, default=None):
    try:
        return row[name] if row[name] is not None else default
    except Exception:
        return default


def _localized(lang, id_text, en_text, zh_text):
    return {"id": id_text, "en": en_text, "zh": zh_text}.get(lang, id_text)


async def _find_showjs_code(code: str):
    pool = await get_showjs_pool()
    return await pool.fetchrow(
        """
        SELECT *
        FROM files
        WHERE LOWER(TRIM(code)) = LOWER(TRIM($1))
          AND COALESCE(active, TRUE) = TRUE
        LIMIT 1
        """,
        code,
    )


async def _send_b2_media(message: Message, media_items: list[dict], title: str):
    """Download each Showjs B2 object and send it through the Pastele bot."""
    sent = 0
    for index, item in enumerate(media_items, 1):
        account_id = item.get("drive_account")
        object_key = (
            item.get("drive_file_id")
            or item.get("b2_object_key")
            or item.get("object_key")
        )
        if not account_id or not object_key:
            logger.warning("SHOWJS MEDIA MISSING B2 REFERENCE | index=%s", index)
            continue

        suffix = ""
        name = str(item.get("file_name") or item.get("name") or "media")
        if "." in name:
            suffix = "." + name.rsplit(".", 1)[-1][:12]

        tmp = tempfile.NamedTemporaryFile(
            prefix="showjs_b2_",
            suffix=suffix,
            delete=False,
        )
        path = tmp.name
        tmp.close()

        try:
            ok = await download_file_from_b2(int(account_id), object_key, path)
            if not ok:
                continue

            file_type = str(
                item.get("type") or item.get("file_type") or "document"
            ).lower()
            caption = title if index == 1 else None
            inp = FSInputFile(path, filename=name)

            if file_type in {"photo", "image"}:
                await message.answer_photo(inp, caption=caption)
            elif file_type == "video":
                await message.answer_video(inp, caption=caption)
            elif file_type == "audio":
                await message.answer_audio(inp, caption=caption)
            elif file_type == "voice":
                await message.answer_voice(inp, caption=caption)
            elif file_type in {"animation", "gif"}:
                await message.answer_animation(inp, caption=caption)
            else:
                await message.answer_document(inp, caption=caption)

            sent += 1
        except TelegramRetryAfter as exc:
            await asyncio.sleep(max(1.0, float(exc.retry_after) + 0.5))
            try:
                inp = FSInputFile(path, filename=name)
                if file_type == "video":
                    await message.answer_video(inp, caption=caption)
                elif file_type in {"photo", "image"}:
                    await message.answer_photo(inp, caption=caption)
                else:
                    await message.answer_document(inp, caption=caption)
                sent += 1
            except Exception:
                logger.exception("SHOWJS MEDIA RETRY FAILED | index=%s", index)
        except Exception:
            logger.exception("SHOWJS MEDIA SEND FAILED | index=%s", index)
        finally:
            try:
                os.unlink(path)
            except Exception:
                pass

    return sent


async def process_showjs_code(message: Message, code: str):
    user_id = int(message.from_user.id)
    code = str(code or "").strip()

    # Admin can disable the legacy Showjs bridge without redeploying.
    try:
        control_pool = await get_pool()
        enabled = await control_pool.fetchval(
            "SELECT value FROM settings WHERE key=$1",
            "showjs_bridge_enabled",
        )
        if str(enabled or "on").lower() not in {"on", "1", "true", "yes"}:
            return await message.answer("⛔ Akses CODE Showjs sedang dinonaktifkan admin.")
    except Exception:
        logger.exception("SHOWJS CONTROL CHECK FAILED")

    async with _lock(user_id):
        try:
            row = await _find_showjs_code(code)
        except Exception:
            logger.exception("SHOWJS CODE LOOKUP FAILED | code=%s", code)
            return await message.answer(
                "❌ Database media Showjs sedang tidak dapat diakses."
            )

        if not row:
            return await message.answer("❌ CODE Showjs tidak ditemukan.")

        media = _parse_media(_field(row, "media"))
        if not media:
            return await message.answer("❌ Media pada CODE Showjs kosong.")

        title = str(_field(row, "title", "Showjs Media") or "Showjs Media")
        # Validate every B2 mapping before charging points. This prevents a
        # misconfigured Admin -> B2 account from consuming user points.
        b2_refs = []
        for idx, item in enumerate(media, 1):
            account_id = item.get("drive_account")
            object_key = (
                item.get("drive_file_id")
                or item.get("b2_object_key")
                or item.get("object_key")
            )
            if not account_id or not object_key:
                return await message.answer(
                    f"❌ Media #{idx} tidak memiliki referensi B2 yang valid."
                )
            account = await get_b2_account(int(account_id))
            if not account:
                return await message.answer(
                    f"❌ B2 #{int(account_id)} belum dikonfigurasi di panel admin."
                )
            b2_refs.append((int(account_id), str(object_key)))

        is_paid = bool(_field(row, "is_paid", False))
        price = int(_field(row, "price", 0) or 0)
        owner_id = int(_field(row, "owner_id", 0) or 0)

        # Existing Pastele point economy is the ONLY access gate.
        # The Showjs database is never modified by this handler.
        pool = await get_pool()
        if owner_id and owner_id == user_id:
            allowed = True
            reason = "owner"
        elif is_paid:
            # A successful point unlock is stored in Pastele's
            # point_code_unlocks table, so the same CODE is not charged twice.
            allowed, balance = await unlock_paid_code(
                pool, user_id, code, price
            )
            reason = "points" if allowed else "points_required"
            if not allowed:
                lang = await get_user_language(user_id)
                return await message.answer(
                    _localized(
                        lang,
                        f"⭐ <b>POIN TIDAK CUKUP</b>\n\nDibutuhkan: <b>{fmt_points(price)} poin</b>\nPoin kamu: <b>{fmt_points(balance)}</b>.",
                        f"⭐ <b>NOT ENOUGH POINTS</b>\n\nRequired: <b>{fmt_points(price)} points</b>\nYour points: <b>{fmt_points(balance)}</b>.",
                        f"⭐ <b>积分不足</b>\n\n需要：<b>{fmt_points(price)} 积分</b>.",
                    ),
                    parse_mode="HTML",
                )
        else:
            allowed, balance, charged = await unlock_free_code(
                pool, user_id, code, len(media)
            )
            reason = "points" if allowed else "points_required"
            if not allowed:
                lang = await get_user_language(user_id)
                return await message.answer(
                    _localized(
                        lang,
                        f"⭐ <b>POIN TIDAK CUKUP</b>\n\nMedia: <b>{len(media)}</b>\nDibutuhkan: <b>{fmt_points(charged)} poin</b>\nPoin kamu: <b>{fmt_points(balance)}</b>.",
                        f"⭐ <b>NOT ENOUGH POINTS</b>\n\nMedia: <b>{len(media)}</b>\nRequired: <b>{fmt_points(charged)} points</b>\nYour points: <b>{fmt_points(balance)}</b>.",
                        f"⭐ <b>积分不足</b>\n\n媒体：<b>{len(media)}</b>\n需要：<b>{fmt_points(charged)} 积分</b>.",
                    ),
                    parse_mode="HTML",
                )

        lang = await get_user_language(user_id)
        status = await message.answer(
            _localized(
                lang,
                f"⏳ Mengambil <b>{len(media)}</b> media dari storage Showjs...",
                f"⏳ Fetching <b>{len(media)}</b> media from Showjs storage...",
                f"⏳ 正在从 Showjs 存储获取 <b>{len(media)}</b> 个媒体...",
            ),
            parse_mode="HTML",
        )

        b2_enabled = await pool.fetchval(
            "SELECT value FROM settings WHERE key=$1",
            "showjs_b2_enabled",
        )
        if str(b2_enabled or "on").lower() not in {"on", "1", "true", "yes"}:
            return await status.edit_text("⛔ Storage B2 Showjs sedang dinonaktifkan admin.", parse_mode="HTML")

        sent = await _send_b2_media(message, media, title)

        try:
            await status.edit_text(
                _localized(
                    lang,
                    f"✅ <b>SELESAI</b>\n\n📝 {title}\n📦 Berhasil dikirim: <b>{sent}/{len(media)}</b>",
                    f"✅ <b>DONE</b>\n\n📝 {title}\n📦 Sent: <b>{sent}/{len(media)}</b>",
                    f"✅ <b>完成</b>\n\n📝 {title}\n📦 已发送：<b>{sent}/{len(media)}</b>",
                ),
                parse_mode="HTML",
            )
        except Exception:
            pass


@router.message(
    F.text.regexp(SHOWJS_CODE_RE)
)
async def showjs_code_global(message: Message, state: FSMContext):
    text = (message.text or "").strip()
    match = SHOWJS_CODE_RE.search(text)
    if not match:
        return
    try:
        await state.clear()
    except Exception:
        pass
    return await process_showjs_code(message, match.group())


