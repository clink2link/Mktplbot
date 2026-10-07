from __future__ import annotations

import logging

from aiogram import Router, F
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)

from database import get_pool
from utils.points import get_points, checkin, fmt_points
from utils.cashi import Cashi
from utils.bayargg import BayarGG
from config import ADMIN_IDS
from utils.payment_channel import send_payment_success_channel


router = Router()
logger = logging.getLogger(__name__)


# ============================================================
# POINT PACKAGES
#
# Harga:
# Rp 2.000  -> 20 poin
# Rp 5.000  -> 100 poin
# Rp 10.000 -> 200 poin
# Rp 20.000 -> 400 poin
# Rp 50.000 -> 1.000 poin
#
# Format:
# (JUMLAH_POIN, HARGA_RUPIAH)
# ============================================================

PACKAGES = [
    (20, 2_000),
    (100, 5_000),
    (200, 10_000),
    (400, 20_000),
    (1_000, 50_000),
]


# ============================================================
# POINT MENU KEYBOARD
# ============================================================

def menu_kb(lang: str) -> InlineKeyboardMarkup:
    labels = {
        "id": ("📅 Cek In Harian", "💳 Buy Poin", "📖 Kegunaan Poin", "⬅️ Kembali"),
        "en": ("📅 Daily Check-in", "💳 Buy Points", "📖 How Points Work", "⬅️ Back"),
        "zh": ("📅 每日签到", "💳 购买积分", "📖 积分说明", "⬅️ 返回"),
    }
    a, b, c, d = labels.get(lang, labels["id"])
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text=a, callback_data="points_checkin"),
            InlineKeyboardButton(text=b, callback_data="points_buy"),
        ],
        [
            InlineKeyboardButton(text=c, callback_data="points_info"),
            InlineKeyboardButton(text=d, callback_data="home"),
        ],
    ])


# ============================================================
# GET USER LANGUAGE
# ============================================================

async def lang(uid: int) -> str:
    pool = await get_pool()

    language = await pool.fetchval(
        """
        SELECT language
        FROM users
        WHERE user_id = $1
        """,
        uid,
    )

    return language or "id"


# ============================================================
# POINTS MAIN PAGE
# ============================================================

async def _checkin_summary(pool, uid: int):
    row = await pool.fetchrow(
        "SELECT checkin_streak,last_checkin_date FROM users WHERE user_id=$1", uid
    )
    total = await pool.fetchval(
        "SELECT COUNT(*) FROM point_checkins WHERE user_id=$1", uid
    )
    streak = int(row["checkin_streak"] or 0) if row else 0
    return streak, row["last_checkin_date"] if row else None, int(total or 0)

