from aiogram import Router, F
from aiogram.types import Message, CallbackQuery

router = Router()


@router.message(F.text.in_({"🏪 Store","Store"}))
async def store_menu(message: Message):
    from handlers.store import store_open
    await store_open(message)


@router.message(F.text.in_({"🏆 Top 10 Code","Top 10 Code"}))
async def top_menu(message: Message):
    from handlers.top import top_open
    await top_open(message)


@router.message(F.text.in_({"👤 Akun","👤 Account"}))
async def account_menu(message: Message):
    from handlers.account import account_open
    await account_open(message)


@router.message(F.text=="💎 Upgrade")
async def upgrade_menu(message: Message):
    from handlers.vvip import vvip_open
    await vvip_open(message)
