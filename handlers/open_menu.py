from aiogram import Router, F
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from database import get_pool

router = Router()

LABELS = {
    "id": {
        "page": "📂 Open Page", "all": "📤 Open All",
        "loading": "🔎 <b>Mencari Media Code...</b>\n\n⏳ Mohon tunggu sebentar...",
        "menu": "📂 <b>OPEN MENU</b>\n\nPilih cara membuka media:",
        "not_found": "❌ Code tidak ditemukan.",
        "starting": "📤 Memulai pengiriman...",
    },
    "en": {
        "page": "📂 Open Page", "all": "📤 Open All",
        "loading": "🔎 <b>Searching Code Media...</b>\n\n⏳ Please wait a moment...",
        "menu": "📂 <b>OPEN MENU</b>\n\nChoose how to open the media:",
        "not_found": "❌ Code not found.",
        "starting": "📤 Starting delivery...",
    },
    "zh": {
        "page": "📂 打开页面", "all": "📤 全部打开",
        "loading": "🔎 <b>正在查找 Code 媒体...</b>\n\n⏳ 请稍候...",
        "menu": "📂 <b>打开菜单</b>\n\n请选择媒体打开方式：",
        "not_found": "❌ 未找到 Code。",
        "starting": "📤 开始发送...",
    },
}

def open_keyboard(code: str, lang: str = "id"):
    l = LABELS.get(lang, LABELS["id"])
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=l["page"], callback_data=f"page:{code}:1")],
        [InlineKeyboardButton(text=l["all"], callback_data=f"all:{code}")],
    ])

async def _language(uid: int) -> str:
    try:
        pool = await get_pool()
        return (await pool.fetchval(
            "SELECT language FROM users WHERE user_id=$1", uid
        ) or "id")
    except Exception:
        return "id"

async def _show_open_menu(call: CallbackQuery, code: str):
    pool = await get_pool()
    exists = await pool.fetchval(
        "SELECT EXISTS(SELECT 1 FROM files WHERE lower(trim(code))=lower(trim($1)))",
        code,
    )
    lang = await _language(call.from_user.id)
    l = LABELS.get(lang, LABELS["id"])
    if not exists:
        return await call.answer(l["not_found"], show_alert=True)
    await call.answer()
    # Never expose the media open menu before the canonical access check.
    # This prevents a forged open_code callback from bypassing payment.
    from handlers.getfile import process_code
    return await process_code(call.message, code, user_id=call.from_user.id)

# Keep both callback names for compatibility with Marketplace and typed-code flows.
@router.callback_query(F.data.startswith("open:"))
async def open_code_callback(call: CallbackQuery):
    await _show_open_menu(call, call.data.split(":", 1)[1])

@router.callback_query(F.data.startswith("open_code:"))
async def open_code_legacy_callback(call: CallbackQuery):
    await _show_open_menu(call, call.data.split(":", 1)[1])

@router.callback_query(F.data.startswith("all:"))
async def all_callback(call: CallbackQuery):
    code = call.data.split(":", 1)[1]
    lang = await _language(call.from_user.id)
    l = LABELS.get(lang, LABELS["id"])
    await call.answer()
    # Edit the existing bubble immediately so there is no visible dead delay.
    try:
        await call.message.edit_text(l["loading"], parse_mode="HTML")
    except Exception:
        pass
    from handlers.sendall import send_all
    await send_all(call.message, code, user_id=call.from_user.id, lang=lang)