async def render(call: CallbackQuery):
    uid = call.from_user.id
    await call.answer()
    language = await lang(uid)
    pool = await get_pool()
    pts = await get_points(pool, uid)
    streak, last_date, total_checkin = await _checkin_summary(pool, uid)

    # 7-day visual: completed days get ✅, the next day gets 🛑,
    # remaining days are neutral. The reward amount is always shown.
    rewards = ["0.5", "0.5", "1", "1", "1.5", "2", "3"]
    icons = []
    for day, reward in enumerate(rewards, 1):
        if day <= min(streak, 7):
            icon = "❇️" if day == 1 else "✅"
        elif day == min(streak + 1, 7):
            icon = "🛑"
        else:
            icon = "▫️"
        icons.append(f"{day}. {reward} {icon}")
    checkin_lines = "  ".join(icons[:4]) + "\n" + "  ".join(icons[4:])

    texts = {
        "id": (
            "⭐ <b>Poin kamu 💰</b>\n"
            "━━━━━━━━━━━━━━\n"
            f"⭐ Saldo Poin : <b>{fmt_points(pts)}</b>\n\n"
            "📅 <b>Cek in harian</b>\n"
            f"{checkin_lines}\n\n"
            f"📊 Total cek in : <b>{total_checkin} hari</b>\n"
            f"🔥 Streak saat ini : <b>{streak}/7 hari</b>\n\n"
            "Gunakan poin untuk membuka media FREE, membuka code berbayar, "
            "dan mendapatkan akses dari aktivitas di bot."
        ),
        "en": (
            "⭐ <b>Your Points 💰</b>\n"
            "━━━━━━━━━━━━━━\n"
            f"⭐ Point Balance : <b>{fmt_points(pts)}</b>\n\n"
            "📅 <b>Daily check-in</b>\n"
            f"{checkin_lines}\n\n"
            f"📊 Total check-ins : <b>{total_checkin} days</b>\n"
            f"🔥 Current streak : <b>{streak}/7 days</b>\n\n"
            "Use points to open FREE media, unlock paid codes, and earn through bot activity."
        ),
        "zh": (
            "⭐ <b>你的积分 💰</b>\n"
            "━━━━━━━━━━━━━━\n"
            f"⭐ 积分余额：<b>{fmt_points(pts)}</b>\n\n"
            "📅 <b>每日签到</b>\n"
            f"{checkin_lines}\n\n"
            f"📊 总签到：<b>{total_checkin} 天</b>\n"
            f"🔥 当前连续：<b>{streak}/7 天</b>\n\n"
            "积分可用于打开免费媒体、解锁付费代码以及通过机器人活动获得积分。"
        ),
    }
    await call.message.edit_text(
        texts.get(language, texts["id"]),
        parse_mode="HTML",
        reply_markup=menu_kb(language),
    )


# ============================================================
# OPEN POINTS MENU
# ============================================================

@router.callback_query(F.data == "points")
async def points_menu(call: CallbackQuery):
    await render(call)


# ============================================================
# POINT INFORMATION
# ============================================================

@router.callback_query(F.data == "points_info")
async def points_info(call: CallbackQuery):
    language = await lang(call.from_user.id)
    await call.answer()
    texts = {
        "id": (
            "📖 <b>Kegunaan Poin</b>\n"
            "━━━━━━━━━━━━━━\n"
            "⭐ <b>1.</b> Buka media FREE → <b>1.20 poin/media</b>\n"
            "⭐ <b>2.</b> Buka code PAID → poin sesuai harga code\n"
            "⭐ <b>3.</b> Cek in harian → bonus sampai <b>3 poin</b>\n"
            "⭐ <b>4.</b> Upload → setiap 50 media selesai = <b>+10 poin</b>\n"
            "⭐ <b>5.</b> User unik membuka code share kamu → <b>+1 poin</b>\n\n"
            "💡 <b>Buy Poin</b> memakai pembayaran QR dan setelah pembayaran "
            "berhasil poin otomatis masuk ke akun."
        ),
        "en": (
            "📖 <b>How Points Work</b>\n"
            "━━━━━━━━━━━━━━\n"
            "⭐ <b>1.</b> Open FREE media → <b>1.20 points/media</b>\n"
            "⭐ <b>2.</b> Open PAID code → points equal to the code price\n"
            "⭐ <b>3.</b> Daily check-in → up to <b>3 points</b>\n"
            "⭐ <b>4.</b> Upload → every completed 50 media = <b>+10 points</b>\n"
            "⭐ <b>5.</b> A unique user opening your shared code → <b>+1 point</b>\n\n"
            "💡 <b>Buy Points</b> uses QR payment and points are credited automatically after payment."
        ),
        "zh": (
            "📖 <b>积分用途</b>\n"
            "━━━━━━━━━━━━━━\n"
            "⭐ <b>1.</b> 打开免费媒体 → <b>每个 1.20 积分</b>\n"
            "⭐ <b>2.</b> 打开付费代码 → 消耗等于代码价格的积分\n"
            "⭐ <b>3.</b> 每日签到 → 最高 <b>3 积分</b>\n"
            "⭐ <b>4.</b> 上传 → 每完成 50 个媒体 = <b>+10 积分</b>\n"
            "⭐ <b>5.</b> 独立用户打开你分享的代码 → <b>+1 积分</b>\n\n"
            "💡 <b>购买积分</b>使用 QR 支付，付款成功后积分自动到账。"
        ),
    }
    await call.message.edit_text(
        texts.get(language, texts["id"]),
        parse_mode="HTML",
        reply_markup=menu_kb(language),
    )


