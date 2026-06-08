"""
🧠 Psychology Daily Bot — v3.0
ویژگی‌ها:
- گزارش خودکار به همه کاربران
- گزارش با موضوع دلخواه
- دو سطح محتوا: عمومی / تخصصی
- زمان‌بندی شخصی برای هر کاربر
- سیستم عنوان + شناسه
- منابع به‌روز (اولویت ۵ سال اخیر)
"""

import os
import asyncio
import logging
import random
import json
from datetime import datetime
from pathlib import Path
import httpx
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

# ─────────────────────────────────────────
# تنظیمات پایه
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

# ─────────────────────────────────────────
# لاگ
# ─────────────────────────────────────────
logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(message)s",
                    handlers=[logging.StreamHandler()])
log = logging.getLogger(__name__)

# ─────────────────────────────────────────
# پایگاه داده ساده (فایل JSON)
# ─────────────────────────────────────────
DATA_FILE = Path("/app/data.json")

def load_data() -> dict:
    if DATA_FILE.exists():
        try:
            return json.loads(DATA_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"users": {}, "reports": {}}

def save_data(data: dict):
    try:
        DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
        DATA_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        log.error(f"خطا در ذخیره داده: {e}")

# ساختار پیش‌فرض یک کاربر
def default_user(chat_id: str) -> dict:
    return {
        "chat_id": chat_id,
        "level": "public",          # public | expert
        "schedule_hours": None,     # فاصله ارسال به ساعت (None = فقط روزانه)
        "last_report_id": None,
        "joined": datetime.now().isoformat(),
        "active": True,
    }

