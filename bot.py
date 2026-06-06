"""
🧠 Psychology Daily Bot — Scientific Edition
محتوا بر اساس مقالات معتبر علمی، قابل فهم برای عموم
دارای دستور /report برای گزارش فوری از داخل تلگرام
"""

import os
import asyncio
import logging
import random
from datetime import datetime
import httpx
from apscheduler.schedulers.asyncio import AsyncIOScheduler

# ─────────────────────────────────────────
# تنظیمات
# ─────────────────────────────────────────
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID   = os.getenv("TELEGRAM_CHAT_ID",   "").strip()
GEMINI_API_KEY     = os.getenv("GEMINI_API_KEY",      "").strip()
SEND_HOUR          = int(os.getenv("SEND_HOUR", "8").strip().split()[0])
TIMEZONE           = os.getenv("TIMEZONE", "Asia/Tehran").strip()
SEND_NOW           = os.getenv("SEND_NOW", "0").strip()
# رمز مخفی برای گرفتن گزارش فوری از داخل تلگرام
REPORT_PASSWORD    = os.getenv("REPORT_PASSWORD", "psych123").strip()

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


# ─────────────────────────────────────────
# تولید محتوا با Gemini — پرامپت علمی
# ─────────────────────────────────────────
async def generate_content(topic: str) -> str:
    prompt = f"""You are a neuroscientist and clinical psychologist who writes for the general public.
Your job is to summarize the REAL scientific literature on a topic — as if explaining to a curious, intelligent person with no psychology background.

Write a bilingual (Persian + English) report about: "{topic}"

CRITICAL RULES:
1. Base your content on REAL, peer-reviewed papers (cite actual study authors, journals, years)
2. Explain every technical term in simple language the moment you use it
3. Write like a specialist talking to a smart friend — precise but never confusing
4. Be honest about what science knows vs. what is still debated
5. The Persian sections are PRIMARY — write them first, full, and rich
6. English sections are concise summaries of the same content

Use EXACTLY this structure:

━━━━━━━━━━━━━━━━━━━━━━━━
🧠 روانشناسی امروز | Today's Psychology
📅 {datetime.now().strftime("%Y/%m/%d")}
━━━━━━━━━━━━━━━━━━━━━━━━

📌 موضوع امروز:
{topic}

📌 Today's Topic:
[English name]

━━━━━━━━━━━━━━━━━━━━━━━━
🔬 یافته‌های علمی | Scientific Findings
━━━━━━━━━━━━━━━━━━━━━━━━

[فارسی — ۴ تا ۵ پاراگراف کوتاه]
• با ذکر نام محقق، سال، و مجله معتبر (مثل Nature, JAMA, Psychological Science)
• هر اصطلاح فنی را بلافاصله توضیح بده (مثال: "کورتیزول — هورمون استرس بدن")
• داده‌های عددی واقعی بیاور (مثال: "در مطالعه‌ای با ۲۰۰ شرکت‌کننده...")
• روایت داستانی داشته باش — چطور این کشف اتفاق افتاد؟

[English — 3 concise paragraphs summarizing the above with citations]

━━━━━━━━━━━━━━━━━━━━━━━━
⚡ نقد علمی | Critical Analysis
━━━━━━━━━━━━━━━━━━━━━━━━

[فارسی — ۳ تا ۴ پاراگراف]
• چه انتقادات جدی از محققان دیگر وجود دارد؟
• کدام مطالعات نتایج متناقض داشتند؟
• محدودیت‌های روش‌شناختی (methodology) چیست؟
• آیا بحران تکرارپذیری (replication crisis) این حوزه را تحت تأثیر گذاشته؟

[English — 2 paragraphs with specific critical studies mentioned]

━━━━━━━━━━━━━━━━━━━━━━━━
💡 از آزمایشگاه تا زندگی | From Lab to Life
━━━━━━━━━━━━━━━━━━━━━━━━

[فارسی — این بخش مهم‌ترین بخش است]
توضیح بده که این یافته‌های علمی چطور در زندگی روزمره معنا پیدا می‌کنند.
• یک مثال ملموس و واقعی از زندگی روزمره بده
• دقیقاً چه کاری می‌توان کرد — نه کلیشه، بلکه بر اساس همان مکانیسم علمی که توضیح دادی
• چه اشتباهی مردم معمولاً می‌کنند که علم خلاف آن را نشان می‌دهد؟

[English — 2 practical paragraphs grounded in the same science]

━━━━━━━━━━━━━━━━━━━━━━━━
📚 منابع کلیدی | Key References
━━━━━━━━━━━━━━━━━━━━━━━━

[فقط مقالات و کتاب‌های علمی واقعی — نه کتاب‌های عامه‌پسند]
• نام کامل مقاله — نویسنده(گان) — مجله — سال
• نام کامل مقاله — نویسنده(گان) — مجله — سال
• نام کامل مقاله — نویسنده(گان) — مجله — سال

━━━━━━━━━━━━━━━━━━━━━━━━
🔎 جمله‌ای که ارزش دارد بدانید
━━━━━━━━━━━━━━━━━━━━━━━━

[یک یافته شگفت‌انگیز و واقعی از تحقیقات که اکثر مردم نمی‌دانند — دوزبانه]

#روانشناسی_علمی #نوروساینس #Psychology #Neuroscience #CriticalThinking"""

    errors = []
    async with httpx.AsyncClient(timeout=90) as client:
        for model in MODELS:
            try:
                log.info(f"⏳ امتحان مدل: {model}")
                url = (
                    f"https://generativelanguage.googleapis.com/v1beta/models/"
                    f"{model}:generateContent?key={GEMINI_API_KEY}"
                )
                payload = {
                    "contents": [{"parts": [{"text": prompt}]}],
                    "generationConfig": {
                        "maxOutputTokens": 2500,
                        "temperature": 0.4,  # دقت بیشتر، خلاقیت کمتر
                    },
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


# ─────────────────────────────────────────
# ارسال پیام به تلگرام
# ─────────────────────────────────────────
async def send_telegram_message(text: str, chat_id: str = None) -> bool:
    target = chat_id or TELEGRAM_CHAT_ID
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    
    # تقسیم هوشمند — بر اساس خط جدید، نه وسط جمله
    def smart_split(t: str, limit: int = 3800) -> list:
        if len(t) <= limit:
            return [t]
        parts = []
        while len(t) > limit:
            # پیدا کردن آخرین خط جدید قبل از limit
            cut = t.rfind("\n", 0, limit)
            if cut == -1:
                cut = limit
            parts.append(t[:cut])
            t = t[cut:].lstrip("\n")
        if t:
            parts.append(t)
        return parts

    chunks = smart_split(text)
    log.info(f"📨 ارسال در {len(chunks)} پیام...")
    
    async with httpx.AsyncClient(timeout=30) as client:
        for i, chunk in enumerate(chunks, 1):
            # اگه چند پیام هست، شماره بذار
            if len(chunks) > 1:
                chunk = f"[{i}/{len(chunks)}]\n{chunk}"
            resp = await client.post(url, json={"chat_id": target, "text": chunk})
            resp.raise_for_status()
            log.info(f"✅ پیام {i}/{len(chunks)} ارسال شد ({len(chunk)} کاراکتر)")
            await asyncio.sleep(1.5)  # فاصله بین پیام‌ها
    return True


# ─────────────────────────────────────────
# گوش دادن به پیام‌های تلگرام (برای دستور /report)
# ─────────────────────────────────────────
async def poll_telegram_updates(offset: int = 0) -> tuple[list, int]:
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getUpdates"
    async with httpx.AsyncClient(timeout=35) as client:
        try:
            resp = await client.get(url, params={"offset": offset, "timeout": 30})
            resp.raise_for_status()
            data = resp.json()
            updates = data.get("result", [])
            if updates:
                offset = updates[-1]["update_id"] + 1
            return updates, offset
        except Exception as e:
            log.warning(f"⚠️ خطا در دریافت آپدیت: {e}")
            return [], offset


async def handle_updates(updates: list):
    for update in updates:
        try:
            msg = update.get("message", {})
            text = msg.get("text", "").strip()
            chat_id = str(msg.get("chat", {}).get("id", ""))

            if not text or not chat_id:
                continue

            log.info(f"📩 پیام دریافت شد از {chat_id}: {text}")

            # دستور /start
            if text == "/start":
                await send_telegram_message(
                    f"سلام! 👋\n\n"
                    f"من ربات روانشناسی علمی هستم.\n\n"
                    f"📅 هر روز ساعت {SEND_HOUR}:00 یک گزارش علمی کامل می‌رسد\n"
                    f"⚡ برای گزارش فوری با موضوع جدید: رمز مخصوص رو بفرست\n"
                    f"🔁 هر بار رمز بزنی، موضوع جدید و متفاوتی می‌گیری",
                    chat_id=chat_id
                )

            # رمز مخفی برای گزارش فوری
            elif text == REPORT_PASSWORD:
                await send_telegram_message("⏳ در حال آماده‌سازی گزارش علمی جدید...", chat_id=chat_id)
                await daily_job(chat_id=chat_id, force_random=True)

            # دستور اشتباه
            else:
                await send_telegram_message(
                    "رمز اشتباه است.\nبرای گزارش فوری، رمز مخصوص را وارد کنید.",
                    chat_id=chat_id
                )

        except Exception as e:
            log.error(f"❌ خطا در پردازش پیام: {e}")


# ─────────────────────────────────────────
# وظیفه اصلی روزانه
# ─────────────────────────────────────────
async def daily_job(chat_id: str = None, force_random: bool = False):
    log.info("🚀 شروع وظیفه روزانه...")

    if force_random:
        # گزارش فوری با رمز → موضوع تصادفی جدید
        topic = random.choice(TOPIC_POOL)
        log.info(f"🎲 موضوع تصادفی: {topic}")
    else:
        # گزارش روزانه خودکار → موضوع چرخشی بر اساس روز
        day_of_year = datetime.now().timetuple().tm_yday
        topic = TOPIC_POOL[day_of_year % len(TOPIC_POOL)]
        log.info(f"📌 موضوع امروز: {topic}")

    try:
        content = await generate_content(topic)
        await send_telegram_message(content, chat_id=chat_id)
        log.info("🎉 گزارش با موفقیت ارسال شد!")
    except Exception as e:
        log.error(f"❌ خطا: {e}")
        try:
            await send_telegram_message(f"خطا:\n{str(e)}", chat_id=chat_id)
        except Exception:
            pass


# ─────────────────────────────────────────
# حلقه گوش دادن به تلگرام
# ─────────────────────────────────────────
async def telegram_listener():
    log.info("👂 شروع گوش دادن به پیام‌های تلگرام...")
    offset = 0
    while True:
        try:
            updates, offset = await poll_telegram_updates(offset)
            if updates:
                await handle_updates(updates)
        except Exception as e:
            log.error(f"❌ خطا در listener: {e}")
            await asyncio.sleep(5)


# ─────────────────────────────────────────
# اجرای اصلی
# ─────────────────────────────────────────
async def main():
    log.info(f"🤖 ربات شروع به کار کرد | ارسال روزانه ساعت {SEND_HOUR}:00")
    log.info(f"🔑 رمز گزارش فوری: {REPORT_PASSWORD}")

    if SEND_NOW == "1":
        log.info("📤 ارسال فوری...")
        await daily_job()

    # اطلاع‌رسانی شروع
    await send_telegram_message(
        f"ربات روانشناسی علمی فعال شد! 🧠\n\n"
        f"📅 هر روز ساعت {SEND_HOUR}:00 گزارش علمی می‌رسد\n"
        f"⚡ برای گزارش فوری: رمز مخصوص را به ربات بفرست\n"
        f"رمز شما: {REPORT_PASSWORD}"
    )

    # زمان‌بندی روزانه
    scheduler = AsyncIOScheduler(timezone=TIMEZONE)
    scheduler.add_job(daily_job, trigger="cron", hour=SEND_HOUR, minute=0,
                      id="daily_psychology", replace_existing=True)
    scheduler.start()

    # اجرای موازی: زمان‌بندی + گوش دادن به پیام‌ها
    await asyncio.gather(
        telegram_listener(),
        asyncio.sleep(float("inf"))  # نگه داشتن برنامه
    )


if __name__ == "__main__":
    asyncio.run(main())