# ============================================================
# DAILY CHECK-IN
# ============================================================

@router.callback_query(F.data == "points_checkin")
async def points_checkin(call: CallbackQuery):
    await call.answer("⏳")

    uid = call.from_user.id
    pool = await get_pool()

    result, status = await checkin(pool, uid)

    language = await lang(uid)

    if status == "already":

        messages = {
            "id": "⚠️ Kamu sudah check-in hari ini.",
            "en": "⚠️ You already checked in today.",
            "zh": "⚠️ 今天已经签到。",
        }

        msg = messages.get(
            language,
            messages["id"],
        )

    elif status == "user_not_found":

        messages = {
            "id": "❌ User tidak ditemukan.",
            "en": "❌ User not found.",
            "zh": "❌ 未找到用户。",
        }

        msg = messages.get(
            language,
            messages["id"],
        )

    else:

        day = int(status)

        rewards = [
            "0.5",
            "0.5",
            "1",
            "1",
            "1.5",
            "2",
            "3",
        ]

        reward = rewards[day - 1]

        messages = {
            "id": (
                "✅ <b>Check-in berhasil!</b>\n\n"
                f"Hari ke-{day}: <b>+{reward} poin</b>\n"
                f"Total: <b>{fmt_points(result)}</b>"
            ),

            "en": (
                "✅ <b>Check-in complete!</b>\n\n"
                f"Day {day}: <b>+{reward} points</b>\n"
                f"Total: <b>{fmt_points(result)}</b>"
            ),

            "zh": (
                "✅ <b>签到成功！</b>\n\n"
                f"第 {day} 天：<b>+{reward} 积分</b>\n"
                f"总计：<b>{fmt_points(result)}</b>"
            ),
        }

        msg = messages.get(
            language,
            messages["id"],
        )

    await call.message.edit_text(
        msg,
        parse_mode="HTML",
        reply_markup=menu_kb(language),
    )


# ============================================================
# BUY POINTS PAGE
# ============================================================

@router.callback_query(F.data == "points_buy")
async def points_buy(call: CallbackQuery):

    language = await lang(
        call.from_user.id
    )

    title = {
        "id": "💳 <b>BUY POIN</b>",
        "en": "💳 <b>BUY POINTS</b>",
        "zh": "💳 <b>购买积分</b>",
    }[language]

    desc = {
        "id": "Pilih paket poin yang kamu butuhkan.",
        "en": "Choose the points package you need.",
        "zh": "选择需要的积分套餐。",
    }[language]

    one = {
        "id": "1 poin = Rp1",
        "en": "1 point = Rp1",
        "zh": "1 积分 = Rp1",
    }[language]

    back = {
        "id": "⬅️ Kembali",
        "en": "⬅️ Back",
        "zh": "⬅️ 返回",
    }[language]

    unit = {
        "id": "Poin",
        "en": "Points",
        "zh": "积分",
    }[language]

    rows = []

    for points, amount in PACKAGES:

        price = f"Rp {amount:,}".replace(
            ",",
            ".",
        )

        point_display = f"{points:,}".replace(
            ",",
            ".",
        )

        rows.append(
            [
                InlineKeyboardButton(
                    text=(
                        f"⭐ {point_display} "
                        f"{unit} • {price}"
                    ),
                    callback_data=(
                        f"points_pkg:{points}"
                    ),
                )
            ]
        )

    rows.append(
        [
            InlineKeyboardButton(
                text=back,
                callback_data="points",
            )
        ]
    )

    await call.message.edit_text(
        f"{title}\n\n"
        f"{desc}\n\n"
        f"<b>{one}</b>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=rows
        ),
    )

    await call.answer()


# ============================================================
# SELECT POINT PACKAGE
# ============================================================