# ─────────────────────────────────────────
# موضوعات پیش‌فرض
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
def build_prompt(topic: str, level: str) -> str:
    today = datetime.now().strftime("%Y/%m/%d")

    if level == "expert":
        audience = """TARGET AUDIENCE: Researchers, clinicians, graduate students in psychology/neuroscience.
STYLE: Use precise technical terminology. Include statistical details (effect sizes, p-values, confidence intervals where relevant).
Write as a peer reviewing literature for a colleague."""
        persian_instructions = """
[فارسی — ۵ پاراگراف علمی دقیق]
• اصطلاحات تخصصی را به کار ببر و در پرانتز معادل انگلیسی را بنویس
• آمار و ارقام دقیق: اندازه اثر (effect size)، فاصله اطمینان، مقدار p
• روش‌شناسی مطالعات را شرح بده (RCT، meta-analysis، longitudinal و...)
• مکانیسم‌های نوروبیولوژیک را توضیح بده"""
        english_instructions = "[English — 3 technical paragraphs with full statistical details and methodology]"
        lab_to_life_fa = """[فارسی — ۳ پاراگراف]
• کاربرد بالینی مستقیم این یافته‌ها
• پروتکل‌های درمانی مبتنی بر شواهد
• اشتباهات رایج در تفسیر این یافته‌ها در حوزه بالینی"""
        lab_to_life_en = "[English — 2 paragraphs on evidence-based clinical applications]"
    else:
        audience = """TARGET AUDIENCE: Curious general public with no psychology background.
STYLE: Write like a knowledgeable friend explaining something fascinating over coffee.
Use simple language but never dumbed-down. Every complex idea needs a real-life example."""
        persian_instructions = """
[فارسی — ۴ پاراگراف روان و قابل فهم]
• هر اصطلاح فنی را بلافاصله با یک مثال روزمره توضیح بده
  مثال خوب: «کورتیزول — همان هورمونی که وقتی رئیست صدات می‌کنه معده‌ات فرو می‌ریزه»
• از موقعیت‌های آشنای روزمره استفاده کن: سرکار، خانه، روابط، امتحان
• داستانی روایت کن: چطور این کشف اتفاق افتاد؟ چه چیز عجیبی دیدند؟
• اعداد رو قابل فهم کن: نه «۰.۳۲ effect size»، بلکه «از هر ۱۰ نفر، ۳ نفر...»"""
        english_instructions = "[English — 3 accessible paragraphs with vivid everyday examples]"
        lab_to_life_fa = """[فارسی — ۳ پاراگراف عملی]
• یک سناریوی کاملاً مشخص از زندگی روزمره (نه کلی‌گویی)
• دقیقاً چه کاری انجام بده — گام‌به‌گام، بر اساس همین علم
• یک باور غلط رایج که اکثر مردم دارند و علم خلافش را نشان داده"""
        lab_to_life_en = "[English — 2 practical paragraphs with specific actionable steps]"

    return f"""You are a neuroscientist and clinical psychologist creating a scientific report.

{audience}

CRITICAL RULES:
1. Base EVERY claim on REAL peer-reviewed papers — cite author, journal, year
2. PRIORITIZE studies from 2019–2024. Only use older sources when the original theory requires it
3. If a classic theory has been updated or challenged by recent research, ALWAYS mention the update
4. Complete the ENTIRE report — do not stop before [END OF REPORT]
5. Persian is the PRIMARY language — write it first, full, and rich

━━━━━━━━━━━━━━━━━━━━━━━━
🧠 روانشناسی امروز | Today's Psychology
📅 {today}
━━━━━━━━━━━━━━━━━━━━━━━━

📌 موضوع: {topic}
📌 Topic: [English title]

━━━━━━━━━━━━━━━━━━━━━━━━
🔬 یافته‌های علمی | Scientific Findings
━━━━━━━━━━━━━━━━━━━━━━━━
{persian_instructions}

{english_instructions}

━━━━━━━━━━━━━━━━━━━━━━━━
⚡ نقد علمی | Critical Analysis
━━━━━━━━━━━━━━━━━━━━━━━━

[فارسی — ۳ پاراگراف: انتقادات جدی، مطالعات متناقض (ترجیحاً ۲۰۲۰ به بعد)، محدودیت‌های روش‌شناختی]

[English — 2 paragraphs with specific critical studies and their findings]

━━━━━━━━━━━━━━━━━━━━━━━━
💡 از آزمایشگاه تا زندگی | From Lab to Life
━━━━━━━━━━━━━━━━━━━━━━━━

{lab_to_life_fa}

{lab_to_life_en}

━━━━━━━━━━━━━━━━━━━━━━━━
📚 منابع کلیدی | Key References
━━━━━━━━━━━━━━━━━━━━━━━━

[۳ منبع واقعی — فرمت: عنوان کامل مقاله — نویسنده(گان) — مجله — سال]
[اولویت: ۲۰۱۹–۲۰۲۴ — فقط برای نظریه‌های پایه‌ای منابع قدیمی‌تر قابل قبول است]

━━━━━━━━━━━━━━━━━━━━━━━━
🔎 جمله‌ای که ارزش دارد بدانید | Worth Knowing
━━━━━━━━━━━━━━━━━━━━━━━━

[یک یافته شگفت‌انگیز و واقعی — فارسی و انگلیسی]

#روانشناسی_علمی #نوروساینس #Psychology #Neuroscience #CriticalThinking
[END OF REPORT]"""


async def generate_content(topic: str, level: str = "public") -> str:
    prompt = build_prompt(topic, level)
    errors = []

    async with httpx.AsyncClient(timeout=120) as client:
        for model in MODELS:
            try:
                log.info(f"⏳ مدل: {model} | سطح: {level} | موضوع: {topic[:30]}")
                url = (
                    f"https://generativelanguage.googleapis.com/v1beta/models/"
                    f"{model}:generateContent?key={GEMINI_API_KEY}"
                )
                payload = {
                    "contents": [{"parts": [{"text": prompt}]}],
                    "generationConfig": {
                        "maxOutputTokens": 8192,
                        "temperature": 0.4,
                        "stopSequences": ["[END OF REPORT]"],
                    },
                }
                resp = await client.post(url, json=payload)
                resp.raise_for_status()
                data = resp.json()
                candidate = data["candidates"][0]
                finish_reason = candidate.get("finishReason", "")
                content = candidate["content"]["parts"][0]["text"]

                if finish_reason == "MAX_TOKENS" and "📚" not in content:
                    errors.append(f"مدل {model}: متن ناقص")
                    await asyncio.sleep(3)
                    continue

                log.info(f"✅ محتوا تولید شد (finish: {finish_reason})")
                return content

            except httpx.HTTPStatusError as e:
                err = f"مدل {model}: {e.response.status_code} — {e.response.text[:200]}"
                log.warning(f"⚠️ {err}")
                errors.append(err)
                await asyncio.sleep(3)
            except Exception as e:
                err = f"مدل {model}: {type(e).__name__}: {str(e)[:150]}"
                log.warning(f"⚠️ {err}")
                errors.append(err)
                await asyncio.sleep(3)

    raise RuntimeError("همه مدل‌ها خطا دادند:\n" + "\n".join(errors))


