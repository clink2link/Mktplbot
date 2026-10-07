from aiogram import Router

from .dashboard import router as dashboard_router
from .users import router as users_router
from .files import router as files_router
from .payments import router as payments_router
from .withdraw import router as withdraw_router
from .balance import router as balance_router
from .broadcast import router as broadcast_router
from .settings import router as settings_router
from .logs import router as logs_router
from .admins import router as admins_router

router = Router()

router.include_router(dashboard_router)
router.include_router(users_router)
router.include_router(files_router)
router.include_router(payments_router)
router.include_router(withdraw_router)
router.include_router(balance_router)
router.include_router(broadcast_router)
router.include_router(settings_router)
router.include_router(logs_router)
router.include_router(admins_router)