@router.callback_query(
    F.data.startswith("points_pkg:")
)
async def points_pkg(call: CallbackQuery):

    try:
        points = int(
            call.data.split(
                ":",
                1,
            )[1]
        )

    except (
        ValueError,
        IndexError,
    ):
        return await call.answer(
            "❌ Invalid package.",
            show_alert=True,
        )

    valid_packages = dict(PACKAGES)

    if points not in valid_packages:
        return await call.answer(
            "❌ Paket tidak valid.",
            show_alert=True,
        )

    # Semua pembelian poin masuk
    # ke payment flow utama.
    from handlers.pay import (
        create_points_payment,
    )

    price = valid_packages[points]
    return await create_points_payment(
        call,
        points,
        price,
    )


# ============================================================
# SETTLE POINT ORDER
# ============================================================

async def settle(order_id: str):

    pool = await get_pool()

    async with pool.acquire() as conn:

        async with conn.transaction():

            row = await conn.fetchrow(
                """
                SELECT *
                FROM point_orders
                WHERE order_id = $1
                FOR UPDATE
                """,
                order_id,
            )

            if not row:
                return False

            current_status = str(
                row["status"] or ""
            ).lower()

            if current_status == "paid":
                return True

            await conn.execute(
                """
                UPDATE point_orders
                SET
                    status = 'paid',
                    paid_at = NOW(),
                    updated_at = NOW()
                WHERE id = $1
                """,
                row["id"],
            )

            ref = (
                f'points_purchase:{row["id"]}'
            )

            balance = await conn.fetchval(
                """
                SELECT points
                FROM users
                WHERE user_id = $1
                FOR UPDATE
                """,
                row["user_id"],
            )

            if balance is None:
                logger.error(
                    "User %s tidak ditemukan "
                    "saat settle point order %s",
                    row["user_id"],
                    order_id,
                )
                return False

            new_balance = (
                balance + row["points"]
            )

            await conn.execute(
                """
                UPDATE users
                SET
                    points = $1,
                    updated_at = NOW()
                WHERE user_id = $2
                """,
                new_balance,
                row["user_id"],
            )

            await conn.execute(
                """
                INSERT INTO point_transactions(
                    user_id,
                    amount,
                    balance_after,
                    type,
                    reference,
                    description
                )
                VALUES(
                    $1,
                    $2,
                    $3,
                    'purchase',
                    $4,
                    $5
                )
                ON CONFLICT(reference)
                DO NOTHING
                """,
                row["user_id"],
                row["points"],
                new_balance,
                ref,
                f'Buy {row["points"]} points',
            )

            return True


# ============================================================
# CHECK POINT PAYMENT
#
# Routed centrally through handlers.pay
# ============================================================

