"""
نقطه شروع ربات - بارگذاری .env و اجرا
"""
from dotenv import load_dotenv
load_dotenv()  # بارگذاری متغیرهای محیطی از .env

import asyncio
import sys
from bot import main, daily_job

if __name__ == "__main__":
    # اگر آرگومان "test" داده شد، یک پیام فوری ارسال کن
    if len(sys.argv) > 1 and sys.argv[1] == "test":
        print("🧪 حالت تست: یک پیام فوری ارسال می‌شود...")
        asyncio.run(daily_job())
    else:
        asyncio.run(main())
