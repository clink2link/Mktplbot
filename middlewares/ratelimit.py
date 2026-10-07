import time
from collections import defaultdict, deque
from aiogram import BaseMiddleware
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.types import Message, CallbackQuery
class RateLimitMiddleware(BaseMiddleware):
    """
    Lightweight per-user rate limiter.
    Tujuan:
    - Mencegah spam callback/message.
    - Tidak mengganggu typing normal.
    - Tidak melakukan database query.
    - Tidak menyebabkan callback Telegram timeout.
    - Aman terhadap callback yang sudah expired.
    Default:
        interval = 0.35 detik
        burst    = 8 event dalam window 2 detik
    """
    def __init__(
        self,
        interval: float = 0.35,
        burst: int = 8,
        window: float = 2.0,
    ):
        self.interval = max(0.05, float(interval))
        self.burst = max(1, int(burst))
        self.window = max(0.5, float(window))
        # Last accepted event per user.
        self.last: dict[int, float] = {}
        # Recent events per user.
        self.events: dict[int, deque] = defaultdict(deque)
        # Last cleanup timestamp.
        self._last_cleanup = time.monotonic()
    # ========================================================================
    # CALLBACK ACK
    # ========================================================================
    async def _answer_callback(
        self,
        event: CallbackQuery,
        text: str | None = None,
        show_alert: bool = False,
    ):
        """
        Safely answer Telegram callback query.
        CallbackQuery harus di-ACK secepat mungkin.
        """
        try:
            return await event.answer(
                text=text,
                show_alert=show_alert,
            )
        except TelegramBadRequest as e:
            error_text = str(e).lower()
            # Callback sudah expired / invalid.
            if (
                "query is too old" in error_text
                or "query id is invalid" in error_text
                or "response timeout expired" in error_text
            ):
                return None
            # Callback sudah dijawab sebelumnya.
            if (
                "query is too old" in error_text
                or "query id is invalid" in error_text
            ):
                return None
            return None
        except TelegramForbiddenError:
            return None
        except Exception:
            return None
    # ========================================================================
    # CLEANUP
    # ========================================================================
    def _cleanup(self, now: float):
        """
        Remove inactive users from memory periodically.
        Prevents self.events / self.last from growing forever.
        """
        # Cleanup every 60 seconds.
        if now - self._last_cleanup < 60:
            return
        self._last_cleanup = now
        inactive_users = []
        for user_id, queue in self.events.items():
            # Remove expired events first.
            while queue and now - queue[0] > self.window:
                queue.popleft()
            last = self.last.get(user_id, 0.0)
            if not queue and now - last > 120:
                inactive_users.append(user_id)
        for user_id in inactive_users:
            self.events.pop(user_id, None)
            self.last.pop(user_id, None)
    # ========================================================================
    # MIDDLEWARE
    # ========================================================================
    async def __call__(self, handler, event, data):
        # --------------------------------------------------------------------
        # GET USER ID
        # --------------------------------------------------------------------
        user = getattr(event, "from_user", None)
        if not user:
            return await handler(event, data)
        user_id = getattr(user, "id", None)
        if not user:
            return await handler(event, data)
        now = time.monotonic()
        # Periodic memory cleanup.
        self._cleanup(now)
        # --------------------------------------------------------------------
        # USER EVENT HISTORY
        # --------------------------------------------------------------------
        q = self.events[user_id]
        # Remove events outside the sliding window.
        while q and now - q[0] > self.window:
            q.popleft()
        last = self.last.get(user_id, 0.0)
        # --------------------------------------------------------------------
        # RATE LIMIT
        # --------------------------------------------------------------------
        #
        # We only block when:
        #
        # 1. User is sending events faster than interval
        # 2. AND burst limit has already been reached.
        #
        # This keeps normal usage comfortable while stopping heavy spam.
        #
        too_fast = (
            last > 0
            and now - last < self.interval
        )
        burst_exceeded = (
            len(q) >= self.burst
        )
        if too_fast and burst_exceeded:
            # ---------------------------------------------------------------
            # CALLBACK
            # ---------------------------------------------------------------
            if isinstance(event, CallbackQuery):
                await self._answer_callback(
                    event,
                    "⏳ Terlalu cepat. Tunggu sebentar lalu coba lagi.",
                    show_alert=False,
                )
            # ---------------------------------------------------------------
            # MESSAGE
            # ---------------------------------------------------------------
            elif isinstance(event, Message):
                try:
                    await event.answer(
                        "⏳ Terlalu cepat. Tunggu sebentar lalu coba lagi."
                    )
                except (
                    TelegramBadRequest,
                    TelegramForbiddenError,
                ):
                    pass
                except Exception:
                    pass
            return None
        # --------------------------------------------------------------------
        # REGISTER EVENT
        # --------------------------------------------------------------------
        self.last[user_id] = now
        q.append(now)
        # --------------------------------------------------------------------
        # CONTINUE
        # --------------------------------------------------------------------
        try:
            return await handler(event, data)
        except TelegramBadRequest:
            # Do not let a Telegram callback/message error from this
            # middleware crash the dispatcher.
            raise
        except Exception:
            # Handler exceptions should normally be handled by the global
            # error middleware / dispatcher.
            raise