async def points_check(call: CallbackQuery):
    try:
        await call.answer("⏳ Mengecek...")
    except Exception:
        pass
    try:
        order = call.data.split(":", 1)[1].strip()
    except (ValueError, IndexError):
        return await call.answer("❌ Order tidak valid.", show_alert=True)

    uid = int(call.from_user.id)
    pool = await get_pool()
    row = await pool.fetchrow(
        "SELECT * FROM point_orders WHERE order_id=$1 AND user_id=$2",
        order, uid,
    )
    if not row:
        return await call.message.answer("❌ Order tidak ditemukan.")

    status_local = str(row["status"] or "").lower()
    provider = str(row["provider"] or "cashi").lower()

    # Manual QR is never auto-approved. User reports payment -> admin verifies.
    if provider == "manual":
        if status_local == "paid":
            pts = await get_points(pool, uid)
            return await call.message.answer(
                f"✅ <b>Poin sudah ditambahkan.</b>\n\n⭐ Total: <b>{fmt_points(pts)}</b>", parse_mode="HTML"
            )
        if status_local == "verifying":
            return await call.answer("⏳ Sudah dikirim ke admin. Tunggu persetujuan.", show_alert=True)

        await pool.execute(
            "UPDATE point_orders SET status='verifying', updated_at=NOW() WHERE id=$1 AND status='pending'",
            row["id"],
        )
        kb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="✅ APPROVE", callback_data=f"pointapprove:{row['id']}"),
            InlineKeyboardButton(text="❌ REJECT", callback_data=f"pointreject:{row['id']}"),
        ]])
        admin_text = (
            "📥 <b>PEMBAYARAN POIN MANUAL</b>\n"
            "━━━━━━━━━━━━━━\n\n"
            f"👤 User: <code>{uid}</code>\n"
            f"⭐ Poin: <b>{fmt_points(row['points'])}</b>\n"
            f"💰 Nominal: <b>Rp {int(row['amount']):,}</b>\n"
            f"🧾 Order: <code>{order}</code>\n\n"
            "🔎 Cek pembayaran lalu pilih APPROVE atau REJECT."
        ).replace(",", ".")
        sent = 0
        for admin_id in ADMIN_IDS:
            try:
                await call.bot.send_message(admin_id, admin_text, parse_mode="HTML", reply_markup=kb)
                sent += 1
            except Exception:
                logger.exception("POINT MANUAL ADMIN NOTIFY ERROR admin=%s", admin_id)
        lang = "id"
        try:
            from utils.user_lang import get_user_language
            lang = await get_user_language(uid)
        except Exception:
            pass
        if sent:
            msg = {
                "id":"⏳ <b>Menunggu persetujuan admin.</b>\n\nPembayaran kamu sudah dilaporkan. Poin akan masuk setelah admin menyetujui.",
                "en":"⏳ <b>Waiting for admin approval.</b>\n\nYour payment has been reported. Points will be added after admin approval.",
                "zh":"⏳ <b>等待管理员审核。</b>\n\n付款已提交，管理员批准后积分会到账。",
            }[lang]
            return await call.message.answer(msg, parse_mode="HTML")
        return await call.message.answer("❌ Admin tidak dapat menerima notifikasi.")

    if status_local == "paid":
        pts = await get_points(pool, uid)
        return await call.message.answer(
            "✅ <b>Poin sudah ditambahkan.</b>\n\n" f"⭐ Total: <b>{fmt_points(pts)}</b>", parse_mode="HTML"
        )

    try:
        result = await (BayarGG.check_payment(order) if provider == "bayargg" else Cashi.check_payment(order))
    except Exception:
        logger.exception("POINT PAYMENT CHECK ERROR provider=%s order=%s", provider, order)
        return await call.answer("❌ Gagal mengecek pembayaran.", show_alert=True)

    remote = str((result or {}).get("status") or "").lower()
    if remote in {"paid","success","settled","completed","completed_payment","success_payment","settlement"}:
        success = await settle(order)
        if not success:
            return await call.message.answer("❌ Gagal menambahkan poin. Silakan coba lagi.")
        pts = await get_points(pool, uid)
        lang = "id"
        try:
            from utils.user_lang import get_user_language
            lang = await get_user_language(uid)
        except Exception:
            pass
        msg = {
            "id":f"🎉 <b>Pembelian poin berhasil!</b>\n\n⭐ +{fmt_points(row['points'])} poin\n⭐ Total: <b>{fmt_points(pts)}</b>\n\nPoin sudah ditambahkan ke akun kamu.",
            "en":f"🎉 <b>Point purchase successful!</b>\n\n⭐ +{fmt_points(row['points'])} points\n⭐ Total: <b>{fmt_points(pts)}</b>\n\nThe points have been added to your account.",
            "zh":f"🎉 <b>积分购买成功！</b>\n\n⭐ +{fmt_points(row['points'])} 积分\n⭐ 总计：<b>{fmt_points(pts)}</b>\n\n积分已添加到你的账户。",
        }[lang]
        try:
            await pool.execute(
                "INSERT INTO user_notifications(user_id,type,title,message) VALUES($1,'payment','Points Purchase',$2)",
                uid, msg,
            )
        except Exception:
            logger.exception("POINT USER NOTIFICATION INSERT ERROR")
        await send_payment_success_channel(
            call.bot, "points", uid, row.get("amount"), provider,
            f"{fmt_points(row['points'])} Points", order
        )
        return await call.message.answer(msg, parse_mode="HTML")

    return await call.answer("⏳ Belum terkonfirmasi.", show_alert=True)


