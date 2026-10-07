from aiogram import Router, F
from aiogram.types import CallbackQuery
from database import get_pool
from keyboards.menu import home_kb, other_menu_kb, settings_kb
from config import REVIEW_CHANNEL_URL, NOTIFICATION_CHANNEL_URL, TRANSACTION_CHANNEL_URL, ALL_CODE_CHANNEL_URL

router = Router()

async def lang_for(user_id):
    pool=await get_pool()
    return (await pool.fetchval("SELECT language FROM users WHERE user_id=$1", user_id)) or "id"


@router.callback_query(F.data == "vip_creator")
async def vip_creator_menu(callback: CallbackQuery):
    lang = await lang_for(callback.from_user.id)
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    idn = lang == "id"
    await callback.message.edit_text(
        "💎 <b>VIP / KREATOR</b>\n\n"
        "Pilih layanan yang ingin kamu buka." if idn
        else "💎 <b>VIP / CREATOR</b>\n\nChoose a service.",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="💎 VIP",
                    callback_data="vvip",
                ),
                InlineKeyboardButton(
                    text="🎨 Kreator" if idn else "🎨 Creator",
                    callback_data="creator",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="⬅️ Kembali" if idn else "⬅️ Back",
                    callback_data="home",
                )
            ],
        ]),
    )
    await callback.answer()

@router.callback_query(F.data == "menu_lainnya")
async def menu_lainnya(callback: CallbackQuery):
    lang=await lang_for(callback.from_user.id)
    await callback.message.edit_text("📂 <b>MENU LAINNYA</b>" if lang=="id" else "📂 <b>MORE MENU</b>", parse_mode="HTML", reply_markup=other_menu_kb(lang))
    await callback.answer()

@router.callback_query(F.data == "account_settings")
async def account_settings(callback: CallbackQuery):
    lang=await lang_for(callback.from_user.id)
    await callback.message.edit_text("⚙️ <b>PENGATURAN ACCOUNT</b>" if lang=="id" else "⚙️ <b>ACCOUNT SETTINGS</b>", parse_mode="HTML", reply_markup=settings_kb(lang))
    await callback.answer()

@router.callback_query(F.data.in_({"channel_review","channel_notification","channel_transaction"}))
async def channel_links(callback: CallbackQuery):
    lang=await lang_for(callback.from_user.id)
    links={"channel_review":(REVIEW_CHANNEL_URL,"⭐ Channel Review Semua Media" if lang=="id" else "⭐ All Media Review Channel"),"channel_notification":(NOTIFICATION_CHANNEL_URL,"🔔 Channel Notifikasi" if lang=="id" else "🔔 Notification Channel"),"channel_transaction":(TRANSACTION_CHANNEL_URL,"💳 Channel Transaksi" if lang=="id" else "💳 Transaction Channel")}
    url,label=links[callback.data]
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    await callback.message.edit_text(label, reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=label,url=url)],[InlineKeyboardButton(text="⬅️ Kembali" if lang=="id" else "⬅️ Back",callback_data="menu_lainnya")]]))
    await callback.answer()

@router.callback_query(F.data == "collect_all_codes")
async def collect_all_codes(callback: CallbackQuery):
    from handlers.sendall import send_all
    pool=await get_pool()
    rows=await pool.fetch("SELECT code FROM files WHERE owner_id=$1 ORDER BY id DESC", callback.from_user.id)
    if not rows:
        lang=await lang_for(callback.from_user.id)
        return await callback.answer("❌ Belum ada code." if lang=="id" else "❌ No codes found.", show_alert=True)
    # The existing Open All flow is per-code; this button intentionally opens a compact list.
    lang=await lang_for(callback.from_user.id)
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    buttons=[[InlineKeyboardButton(text=f"📦 {r['code']}",callback_data=f"all:{r['code']}")] for r in rows[:50]]
    buttons.append([InlineKeyboardButton(text="⬅️ Kembali" if lang=="id" else "⬅️ Back",callback_data="menu_lainnya")])
    await callback.message.edit_text(("📦 <b>KUMPULKAN SEMUA CODE</b>\n\nPilih code untuk membuka semua media." if lang=="id" else "📦 <b>COLLECT ALL CODES</b>\n\nChoose a code to open all media."),parse_mode="HTML",reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await callback.answer()

@router.callback_query(F.data == "home")
async def back_home(callback: CallbackQuery):
    pool=await get_pool()
    row=await pool.fetchrow("SELECT language,is_creator,creator_status FROM users WHERE user_id=$1",callback.from_user.id)
    lang=(row["language"] if row else "id") or "id"
    creator=bool(row and row["is_creator"] and row["creator_status"]=="approved")
    await callback.message.edit_text("🏠 <b>MENU UTAMA</b>" if lang=="id" else "🏠 <b>MAIN MENU</b>",parse_mode="HTML",reply_markup=home_kb(callback.from_user.id,lang,creator))
    await callback.answer()

@router.callback_query(F.data == "share_code")
async def share_code_menu(callback: CallbackQuery):
    """List the user's codes with Telegram share links."""
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    from utils.share_unlock import share_url
    pool = await get_pool()
    lang = await lang_for(callback.from_user.id)
    rows = await pool.fetch(
        """SELECT code,title,media_count,is_paid
           FROM files WHERE owner_id=$1 ORDER BY id DESC LIMIT 20""",
        callback.from_user.id,
    )
    if not rows:
        return await callback.answer(
            "❌ Belum ada code." if lang == "id" else "❌ No codes yet.",
            show_alert=True,
        )
    me = await callback.bot.get_me()
    buttons = []
    for r in rows:
        url = share_url(
            me.username, r["code"], callback.from_user.id,
            str(r["title"] or r["code"])
        )
        label = f"📤 {r['code']} • {int(r['media_count'] or 0)} media"
        buttons.append([InlineKeyboardButton(text=label, url=url)])
    buttons.append([InlineKeyboardButton(
        text="⬅️ Kembali" if lang == "id" else "⬅️ Back",
        callback_data="menu_lainnya"
    )])
    await callback.message.edit_text(
        "📤 <b>SHARE CODE</b>\n\n"
        + ("Bagikan code. Kamu mendapat +1 poin ketika pengguna lain benar-benar membuka code tersebut."
           if lang == "id" else
           "Share a code. You get +1 point when another user actually opens the code."),
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
    )
