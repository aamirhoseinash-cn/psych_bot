"""
🧠 Psychology Daily Bot — Gemini Edition
"""

import os
import asyncio
import logging
from datetime import datetime
import httpx
from apscheduler.schedulers.asyncio import AsyncIOScheduler

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID   = os.getenv("TELEGRAM_CHAT_ID",   "").strip()
GEMINI_API_KEY     = os.getenv("GEMINI_API_KEY",      "").strip()
SEND_HOUR          = int(os.getenv("SEND_HOUR", "8").strip().split()[0])
TIMEZONE           = os.getenv("TIMEZONE", "Asia/Tehran").strip()
SEND_NOW           = os.getenv("SEND_NOW", "0").strip()

# مدل‌های Gemini رایگان — به ترتیب اولویت
MODELS = [
    "gemini-2.5-flash-lite",
    "gemini-2.5-flash",
    "gemini-2.0-flash",
]

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(message)s",
                    handlers=[logging.StreamHandler()])
log = logging.getLogger(__name__)

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


async def generate_content(topic: str) -> str:
    prompt = f"""You are an expert science communicator specializing in psychology.
Write a bilingual (Persian + English) daily psychology insight post about:
"{topic}"

Structure EXACTLY as follows:

🧠 روانشناسی امروز | Today's Psychology
📅 {datetime.now().strftime("%Y/%m/%d")}

📌 موضوع | Topic:
[نام موضوع به فارسی و انگلیسی]

🔬 دستاورد علمی | Scientific Achievement:
[3-4 جمله فارسی درباره یافته‌های کلیدی، پیشینه و اهمیت آن]

[2-3 English sentences summarizing the same]

⚡ نقد و بررسی | Critical Analysis:
[3-4 جمله فارسی درباره انتقادات اصلی، بحث‌ها یا محدودیت‌ها]

[2-3 English sentences about the same criticisms]

💡 کاربرد روزمره | Practical Application:
[2-3 جمله فارسی درباره کاربرد در زندگی روزمره]

[1-2 English sentences]

📚 منابع پیشنهادی | Suggested Reading:
- [کتاب یا مقاله ۱ - نویسنده]
- [کتاب یا مقاله ۲ - نویسنده]

🔎 آیا می‌دانستید؟ | Did You Know?
[یک واقعیت جالب دوزبانه]

#روانشناسی #علم #Psychology #Science #CriticalThinking"""

    errors = []
    async with httpx.AsyncClient(timeout=60) as client:
        for model in MODELS:
            try:
                log.info(f"⏳ امتحان مدل: {model}")
                url = (
                    f"https://generativelanguage.googleapis.com/v1beta/models/"
                    f"{model}:generateContent?key={GEMINI_API_KEY}"
                )
                payload = {
                    "contents": [{"parts": [{"text": prompt}]}],
                    "generationConfig": {"maxOutputTokens": 1500, "temperature": 0.7},
                }
                resp = await client.post(url, json=payload)
                resp.raise_for_status()
                data = resp.json()
                content = data["candidates"][0]["content"]["parts"][0]["text"]
                log.info(f"✅ محتوا با مدل {model} تولید شد")
                return content

            except httpx.HTTPStatusError as e:
                err = f"مدل {model}: {e.response.status_code} — {e.response.text[:300]}"
                log.warning(f"⚠️ {err}")
                errors.append(err)
                await asyncio.sleep(3)
            except Exception as e:
                err = f"مدل {model}: {type(e).__name__}: {str(e)[:200]}"
                log.warning(f"⚠️ {err}")
                errors.append(err)
                await asyncio.sleep(3)

    raise RuntimeError("همه مدل‌ها خطا دادند:\n" + "\n".join(errors))


async def send_telegram_message(text: str) -> bool:
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    chunks = [text[i:i+4000] for i in range(0, len(text), 4000)]
    async with httpx.AsyncClient(timeout=30) as client:
        for chunk in chunks:
            resp = await client.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": chunk})
            resp.raise_for_status()
            log.info(f"✅ پیام ارسال شد ({len(chunk)} کاراکتر)")
            await asyncio.sleep(1)
    return True


async def daily_job():
    log.info("🚀 شروع وظیفه روزانه...")
    day_of_year = datetime.now().timetuple().tm_yday
    topic = TOPIC_POOL[day_of_year % len(TOPIC_POOL)]
    log.info(f"📌 موضوع امروز: {topic}")
    try:
        content = await generate_content(topic)
        await send_telegram_message(content)
        log.info("🎉 ارسال شد!")
    except Exception as e:
        log.error(f"❌ خطا: {e}")
        try:
            await send_telegram_message(f"خطا:\n{str(e)}")
        except Exception:
            pass


async def main():
    log.info(f"🤖 ربات شروع | ارسال روزانه ساعت {SEND_HOUR}:00")
    if SEND_NOW == "1":
        await daily_job()
    else:
        await send_telegram_message(
            f"ربات روانشناسی فعال شد!\nهر روز ساعت {SEND_HOUR}:00 گزارش می‌رسد.\nموتور: Gemini"
        )
    scheduler = AsyncIOScheduler(timezone=TIMEZONE)
    scheduler.add_job(daily_job, trigger="cron", hour=SEND_HOUR, minute=0,
                      id="daily_psychology", replace_existing=True)
    scheduler.start()
    try:
        while True:
            await asyncio.sleep(60)
    except (KeyboardInterrupt, SystemExit):
        scheduler.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