# ─────────────────────────────────────────
# استخراج عنوان از متن گزارش
# ─────────────────────────────────────────
def extract_title(content: str, topic: str) -> str:
    for line in content.split("\n"):
        if "📌 موضوع:" in line:
            title = line.replace("📌 موضوع:", "").strip()
            if title:
                return title[:60]
    return topic[:60]


# ─────────────────────────────────────────
# ارسال پیام به تلگرام — تقسیم هوشمند
# ─────────────────────────────────────────
async def send_telegram_message(text: str, chat_id: str = None, show_menu: bool = False) -> bool:
    target = chat_id or TELEGRAM_CHAT_ID
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"

    def smart_split(t: str, limit: int = 3500) -> list[str]:
        if len(t) <= limit:
            return [t]
        parts, current = [], ""
        for line in t.split("\n"):
            if len(current) + len(line) + 1 > limit:
                if current:
                    parts.append(current.strip())
                current = line + "\n"
            else:
                current += line + "\n"
        if current.strip():
            parts.append(current.strip())
        return parts

    # کیبورد منو پایین صفحه
    menu_keyboard = {
        "keyboard": [
            ["📊 گزارش جدید", "✏️ موضوع دلخواه"],
            ["🎚 تغییر سطح", "⏰ زمان‌بندی"],
            ["📚 گزارش‌های قبلی", "❓ راهنما"],
        ],
        "resize_keyboard": True,
        "persistent": True,
    }

    chunks = smart_split(text)
    total = len(chunks)

    async with httpx.AsyncClient(timeout=30) as client:
        for i, chunk in enumerate(chunks, 1):
            header = f"📄 [{i}/{total}]\n" if total > 1 else ""
            payload = {
                "chat_id": target,
                "text": header + chunk,
            }
            # فقط آخرین پیام منو رو نشون بده
            if show_menu and i == total:
                payload["reply_markup"] = menu_keyboard

            resp = await client.post(url, json=payload)
            resp.raise_for_status()
            log.info(f"✅ پیام {i}/{total} ارسال شد به {target}")
            await asyncio.sleep(1.5)
    return True


# ─────────────────────────────────────────
# تولید + ذخیره + ارسال گزارش
# ─────────────────────────────────────────
async def send_report(chat_id: str, topic: str = None, level: str = None) -> str | None:
    data = load_data()

    # اطمینان از وجود کاربر
    if chat_id not in data["users"]:
        data["users"][chat_id] = default_user(chat_id)

    user = data["users"][chat_id]
    effective_level = level or user.get("level", "public")

    # انتخاب موضوع
    if not topic:
        day_of_year = datetime.now().timetuple().tm_yday
        topic = TOPIC_POOL[day_of_year % len(TOPIC_POOL)]

    try:
        # برچسب سطح
        level_label = "🎓 تخصصی" if effective_level == "expert" else "🌍 عمومی"
        await send_telegram_message(
            f"⏳ در حال تهیه گزارش {level_label}...\n"
            f"📌 موضوع: {topic}\n"
            f"(۳۰ تا ۶۰ ثانیه زمان می‌برد)",
            chat_id=chat_id
        )

        content = await generate_content(topic, effective_level)

        # ساخت شناسه و عنوان
        report_id = datetime.now().strftime("%m%d%H%M")
        title = extract_title(content, topic)

        # ذخیره گزارش
        data["reports"][report_id] = {
            "id": report_id,
            "title": title,
            "topic": topic,
            "level": effective_level,
            "content": content,
            "date": datetime.now().isoformat(),
            "chat_id": chat_id,
        }
        data["users"][chat_id]["last_report_id"] = report_id
        save_data(data)

        # footer با شناسه و عنوان
        footer = (
            f"\n\n{'━'*24}\n"
            f"🆔 شناسه: #{report_id}\n"
            f"📝 عنوان: {title}\n"
            f"🎚 سطح: {level_label}\n"
            f"برای دریافت مجدد: #{report_id} یا عنوان را بفرست"
        )

        await send_telegram_message(content + footer, chat_id=chat_id)
        log.info(f"🎉 گزارش #{report_id} '{title}' ارسال شد به {chat_id}")
        return report_id

    except Exception as e:
        log.error(f"❌ خطا در تولید گزارش: {e}")
        await send_telegram_message(f"❌ خطا در تولید گزارش:\n{str(e)}", chat_id=chat_id)
        return None


