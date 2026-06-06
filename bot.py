"""
🧠 Psychology Daily Bot
روزانه دستاوردها و نقدهای علم روانشناسی را به تلگرام ارسال می‌کند
از OpenRouter با مدل‌های رایگان قوی استفاده می‌کند
"""

import os
import asyncio
import logging
from datetime import datetime
import httpx
from apscheduler.schedulers.asyncio import AsyncIOScheduler

# ─────────────────────────────────────────
# تنظیمات
# ─────────────────────────────────────────
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID   = os.getenv("TELEGRAM_CHAT_ID",   "").strip()
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY",  "").strip()
SEND_HOUR          = int(os.getenv("SEND_HOUR", "8").strip().split()[0])
TIMEZONE           = os.getenv("TIMEZONE", "Asia/Tehran").strip()
SEND_NOW           = os.getenv("SEND_NOW", "0").strip()

# مدل اصلی + مدل‌های جایگزین (اگه یکی خطا داد بعدی امتحان میشه)
MODELS = [
    "deepseek/deepseek-r1:free",                      # قوی‌ترین — استدلال علمی عالی
    "deepseek/deepseek-chat-v3-0324:free",            # جایگزین اول — سریع و قوی
    "qwen/qwen3-235b-a22b:free",                      # جایگزین دوم — بسیار قوی
    "google/gemma-3-27b-it:free",                     # جایگزین سوم
    "mistralai/mistral-small-3.1-24b-instruct:free",  # جایگزین چهارم
]

# ─────────────────────────────────────────
# لاگ‌گذاری
# ─────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler()]
)
log = logging.getLogger(__name__)

# ─────────────────────────────────────────
# موضوعات چرخشی (۲۰ موضوع)
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
# تولید محتوا با OpenRouter (با fallback خودکار)
# ─────────────────────────────────────────
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
- [کتاب/مقاله ۱ - نویسنده]
- [کتاب/مقاله ۲ - نویسنده]

🔎 آیا می‌دانستید؟ | Did You Know?
[یک واقعیت جالب دوزبانه]

#روانشناسی #علم #Psychology #Science #CriticalThinking"""

    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com/psych-bot",
        "X-Title": "Psychology Daily Bot",
    }

    errors = []
    async with httpx.AsyncClient(timeout=60) as client:
        for model in MODELS:
            try:
                log.info(f"⏳ امتحان مدل: {model}")
                payload = {
                    "model": model,
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": 1500,
                }
                resp = await client.post(
                    "https://openrouter.ai/api/v1/chat/completions",
                    headers=headers,
                    json=payload,
                )
                resp.raise_for_status()
                data = resp.json()
                content = data["choices"][0]["message"]["content"]
                log.info(f"✅ محتوا با مدل {model} تولید شد")
                return content

            except Exception as e:
                err_msg = f"مدل {model} خطا: {e}"
                log.warning(f"⚠️ {err_msg}")
                errors.append(err_msg)
                await asyncio.sleep(2)

    raise RuntimeError("همه مدل‌ها خطا دادند:\n" + "\n".join(errors))


# ─────────────────────────────────────────
# ارسال پیام به تلگرام
# ─────────────────────────────────────────
async def send_telegram_message(text: str) -> bool:
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    chunks = [text[i:i+4000] for i in range(0, len(text), 4000)]

    async with httpx.AsyncClient(timeout=30) as client:
        for chunk in chunks:
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
        content = await generate_content(topic)
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

    if SEND_NOW == "1":
        log.info("📤 SEND_NOW=1 — ارسال فوری گزارش...")
        await daily_job()
    else:
        await send_telegram_message(
            f"ربات روانشناسی فعال شد!\n\n"
            f"هر روز ساعت {SEND_HOUR}:00 گزارش دریافت می‌کنید.\n"
            f"موتور: OpenRouter (DeepSeek R1)"
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
