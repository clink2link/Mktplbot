from aiogram import Router, F
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from database import get_pool


router = Router()


# ============================================================
# KEYBOARD HELPER
# ============================================================

def kb(rows):
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=text,
                    callback_data=data,
                )
                for text, data in row
            ]
            for row in rows
        ]
    )


# ============================================================
# LANGUAGE
# ============================================================

async def lang_of(user_id: int) -> str:
    pool = await get_pool()

    language = await pool.fetchval(
        """
        SELECT language
        FROM users
        WHERE user_id = $1
        """,
        user_id,
    )

    language = language or "id"

    if language not in {"id", "en", "zh"}:
        language = "id"

    return language


# ============================================================
# HELP MENU
# ============================================================

@router.callback_query(F.data == "help")
async def help_menu(call: CallbackQuery):

    language = await lang_of(
        call.from_user.id
    )

    # ========================================================
    # INDONESIAN
    # ========================================================

    if language == "id":

        text = (
            "❓ <b>PUSAT BANTUAN</b>\n"
            "━━━━━━━━━━━━━━━━━━\n\n"

            "<b>Apa itu bot ini?</b>\n"
            "Marketplace Telegram untuk upload, menyimpan, "
            "membagikan, membeli, dan menjual code/media "
            "dengan cara yang mudah dipahami.\n\n"

            "<b>Apa yang bisa dilakukan?</b>\n"
            "📤 Upload & buat code\n"
            "🛍 Cari dan beli code\n"
            "💰 Jual code sendiri\n"
            "🎁 Dapatkan akses gratis dari progres pembelian nyata\n"
            "⭐ Like, dislike, rating, dan review\n"
            "❤️ Simpan favorit\n"
            "👤 Kelola akun dan saldo\n"
            "💎 Upgrade VIP/VVIP\n"
            "🤝 Undang teman lewat referral\n\n"

            "Pilih panduan di bawah."
        )

        rows = [
            [
                ("📤 Upload & Jual", "help_upload"),
                ("🛍 Beli Code", "help_buy"),
            ],
            [
                ("🎁 Buka Gratis 3/3", "help_free"),
                ("⭐ Like / Rating / Review", "help_reaction"),
            ],
            [
                ("💰 Cuan & Referral", "help_earn"),
                ("💎 VIP / VVIP", "help_vip"),
            ],
            [
                ("🔐 Keamanan & Batasan", "help_safety"),
            ],
            [
                ("🌐 Bahasa", "change_language"),
            ],
            [
                ("🏠 Home", "home"),
            ],
        ]

    # ========================================================
    # ENGLISH
    # ========================================================

    elif language == "en":

        text = (
            "❓ <b>HELP CENTER</b>\n"
            "━━━━━━━━━━━━━━━━━━\n\n"

            "<b>What is this bot?</b>\n"
            "A Telegram marketplace to upload, store, share, "
            "buy and sell Telegram codes/media safely and conveniently.\n\n"

            "<b>What can you do?</b>\n"
            "📤 Upload & create a code\n"
            "🛍 Browse and buy codes\n"
            "💰 Sell your own code\n"
            "🎁 Earn free unlock progress from real purchases\n"
            "⭐ Rate, like/dislike and review media\n"
            "❤️ Save favorites\n"
            "👤 Manage your account and balance\n"
            "💎 Upgrade VIP/VVIP\n"
            "🤝 Invite friends with referral\n\n"

            "Choose a guide below."
        )

        rows = [
            [
                ("📤 Upload & Sell", "help_upload"),
                ("🛍 Buy Code", "help_buy"),
            ],
            [
                ("🎁 Free Unlock 3/3", "help_free"),
                ("⭐ Like / Rating / Review", "help_reaction"),
            ],
            [
                ("💰 Earnings & Referral", "help_earn"),
                ("💎 VIP / VVIP", "help_vip"),
            ],
            [
                ("🔐 Safety & Limits", "help_safety"),
            ],
            [
                ("🌐 Language", "change_language"),
            ],
            [
                ("🏠 Home", "home"),
            ],
        ]

    # ========================================================
    # CHINESE
    # ========================================================

    else:

        text = (
            "❓ <b>帮助中心</b>\n"
            "━━━━━━━━━━━━━━━━━━\n\n"

            "<b>这个机器人是什么？</b>\n"
            "这是一个 Telegram Marketplace，"
            "可以上传、保存、分享、购买和出售 Code / 媒体，"
            "让文件交易更加方便。\n\n"

            "<b>你可以做什么？</b>\n"
            "📤 上传并创建 Code\n"
            "🛍 浏览和购买 Code\n"
            "💰 出售自己的 Code\n"
            "🎁 通过真实购买获得免费解锁进度\n"
            "⭐ 点赞、点踩、评分和评论\n"
            "❤️ 收藏喜欢的内容\n"
            "👤 管理账户和余额\n"
            "💎 升级 VIP / VVIP\n"
            "🤝 通过邀请链接邀请朋友\n\n"

            "请选择下面的帮助指南。"
        )

        rows = [
            [
                ("📤 上传 & 出售", "help_upload"),
                ("🛍 购买 Code", "help_buy"),
            ],
            [
                ("🎁 免费解锁 3/3", "help_free"),
                ("⭐ 点赞 / 评分 / 评论", "help_reaction"),
            ],
            [
                ("💰 收益 & 邀请", "help_earn"),
                ("💎 VIP / VVIP", "help_vip"),
            ],
            [
                ("🔐 安全 & 限制", "help_safety"),
            ],
            [
                ("🌐 语言", "change_language"),
            ],
            [
                ("🏠 首页", "home"),
            ],
        ]

    await call.message.edit_text(
        text,
        parse_mode="HTML",
        reply_markup=kb(rows),
    )

    await call.answer()


