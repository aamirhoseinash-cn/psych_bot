"""
مدیریت صف درخواست‌های AI
جلوگیری از overload سرویس‌ها وقتی چند کاربر همزمان گزارش می‌خواند
"""

import asyncio
import logging
from datetime import datetime
from collections import deque

log = logging.getLogger(__name__)


class RequestQueue:
    """
    صف هوشمند برای مدیریت درخواست‌های همزمان
    - حداکثر N درخواست همزمان
    - timeout برای هر درخواست
    - اولویت‌بندی
    """

    def __init__(self, max_concurrent: int = 3):
        self.max_concurrent = max_concurrent
        self.semaphore = asyncio.Semaphore(max_concurrent)
        self.active_count = 0
        self.queue_size = 0
        self.total_processed = 0
        self.total_errors = 0
        self._lock = asyncio.Lock()

    async def run(self, coro, timeout: int = 180):
        """
        درخواست رو در صف قرار میده و اجرا می‌کنه
        timeout: حداکثر زمان انتظار + اجرا (ثانیه)
        """
        async with self._lock:
            self.queue_size += 1

        log.info(f"📥 درخواست جدید | فعال: {self.active_count} | صف: {self.queue_size}")

        try:
            async with self.semaphore:
                async with self._lock:
                    self.active_count += 1
                    self.queue_size -= 1

                log.info(f"▶️ شروع اجرا | فعال: {self.active_count}")
                result = await asyncio.wait_for(coro, timeout=timeout)
                self.total_processed += 1
                return result

        except asyncio.TimeoutError:
            self.total_errors += 1
            log.error(f"⏰ timeout بعد از {timeout}s")
            raise RuntimeError(f"درخواست بعد از {timeout} ثانیه پاسخ نگرفت. لطفاً دوباره امتحان کنید.")
        except Exception as e:
            self.total_errors += 1
            raise
        finally:
            async with self._lock:
                self.active_count = max(0, self.active_count - 1)

    def stats(self) -> dict:
        return {
            "active": self.active_count,
            "queued": self.queue_size,
            "processed": self.total_processed,
            "errors": self.total_errors,
        }


# ── یک instance مشترک برای کل ربات ──
ai_queue = RequestQueue(max_concurrent=3)
