from aiogram import Router, types
from aiogram.filters import Command

from utils.user import get_user_data, save_user_data
import time

router = Router()


@router.message(Command("testvip"))
async def testvip(message: types.Message):

    user_id = message.from_user.id

    # 🔥 ambil data SEKALI
    data = await get_user_data(user_id)

    # 🔥 set VIP
    data["level"] = "vip"
    data["expired_at"] = int(time.time()) + 86400

    # 🔥 tambah quota
    data["paid_quota"] = data.get("paid_quota", 0) + 2

    # 🔥 simpan SEKALI (ini kunci utama)
    await save_user_data(user_id, data)

    await message.answer(
        f"✅ VIP aktif!\n📦 Quota: {data['paid_quota']}"
    )