# ============================================================
# GUIDES
# ============================================================

GUIDES = {

    # ========================================================
    # INDONESIAN
    # ========================================================

    "id": {

        "help_upload": (
            "📤 <b>UPLOAD & JUAL CODE</b>\n"
            "━━━━━━━━━━━━━━━━━━\n\n"

            "1️⃣ Tekan <b>Upload File</b>.\n"
            "2️⃣ Kirim media yang ingin disimpan.\n"
            "3️⃣ Tekan <b>STOP & SAVE</b> setelah selesai.\n"
            "4️⃣ Isi judul, kategori, deskripsi, dan tipe FREE/PAID.\n"
            "5️⃣ Jika PAID, tentukan harga sesuai ketentuan bot.\n"
            "6️⃣ Bot membuat <b>CODE</b> otomatis.\n\n"

            "<b>Keuntungan seller:</b>\n"
            "Code bisa dipromosikan di marketplace. "
            "Pembeli dapat membuka media setelah pembayaran berhasil. "
            "Seller juga dapat melihat statistik seperti view, "
            "like, dislike, rating, review, dan penjualan.\n\n"

            "💡 Gunakan judul dan deskripsi yang jujur serta jelas "
            "agar calon pembeli memahami isi code."
        ),

        "help_buy": (
            "🛍 <b>CARA BELI CODE</b>\n"
            "━━━━━━━━━━━━━━━━━━\n\n"

            "1️⃣ Buka Marketplace.\n"
            "2️⃣ Pilih code yang menarik.\n"
            "3️⃣ Periksa harga, jumlah media, terjual, "
            "like/dislike, rating, dan review.\n"
            "4️⃣ Tekan <b>Beli</b>.\n"
            "5️⃣ Selesaikan pembayaran.\n"
            "6️⃣ Setelah pembayaran terkonfirmasi, "
            "akses media diberikan.\n\n"

            "Jika QR otomatis bermasalah, gunakan metode "
            "atau QR manual yang disediakan bot."
        ),

        "help_free": (
            "🎁 <b>BUKA CODE GRATIS — PROGRESS 3/3</b>\n"
            "━━━━━━━━━━━━━━━━━━\n\n"

            "Fitur ini membantu seller mendapatkan pembeli "
            "melalui promosi code.\n\n"

            "📈 Ada <b>3 progress</b>. "
            "Kamu membagikan code terlebih dahulu. "
            "Progress bertambah <b>hanya ketika ada pembelian "
            "yang benar-benar berhasil</b>, bukan hanya karena "
            "tombol share ditekan.\n\n"

            "1/3 → 1 pembelian\n"
            "2/3 → 2 pembelian\n"
            "3/3 → 3 pembelian\n\n"

            "Setelah 3/3, code yang kamu promosikan dapat "
            "dibuka sesuai sistem unlock gratis.\n\n"

            "Sistem mencatat progres berdasarkan user dan code."
        ),

        "help_reaction": (
            "⭐ <b>LIKE, DISLIKE, RATING & REVIEW</b>\n"
            "━━━━━━━━━━━━━━━━━━\n\n"

            "Saat membuka detail media, kamu dapat memilih "
            "👍 Suka atau 👎 Tidak suka.\n\n"

            "Satu user hanya memiliki satu reaksi aktif "
            "dan dapat menggantinya.\n\n"

            "⭐ <b>Rating</b> membantu menunjukkan kualitas "
            "berdasarkan penilaian pengguna.\n\n"

            "💬 <b>Review</b> digunakan untuk menulis pengalaman "
            "atau masukan. Review dapat diperbarui oleh pemiliknya.\n\n"

            "Marketplace menggunakan data tersebut untuk "
            "membantu pengguna menemukan code yang populer "
            "dan memiliki reputasi baik."
        ),

        "help_earn": (
            "💰 <b>CUAN & REFERRAL</b>\n"
            "━━━━━━━━━━━━━━━━━━\n\n"

            "💵 <b>Penjualan:</b> seller mendapatkan pendapatan "
            "sesuai aturan komisi bot.\n\n"

            "🤝 <b>Referral:</b> bagikan link referral pribadi. "
            "Jika user baru masuk melalui link tersebut dan "
            "memenuhi syarat sistem, referral akan tercatat "
            "dan reward diberikan sesuai program aktif.\n\n"

            "Gunakan tombol <b>Bagikan Referral</b> agar link "
            "mudah dikirim melalui Telegram.\n\n"

            "⚠️ Hindari spam dan kirim hanya kepada orang "
            "yang memang ingin menggunakan bot."
        ),

        "help_vip": (
            "💎 <b>VIP / VVIP</b>\n"
            "━━━━━━━━━━━━━━━━━━\n\n"

            "VIP/VVIP memberikan akses premium sesuai paket aktif.\n\n"

            "Pembayaran menggunakan <b>QR Manual</b>. "
            "Setelah membayar, tekan <b>Saya Sudah Bayar</b>.\n\n"

            "Admin akan menerima notifikasi untuk memeriksa pembayaran.\n\n"

            "✅ APPROVE → paket aktif dan user menerima notifikasi.\n"
            "❌ FAILED → admin wajib memberikan alasan, "
            "misalnya pembayaran belum lunas, nominal tidak sesuai, "
            "atau pembayaran belum masuk."
        ),

        "help_safety": (
            "🔐 <b>KEAMANAN & PENGGUNAAN AMAN</b>\n"
            "━━━━━━━━━━━━━━━━━━\n\n"

            "Bot menerapkan pembatasan dan pemrosesan bertahap "
            "untuk mengurangi spam, duplikasi transaksi, "
            "dan beban Telegram.\n\n"

            "⚠️ Tidak ada bot yang dapat menjamin 100% bebas "
            "dari banned atau flood karena keputusan akhir "
            "tetap berada pada Telegram.\n\n"

            "Agar aman:\n"
            "• Jangan spam command/callback.\n"
            "• Jangan broadcast tanpa izin.\n"
            "• Jangan upload konten ilegal atau melanggar hak cipta.\n"
            "• Jangan memanipulasi pembayaran, like, rating, "
            "review, atau referral.\n"
            "• Gunakan tombol resmi bot dan tunggu proses selesai."
        ),
    },


    # ========================================================
    # ENGLISH
    # ========================================================

    "en": {

        "help_upload": (
            "📤 <b>UPLOAD & SELL CODE</b>\n"
            "━━━━━━━━━━━━━━━━━━\n\n"

            "1️⃣ Tap <b>Upload File</b>.\n"
            "2️⃣ Send the media you want to store.\n"
            "3️⃣ Press <b>STOP & SAVE</b> when finished.\n"
            "4️⃣ Set title, category, description and FREE/PAID type.\n"
            "5️⃣ For PAID, set the allowed price.\n"
            "6️⃣ The bot creates a unique <b>CODE</b>.\n\n"

            "<b>Seller benefits:</b>\n"
            "Promote your code in the marketplace and track "
            "views, likes, dislikes, ratings, reviews and sales.\n\n"

            "Buyers receive media access after successful payment."
        ),

        "help_buy": (
            "🛍 <b>HOW TO BUY A CODE</b>\n"
            "━━━━━━━━━━━━━━━━━━\n\n"

            "1️⃣ Open Marketplace.\n"
            "2️⃣ Choose a code.\n"
            "3️⃣ Check price, media count, sales, "
            "likes/dislikes, rating and reviews.\n"
            "4️⃣ Tap <b>Buy</b>.\n"
            "5️⃣ Complete payment.\n"
            "6️⃣ After confirmation, media access is delivered.\n\n"

            "If automatic QR fails, use the manual QR/payment "
            "option shown by the bot."
        ),

        "help_free": (
            "🎁 <b>FREE CODE UNLOCK — PROGRESS 3/3</b>\n"
            "━━━━━━━━━━━━━━━━━━\n\n"

            "Share the code first to help the seller get real buyers.\n\n"

            "Progress increases <b>only after a real successful "
            "purchase</b>, not simply because the share button "
            "was pressed.\n\n"

            "1/3 → 1 purchase\n"
            "2/3 → 2 purchases\n"
            "3/3 → 3 purchases\n\n"

            "At 3/3, the promoted code can be opened according "
            "to the free unlock system.\n\n"

            "Progress is tracked per user and per code."
        ),

        "help_reaction": (
            "⭐ <b>LIKE, DISLIKE, RATING & REVIEW</b>\n"
            "━━━━━━━━━━━━━━━━━━\n\n"

            "On a media detail page you can choose "
            "👍 Like or 👎 Dislike.\n\n"

            "One user has one active reaction and can change it.\n\n"

            "⭐ <b>Rating</b> reflects user scoring.\n"
            "💬 <b>Review</b> lets users leave useful feedback "
            "and update their own review.\n\n"

            "Marketplace statistics use these signals to "
            "highlight popular and well-reviewed codes."
        ),

        "help_earn": (
            "💰 <b>EARNINGS & REFERRAL</b>\n"
            "━━━━━━━━━━━━━━━━━━\n\n"

            "💵 <b>Sales:</b> sellers receive earnings according "
            "to the active commission rules.\n\n"

            "🤝 <b>Referral:</b> share your personal referral link. "
            "Eligible new users are recorded and rewards are "
            "issued according to the active referral program.\n\n"

            "Use <b>Share Referral</b> and avoid unsolicited spam."
        ),

        "help_vip": (
            "💎 <b>VIP / VVIP</b>\n"
            "━━━━━━━━━━━━━━━━━━\n\n"

            "VIP/VVIP provides premium access according "
            "to the active plan.\n\n"

            "Payment uses <b>Manual QR</b>. "
            "After paying, tap <b>I Have Paid</b>.\n\n"

            "Admin receives a verification request.\n\n"

            "✅ APPROVE → the plan is activated and the user is notified.\n"
            "❌ FAILED → admin must enter a reason, such as "
            "incomplete payment, wrong amount, or payment not received."
        ),

        "help_safety": (
            "🔐 <b>SAFETY & USAGE</b>\n"
            "━━━━━━━━━━━━━━━━━━\n\n"

            "The bot uses throttling and step-by-step processing "
            "to reduce spam, duplicate transactions and excessive "
            "Telegram API load.\n\n"

            "⚠️ No bot can guarantee 100% protection from "
            "Telegram restrictions.\n\n"

            "For safer use:\n"
            "• Do not spam commands or callbacks.\n"
            "• Do not broadcast without permission.\n"
            "• Do not upload illegal/copyright-infringing content.\n"
            "• Do not manipulate payments, likes, ratings, reviews or referrals.\n"
            "• Use official buttons and wait for the process to finish."
        ),
    },


    # ========================================================
    # CHINESE
    # ========================================================

    "zh": {

        "help_upload": (
            "📤 <b>上传 & 出售 CODE</b>\n"
            "━━━━━━━━━━━━━━━━━━\n\n"

            "1️⃣ 点击 <b>上传文件</b>。\n"
            "2️⃣ 发送你想保存的媒体。\n"
            "3️⃣ 完成后点击 <b>STOP & SAVE</b>。\n"
            "4️⃣ 填写标题、分类、描述以及 FREE / PAID 类型。\n"
            "5️⃣ 如果选择 PAID，请设置符合机器人规则的价格。\n"
            "6️⃣ 机器人会自动创建唯一的 <b>CODE</b>。\n\n"

            "<b>卖家可以获得：</b>\n"
            "Code 可以在 Marketplace 中推广。"
            "买家付款成功后即可获得媒体访问权限。\n\n"

            "卖家还可以查看浏览量、点赞、点踩、评分、评论和销售数据。\n\n"

            "💡 建议使用真实、清晰的标题和描述，"
            "让买家更容易了解 Code 的内容。"
        ),

        "help_buy": (
            "🛍 <b>如何购买 CODE</b>\n"
            "━━━━━━━━━━━━━━━━━━\n\n"

            "1️⃣ 打开 Marketplace。\n"
            "2️⃣ 选择你感兴趣的 Code。\n"
            "3️⃣ 查看价格、媒体数量、销售量、"
            "点赞/点踩、评分和评论。\n"
            "4️⃣ 点击 <b>购买</b>。\n"
            "5️⃣ 完成付款。\n"
            "6️⃣ 付款确认后即可获得媒体访问权限。\n\n"

            "如果自动 QR 支付出现问题，"
            "可以使用机器人提供的手动 QR / 支付方式。"
        ),

        "help_free": (
            "🎁 <b>免费解锁 CODE — 进度 3/3</b>\n"
            "━━━━━━━━━━━━━━━━━━\n\n"

            "这个功能用于帮助卖家通过推广 Code 获得真实买家。\n\n"

            "📈 一共有 <b>3 个进度</b>。"
            "你需要先分享 Code。\n\n"

            "进度只有在产生<b>真实且成功的购买</b>后才会增加，"
            "仅点击分享按钮不会增加进度。\n\n"

            "1/3 → 1 次购买\n"
            "2/3 → 2 次购买\n"
            "3/3 → 3 次购买\n\n"

            "达到 3/3 后，你推广的 Code 可以按照免费解锁规则打开。\n\n"

            "系统会分别记录每个用户和每个 Code 的进度。"
        ),

        "help_reaction": (
            "⭐ <b>点赞、点踩、评分 & 评论</b>\n"
            "━━━━━━━━━━━━━━━━━━\n\n"

            "查看媒体详情时，可以选择：\n"
            "👍 喜欢\n"
            "👎 不喜欢\n\n"

            "每个用户对一个内容只有一个有效反应，"
            "之后可以修改自己的选择。\n\n"

            "⭐ <b>评分</b> 用于反映用户对内容质量的评价。\n\n"

            "💬 <b>评论</b> 可以用于分享体验和建议，"
            "用户可以修改自己的评论。\n\n"

            "Marketplace 会使用这些数据帮助用户发现"
            "更受欢迎、评分更高的 Code。"
        ),

        "help_earn": (
            "💰 <b>收益 & 邀请</b>\n"
            "━━━━━━━━━━━━━━━━━━\n\n"

            "💵 <b>销售：</b>卖家按照机器人当前的佣金规则获得收益。\n\n"

            "🤝 <b>邀请：</b>分享你的个人邀请链接。"
            "如果新用户通过你的链接进入并满足系统条件，"
            "邀请关系会被记录，并按照当前活动规则发放奖励。\n\n"

            "使用 <b>分享邀请</b> 可以方便地将链接发送到 Telegram。\n\n"

            "⚠️ 请勿进行骚扰或垃圾信息推广。"
        ),

        "help_vip": (
            "💎 <b>VIP / VVIP</b>\n"
            "━━━━━━━━━━━━━━━━━━\n\n"

            "VIP / VVIP 根据当前套餐提供高级功能和权限。\n\n"

            "付款使用 <b>手动 QR</b>。\n"
            "付款后点击 <b>我已付款</b>。\n\n"

            "管理员会收到付款审核通知。\n\n"

            "✅ APPROVE → 套餐激活，并向用户发送通知。\n"
            "❌ FAILED → 管理员必须填写失败原因，"
            "例如金额不足、金额错误或尚未收到付款。\n\n"

            "失败原因会发送给用户，方便用户了解下一步操作。"
        ),

        "help_safety": (
            "🔐 <b>安全 & 使用规则</b>\n"
            "━━━━━━━━━━━━━━━━━━\n\n"

            "机器人使用限流和分阶段处理，"
            "减少垃圾请求、重复交易以及 Telegram API 的负载。\n\n"

            "⚠️ 没有任何机器人可以保证 100% 不会受到 "
            "Telegram 的限制或封禁。\n\n"

            "为了安全使用：\n"
            "• 不要重复快速点击按钮或发送命令。\n"
            "• 不要在未经允许的情况下进行广播。\n"
            "• 不要上传违法或侵犯版权的内容。\n"
            "• 不要操纵付款、点赞、评分、评论或邀请数据。\n"
            "• 使用机器人官方按钮，并等待当前操作完成后再重试。"
        ),
    },
}


