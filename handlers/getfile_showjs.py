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
from utils.points import unlock_free_code, unlock_paid_code_status, rollback_code_unlock, get_points, fmt_points
from utils.user_lang import get_user_language

router = Router()
logger = logging.getLogger(__name__)

# Showjs CODE: prefix + variable alphanumeric media id + _version marker.
# Example: Jsshowbot_77X4xx727x3_0p90v0d
SHOWJS_CODE_RE = re.compile(
    r"(?<![A-Za-z0-9])Jsshowbot_[A-Za-z0-9]+_[0-9]+p[0-9]+v[0-9]+d(?![A-Za-z0-9])",
    re.IGNORECASE,
)
SHOWJS_CODE_EXACT_RE = re.compile(
    r"^\s*Jsshowbot_[A-Za-z0-9]+_[0-9]+p[0-9]+v[0-9]+d\s*$",
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
    row = await pool.fetchrow(
        """
        SELECT *
        FROM files
        WHERE LOWER(TRIM(code)) = LOWER(TRIM($1))
        LIMIT 1
        """,
        code,
    )
    if not row:
        return None

    # Showjs schema variants may or may not have an `active` column.
    # Do not make the bridge fail merely because the legacy schema lacks it.
    try:
        active = row["active"]
    except (KeyError, IndexError):
        active = True
    if active is False:
        return None
    return row


async def _prepare_b2_media(media_items: list[dict]):
    """Download every Showjs object before any points are charged.

    This is intentionally all-or-nothing for the point gate: if even one
    object cannot be downloaded, the caller receives no charge.
    Returns (prepared_items, error_index). Each prepared item contains the
    original metadata plus a temporary local path.
    """
    prepared = []
    for index, item in enumerate(media_items, 1):
        account_id = item.get("drive_account")
        object_key = (
            item.get("drive_file_id")
            or item.get("b2_object_key")
            or item.get("object_key")
        )
        if not account_id or not object_key:
            return prepared, index

        name = str(item.get("file_name") or item.get("name") or "media")
        suffix = ""
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
            ok = await download_file_from_b2(
                int(account_id), str(object_key), path
            )
            if not ok:
                os.unlink(path)
                return prepared, index

            prepared.append({
                "item": item,
                "path": path,
                "name": name,
            })
        except Exception:
            logger.exception(
                "SHOWJS B2 PREPARE FAILED | index=%s", index
            )
            try:
                os.unlink(path)
            except Exception:
                pass
            return prepared, index

    return prepared, None


async def _send_prepared_b2_media(message: Message, prepared: list[dict], title: str):
    """Send already-downloaded Showjs media through the Pastele bot."""
    sent_messages = []
    for index, entry in enumerate(prepared, 1):
        item = entry["item"]
        path = entry["path"]
        name = entry["name"]
        file_type = str(
            item.get("type") or item.get("file_type") or "document"
        ).lower()
        caption = title if index == 1 else None

        try:
            inp = FSInputFile(path, filename=name)
            if file_type in {"photo", "image"}:
                sent_msg = await message.answer_photo(inp, caption=caption)
            elif file_type == "video":
                sent_msg = await message.answer_video(inp, caption=caption)
            elif file_type == "audio":
                sent_msg = await message.answer_audio(inp, caption=caption)
            elif file_type == "voice":
                sent_msg = await message.answer_voice(inp, caption=caption)
            elif file_type in {"animation", "gif"}:
                sent_msg = await message.answer_animation(inp, caption=caption)
            else:
                sent_msg = await message.answer_document(inp, caption=caption)
            sent_messages.append(sent_msg)
        except TelegramRetryAfter as exc:
            await asyncio.sleep(max(1.0, float(exc.retry_after) + 0.5))
            try:
                inp = FSInputFile(path, filename=name)
                if file_type == "video":
                    sent_msg = await message.answer_video(inp, caption=caption)
                elif file_type in {"photo", "image"}:
                    sent_msg = await message.answer_photo(inp, caption=caption)
                elif file_type == "audio":
                    sent_msg = await message.answer_audio(inp, caption=caption)
                elif file_type == "voice":
                    sent_msg = await message.answer_voice(inp, caption=caption)
                elif file_type in {"animation", "gif"}:
                    sent_msg = await message.answer_animation(inp, caption=caption)
                else:
                    sent_msg = await message.answer_document(inp, caption=caption)
                sent_messages.append(sent_msg)
            except Exception:
                logger.exception(
                    "SHOWJS MEDIA RETRY FAILED | index=%s", index
                )
        except Exception:
            logger.exception(
                "SHOWJS MEDIA SEND FAILED | index=%s", index
            )
        finally:
            try:
                os.unlink(path)
            except Exception:
                pass

    return sent_messages


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
        # Validate every B2 mapping and the admin switch BEFORE charging
        # points. The complete media batch is downloaded first as well.
        # Therefore a missing B2 object, bad credentials, or B2 outage can
        # never consume the user's points.
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
            try:
                account_id = int(account_id)
            except (TypeError, ValueError):
                return await message.answer(
                    f"❌ Media #{idx} memiliki B2 account ID yang tidak valid."
                )
            account = await get_b2_account(account_id)
            if not account:
                return await message.answer(
                    f"❌ B2 #{account_id} belum dikonfigurasi di panel admin."
                )
            b2_refs.append((account_id, str(object_key)))

        pool = await get_pool()
        b2_enabled = await pool.fetchval(
            "SELECT value FROM settings WHERE key=$1",
            "showjs_b2_enabled",
        )
        if str(b2_enabled or "on").lower() not in {"on", "1", "true", "yes"}:
            return await message.answer(
                "⛔ Storage B2 Showjs sedang dinonaktifkan admin."
            )

        # Download the complete batch before touching the point balance.
        prepared, failed_index = await _prepare_b2_media(media)
        if failed_index is not None or len(prepared) != len(media):
            for entry in prepared:
                try:
                    os.unlink(entry["path"])
                except Exception:
                    pass
            return await message.answer(
                f"❌ Media Showjs #{failed_index or '?'} gagal diambil dari B2. "
                "Poin kamu tidak dipotong. Silakan coba lagi nanti."
            )

        is_paid = bool(_field(row, "is_paid", False))
        price = int(_field(row, "price", 0) or 0)
        owner_id = int(_field(row, "owner_id", 0) or 0)
        charged_this_request = False

        # Existing Pastele point economy is the ONLY access gate.
        # The Showjs database is never modified by this handler.
        if owner_id and owner_id == user_id:
            allowed = True
        elif is_paid:
            # The charged flag comes from the same DB transaction that
            # performs the unlock. Never infer it with a separate pre-check.
            allowed, balance, charged_this_request = await unlock_paid_code_status(
                pool, user_id, code, price
            )
            if not allowed:
                for entry in prepared:
                    try:
                        os.unlink(entry["path"])
                    except Exception:
                        pass
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
            charged_this_request = charged > 0
            if not allowed:
                for entry in prepared:
                    try:
                        os.unlink(entry["path"])
                    except Exception:
                        pass
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
                f"⏳ Mengirim <b>{len(media)}</b> media dari storage Showjs...",
                f"⏳ Sending <b>{len(media)}</b> media from Showjs storage...",
                f"⏳ 正在发送 <b>{len(media)}</b> 个 Showjs 媒体...",
            ),
            parse_mode="HTML",
        )

        sent_messages = await _send_prepared_b2_media(message, prepared, title)
        sent = len(sent_messages)

        if sent != len(media) and charged_this_request:
            # Remove any partially delivered messages before refunding. This
            # prevents a Telegram delivery failure from becoming a free unlock.
            for sent_message in sent_messages:
                try:
                    await sent_message.delete()
                except Exception:
                    pass
            rolled_back, refunded = await rollback_code_unlock(pool, user_id, code)
            if rolled_back:
                lang = await get_user_language(user_id)
                try:
                    await status.edit_text(
                        _localized(
                            lang,
                            f"❌ Pengiriman gagal. <b>{fmt_points(refunded)} poin</b> dikembalikan. Tidak ada poin yang hilang.",
                            f"❌ Delivery failed. <b>{fmt_points(refunded)} points</b> were refunded. No points were lost.",
                            f"❌ 发送失败，已退还 <b>{fmt_points(refunded)} 积分</b>。积分未损失。",
                        ),
                        parse_mode="HTML",
                    )
                except Exception:
                    pass
                return

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



@router.callback_query(F.data.startswith("open_showjs:"))
async def open_showjs_from_notification(call: CallbackQuery):
    code = call.data.split(":", 1)[1].strip()
    await call.answer("⏳")
    return await process_showjs_code(call.message, code)


@router.message(
    F.text.regexp(SHOWJS_CODE_EXACT_RE)
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