# ─────────────────────────────────────────
# گزارش خودکار به همه کاربران
# ─────────────────────────────────────────
async def broadcast_daily():
    log.info("📢 شروع ارسال روزانه به همه کاربران...")
    data = load_data()
    day_of_year = datetime.now().timetuple().tm_yday
    topic = TOPIC_POOL[day_of_year % len(TOPIC_POOL)]

    users = [u for u in data["users"].values() if u.get("active", True)]
    log.info(f"👥 تعداد کاربران فعال: {len(users)}")

    for user in users:
        try:
            await send_report(
                chat_id=user["chat_id"],
                topic=topic,
                level=user.get("level", "public")
            )
            await asyncio.sleep(2)  # فاصله بین کاربران
        except Exception as e:
            log.error(f"❌ خطا در ارسال به {user['chat_id']}: {e}")


# ─────────────────────────────────────────
# جستجوی گزارش بر اساس عنوان
# ─────────────────────────────────────────
def search_report_by_title(query: str, reports: dict) -> dict | None:
    query_lower = query.strip().lower()
    best_match = None
    best_score = 0

    for report in reports.values():
        title = report.get("title", "").lower()
        topic = report.get("topic", "").lower()
        # امتیازدهی ساده
        score = 0
        if query_lower in title:
            score = 3
        elif query_lower in topic:
            score = 2
        else:
            # جستجوی کلمه به کلمه
            words = query_lower.split()
            matches = sum(1 for w in words if w in title or w in topic)
            score = matches

        if score > best_score:
            best_score = score
            best_match = report

    return best_match if best_score > 0 else None


# ─────────────────────────────────────────
# پردازش پیام‌ها
# ─────────────────────────────────────────

# وضعیت انتظار برای هر کاربر
waiting_state: dict[str, str] = {}

