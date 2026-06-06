"""
🧠 Psychology Daily Bot — Scientific Edition
محتوا بر اساس مقالات معتبر علمی، قابل فهم برای عموم
دارای رمز برای گزارش فوری از داخل تلگرام
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
REPORT_PASSWORD    = os.getenv("REPORT_PASSWORD", "psych123").strip()

MODELS = [
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite",
    "gemini-2.0-flash",
]

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(message)s",
                    handlers=[logging.StreamHandler()])
log = logging.getLogger(__name__)

# ذخیره گزارش‌های ارسال‌شده: { شناسه: متن_کامل }
report_cache: dict[str, str] = {}

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
async def generate_content(topic: str) -> str:
    prompt = f"""You are a neuroscientist and clinical psychologist who writes for the general public.
Your job is to summarize REAL scientific literature on a topic — explaining it to a curious, intelligent person with no psychology background.

Write a bilingual (Persian + English) scientific report about: "{topic}"

CRITICAL RULES:
1. Base content on REAL peer-reviewed papers (cite actual authors, journals, years)
2. Explain every technical term simply the moment you use it
3. Write like a specialist talking to a smart friend — precise but never confusing
4. Be honest about what science knows vs. what is still debated
5. Persian sections are PRIMARY — write them first, full, and rich
6. English sections are concise summaries
7. YOU MUST WRITE THE COMPLETE REPORT — do not stop until the final hashtag line
8. Every section must be fully completed before moving to the next

Use EXACTLY this structure and complete EVERY section fully:

━━━━━━━━━━━━━━━━━━━━━━━━
🧠 روانشناسی امروز | Today's Psychology
📅 {datetime.now().strftime("%Y/%m/%d")}
━━━━━━━━━━━━━━━━━━━━━━━━

📌 موضوع امروز: {topic}
📌 Today's Topic: [English name]

━━━━━━━━━━━━━━━━━━━━━━━━
🔬 یافته‌های علمی | Scientific Findings
━━━━━━━━━━━━━━━━━━━━━━━━

[فارسی — 4 پاراگراف کامل با ذکر محقق، سال، مجله، داده عددی واقعی و توضیح اصطلاحات]

[English — 3 concise paragraphs with citations]

━━━━━━━━━━━━━━━━━━━━━━━━
⚡ نقد علمی | Critical Analysis
━━━━━━━━━━━━━━━━━━━━━━━━

[فارسی — 3 پاراگراف کامل درباره انتقادات جدی، مطالعات متناقض، محدودیت‌های روش‌شناختی]

[English — 2 paragraphs with specific critical studies]

━━━━━━━━━━━━━━━━━━━━━━━━
💡 از آزمایشگاه تا زندگی | From Lab to Life
━━━━━━━━━━━━━━━━━━━━━━━━

[فارسی — 3 پاراگراف کامل: مثال ملموس واقعی، دقیقاً چه کاری بر اساس علم، اشتباه رایج مردم]

[English — 2 practical paragraphs grounded in the science]

━━━━━━━━━━━━━━━━━━━━━━━━
📚 منابع کلیدی | Key References
━━━━━━━━━━━━━━━━━━━━━━━━

[3 مقاله peer-reviewed واقعی با فرمت: عنوان کامل — نویسنده(گان) — مجله — سال]

━━━━━━━━━━━━━━━━━━━━━━━━
🔎 جمله‌ای که ارزش دارد بدانید | Worth Knowing
━━━━━━━━━━━━━━━━━━━━━━━━

[یک یافته شگفت‌انگیز و واقعی — فارسی و انگلیسی]

#روانشناسی_علمی #نوروساینس #Psychology #Neuroscience #CriticalThinking
[END OF REPORT]"""

    errors = []
    async with httpx.AsyncClient(timeout=120) as client:
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
                        "maxOutputTokens": 8192,   # حداکثر ممکن
                        "temperature": 0.4,
                        "stopSequences": ["[END OF REPORT]"],  # توقف فقط بعد از پایان
                    },
                }
                resp = await client.post(url, json=payload)
                resp.raise_for_status()
                data = resp.json()

                # بررسی دلیل توقف
                candidate = data["candidates"][0]
                finish_reason = candidate.get("finishReason", "")
                content = candidate["content"]["parts"][0]["text"]

                if finish_reason == "MAX_TOKENS":
                    log.warning(f"⚠️ مدل {model} به حد توکن رسید — متن ممکن است ناقص باشد")
                    # اگه حداقل بخش منابع وجود داشت، قبول کن
                    if "📚" not in content:
                        errors.append(f"مدل {model}: متن ناقص (MAX_TOKENS)")
                        await asyncio.sleep(3)
                        continue

                log.info(f"✅ محتوا با مدل {model} کامل تولید شد (finish: {finish_reason})")
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
# ارسال پیام — تقسیم هوشمند بدون قطع جمله
# ─────────────────────────────────────────
async def send_telegram_message(text: str, chat_id: str = None) -> bool:
    target = chat_id or TELEGRAM_CHAT_ID
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"

    # تقسیم بر اساس بخش‌های اصلی (━━━) یا خط جدید — نه وسط جمله
    def smart_split(t: str, limit: int = 3500) -> list[str]:
        if len(t) <= limit:
            return [t]

        parts = []
        current = ""

        for line in t.split("\n"):
            # اگه اضافه کردن این خط از حد رد میشه
            if len(current) + len(line) + 1 > limit:
                if current:
                    parts.append(current.strip())
                current = line + "\n"
            else:
                current += line + "\n"

        if current.strip():
            parts.append(current.strip())

        return parts

    chunks = smart_split(text)
    total = len(chunks)
    log.info(f"📨 ارسال در {total} پیام...")

    async with httpx.AsyncClient(timeout=30) as client:
        for i, chunk in enumerate(chunks, 1):
            header = f"📄 [{i}/{total}]\n" if total > 1 else ""
            payload = {"chat_id": target, "text": header + chunk}
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
            log.info(f"✅ پیام {i}/{total} ارسال شد ({len(chunk)} کاراکتر)")
            await asyncio.sleep(1.5)

    return True


# ─────────────────────────────────────────
# تولید و ارسال گزارش — با ذخیره شناسه
# ─────────────────────────────────────────
async def daily_job(chat_id: str = None, force_random: bool = False) -> str | None:
    log.info("🚀 شروع تولید گزارش...")

    if force_random:
        topic = random.choice(TOPIC_POOL)
        log.info(f"🎲 موضوع تصادفی: {topic}")
    else:
        day_of_year = datetime.now().timetuple().tm_yday
        topic = TOPIC_POOL[day_of_year % len(TOPIC_POOL)]
        log.info(f"📌 موضوع امروز: {topic}")

    try:
        content = await generate_content(topic)

        # ساخت شناسه یکتا برای این گزارش
        report_id = datetime.now().strftime("%m%d%H%M")
        report_cache[report_id] = content

        # اضافه کردن شناسه به پایان گزارش
        footer = f"\n\n🆔 شناسه این گزارش: #{report_id}\n(برای دریافت مجدد همین گزارش، شناسه را بفرست)"
        await send_telegram_message(content + footer, chat_id=chat_id)
        log.info(f"🎉 گزارش #{report_id} ارسال شد!")
        return report_id

    except Exception as e:
        log.error(f"❌ خطا: {e}")
        try:
            await send_telegram_message(f"خطا در تولید گزارش:\n{str(e)}", chat_id=chat_id)
        except Exception:
            pass
        return None


# ─────────────────────────────────────────
# گوش دادن به پیام‌های تلگرام
# ─────────────────────────────────────────
async def poll_telegram_updates(offset: int = 0) -> tuple[list, int]:
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getUpdates"
    async with httpx.AsyncClient(timeout=35) as client:
        try:
            resp = await client.get(url, params={"offset": offset, "timeout": 30})
            resp.raise_for_status()
            updates = resp.json().get("result", [])
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

            log.info(f"📩 پیام از {chat_id}: {text}")

            # ── /start ──
            if text == "/start":
                await send_telegram_message(
                    f"سلام! 👋\n\n"
                    f"🧠 ربات روانشناسی علمی\n\n"
                    f"📅 هر روز ساعت {SEND_HOUR}:00 گزارش علمی می‌رسد\n\n"
                    f"⚡ گزارش فوری با موضوع جدید:\n"
                    f"    رمز: {REPORT_PASSWORD}\n\n"
                    f"🔁 دریافت مجدد یک گزارش قبلی:\n"
                    f"    شناسه آن گزارش را بفرست (مثلاً: #0606830)",
                    chat_id=chat_id
                )

            # ── شناسه گزارش قبلی (#XXXX) ──
            elif text.startswith("#") and text[1:] in report_cache:
                report_id = text[1:]
                log.info(f"📂 ارسال مجدد گزارش #{report_id}")
                await send_telegram_message("📂 در حال ارسال گزارش قبلی...", chat_id=chat_id)
                stored = report_cache[report_id]
                footer = f"\n\n🆔 شناسه این گزارش: #{report_id}"
                await send_telegram_message(stored + footer, chat_id=chat_id)

            # ── رمز ← گزارش جدید ──
            elif text == REPORT_PASSWORD:
                await send_telegram_message(
                    "⏳ در حال تهیه گزارش علمی جدید...\n(ممکن است ۳۰ تا ۶۰ ثانیه طول بکشد)",
                    chat_id=chat_id
                )
                await daily_job(chat_id=chat_id, force_random=True)

            # ── پیام ناشناس ──
            else:
                await send_telegram_message(
                    f"دستور شناخته نشد.\n\n"
                    f"برای گزارش جدید: {REPORT_PASSWORD}\n"
                    f"برای گزارش قبلی: شناسه را بفرست (مثلاً #0606830)",
                    chat_id=chat_id
                )

        except Exception as e:
            log.error(f"❌ خطا در پردازش پیام: {e}")


# ─────────────────────────────────────────
# حلقه گوش دادن
# ─────────────────────────────────────────
async def telegram_listener():
    log.info("👂 گوش دادن به پیام‌های تلگرام شروع شد...")
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
    log.info(f"🤖 ربات شروع | ارسال روزانه ساعت {SEND_HOUR}:00 | رمز: {REPORT_PASSWORD}")

    if SEND_NOW == "1":
        await daily_job()

    await send_telegram_message(
        f"🧠 ربات روانشناسی علمی فعال شد!\n\n"
        f"📅 گزارش روزانه: ساعت {SEND_HOUR}:00\n"
        f"⚡ گزارش فوری: رمز {REPORT_PASSWORD} را بفرست\n"
        f"🔁 گزارش قبلی: شناسه (#XXXX) را بفرست"
    )

    scheduler = AsyncIOScheduler(timezone=TIMEZONE)
    scheduler.add_job(daily_job, trigger="cron", hour=SEND_HOUR, minute=0,
                      id="daily_psychology", replace_existing=True)
    scheduler.start()

    await telegram_listener()


if __name__ == "__main__":
    asyncio.run(main())
