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
from google.genai import types
import httpx
from apscheduler.schedulers.asyncio import AsyncIOScheduler

# ─────────────────────────────────────────
# تنظیمات (از فایل .env خوانده می‌شوند)
# ─────────────────────────────────────────
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "YOUR_BOT_TOKEN")
TELEGRAM_CHAT_ID   = os.getenv("TELEGRAM_CHAT_ID",   "YOUR_CHAT_ID")
GEMINI_API_KEY     = os.getenv("GEMINI_API_KEY",      "YOUR_GEMINI_KEY")
# ساعت ارسال — فقط عدد خالص میگیریم (مثلاً 8، نه "8 AM")
_send_hour_raw = os.getenv("SEND_HOUR", "8").strip().split()[0]  # "8 AM" → "8"
SEND_HOUR = int(_send_hour_raw)
TIMEZONE           = os.getenv("TIMEZONE", "Asia/Tehran")

# ─────────────────────────────────────────
# لاگ‌گذاری
# ─────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("bot.log", encoding="utf-8"),
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

    prompt = f"""
You are an expert science communicator specializing in psychology.
Write a bilingual (Persian + English) daily psychology insight post about:
**"{topic}"**

Structure EXACTLY as follows (use emojis):

---
🧠 **روانشناسی امروز | Today's Psychology**
📅 {datetime.now().strftime("%Y/%m/%d")}
---

📌 **موضوع | Topic:**
[Topic name in Persian and English]

---
🔬 **دستاورد علمی | Scientific Achievement:**
[3-4 sentences in Persian explaining the key finding/theory, its background and importance]

[2-3 sentences in English summarizing the same]

---
⚡ **نقد و بررسی | Critical Analysis:**
[3-4 sentences in Persian about the main criticisms, controversies or limitations]

[2-3 sentences in English about the same criticisms]

---
💡 **کاربرد روزمره | Practical Application:**
[2-3 sentences in Persian on how to apply this in daily life]

[1-2 sentences in English]

---
📚 **منابع پیشنهادی | Suggested Reading:**
- [Book/Paper 1 – Author]
- [Book/Paper 2 – Author]

---
🔎 **آیا می‌دانستید؟ | Did You Know?**
[One surprising fact related to the topic – bilingual one sentence each]

---
#روانشناسی #علم #Psychology #Science #CriticalThinking
"""

    response = client.models.generate_content(
        model="gemini-2.0-flash",
        contents=prompt,
    )
    return response.text


# ─────────────────────────────────────────
# ارسال پیام به تلگرام
# ─────────────────────────────────────────
async def send_telegram_message(text: str) -> bool:
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    
    # تلگرام حداکثر 4096 کاراکتر در هر پیام می‌پذیرد
    chunks = [text[i:i+4000] for i in range(0, len(text), 4000)]
    
    async with httpx.AsyncClient(timeout=30) as client:
        for chunk in chunks:
            payload = {
                "chat_id": TELEGRAM_CHAT_ID,
                "text": chunk,
                "parse_mode": "Markdown",
            }
            try:
                resp = await client.post(url, json=payload)
                resp.raise_for_status()
                log.info(f"✅ پیام ارسال شد ({len(chunk)} کاراکتر)")
                await asyncio.sleep(1)  # جلوگیری از rate-limit
            except httpx.HTTPStatusError as e:
                # اگر Markdown خطا داشت، بدون فرمت ارسال کن
                log.warning(f"⚠️ خطای Markdown، بدون فرمت ارسال می‌شود: {e}")
                payload["parse_mode"] = None
                resp = await client.post(url, json=payload)
                resp.raise_for_status()
    
    return True


# ─────────────────────────────────────────
# وظیفه اصلی روزانه
# ─────────────────────────────────────────
async def daily_job():
    log.info("🚀 شروع وظیفه روزانه...")
    
    # انتخاب موضوع (چرخشی بر اساس روز سال)
    day_of_year = datetime.now().timetuple().tm_yday
    topic = TOPIC_POOL[day_of_year % len(TOPIC_POOL)]
    log.info(f"📌 موضوع امروز: {topic}")
    
    try:
        # تولید محتوا
        log.info("⏳ در حال تولید محتوا با Gemini...")
        content = generate_psychology_content(topic)
        log.info("✅ محتوا با موفقیت تولید شد")
        
        # ارسال به تلگرام
        await send_telegram_message(content)
        log.info("🎉 وظیفه روزانه با موفقیت انجام شد!")
        
    except Exception as e:
        log.error(f"❌ خطا در وظیفه روزانه: {e}")
        # ارسال پیام خطا به تلگرام
        try:
            await send_telegram_message(
                f"⚠️ خطا در ربات روانشناسی:\n`{str(e)}`\n\nلطفاً لاگ را بررسی کنید."
            )
        except Exception:
            pass


# ─────────────────────────────────────────
# ارسال فوری (برای تست)
# ─────────────────────────────────────────
async def send_test_message():
    log.info("🧪 ارسال پیام تست...")
    topic = random.choice(TOPIC_POOL)
    await daily_job.__wrapped__(topic) if hasattr(daily_job, '__wrapped__') else await daily_job()


# ─────────────────────────────────────────
# اجرای اصلی
# ─────────────────────────────────────────
async def main():
    log.info(f"🤖 ربات روانشناسی شروع به کار کرد | ارسال روزانه ساعت {SEND_HOUR}:00")
    
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
    
    # ارسال فوری یک پیام تست هنگام شروع
    log.info("📤 ارسال پیام خوش‌آمدگویی...")
    welcome = (
        "🧠 *ربات روانشناسی فعال شد!*\n\n"
        f"✅ هر روز ساعت *{SEND_HOUR}:00* محتوای روانشناسی دوزبانه دریافت می‌کنید.\n"
        "🔬 شامل: دستاوردهای علمی + نقد نظریه‌ها\n\n"
        "_اولین گزارش کامل را فردا صبح دریافت خواهید کرد..._"
    )
    await send_telegram_message(welcome)
    
    # حلقه اصلی
    try:
        while True:
            await asyncio.sleep(60)
    except (KeyboardInterrupt, SystemExit):
        log.info("🛑 ربات متوقف شد")
        scheduler.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