async def handle_updates(updates: list):
    data = load_data()

    for update in updates:
        try:
            msg = update.get("message", {})
            text = msg.get("text", "").strip()
            chat_id = str(msg.get("chat", {}).get("id", ""))
            if not text or not chat_id:
                continue

            log.info(f"📩 پیام از {chat_id}: {text[:50]}")

            # ثبت کاربر جدید
            if chat_id not in data["users"]:
                data["users"][chat_id] = default_user(chat_id)
                save_data(data)
                log.info(f"👤 کاربر جدید ثبت شد: {chat_id}")

            user = data["users"][chat_id]

            # ── بررسی وضعیت انتظار ──
            state = waiting_state.get(chat_id)

            if state == "waiting_topic":
                waiting_state.pop(chat_id, None)
                await send_report(chat_id=chat_id, topic=text)
                continue

            elif state == "waiting_schedule":
                waiting_state.pop(chat_id, None)
                await handle_schedule_input(chat_id, text, data)
                continue

            # ── نگاشت دکمه‌های منو به دستورات ──
            menu_map = {
                "📊 گزارش جدید": "/report",
                "✏️ موضوع دلخواه": "/topic",
                "🎚 تغییر سطح": "/level",
                "⏰ زمان‌بندی": "/schedule",
                "📚 گزارش‌های قبلی": "/history",
                "❓ راهنما": "/help",
            }
            if text in menu_map:
                text = menu_map[text]

            # ── دستورات اصلی ──

            if text in ["/start", "start"]:
                data["users"][chat_id]["active"] = True
                save_data(data)
                level = user.get("level", "public")
                level_text = "🌍 عمومی" if level == "public" else "🎓 تخصصی"
                await send_telegram_message(
                    f"سلام! 👋 به ربات روانشناسی علمی خوش آمدی\n\n"
                    f"🎚 سطح فعلی تو: {level_text}\n\n"
                    f"از دکمه‌های پایین صفحه استفاده کن 👇\n\n"
                    f"⚡ گزارش فوری: رمز {REPORT_PASSWORD} را بفرست\n"
                    f"🔁 گزارش قبلی: #شناسه یا عنوان را بفرست",
                    chat_id=chat_id,
                    show_menu=True
                )

            elif text in ["/report"]:
                await send_report(chat_id=chat_id, force_random=True if False else None)

            elif text in ["/topic"]:
                waiting_state[chat_id] = "waiting_topic"
                await send_telegram_message(
                    "📝 موضوع مورد نظرت را بنویس:\n\n"
                    "مثال‌ها:\n"
                    "• اضطراب اجتماعی\n"
                    "• تأثیر خواب بر حافظه\n"
                    "• روان‌شناسی تصمیم‌گیری\n"
                    "• افسردگی و التهاب مغز\n\n"
                    "هر موضوعی در حوزه روانشناسی و علوم اعصاب می‌توانی بنویسی:",
                    chat_id=chat_id
                )

            elif text in ["/level"]:
                current = user.get("level", "public")
                await send_telegram_message(
                    f"🎚 سطح فعلی: {'🌍 عمومی' if current == 'public' else '🎓 تخصصی'}\n\n"
                    f"برای تغییر یکی را انتخاب کن:\n\n"
                    f"1️⃣ بنویس: public — سطح عمومی\n"
                    f"   مناسب برای همه، با مثال‌های روزمره\n\n"
                    f"2️⃣ بنویس: expert — سطح تخصصی\n"
                    f"   برای متخصصان، با جزئیات آماری",
                    chat_id=chat_id
                )
                waiting_state[chat_id] = "waiting_level"

            elif text in ["/schedule"]:
                schedule = user.get("schedule_hours")
                current_text = f"هر {schedule} ساعت" if schedule else "فقط روزانه ساعت 8"
                await send_telegram_message(
                    f"⏰ زمان‌بندی فعلی: {current_text}\n\n"
                    f"چه فاصله‌ای بین گزارش‌ها می‌خواهی؟\n\n"
                    f"مثال‌ها:\n"
                    f"• بنویس 8 ← هر 8 ساعت\n"
                    f"• بنویس 12 ← هر 12 ساعت\n"
                    f"• بنویس 24 ← روزی یک بار\n"
                    f"• بنویس 0 ← فقط روزانه ساعت 8 (پیش‌فرض)",
                    chat_id=chat_id
                )
                waiting_state[chat_id] = "waiting_schedule"

            elif text in ["/history"]:
                reports = data.get("reports", {})
                user_reports = [
                    r for r in reports.values()
                    if r.get("chat_id") == chat_id
                ]
                user_reports.sort(key=lambda x: x.get("date", ""), reverse=True)
                last_10 = user_reports[:10]

                if not last_10:
                    await send_telegram_message(
                        "هنوز هیچ گزارشی دریافت نکردی!\n"
                        "برای گزارش جدید /report را بزن.",
                        chat_id=chat_id
                    )
                else:
                    history_text = "📚 آخرین گزارش‌های تو:\n\n"
                    for r in last_10:
                        date = r.get("date", "")[:10]
                        history_text += (
                            f"🆔 #{r['id']} — {date}\n"
                            f"📝 {r.get('title', r.get('topic', ''))}\n\n"
                        )
                    history_text += "برای دریافت مجدد، شناسه (#XXXX) یا عنوان را بفرست."
                    await send_telegram_message(history_text, chat_id=chat_id)

            elif text in ["/help"]:
                await send_telegram_message(
                    "📖 راهنمای کامل ربات روانشناسی علمی\n\n"
                    "📊 گزارش جدید — موضوع تصادفی\n"
                    "✏️ موضوع دلخواه — هر موضوعی در روانشناسی\n"
                    "🎚 تغییر سطح — عمومی یا تخصصی\n"
                    "⏰ زمان‌بندی — هر چند ساعت گزارش بگیری\n"
                    "📚 گزارش‌های قبلی — ۱۰ گزارش آخر\n\n"
                    f"⚡ گزارش فوری: رمز {REPORT_PASSWORD}\n"
                    "🔁 گزارش قبلی: #شناسه را بفرست\n"
                    "🔍 جستجو: عنوان یا کلیدواژه را بفرست",
                    chat_id=chat_id,
                    show_menu=True
                )

            # ── وضعیت انتظار سطح ──
            elif waiting_state.get(chat_id) == "waiting_level":
                waiting_state.pop(chat_id, None)
                if text.lower() in ["public", "عمومی", "1"]:
                    data["users"][chat_id]["level"] = "public"
                    save_data(data)
                    await send_telegram_message(
                        "✅ سطح به 🌍 عمومی تغییر کرد!\n"
                        "گزارش‌های بعدی با زبان ساده و مثال‌های روزمره خواهند بود.",
                        chat_id=chat_id
                    )
                elif text.lower() in ["expert", "تخصصی", "2"]:
                    data["users"][chat_id]["level"] = "expert"
                    save_data(data)
                    await send_telegram_message(
                        "✅ سطح به 🎓 تخصصی تغییر کرد!\n"
                        "گزارش‌های بعدی با جزئیات آماری و اصطلاحات تخصصی خواهند بود.",
                        chat_id=chat_id
                    )
                else:
                    await send_telegram_message(
                        "لطفاً public یا expert بنویس.", chat_id=chat_id
                    )

            # ── رمز مخفی ──
            elif text == REPORT_PASSWORD:
                topic = random.choice(TOPIC_POOL)
                await send_report(chat_id=chat_id, topic=topic)

            # ── شناسه گزارش (#XXXX) ──
            elif text.startswith("#"):
                report_id = text[1:]
                reports = data.get("reports", {})
                if report_id in reports:
                    stored = reports[report_id]
                    footer = (
                        f"\n\n{'━'*24}\n"
                        f"🆔 شناسه: #{report_id}\n"
                        f"📝 عنوان: {stored.get('title', '')}"
                    )
                    await send_telegram_message(
                        "📂 ارسال مجدد گزارش...", chat_id=chat_id
                    )
                    await send_telegram_message(
                        stored["content"] + footer, chat_id=chat_id
                    )
                else:
                    await send_telegram_message(
                        f"گزارشی با شناسه #{report_id} پیدا نشد.\n"
                        f"از /history لیست گزارش‌هات را ببین.",
                        chat_id=chat_id
                    )

            # ── جستجو با عنوان یا کلیدواژه ──
            elif len(text) > 3 and not text.startswith("/"):
                reports = data.get("reports", {})
                match = search_report_by_title(text, reports)
                if match:
                    await send_telegram_message(
                        f"🔍 گزارش پیدا شد:\n"
                        f"📝 {match.get('title', '')}\n"
                        f"🆔 #{match['id']}\n\n"
                        f"ارسال می‌شود...",
                        chat_id=chat_id
                    )
                    footer = (
                        f"\n\n{'━'*24}\n"
                        f"🆔 شناسه: #{match['id']}\n"
                        f"📝 عنوان: {match.get('title', '')}"
                    )
                    await send_telegram_message(
                        match["content"] + footer, chat_id=chat_id
                    )
                else:
                    # اگه گزارشی پیدا نشد، بپرس آیا میخواد روی این موضوع گزارش بگیره
                    waiting_state[chat_id] = "waiting_topic_confirm"
                    waiting_state[f"{chat_id}_pending_topic"] = text
                    await send_telegram_message(
                        f"گزارشی با این موضوع پیدا نشد.\n\n"
                        f"آیا می‌خواهی روی «{text}» یک گزارش جدید تهیه شود?\n\n"
                        f"بله بنویس یا خیر",
                        chat_id=chat_id
                    )

            elif waiting_state.get(chat_id) == "waiting_topic_confirm":
                pending = waiting_state.pop(f"{chat_id}_pending_topic", None)
                waiting_state.pop(chat_id, None)
                if text.strip() in ["بله", "yes", "آره", "بله،", "بله."]:
                    if pending:
                        await send_report(chat_id=chat_id, topic=pending)
                else:
                    await send_telegram_message(
                        "باشه! برای گزارش جدید /report یا /topic را بزن.",
                        chat_id=chat_id
                    )

        except Exception as e:
            log.error(f"❌ خطا در پردازش پیام: {e}")


