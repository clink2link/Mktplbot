from aiogram import Router
from config import ADMIN_IDS

router = Router()


# =========================
# CHECK ADMIN
# =========================
def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS
