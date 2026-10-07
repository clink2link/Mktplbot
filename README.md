# MEKTPL — Telegram Marketplace Bot

Project baru siap deploy untuk bot Telegram marketplace/media dengan:

- Force Subscribe hanya 2 channel.
- Feedback/loading pada callback agar UI tidak terasa freeze.
- Upload media diproses **satu per satu** ke storage channel.
- Open All dikirim **1 media setiap ±2 detik**.
- Maksimal 10 media per batch, lalu tombol **Lanjut Kirim** / **Stop Kirim**.
- Media code per item (`CODE-m001`, `CODE-m002`, dst.).
- Like, No Like, Favorit, Rating.
- Cari Code dan Marketplace.
- Dua QR otomatis: Cashi dan BayarGG.
- Webhook pembayaran dan proteksi idempotensi melalui database.
- Worker cleanup/payment/VIP.
- PostgreSQL/Supabase.
- Railway deployment.

> Catatan keamanan: tidak ada konfigurasi bot yang bisa menjamin Telegram tidak pernah memberikan rate limit. Project ini mengurangi burst traffic dan menangani `RetryAfter`; tetap patuhi aturan Telegram dan jangan melakukan spam.

## Struktur penting

```text
.
├── database.sql              # SATU SQL master yang dijalankan
├── .env.example              # template environment
├── railway.toml              # start command Railway
├── main.py                   # FastAPI + polling + webhook
├── bot.py
├── database.py
├── handlers/
├── keyboards/
├── middlewares/
├── services/
├── tasks/
├── utils/
└── docs/
    ├── TUTORIAL_LENGKAP_ID.md
    ├── DEPLOY_RAILWAY.md
    └── PAYMENT_SETUP.md
```

## Mulai cepat

1. Buat bot melalui BotFather dan salin `BOT_TOKEN`.
2. Buat PostgreSQL/Supabase database.
3. Buka SQL Editor dan jalankan **`database.sql` sekali**.
4. Buat storage channel dan jadikan bot admin.
5. Siapkan dua channel Force Subscribe dan jadikan bot admin agar dapat mengecek membership.
6. Isi `.env` berdasarkan `.env.example`.
7. Deploy folder project ini ke Railway.
8. Set webhook URL provider ke endpoint yang dijelaskan di `docs/PAYMENT_SETUP.md`.
9. Cek `/health`.
10. Test: `/start` → force join → dashboard → upload → get code → payment → open.

Untuk tutorial langkah demi langkah, buka `docs/TUTORIAL_LENGKAP_ID.md`.


## Loading UX
Semua inline callback memakai middleware loading global. `/start` dan tombol reply-keyboard memakai message loading middleware. Lihat `LOADING_UX_FULL.md`.