async def handle_schedule_input(chat_id: str, text: str, data: dict):
    try:
        hours = int(text.strip())
        if hours == 0:
            data["users"][chat_id]["schedule_hours"] = None
            save_data(data)
            await send_telegram_message(
                "✅ زمان‌بندی شخصی حذف شد.\n"
                f"فقط گزارش روزانه ساعت {SEND_HOUR}:00 دریافت خواهی کرد.",
                chat_id=chat_id
            )
        elif 1 <= hours <= 168:
            data["users"][chat_id]["schedule_hours"] = hours
            save_data(data)
            await send_telegram_message(
                f"✅ زمان‌بندی تنظیم شد: هر {hours} ساعت یک گزارش دریافت خواهی کرد.",
                chat_id=chat_id
            )
        else:
            await send_telegram_message(
                "عدد باید بین 1 تا 168 باشد. دوباره امتحان کن.", chat_id=chat_id
            )
    except ValueError:
        await send_telegram_message(
            "لطفاً فقط عدد بنویس (مثلاً: 8 یا 12 یا 24)", chat_id=chat_id
        )


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
            log.warning(f"⚠️ خطا در poll: {e}")
            return [], offset


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
# زمان‌بندی گزارش‌های شخصی
# ─────────────────────────────────────────
async def check_personal_schedules(scheduler: AsyncIOScheduler):
    """هر ساعت چک می‌کند آیا کاربری باید گزارش شخصی دریافت کند"""
    data = load_data()
    now = datetime.now()

    for user in data["users"].values():
        if not user.get("active"):
            continue
        hours = user.get("schedule_hours")
        if not hours:
            continue

        last_report_id = user.get("last_report_id")
        if last_report_id and last_report_id in data.get("reports", {}):
            last_date_str = data["reports"][last_report_id].get("date", "")
            try:
                last_date = datetime.fromisoformat(last_date_str)
                diff_hours = (now - last_date).total_seconds() / 3600
                if diff_hours < hours:
                    continue
            except Exception:
                pass

        topic = random.choice(TOPIC_POOL)
        await send_report(chat_id=user["chat_id"], topic=topic)
        await asyncio.sleep(2)


