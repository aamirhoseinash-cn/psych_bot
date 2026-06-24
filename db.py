"""
لایه دیتابیس بهینه‌شده
- کش در حافظه برای سرعت
- نوشتن async برای جلوگیری از blocking
- مدیریت خطا
"""

import os
import json
import asyncio
import logging
from pathlib import Path
from datetime import datetime
from typing import Any

log = logging.getLogger(__name__)

# مسیر از متغیر محیطی خوانده میشه — پیش‌فرض /data برای Volume
_data_dir = os.getenv("DATA_DIR", "/data")
DATA_FILE = Path(_data_dir) / "data.json"
_cache: dict = {}
_dirty = False
_lock = asyncio.Lock()
_save_task = None


def _load_from_disk() -> dict:
    if DATA_FILE.exists():
        try:
            return json.loads(DATA_FILE.read_text(encoding="utf-8"))
        except Exception as e:
            log.error(f"خطا در خواندن دیتابیس: {e}")
    return {"users": {}, "reports": {}}


def get_data() -> dict:
    """دریافت داده از کش"""
    global _cache
    if not _cache:
        _cache = _load_from_disk()
    return _cache


async def save_data_async():
    """ذخیره async — blocking نمی‌کند"""
    global _dirty, _cache
    if not _dirty:
        return
    async with _lock:
        try:
            DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
            content = json.dumps(_cache, ensure_ascii=False, indent=2)
            # نوشتن در thread pool تا event loop بلاک نشه
            await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: DATA_FILE.write_text(content, encoding="utf-8")
            )
            _dirty = False
            log.debug("💾 دیتابیس ذخیره شد")
        except Exception as e:
            log.error(f"خطا در ذخیره دیتابیس: {e}")


def mark_dirty():
    """علامت‌گذاری که داده تغییر کرده"""
    global _dirty
    _dirty = True


def save_data(data: dict = None):
    """ذخیره sync (برای سازگاری با کد قدیمی)"""
    global _cache, _dirty
    if data is not None:
        _cache = data
    _dirty = True
    # ذخیره فوری در پس‌زمینه
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            loop.create_task(save_data_async())
        else:
            DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
            DATA_FILE.write_text(
                json.dumps(_cache, ensure_ascii=False, indent=2),
                encoding="utf-8"
            )
            _dirty = False
    except Exception as e:
        log.error(f"خطا در save_data: {e}")


def load_data() -> dict:
    """دریافت داده (سازگار با کد قدیمی)"""
    return get_data()


async def periodic_save():
    """ذخیره دوره‌ای هر ۳۰ ثانیه"""
    while True:
        await asyncio.sleep(30)
        if _dirty:
            await save_data_async()


# ── توابع کمکی ──

def get_user(chat_id: str) -> dict | None:
    data = get_data()
    return data["users"].get(chat_id)


def set_user_field(chat_id: str, field: str, value: Any):
    data = get_data()
    if chat_id in data["users"]:
        data["users"][chat_id][field] = value
        mark_dirty()


def get_report(report_id: str) -> dict | None:
    data = get_data()
    return data["reports"].get(report_id)


def save_report(report_id: str, report: dict):
    data = get_data()
    data["reports"][report_id] = report
    # نگه داشتن فقط ۵۰۰ گزارش آخر برای جلوگیری از بزرگ شدن فایل
    if len(data["reports"]) > 500:
        sorted_ids = sorted(
            data["reports"].keys(),
            key=lambda x: data["reports"][x].get("date", ""),
        )
        for old_id in sorted_ids[:-500]:
            del data["reports"][old_id]
    mark_dirty()


def get_user_reports(chat_id: str, limit: int = 10) -> list[dict]:
    data = get_data()
    user_reports = [
        r for r in data["reports"].values()
        if r.get("chat_id") == chat_id
    ]
    return sorted(user_reports, key=lambda x: x.get("date", ""), reverse=True)[:limit]


def count_today_reports() -> int:
    data = get_data()
    today = datetime.now().strftime("%Y-%m-%d")
    return sum(1 for r in data["reports"].values() if r.get("date", "")[:10] == today)
