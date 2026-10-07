from aiogram import Bot, Dispatcher
from aiogram.exceptions import TelegramBadRequest
import logging
from aiogram.client.default import DefaultBotProperties
from config import BOT_TOKEN
from middlewares.ban import BanMiddleware
from middlewares.maintenance import MaintenanceMiddleware
from middlewares.ratelimit import RateLimitMiddleware
from middlewares.loading import CallbackLoadingMiddleware
from middlewares.message_loading import MessageLoadingMiddleware
from utils.telegram_safe import install_telegram_edit_guards
# Install before routers are imported so every direct aiogram edit call is protected.
install_telegram_edit_guards()

# ============================================================
# BOT INIT
# ============================================================
bot = Bot(
    token=BOT_TOKEN,
    default=DefaultBotProperties(
        parse_mode="HTML"
    )
)
dp = Dispatcher()

# ============================================================
# GLOBAL TELEGRAM ERROR HANDLING
# ============================================================
# Telegram returns this error when code tries to edit a message
# with exactly the same text and inline keyboard. This is a benign
# race condition (often caused by double-clicks / concurrent workers),
# so do not let it bubble up as an unhandled update exception.
@dp.errors()
async def telegram_error_handler(event):
    exception = event.exception

    if isinstance(exception, TelegramBadRequest) and "message is not modified" in str(exception).lower():
        logging.debug("Telegram ignored duplicate message edit: %s", exception)
        return True

    # Let other errors keep their normal aiogram behaviour/logging.
    return False
# ============================================================
# MIDDLEWARE
# ============================================================
# IMPORTANT: loading is registered FIRST so Telegram receives the
# callback ACK before maintenance/ban/rate-limit/database work.
dp.callback_query.middleware(
    CallbackLoadingMiddleware()
)
dp.message.middleware(
    MessageLoadingMiddleware()
)

dp.message.middleware(
    BanMiddleware()
)
dp.callback_query.middleware(
    BanMiddleware()
)
dp.message.middleware(
    MaintenanceMiddleware()
)
dp.callback_query.middleware(
    MaintenanceMiddleware()
)
# Conservative anti-spam guard
dp.callback_query.middleware(
    RateLimitMiddleware()
)
# ============================================================
# ROUTERS IMPORT
# ============================================================
# BASIC
from handlers.start import router as start_router
from handlers.check_sub import router as check_sub_router
from handlers.page import router as page_router
from handlers.open_menu import router as open_menu_router
from handlers.sendall import router as sendall_router
from handlers.menu import router as menu_router
# FILE SYSTEM
from handlers.upfile import router as upfile_router
from handlers.getfile_showjs import router as getfile_showjs_router
from handlers.getfile import router as getfile_router
from handlers.review_code import router as review_code_router
from handlers.getreview import router as getreview_router
# STORE
from handlers.top import router as top_router
from handlers.code import router as code_router
# SEARCH
from handlers.channel import router as channel_router
from handlers.search_code import router as search_router
from handlers.price_code import router as price_router
from handlers.new_code import router as new_code_router
from handlers.category_code import router as category_router
# ACCOUNT
from handlers.account import router as account_router
from handlers.points import router as points_router
from handlers.vip import router as vip_router
from handlers.my_code import router as my_code_router
from handlers.help import router as help_router
from handlers.myfile import router as myfile_router
from handlers.delete_file import router as delete_file_router
from handlers.edit_price import router as edit_price_router
from handlers.ewallet import router as ewallet_router
# PAYMENT
from handlers.pay import router as pay_router
from handlers.cancel import router as cancel_router
from handlers.qrid import router as qrid_router
# CASHI PAYMENT
from handlers.cashi import router as cashi_router
from handlers.bayargg_payment import router as bayargg_payment_router
# WITHDRAW
from handlers.withdraw import (
    withdraw_router,
    withdraw_confirm_router,
)
# CREATOR
from handlers.creator import router as creator_router
# ADMIN
from handlers.admin import router as admin_router
# MARKET FEATURES
from handlers.favorite import router as favorite_router
from handlers.rating import router as rating_router
from handlers.review import router as review_router
from handlers.free_code import router as free_code_router
from handlers.market_all import router as market_all_router
from handlers.market_purchase import router as market_purchase_router
# MARKETPLACE
from handlers.marketplace import router as marketplace_router
from handlers.market_detail import router as market_detail_router
from handlers.market_rating import router as market_rating_router
from handlers.market_favorite import router as market_favorite_router
from handlers.market_reaction import router as market_reaction_router
# NOTIFICATION
from handlers.notify import router as notify_router
# ============================================================
# REGISTER ROUTERS
# ============================================================
# ------------------------------------------------------------
# BASIC
# ------------------------------------------------------------
dp.include_router(start_router)
dp.include_router(check_sub_router)
dp.include_router(menu_router)
# ------------------------------------------------------------
# FILE SYSTEM
# ------------------------------------------------------------
dp.include_router(upfile_router)
# Review codes must be handled before the global Get File text handler.
dp.include_router(review_code_router)
dp.include_router(getfile_showjs_router)
dp.include_router(getfile_router)
dp.include_router(getreview_router)
dp.include_router(page_router)
dp.include_router(open_menu_router)
dp.include_router(sendall_router)
# ------------------------------------------------------------
# STORE
# ------------------------------------------------------------
dp.include_router(top_router)
dp.include_router(code_router)
# ------------------------------------------------------------
# SEARCH
# ------------------------------------------------------------
dp.include_router(channel_router)
dp.include_router(search_router)
dp.include_router(price_router)
dp.include_router(category_router)
dp.include_router(new_code_router)
# ------------------------------------------------------------
# ACCOUNT
# ------------------------------------------------------------
dp.include_router(account_router)
dp.include_router(points_router)
# Account -> 💎 VIP -> callback_data="vvip"
dp.include_router(vip_router)
dp.include_router(my_code_router)
dp.include_router(help_router)
dp.include_router(myfile_router)
dp.include_router(delete_file_router)
dp.include_router(edit_price_router)
dp.include_router(ewallet_router)
# ------------------------------------------------------------
# PAYMENT
# ------------------------------------------------------------
dp.include_router(pay_router)
# CASHI
# Semua callback payment Cashi ditangani oleh handlers.cashi
dp.include_router(cashi_router)
dp.include_router(bayargg_payment_router)
dp.include_router(cancel_router)
dp.include_router(qrid_router)
# ------------------------------------------------------------
# WITHDRAW
# ------------------------------------------------------------
dp.include_router(withdraw_router)
dp.include_router(withdraw_confirm_router)
# ------------------------------------------------------------
# ADMIN
# ------------------------------------------------------------
dp.include_router(admin_router)
# ------------------------------------------------------------
# CREATOR
# ------------------------------------------------------------
dp.include_router(creator_router)
# ------------------------------------------------------------
# MARKET FEATURES
# ------------------------------------------------------------
dp.include_router(favorite_router)
dp.include_router(rating_router)
dp.include_router(review_router)
dp.include_router(free_code_router)
dp.include_router(market_all_router)
dp.include_router(market_purchase_router)
# ------------------------------------------------------------
# MARKETPLACE
# ------------------------------------------------------------
dp.include_router(marketplace_router)
dp.include_router(market_detail_router)
dp.include_router(market_rating_router)
dp.include_router(market_favorite_router)
dp.include_router(market_reaction_router)
# ------------------------------------------------------------
# NOTIFICATION
# ------------------------------------------------------------
dp.include_router(notify_router)