# ─────────────────────────────────────────
# اجرای اصلی
# ─────────────────────────────────────────
async def main():
    log.info(f"🤖 ربات v3.0 شروع به کار کرد | ارسال روزانه ساعت {SEND_HOUR}:00")

    # اطمینان از وجود سازنده در لیست کاربران
    data = load_data()
    if TELEGRAM_CHAT_ID and TELEGRAM_CHAT_ID not in data["users"]:
        data["users"][TELEGRAM_CHAT_ID] = default_user(TELEGRAM_CHAT_ID)
        save_data(data)

    if SEND_NOW == "1":
        await broadcast_daily()

    await send_telegram_message(
        f"🧠 ربات روانشناسی علمی v3.0 فعال شد!\n\n"
        f"📅 گزارش روزانه: ساعت {SEND_HOUR}:00 به همه کاربران\n"
        f"⚡ گزارش فوری: رمز {REPORT_PASSWORD}\n\n"
        f"از دکمه‌های پایین صفحه استفاده کن 👇",
        show_menu=True
    )

    scheduler = AsyncIOScheduler(timezone=TIMEZONE)

    # گزارش روزانه به همه
    scheduler.add_job(broadcast_daily, trigger="cron",
                      hour=SEND_HOUR, minute=0,
                      id="daily_broadcast", replace_existing=True)

    # چک زمان‌بندی شخصی — هر ساعت
    scheduler.add_job(
        check_personal_schedules,
        trigger=IntervalTrigger(hours=1),
        args=[scheduler],
        id="personal_schedules",
        replace_existing=True
    )

    scheduler.start()
    await telegram_listener()


if __name__ == "__main__":
    asyncio.run(main())