# ============================================================
# GUIDE HANDLER
# ============================================================

@router.callback_query(
    F.data.in_(
        [
            "help_upload",
            "help_buy",
            "help_free",
            "help_reaction",
            "help_earn",
            "help_vip",
            "help_safety",
        ]
    )
)
async def guide(call: CallbackQuery):

    language = await lang_of(
        call.from_user.id
    )

    # Safety fallback jika bahasa user belum valid.
    if language not in GUIDES:
        language = "id"

    # Ambil guide sesuai bahasa.
    text = GUIDES[language].get(
        call.data
    )

    # Jika guide belum tersedia, fallback Indonesia.
    if not text:
        text = GUIDES["id"].get(
            call.data,
            "❌ Panduan tidak ditemukan.",
        )

    back_labels = {
        "id": "⬅️ Kembali",
        "en": "⬅️ Back",
        "zh": "⬅️ 返回",
    }

    home_labels = {
        "id": "🏠 Home",
        "en": "🏠 Home",
        "zh": "🏠 首页",
    }

    await call.message.edit_text(
        text,
        parse_mode="HTML",
        reply_markup=kb(
            [
                [
                    (
                        back_labels[language],
                        "help",
                    )
                ],
                [
                    (
                        home_labels[language],
                        "home",
                    )
                ],
            ]
        ),
    )

    await call.answer()
