"""
🧠 Psychology Daily Bot
روزانه دستاوردها و نقدهای علم روانشناسی را به تلگرام ارسال می‌کند
"""

import os
import asyncio
import logging
import random
from datetime import datetime
from google import genai
import httpx
from apscheduler.schedulers.asyncio import AsyncIOScheduler

# ─────────────────────────────────────────
# تنظیمات
# ─────────────────────────────────────────
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID   = os.getenv("TELEGRAM_CHAT_ID",   "").strip()
GEMINI_API_KEY     = os.getenv("GEMINI_API_KEY",      "").strip()
_send_hour_raw     = os.getenv("SEND_HOUR", "8").strip().split()[0]
SEND_HOUR          = int(_send_hour_raw)
TIMEZONE           = os.getenv("TIMEZONE", "Asia/Tehran").strip()
# اگه این متغیر روی "1" باشه، هنگام استارت فوری یه گزارش می‌فرسته
SEND_NOW           = os.getenv("SEND_NOW", "0").strip()

# ─────────────────────────────────────────
# لاگ‌گذاری
# ─────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler()
    ]
)
log = logging.getLogger(__name__)

# ─────────────────────────────────────────
# موضوعات چرخشی
# ─────────────────────────────────────────
TOPIC_POOL = [
    "شناخت‌درمانی (CBT) و شواهد علمی جدید",
    "روان‌شناسی مثبت‌گرا و نقدهای آن",
    "نظریه دلبستگی بالبی و تحقیقات نوین",
    "اثر دارونما و بحث‌های اخیر",
    "تروما و عصب‌شناسی PTSD",
    "نظریه هوش‌های چندگانه گاردنر",
    "روان‌شناسی رفتاری سکینر و انتقادها",
    "بحران تکرارپذیری (Replication Crisis) در روان‌شناسی",
    "نظریه ذهن (Theory of Mind) و اوتیسم",
    "اثر هاله‌ای و سوگیری‌های شناختی",
    "روان‌شناسی اجتماعی: آزمایش میلگرام",
    "نوروپلاستیسیتی مغز در بزرگسالی",
    "درمان EMDR برای تروما",
    "نظریه انگیزش ذاتی دسی و ریان",
    "روان‌شناسی رشد: پیاژه در مقابل ویگوتسکی",
    "اثر دانینگ-کروگر و انتقادهای جدید",
    "روان‌شناسی تکاملی و محدودیت‌هایش",
    "ذهن‌آگاهی (Mindfulness) و پشتوانه علمی آن",
    "نظریه احساسات سازنده لیزا فلدمن بارت",
    "نقش ژنتیک و محیط در شخصیت",
]


# ─────────────────────────────────────────
# تولید محتوا با Gemini
# ─────────────────────────────────────────
def generate_psychology_content(topic: str) -> str:
    client = genai.Client(api_key=GEMINI_API_KEY)

    prompt = f"""You are an expert science communicator specializing in psychology.
Write a bilingual (Persian + English) daily psychology insight post about:
"{topic}"

Structure EXACTLY as follows:

🧠 روانشناسی امروز | Today's Psychology
📅 {datetime.now().strftime("%Y/%m/%d")}

📌 موضوع | Topic:
[Topic name in Persian and English]

🔬 دستاورد علمی | Scientific Achievement:
[3-4 sentences in Persian explaining the key finding/theory]

[2-3 sentences in English summarizing the same]

⚡ نقد و بررسی | Critical Analysis:
[3-4 sentences in Persian about the main criticisms or limitations]

[2-3 sentences in English about the same criticisms]

💡 کاربرد روزمره | Practical Application:
[2-3 sentences in Persian on how to apply this in daily life]

[1-2 sentences in English]

📚 منابع پیشنهادی | Suggested Reading:
- [Book/Paper 1 - Author]
- [Book/Paper 2 - Author]

🔎 آیا می‌دانستید؟ | Did You Know?
[One surprising bilingual fact]

#روانشناسی #علم #Psychology #Science #CriticalThinking
"""

    response = client.models.generate_content(
        model="gemini-1.5-flash",
        contents=prompt,
    )
    return response.text


# ─────────────────────────────────────────
# ارسال پیام به تلگرام
# ─────────────────────────────────────────
async def send_telegram_message(text: str) -> bool:
    # پاک کردن کاراکترهای مشکل‌ساز Markdown برای تلگرام
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"

    chunks = [text[i:i+4000] for i in range(0, len(text), 4000)]

    async with httpx.AsyncClient(timeout=60) as client:
        for chunk in chunks:
            # اول بدون parse_mode امتحان می‌کنیم - ساده‌ترین و مطمئن‌ترین روش
            payload = {
                "chat_id": TELEGRAM_CHAT_ID,
                "text": chunk,
            }
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
            log.info(f"✅ پیام ارسال شد ({len(chunk)} کاراکتر)")
            await asyncio.sleep(1)

    return True


# ─────────────────────────────────────────
# وظیفه اصلی روزانه
# ─────────────────────────────────────────
async def daily_job():
    log.info("🚀 شروع وظیفه روزانه...")

    day_of_year = datetime.now().timetuple().tm_yday
    topic = TOPIC_POOL[day_of_year % len(TOPIC_POOL)]
    log.info(f"📌 موضوع امروز: {topic}")

    try:
        log.info("⏳ در حال تولید محتوا با Gemini...")
        content = generate_psychology_content(topic)
        log.info("✅ محتوا تولید شد")

        await send_telegram_message(content)
        log.info("🎉 گزارش با موفقیت ارسال شد!")

    except Exception as e:
        log.error(f"❌ خطا: {e}")
        try:
            await send_telegram_message(f"خطا در ربات روانشناسی:\n{str(e)}")
        except Exception:
            pass


# ─────────────────────────────────────────
# اجرای اصلی
# ─────────────────────────────────────────
async def main():
    log.info(f"🤖 ربات شروع به کار کرد | ارسال روزانه ساعت {SEND_HOUR}:00")

    # اگه SEND_NOW=1 باشه، همین الان یه گزارش بفرست
    if SEND_NOW == "1":
        log.info("📤 SEND_NOW=1 — ارسال فوری گزارش...")
        await daily_job()
    else:
        log.info("⏰ منتظر زمان برنامه‌ریزی‌شده...")
        await send_telegram_message(
            f"ربات روانشناسی فعال شد!\n\n"
            f"هر روز ساعت {SEND_HOUR}:00 گزارش دریافت می‌کنید.\n"
            f"برای گرفتن گزارش فوری، SEND_NOW را روی 1 بگذار."
        )

    scheduler = AsyncIOScheduler(timezone=TIMEZONE)
    scheduler.add_job(
        daily_job,
        trigger="cron",
        hour=SEND_HOUR,
        minute=0,
        id="daily_psychology",
        replace_existing=True,
    )
    scheduler.start()

    try:
        while True:
            await asyncio.sleep(60)
    except (KeyboardInterrupt, SystemExit):
        log.info("🛑 ربات متوقف شد")
        scheduler.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
