from aiogram import Router, F
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton
)
from utils.user import set_vip, set_vvip
from database import get_pool
from urllib.parse import quote


router = Router()

BOT_USERNAME = "ZyxFidxBot"


# =========================
# PROGRESS BAR
# =========================

def make_bar(current, target):
    if target <= 0:
        return "░" * 10

    filled = min(int((current / target) * 10), 10)
    return "█" * filled + "░" * (10 - filled)



# =========================
# SHOW REWARD
# =========================

async def show_reward(message: Message):

    pool = await get_pool()

    user = await pool.fetchrow(
        """
        SELECT
            referral_count,
            ref_10_claimed,
            ref_20_claimed,
            ref_50_claimed
        FROM users
        WHERE chat_id=$1
        """,
        message.from_user.id
    )


    if not user:
        return await message.answer(
            "❌ User tidak ditemukan"
        )


    count = user["referral_count"] or 0


    # target progress

    if count < 10:
        target = 10
        reward = "💠 VIP 1 Hari"

    elif count < 20:
        target = 20
        reward = "💠 VIP 5 Hari"

    elif count < 50:
        target = 50
        reward = "💎 VVIP 7 Hari"

    else:
        target = 50
        reward = "🎉 Semua reward terbuka"



    bar = make_bar(
        min(count,target),
        target
    )


    link = (
        f"https://t.me/{BOT_USERNAME}"
        f"?start=ref_{message.from_user.id}"
    )


    kb = []


    # ======================
    # CLAIM BUTTON
    # ======================


    if count >= 10:

        if not user["ref_10_claimed"]:

            kb.append([
                InlineKeyboardButton(
                    text="🎁 Claim VIP 1 Hari",
                    callback_data="claim_ref_10"
                )
            ])

        else:

            kb.append([
                InlineKeyboardButton(
                    text="✅ VIP 1 Hari Claimed",
                    callback_data="none"
                )
            ])



    if count >= 20:

        if not user["ref_20_claimed"]:

            kb.append([
                InlineKeyboardButton(
                    text="🎁 Claim VIP 5 Hari",
                    callback_data="claim_ref_20"
                )
            ])

        else:

            kb.append([
                InlineKeyboardButton(
                    text="✅ VIP 5 Hari Claimed",
                    callback_data="none"
                )
            ])




    if count >= 50:

        if not user["ref_50_claimed"]:

            kb.append([
                InlineKeyboardButton(
                    text="🎁 Claim VVIP 7 Hari",
                    callback_data="claim_ref_50"
                )
            ])

        else:

            kb.append([
                InlineKeyboardButton(
                    text="✅ VVIP 7 Hari Claimed",
                    callback_data="none"
                )
            ])



    link = f"https://t.me/{BOT_USERNAME}?start=ref_{message.from_user.id}"
    share_text = (
        "🚀 Ayo Gabung Di Bot Ini!😇\n\n"
        "🎞️ Banyak Media Viral.\n"
        "💎 Dan Media Bisa Di Save Dengan Gratis.\n\n"
    )

    share_url = (
        "https://t.me/share/url?"
        f"url={quote(link)}"
        f"&text={quote(share_text)}"
    )

    kb.append([
        InlineKeyboardButton(
            text="📤 Bagikan Referral",
            url=share_url
        )
    ])



    text = (
        "🎁 <b>REFERRAL REWARD</b>\n\n"

        f"👥 Total Referral : <b>{count}</b>\n\n"

        f"{bar} "
        f"{min(count,target)}/{target}\n\n"

        f"🎯 Reward Berikutnya:\n"
        f"{reward}\n\n"

        "🔗 Link Referral Kamu:\n"
        f"<code>{link}</code>"
    )


    await message.answer(
        text,
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=kb
        )
    )



# =========================
# BUTTON REWARD
# =========================

@router.message(F.text=="🎁 Reward")
async def reward_button(message: Message):

    await show_reward(message)



# =========================
# CLAIM VIP 1 HARI
# =========================

@router.callback_query(F.data=="claim_ref_10")
async def claim_10(call:CallbackQuery):

    pool=await get_pool()

    user=await pool.fetchrow(
        """
        SELECT referral_count,ref_10_claimed
        FROM users
        WHERE chat_id=$1
        """,
        call.from_user.id
    )


    if user["referral_count"] < 10:
        return await call.answer(
            "❌ Belum mencapai 10 referral",
            show_alert=True
        )


    if user["ref_10_claimed"]:
        return await call.answer(
            "Sudah diklaim",
            show_alert=True
        )


    await set_vip(call.from_user.id, 1)

    await pool.execute(
        """
        UPDATE users
        SET ref_10_claimed=TRUE
        WHERE user_id=$1
        """,
        call.from_user.id
    )


    await call.answer(
        "🎉 VIP 1 Hari Aktif"
    )

    await call.message.edit_text(
        "🎉 <b>VIP 1 HARI AKTIF</b>\n\n"
        "Terima kasih sudah mengajak user!",
        parse_mode="HTML"
    )



# =========================
# CLAIM VIP 5 HARI
# =========================

@router.callback_query(F.data=="claim_ref_20")
async def claim_20(call:CallbackQuery):

    pool=await get_pool()

    user=await pool.fetchrow(
        """
        SELECT referral_count,ref_20_claimed
        FROM users
        WHERE chat_id=$1
        """,
        call.from_user.id
    )


    if user["referral_count"] < 20:
        return await call.answer(
            "Belum 20 referral",
            show_alert=True
        )


    if user["ref_20_claimed"]:
        return await call.answer(
            "Sudah diklaim",
            show_alert=True
        )


    await set_vip(call.from_user.id, 5)

    await pool.execute(
        """
        UPDATE users
        SET ref_20_claimed=TRUE
        WHERE user_id=$1
        """,
        call.from_user.id
    )


    await call.answer(
        "🎉 VIP 5 Hari Aktif"
    )

    await call.message.edit_text(
        "🎉 <b>VIP 5 HARI AKTIF</b>",
        parse_mode="HTML"
    )



# =========================
# CLAIM VVIP 7 HARI
# =========================

@router.callback_query(F.data=="claim_ref_50")
async def claim_50(call:CallbackQuery):

    pool=await get_pool()

    user=await pool.fetchrow(
        """
        SELECT referral_count,ref_50_claimed
        FROM users
        WHERE chat_id=$1
        """,
        call.from_user.id
    )


    if user["referral_count"] < 50:
        return await call.answer(
            "Belum 50 referral",
            show_alert=True
        )


    if user["ref_50_claimed"]:
        return await call.answer(
            "Sudah diklaim",
            show_alert=True
        )


    await set_vvip(call.from_user.id, 7)

    await pool.execute(
        """
        UPDATE users
        SET ref_50_claimed=TRUE
        WHERE user_id=$1
        """,
        call.from_user.id
    )


    await call.answer(
        "💎 VVIP 7 Hari Aktif"
    )


    await call.message.edit_text(
        "💎 <b>VVIP 7 HARI AKTIF</b>\n\n"
        "Semua reward referral selesai 🎉",
        parse_mode="HTML"
    )


@router.callback_query(F.data == "none")
async def none_callback(call: CallbackQuery):
    await call.answer(
        "✅ Reward ini sudah diklaim.",
        show_alert=False
    )