@router.callback_query(F.data.startswith("pointapprove:"))
async def point_manual_approve(call: CallbackQuery):
    if call.from_user.id not in ADMIN_IDS:
        return await call.answer("❌ Bukan admin.", show_alert=True)
    await call.answer()
    try: oid=int(call.data.split(":",1)[1])
    except Exception: return await call.answer("❌ Order tidak valid.",show_alert=True)
    pool=await get_pool()
    row=await pool.fetchrow("SELECT * FROM point_orders WHERE id=$1 AND provider='manual' AND status='verifying'",oid)
    if not row: return await call.answer("❌ Order sudah diproses.",show_alert=True)
    ok=await settle(str(row["order_id"]))
    if not ok: return await call.answer("❌ Gagal menambahkan poin.",show_alert=True)
    pts=await get_points(pool,row["user_id"])
    lang="id"
    try:
        from utils.user_lang import get_user_language
        lang=await get_user_language(row["user_id"])
    except Exception: pass
    msg={
        "id":f"🎉 <b>Poin berhasil masuk!</b>\n\n⭐ +{fmt_points(row['points'])} poin\n⭐ Total: <b>{fmt_points(pts)}</b>\n\n💳 Pembayaran manual kamu telah disetujui admin.",
        "en":f"🎉 <b>Points added successfully!</b>\n\n⭐ +{fmt_points(row['points'])} points\n⭐ Total: <b>{fmt_points(pts)}</b>\n\n💳 Your manual payment was approved by admin.",
        "zh":f"🎉 <b>积分已到账！</b>\n\n⭐ +{fmt_points(row['points'])} 积分\n⭐ 总计：<b>{fmt_points(pts)}</b>\n\n💳 你的手动付款已获管理员批准。",
    }[lang]
    try:
        await pool.execute("INSERT INTO user_notifications(user_id,type,title,message) VALUES($1,'payment','Points Payment',$2)",row["user_id"],msg)
        await call.bot.send_message(row["user_id"],msg,parse_mode="HTML")
    except Exception: logger.exception("POINT APPROVE USER NOTIFY ERROR")
    await send_payment_success_channel(
        call.bot, "points", row["user_id"], row.get("amount"), "manual",
        f"{fmt_points(row['points'])} Points", str(row["order_id"])
    )
    await call.message.edit_text("✅ <b>PEMBAYARAN POIN DISETUJUI</b>\n\n"+f"👤 <code>{row['user_id']}</code>\n⭐ +{fmt_points(row['points'])} poin",parse_mode="HTML")


@router.callback_query(F.data.startswith("pointreject:"))
async def point_manual_reject(call: CallbackQuery):
    if call.from_user.id not in ADMIN_IDS:
        return await call.answer("❌ Bukan admin.", show_alert=True)
    await call.answer()
    try: oid=int(call.data.split(":",1)[1])
    except Exception: return
    pool=await get_pool()
    row=await pool.fetchrow("UPDATE point_orders SET status='rejected',updated_at=NOW() WHERE id=$1 AND provider='manual' AND status='verifying' RETURNING *",oid)
    if not row: return await call.answer("❌ Order sudah diproses.",show_alert=True)
    msg="❌ <b>Pembayaran poin ditolak admin.</b>\n\nSilakan periksa pembayaran kamu dan lakukan kembali jika diperlukan."
    try:
        await pool.execute("INSERT INTO user_notifications(user_id,type,title,message) VALUES($1,'payment','Points Payment Rejected',$2)",row["user_id"],msg)
        await call.bot.send_message(row["user_id"],msg,parse_mode="HTML")
    except Exception: logger.exception("POINT REJECT USER NOTIFY ERROR")
    await call.message.edit_text("❌ <b>PEMBAYARAN POIN DITOLAK</b>\n\n"+f"👤 <code>{row['user_id']}</code>\n⭐ {fmt_points(row['points'])} poin",parse_mode="HTML")
