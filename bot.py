"""
🧠 Psychology Daily Bot — v4.0
"""

import os
import asyncio
import logging
import random
import json
from datetime import datetime, timedelta
from pathlib import Path
import httpx
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sources import get_sources_for_topic, format_sources
from research import fetch_real_papers

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID   = os.getenv("TELEGRAM_CHAT_ID",   "").strip()
GEMINI_API_KEY     = os.getenv("GEMINI_API_KEY",      "").strip()
SEND_HOUR          = int(os.getenv("SEND_HOUR", "8").strip().split()[0])
TIMEZONE           = os.getenv("TIMEZONE", "Asia/Tehran").strip()
SEND_NOW           = os.getenv("SEND_NOW", "0").strip()
REPORT_PASSWORD    = os.getenv("REPORT_PASSWORD", "psych123").strip()

MODELS = ["gemini-2.5-flash", "gemini-2.5-flash-lite", "gemini-2.0-flash"]

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(message)s",
                    handlers=[logging.StreamHandler()])
log = logging.getLogger(__name__)

# ─────────────────────────────────────────
# پایگاه داده
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
        DATA_FILE.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except Exception as e:
        log.error(f"خطا در ذخیره: {e}")

def default_user(chat_id: str, username: str = "", full_name: str = "") -> dict:
    return {
        "chat_id": chat_id,
        "username": username,
        "full_name": full_name,
        "level": "public",          # public | expert
        "language": "fa",           # fa | en | bilingual
        "schedule_hours": None,     # None=فقط روزانه | 8|12|24
        "schedule_hour": None,      # ساعت ارسال شخصی (0-23)
        "last_report_time": None,   # آخرین زمان ارسال (ISO)
        "last_report_id": None,
        "joined": datetime.now().isoformat(),
        "last_seen": datetime.now().isoformat(),
        "active": True,
        "authorized": False,
    }

def update_last_seen(data: dict, chat_id: str):
    if chat_id in data["users"]:
        data["users"][chat_id]["last_seen"] = datetime.now().isoformat()

# ─────────────────────────────────────────
# موضوعات
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
# ساخت پرامپت
# ─────────────────────────────────────────
def build_prompt(topic: str, level: str, language: str, extra_sources: str = "") -> str:
    today = datetime.now().strftime("%Y/%m/%d")

    # ── تعیین زبان خروجی ──
    if language == "fa":
        lang_instruction = """LANGUAGE RULE — ABSOLUTE AND NON-NEGOTIABLE:
✅ Write the ENTIRE report in PERSIAN (Farsi) only.
✅ Every single sentence, word, and character must be in Persian.
✅ Technical terms: write the Persian term first, then the English equivalent in parentheses.
   Example: ذهن‌آگاهی (Mindfulness)، کورتیزول (Cortisol)
✅ References: write authors' names in Persian transliteration + journal name in English.
❌ Do NOT write any full sentences or paragraphs in English.
❌ Do NOT add an English summary section.
❌ Do NOT switch to English under any circumstance."""
        structure_lang = "فارسی"

    elif language == "en":
        lang_instruction = """LANGUAGE RULE — ABSOLUTE AND NON-NEGOTIABLE:
✅ Write the ENTIRE report in ENGLISH only.
✅ Every single sentence, word, and character must be in English.
✅ Technical terms: write in English with a brief plain-language explanation.
❌ Do NOT write any sentences or paragraphs in Persian/Farsi.
❌ Do NOT add a Persian section.
❌ Do NOT switch to Persian under any circumstance."""
        structure_lang = "English"

    else:  # bilingual
        lang_instruction = """LANGUAGE RULE — ABSOLUTE AND NON-NEGOTIABLE:
✅ Write each section TWICE: first in PERSIAN, then in ENGLISH.
✅ Persian section comes FIRST and must be complete and rich.
✅ English section follows immediately after, as a complete parallel.
✅ Both sections must be full — do not abbreviate either.
❌ Do NOT skip either language in any section.
❌ Do NOT mix languages within a paragraph."""
        structure_lang = "فارسی + English"

    # ── تعیین سطح محتوا ──
    if level == "expert":
        level_instruction = """CONTENT LEVEL: EXPERT
- Audience: psychologists, researchers, graduate students
- Use precise technical terminology (with brief clarification if needed)
- Discuss theoretical frameworks, research methodology, clinical implications
- Mention specific studies with author, journal, year
- Discuss limitations, contradictions, and ongoing debates in the field
- Do NOT include excessive statistics or p-values — focus on conceptual depth
- Do NOT provide treatment protocols or medical advice"""
    else:
        level_instruction = """CONTENT LEVEL: GENERAL PUBLIC
- Audience: curious, intelligent adults with no psychology background
- Every technical term must be immediately explained with a vivid everyday example
  Good example: "cortisol — the hormone that makes your stomach drop when your boss calls your name"
- Use familiar situations: work, relationships, family, daily choices
- Tell the story of how this was discovered
- Make concepts feel personal and relevant
- Do NOT use jargon without explanation
- Do NOT be condescending or oversimplify to the point of inaccuracy"""

    return f"""You are a scientific psychology writer creating a Telegram report.

{lang_instruction}

{level_instruction}

STRICT CONTENT RULES:
1. ONLY use sources from the SOURCE_PACK below. Do NOT cite any other paper, book, or author.
2. If SOURCE_PACK is provided, every factual claim must trace back to one of those sources.
3. For topics without a SOURCE_PACK: only cite sources you are highly confident are real and verifiable — when uncertain, describe findings without a citation rather than fabricating one.
4. NEVER invent, hallucinate, or approximate a citation. A reader must be able to find the exact paper or book by searching online.
5. Do NOT provide therapy, diagnosis, medication advice, or personal mental health judgments.
6. Do NOT use exaggerated, pseudoscientific, or superficial motivational language.
7. Do NOT produce long direct quotes.
8. Keep the report concise and readable for Telegram: short paragraphs, clear headers.
9. Maximum 4 hashtags. Maximum 2 emojis per section.
10. You MUST write the complete report. Do NOT stop before [END OF REPORT].{extra_sources}

TODAY'S TOPIC: {topic}
DATE: {today}
OUTPUT LANGUAGE: {structure_lang}

━━━━━━━━━━━━━━━━━━━━━━━━
🧠 {"روانشناسی امروز" if language != "en" else "Today's Psychology"}
📅 {today}
━━━━━━━━━━━━━━━━━━━━━━━━

{"📌 موضوع: " + topic if language != "en" else "📌 Topic: " + topic}

━━━━━━━━━━━━━━━━━━━━━━━━
{"🔬 یافته‌های علمی" if language == "fa" else ("🔬 Scientific Findings" if language == "en" else "🔬 یافته‌های علمی | Scientific Findings")}
━━━━━━━━━━━━━━━━━━━━━━━━

[{"۴ پاراگراف کوتاه و خوش‌خوان — بر اساس مقالات واقعی با ذکر نویسنده و سال" if language == "fa" else ("4 short readable paragraphs — based on real papers with author and year" if language == "en" else "۴ پاراگراف فارسی کامل\n\n4 English paragraphs")}]

━━━━━━━━━━━━━━━━━━━━━━━━
{"⚡ نقد علمی" if language == "fa" else ("⚡ Critical Analysis" if language == "en" else "⚡ نقد علمی | Critical Analysis")}
━━━━━━━━━━━━━━━━━━━━━━━━

[{"۲ پاراگراف: انتقادات واقعی از مطالعات موجود و محدودیت‌های روش‌شناختی" if language == "fa" else ("2 paragraphs: real criticisms from existing studies and methodological limitations" if language == "en" else "۲ پاراگراف فارسی\n\n2 English paragraphs")}]

━━━━━━━━━━━━━━━━━━━━━━━━
{"💡 کاربرد در زندگی" if language == "fa" else ("💡 From Lab to Life" if language == "en" else "💡 کاربرد در زندگی | From Lab to Life")}
━━━━━━━━━━━━━━━━━━━━━━━━

[{"۲ پاراگراف عملی — یک سناریوی مشخص از زندگی روزمره و یک کاربرد دقیق بر اساس همین علم" if language == "fa" else ("2 practical paragraphs — one specific everyday scenario and one precise application based on this science" if language == "en" else "۲ پاراگراف فارسی\n\n2 English paragraphs")}]

━━━━━━━━━━━━━━━━━━━━━━━━
{"📚 منابع" if language == "fa" else ("📚 References" if language == "en" else "📚 منابع | References")}
━━━━━━━━━━━━━━━━━━━━━━━━

[3 real verifiable references — format: Author(s) — Title — Journal/Publisher — Year]
[Priority 2015–2026. Only use older sources for foundational theories]

━━━━━━━━━━━━━━━━━━━━━━━━
{"🔎 نکته‌ای که ارزش دارد بدانید" if language == "fa" else ("🔎 Worth Knowing" if language == "en" else "🔎 نکته‌ای که ارزش دارد بدانید | Worth Knowing")}
━━━━━━━━━━━━━━━━━━━━━━━━

[{"یک یافته شگفت‌انگیز و واقعی از تحقیقات" if language == "fa" else ("One surprising and real research finding" if language == "en" else "فارسی\n\nEnglish")}]

{"#روانشناسی_علمی #علم_روانشناسی #سلامت_روان #Psychology" if language == "fa" else ("#Psychology #Neuroscience #MentalHealth #Science" if language == "en" else "#روانشناسی_علمی #Psychology #Neuroscience #سلامت_روان")}
[END OF REPORT]"""


async def generate_content(topic: str, level: str, language: str) -> str:
    # ۱. جستجوی مقالات واقعی از پایگاه‌های داده
    live_papers = await fetch_real_papers(topic)

    # ۲. منابع ثابت تأییدشده (پشتیبان)
    static_sources = get_sources_for_topic(topic)
    static_formatted = format_sources(static_sources)

    # ترکیب: مقالات زنده اولویت دارند، منابع ثابت پشتیبان
    extra_sources = live_papers if live_papers else static_formatted
    prompt = build_prompt(topic, level, language, extra_sources)
    errors = []
    async with httpx.AsyncClient(timeout=120) as client:
        for model in MODELS:
            try:
                log.info(f"⏳ {model} | {level} | {language} | {topic[:25]}")
                url = (
                    f"https://generativelanguage.googleapis.com/v1beta/models/"
                    f"{model}:generateContent?key={GEMINI_API_KEY}"
                )
                resp = await client.post(url, json={
                    "contents": [{"parts": [{"text": prompt}]}],
                    "generationConfig": {
                        "maxOutputTokens": 8192,
                        "temperature": 0.3,
                        "stopSequences": ["[END OF REPORT]"],
                    },
                })
                resp.raise_for_status()
                data = resp.json()
                candidate = data["candidates"][0]
                finish = candidate.get("finishReason", "")
                content = candidate["content"]["parts"][0]["text"]
                if finish == "MAX_TOKENS" and "📚" not in content:
                    errors.append(f"{model}: ناقص")
                    await asyncio.sleep(3)
                    continue
                log.info(f"✅ تولید شد (finish={finish})")
                return content
            except httpx.HTTPStatusError as e:
                err = f"{model}: {e.response.status_code} — {e.response.text[:150]}"
                log.warning(f"⚠️ {err}")
                errors.append(err)
                await asyncio.sleep(3)
            except Exception as e:
                err = f"{model}: {type(e).__name__}: {str(e)[:100]}"
                log.warning(f"⚠️ {err}")
                errors.append(err)
                await asyncio.sleep(3)
    raise RuntimeError("همه مدل‌ها خطا:\n" + "\n".join(errors))


def extract_title(content: str, topic: str) -> str:
    for line in content.split("\n"):
        if "📌" in line and ("موضوع" in line or "Topic" in line):
            t = line.split(":", 1)[-1].strip() if ":" in line else line.replace("📌", "").strip()
            if t and len(t) > 3:
                return t[:60]
    return topic[:60]


# ─────────────────────────────────────────
# ارسال پیام
# ─────────────────────────────────────────
MENU_KEYBOARD = {
    "keyboard": [
        ["📊 گزارش جدید", "✏️ موضوع دلخواه"],
        ["🎚 سطح محتوا", "🌐 زبان"],
        ["⏰ زمان‌بندی", "📚 گزارش‌های قبلی"],
        ["❓ راهنما"],
    ],
    "resize_keyboard": True,
    "persistent": True,
}

async def send_msg(text: str, chat_id: str, show_menu: bool = False) -> bool:
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

    chunks = smart_split(text)
    total = len(chunks)
    async with httpx.AsyncClient(timeout=30) as client:
        for i, chunk in enumerate(chunks, 1):
            header = f"📄 [{i}/{total}]\n" if total > 1 else ""
            payload = {"chat_id": chat_id, "text": header + chunk}
            if show_menu and i == total:
                payload["reply_markup"] = MENU_KEYBOARD
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
            log.info(f"✅ پیام {i}/{total} → {chat_id}")
            await asyncio.sleep(1.5)
    return True


# ─────────────────────────────────────────
# تولید و ارسال گزارش
# ─────────────────────────────────────────
async def send_report(chat_id: str, topic: str, level: str, language: str) -> str | None:
    level_label = "🎓 تخصصی" if level == "expert" else "🌍 عمومی"
    lang_label = {"fa": "🇮🇷 فارسی", "en": "🇬🇧 English", "bilingual": "🌐 دوزبانه"}.get(language, "")
    await send_msg(
        f"⏳ در حال تهیه گزارش...\n{level_label} | {lang_label}\n📌 {topic}\n(۳۰–۶۰ ثانیه)",
        chat_id=chat_id
    )
    try:
        content = await generate_content(topic, level, language)
        report_id = datetime.now().strftime("%m%d%H%M")
        title = extract_title(content, topic)

        data = load_data()
        data["reports"][report_id] = {
            "id": report_id, "title": title, "topic": topic,
            "level": level, "language": language, "content": content,
            "date": datetime.now().isoformat(), "chat_id": chat_id,
        }
        if chat_id in data["users"]:
            data["users"][chat_id]["last_report_id"] = report_id
            data["users"][chat_id]["last_report_time"] = datetime.now().isoformat()
            data["users"][chat_id]["last_seen"] = datetime.now().isoformat()
        save_data(data)

        footer = (
            f"\n\n{'━'*24}\n"
            f"🆔 #{report_id} | {level_label} | {lang_label}\n"
            f"📝 {title}\n"
            f"برای دریافت مجدد: #{report_id}"
        )
        await send_msg(content + footer, chat_id=chat_id, show_menu=True)
        log.info(f"🎉 #{report_id} ارسال شد به {chat_id}")
        return report_id
    except Exception as e:
        log.error(f"❌ {e}")
        await send_msg(f"❌ خطا:\n{str(e)}", chat_id=chat_id)
        return None


# ─────────────────────────────────────────
# ارسال خودکار — زمان‌بندی
# ─────────────────────────────────────────
async def broadcast_scheduled():
    """هر ۳۰ دقیقه یک بار اجرا میشه و چک میکنه چه کسی باید گزارش بگیره"""
    data = load_data()
    now = datetime.now()
    day_of_year = now.timetuple().tm_yday
    default_topic = TOPIC_POOL[day_of_year % len(TOPIC_POOL)]

    for user in data["users"].values():
        if not user.get("active") or not user.get("authorized"):
            continue

        chat_id = user["chat_id"]
        schedule_hours = user.get("schedule_hours")
        schedule_hour = user.get("schedule_hour")  # ساعت مشخص (مثلاً 8)
        last_report_time = user.get("last_report_time")

        should_send = False
        topic = random.choice(TOPIC_POOL)

        if schedule_hours:
            # حالت interval: هر N ساعت
            if last_report_time:
                try:
                    last_dt = datetime.fromisoformat(last_report_time)
                    hours_passed = (now - last_dt).total_seconds() / 3600
                    if hours_passed >= schedule_hours:
                        should_send = True
                except Exception:
                    should_send = True
            else:
                should_send = True

        elif schedule_hour is not None:
            # حالت ساعت مشخص روزانه
            if now.hour == schedule_hour and now.minute < 30:
                if last_report_time:
                    try:
                        last_dt = datetime.fromisoformat(last_report_time)
                        if (now - last_dt).total_seconds() > 3600:
                            should_send = True
                            topic = default_topic
                    except Exception:
                        should_send = True
                        topic = default_topic
                else:
                    should_send = True
                    topic = default_topic

        else:
            # حالت پیش‌فرض: ساعت SEND_HOUR روزانه
            if now.hour == SEND_HOUR and now.minute < 30:
                if last_report_time:
                    try:
                        last_dt = datetime.fromisoformat(last_report_time)
                        if (now - last_dt).total_seconds() > 3600:
                            should_send = True
                            topic = default_topic
                    except Exception:
                        should_send = True
                        topic = default_topic
                else:
                    should_send = True
                    topic = default_topic

        if should_send:
            log.info(f"📤 ارسال خودکار به {chat_id}")
            try:
                await send_report(
                    chat_id=chat_id,
                    topic=topic,
                    level=user.get("level", "public"),
                    language=user.get("language", "fa")
                )
                await asyncio.sleep(3)
            except Exception as e:
                log.error(f"❌ خطا ارسال به {chat_id}: {e}")


# ─────────────────────────────────────────
# وضعیت انتظار
# ─────────────────────────────────────────
waiting_state: dict[str, str] = {}


# ─────────────────────────────────────────
# پردازش پیام‌ها
# ─────────────────────────────────────────
async def handle_updates(updates: list):
    for update in updates:
        try:
            log.info(f"🔄 update_id={update.get('update_id')}")
            msg = update.get("message", {})
            text = msg.get("text", "").strip()
            chat_id = str(msg.get("chat", {}).get("id", ""))
            username = msg.get("from", {}).get("username", "")
            first_name = msg.get("from", {}).get("first_name", "")
            last_name = msg.get("from", {}).get("last_name", "")
            full_name = f"{first_name} {last_name}".strip()

            if not text or not chat_id:
                continue

            log.info(f"📩 {chat_id} (@{username}): '{text[:60]}'")

            data = load_data()
            if chat_id not in data["users"]:
                data["users"][chat_id] = default_user(chat_id, username, full_name)
                save_data(data)

            data["users"][chat_id]["username"] = username
            data["users"][chat_id]["full_name"] = full_name
            update_last_seen(data, chat_id)
            save_data(data)

            user = data["users"][chat_id]
            is_authorized = user.get("authorized", False)
            is_owner = (chat_id == TELEGRAM_CHAT_ID)

            # نگاشت دکمه‌های منو
            menu_map = {
                "📊 گزارش جدید": "/report",
                "✏️ موضوع دلخواه": "/topic",
                "🎚 سطح محتوا": "/level",
                "🌐 زبان": "/language",
                "⏰ زمان‌بندی": "/schedule",
                "📚 گزارش‌های قبلی": "/history",
                "❓ راهنما": "/help",
            }
            if text in menu_map:
                text = menu_map[text]

            # /start — همیشه
            if text in ["/start", "start"]:
                if is_authorized:
                    level_t = "🌍 عمومی" if user.get("level") == "public" else "🎓 تخصصی"
                    lang_t = {"fa": "🇮🇷 فارسی", "en": "🇬🇧 انگلیسی", "bilingual": "🌐 دوزبانه"}.get(user.get("language","fa"), "")
                    await send_msg(
                        f"سلام {first_name}! 👋\n\n"
                        f"🎚 سطح: {level_t} | {lang_t}\n\n"
                        f"از دکمه‌های پایین استفاده کن 👇",
                        chat_id=chat_id, show_menu=True
                    )
                else:
                    await send_msg(
                        "سلام! 👋\n\nاین ربات خصوصی است.\nرمز عبور را وارد کن:",
                        chat_id=chat_id
                    )
                continue

            # کاربر unauthorized
            if not is_authorized:
                if text == REPORT_PASSWORD:
                    data["users"][chat_id]["authorized"] = True
                    save_data(data)
                    log.info(f"✅ {chat_id} تأیید شد")
                    if TELEGRAM_CHAT_ID and chat_id != TELEGRAM_CHAT_ID:
                        await send_msg(
                            f"🔔 کاربر جدید:\n👤 {full_name} (@{username})\n🆔 {chat_id}\n📅 {datetime.now().strftime('%Y/%m/%d %H:%M')}",
                            chat_id=TELEGRAM_CHAT_ID
                        )
                    level_t = "🌍 عمومی"
                    await send_msg(
                        f"✅ خوش آمدی {first_name}! 🎉\n\n"
                        f"🎚 سطح پیش‌فرض: {level_t}\n"
                        f"🌐 زبان پیش‌فرض: 🇮🇷 فارسی\n\n"
                        f"از دکمه‌های پایین استفاده کن 👇",
                        chat_id=chat_id, show_menu=True
                    )
                else:
                    await send_msg("🔒 رمز اشتباه است. دوباره وارد کن:", chat_id=chat_id)
                continue

            # وضعیت انتظار
            state = waiting_state.get(chat_id)

            if state == "waiting_topic":
                waiting_state.pop(chat_id, None)
                await send_report(chat_id, text, user.get("level","public"), user.get("language","fa"))
                continue

            elif state == "waiting_schedule":
                waiting_state.pop(chat_id, None)
                await handle_schedule_input(chat_id, text, data)
                continue

            elif state == "waiting_level":
                waiting_state.pop(chat_id, None)
                if text.lower() in ["public", "عمومی", "1"]:
                    data["users"][chat_id]["level"] = "public"
                    save_data(data)
                    await send_msg("✅ سطح به 🌍 عمومی تغییر کرد.", chat_id=chat_id, show_menu=True)
                elif text.lower() in ["expert", "تخصصی", "2"]:
                    data["users"][chat_id]["level"] = "expert"
                    save_data(data)
                    await send_msg("✅ سطح به 🎓 تخصصی تغییر کرد.", chat_id=chat_id, show_menu=True)
                else:
                    await send_msg("لطفاً عدد 1 یا 2 را بنویس.", chat_id=chat_id)
                continue

            elif state == "waiting_language":
                waiting_state.pop(chat_id, None)
                if text in ["1", "fa", "فارسی"]:
                    data["users"][chat_id]["language"] = "fa"
                    save_data(data)
                    await send_msg("✅ زبان به 🇮🇷 فارسی تغییر کرد.", chat_id=chat_id, show_menu=True)
                elif text in ["2", "en", "انگلیسی"]:
                    data["users"][chat_id]["language"] = "en"
                    save_data(data)
                    await send_msg("✅ زبان به 🇬🇧 English تغییر کرد.", chat_id=chat_id, show_menu=True)
                elif text in ["3", "bilingual", "دوزبانه"]:
                    data["users"][chat_id]["language"] = "bilingual"
                    save_data(data)
                    await send_msg("✅ زبان به 🌐 دوزبانه تغییر کرد.", chat_id=chat_id, show_menu=True)
                else:
                    await send_msg("لطفاً عدد 1، 2 یا 3 را بنویس.", chat_id=chat_id)
                continue

            elif state == "waiting_topic_confirm":
                pending = waiting_state.pop(f"{chat_id}_pending_topic", None)
                waiting_state.pop(chat_id, None)
                if text.strip() in ["بله", "yes", "آره", "1"]:
                    if pending:
                        await send_report(chat_id, pending, user.get("level","public"), user.get("language","fa"))
                else:
                    await send_msg("باشه! از دکمه 📊 گزارش بگیر.", chat_id=chat_id, show_menu=True)
                continue

            # دستورات اصلی
            if text == "/report":
                topic = random.choice(TOPIC_POOL)
                await send_report(chat_id, topic, user.get("level","public"), user.get("language","fa"))

            elif text == "/topic":
                waiting_state[chat_id] = "waiting_topic"
                await send_msg(
                    "✏️ موضوع مورد نظرت را بنویس:\n\n"
                    "مثال‌ها:\n• اضطراب اجتماعی\n• تأثیر خواب بر حافظه\n"
                    "• روان‌شناسی تصمیم‌گیری\n• افسردگی و التهاب\n• اعتیاد و سیستم پاداش",
                    chat_id=chat_id
                )

            elif text == "/level":
                cur = "🌍 عمومی" if user.get("level","public") == "public" else "🎓 تخصصی"
                await send_msg(
                    f"🎚 سطح فعلی: {cur}\n\nانتخاب کن:\n1️⃣ عمومی — برای همه\n2️⃣ تخصصی — برای متخصصان",
                    chat_id=chat_id
                )
                waiting_state[chat_id] = "waiting_level"

            elif text == "/language":
                lang_map = {"fa": "🇮🇷 فارسی", "en": "🇬🇧 English", "bilingual": "🌐 دوزبانه"}
                cur = lang_map.get(user.get("language","fa"), "")
                await send_msg(
                    f"🌐 زبان فعلی: {cur}\n\nانتخاب کن:\n"
                    f"1️⃣ فارسی\n2️⃣ English\n3️⃣ دوزبانه (فارسی + English)",
                    chat_id=chat_id
                )
                waiting_state[chat_id] = "waiting_language"

            elif text == "/schedule":
                sh = user.get("schedule_hours")
                shr = user.get("schedule_hour")
                if sh:
                    cur = f"هر {sh} ساعت"
                elif shr is not None:
                    cur = f"هر روز ساعت {shr}:00"
                else:
                    cur = f"هر روز ساعت {SEND_HOUR}:00 (پیش‌فرض)"
                await send_msg(
                    f"⏰ زمان‌بندی فعلی: {cur}\n\n"
                    f"حالت‌ها:\n"
                    f"• بنویس i8 ← هر ۸ ساعت (interval)\n"
                    f"• بنویس i12 ← هر ۱۲ ساعت\n"
                    f"• بنویس i24 ← هر ۲۴ ساعت\n"
                    f"• بنویس h9 ← هر روز ساعت ۹ صبح\n"
                    f"• بنویس h18 ← هر روز ساعت ۶ عصر\n"
                    f"• بنویس 0 ← پیش‌فرض (ساعت {SEND_HOUR})\n\n"
                    f"حداقل فاصله بین گزارش‌ها: ۸ ساعت",
                    chat_id=chat_id
                )
                waiting_state[chat_id] = "waiting_schedule"

            elif text == "/history":
                reports = data.get("reports", {})
                user_reports = sorted(
                    [r for r in reports.values() if r.get("chat_id") == chat_id],
                    key=lambda x: x.get("date",""), reverse=True
                )[:10]
                if not user_reports:
                    await send_msg("هنوز گزارشی نداری! دکمه 📊 را بزن.", chat_id=chat_id, show_menu=True)
                else:
                    lang_icons = {"fa": "🇮🇷", "en": "🇬🇧", "bilingual": "🌐"}
                    history_text = "📚 آخرین گزارش‌های تو:\n\n"
                    for r in user_reports:
                        date = r.get("date","")[:10]
                        li = "🎓" if r.get("level") == "expert" else "🌍"
                        la = lang_icons.get(r.get("language","fa"), "")
                        history_text += f"{li}{la} #{r['id']} — {date}\n📝 {r.get('title','')}\n\n"
                    history_text += "برای دریافت مجدد: #شناسه را بفرست"
                    await send_msg(history_text, chat_id=chat_id, show_menu=True)

            elif text == "/help":
                await send_msg(
                    "📖 راهنما\n\n"
                    "📊 گزارش جدید — موضوع تصادفی\n"
                    "✏️ موضوع دلخواه — هر موضوعی\n"
                    "🎚 سطح محتوا — عمومی یا تخصصی\n"
                    "🌐 زبان — فارسی / انگلیسی / دوزبانه\n"
                    "⏰ زمان‌بندی — فاصله دریافت گزارش\n"
                    "📚 گزارش‌های قبلی — ۱۰ گزارش آخر\n\n"
                    "🔁 #شناسه را بفرست — گزارش قبلی\n"
                    "🔍 کلیدواژه — جستجو در گزارش‌ها",
                    chat_id=chat_id, show_menu=True
                )

            elif text == "/users" and is_owner:
                users = data.get("users", {})
                active = [u for u in users.values() if u.get("authorized")]
                lang_icons = {"fa": "🇮🇷", "en": "🇬🇧", "bilingual": "🌐"}
                msg_text = f"👥 کاربران مجاز: {len(active)}\n\n"
                for u in sorted(active, key=lambda x: x.get("last_seen",""), reverse=True):
                    last = u.get("last_seen","")[:16].replace("T"," ")
                    name = u.get("full_name","") or u.get("username","ناشناس")
                    uname = f"@{u['username']}" if u.get("username") else ""
                    li = "🎓" if u.get("level") == "expert" else "🌍"
                    la = lang_icons.get(u.get("language","fa"),"")
                    sh = u.get("schedule_hours")
                    shr = u.get("schedule_hour")
                    sched = f"هر {sh}ساعت" if sh else (f"ساعت {shr}" if shr is not None else "پیش‌فرض")
                    msg_text += (
                        f"{li}{la} {name} {uname}\n"
                        f"   🆔 {u['chat_id']} | ⏰ {sched}\n"
                        f"   🕐 {last}\n\n"
                    )
                await send_msg(msg_text, chat_id=chat_id)

            elif text.startswith("#"):
                report_id = text[1:]
                reports = data.get("reports", {})
                if report_id in reports:
                    stored = reports[report_id]
                    lang_icons = {"fa": "🇮🇷", "en": "🇬🇧", "bilingual": "🌐"}
                    li = "🎓" if stored.get("level") == "expert" else "🌍"
                    la = lang_icons.get(stored.get("language","fa"),"")
                    footer = f"\n\n{'━'*24}\n🆔 #{report_id} {li}{la}\n📝 {stored.get('title','')}"
                    await send_msg("📂 ارسال گزارش قبلی...", chat_id=chat_id)
                    await send_msg(stored["content"] + footer, chat_id=chat_id, show_menu=True)
                else:
                    await send_msg(f"گزارش #{report_id} پیدا نشد.", chat_id=chat_id, show_menu=True)

            elif len(text) > 3 and not text.startswith("/"):
                reports = data.get("reports", {})
                q = text.lower()
                best, best_score = None, 0
                for r in reports.values():
                    score = 0
                    if q in r.get("title","").lower(): score = 3
                    elif q in r.get("topic","").lower(): score = 2
                    else: score = sum(1 for w in q.split() if w in r.get("title","").lower() or w in r.get("topic","").lower())
                    if score > best_score:
                        best_score, best = score, r
                if best and best_score > 0:
                    lang_icons = {"fa": "🇮🇷", "en": "🇬🇧", "bilingual": "🌐"}
                    footer = f"\n\n{'━'*24}\n🆔 #{best['id']}\n📝 {best.get('title','')}"
                    await send_msg(f"🔍 پیدا شد: {best.get('title','')}\nارسال...", chat_id=chat_id)
                    await send_msg(best["content"] + footer, chat_id=chat_id, show_menu=True)
                else:
                    waiting_state[chat_id] = "waiting_topic_confirm"
                    waiting_state[f"{chat_id}_pending_topic"] = text
                    await send_msg(
                        f"گزارشی پیدا نشد.\n\nروی «{text}» گزارش جدید تهیه شود?\nبله / خیر",
                        chat_id=chat_id
                    )

        except Exception as e:
            log.error(f"❌ خطا: {e}")


async def handle_schedule_input(chat_id: str, text: str, data: dict):
    text = text.strip().lower()
    try:
        if text == "0":
            data["users"][chat_id]["schedule_hours"] = None
            data["users"][chat_id]["schedule_hour"] = None
            save_data(data)
            await send_msg(f"✅ پیش‌فرض: هر روز ساعت {SEND_HOUR}:00", chat_id=chat_id, show_menu=True)

        elif text.startswith("i"):
            hours = int(text[1:])
            if hours < 8 or hours > 168:
                await send_msg("⚠️ حداقل ۸ ساعت، حداکثر ۱۶۸ ساعت.", chat_id=chat_id)
                return
            data["users"][chat_id]["schedule_hours"] = hours
            data["users"][chat_id]["schedule_hour"] = None
            save_data(data)
            await send_msg(f"✅ هر {hours} ساعت گزارش می‌رسد.", chat_id=chat_id, show_menu=True)

        elif text.startswith("h"):
            hour = int(text[1:])
            if hour < 0 or hour > 23:
                await send_msg("⚠️ ساعت باید بین ۰ تا ۲۳ باشد.", chat_id=chat_id)
                return
            data["users"][chat_id]["schedule_hour"] = hour
            data["users"][chat_id]["schedule_hours"] = None
            save_data(data)
            await send_msg(f"✅ هر روز ساعت {hour}:00 گزارش می‌رسد.", chat_id=chat_id, show_menu=True)

        else:
            await send_msg(
                "فرمت اشتباه است.\n\nمثال‌ها:\n• i8 ← هر ۸ ساعت\n• h9 ← ساعت ۹ صبح\n• 0 ← پیش‌فرض",
                chat_id=chat_id
            )
    except ValueError:
        await send_msg("فرمت اشتباه. مثال: i8 یا h9 یا 0", chat_id=chat_id)


# ─────────────────────────────────────────
# Polling
# ─────────────────────────────────────────
async def poll_telegram_updates(offset: int = 0) -> tuple[list, int]:
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getUpdates"
    async with httpx.AsyncClient(timeout=40) as client:
        try:
            resp = await client.get(url, params={"offset": offset, "timeout": 30, "allowed_updates": ["message"]})
            data = resp.json()
            if not data.get("ok"):
                log.error(f"❌ Telegram: {data.get('description','')}")
                await asyncio.sleep(5)
                return [], offset
            updates = data.get("result", [])
            if updates:
                log.info(f"📩 {len(updates)} پیام")
                offset = updates[-1]["update_id"] + 1
            return updates, offset
        except httpx.ReadTimeout:
            return [], offset
        except Exception as e:
            log.error(f"❌ poll: {e}")
            await asyncio.sleep(5)
            return [], offset


async def telegram_listener():
    log.info("👂 listener شروع شد")
    offset = 0
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getUpdates",
                params={"offset": -1}
            )
            results = resp.json().get("result", [])
            if results:
                offset = results[-1]["update_id"] + 1
                log.info(f"⏭ offset={offset}")
    except Exception as e:
        log.warning(f"offset اولیه: {e}")

    while True:
        try:
            updates, offset = await poll_telegram_updates(offset)
            if updates:
                await handle_updates(updates)
            else:
                await asyncio.sleep(0.5)
        except Exception as e:
            log.error(f"❌ listener: {e}")
            await asyncio.sleep(5)


# ─────────────────────────────────────────
# اجرای اصلی
# ─────────────────────────────────────────
async def main():
    log.info(f"🤖 ربات v4.0 | ساعت پیش‌فرض: {SEND_HOUR}:00")

    data = load_data()
    if TELEGRAM_CHAT_ID:
        if TELEGRAM_CHAT_ID not in data["users"]:
            data["users"][TELEGRAM_CHAT_ID] = default_user(TELEGRAM_CHAT_ID)
        data["users"][TELEGRAM_CHAT_ID]["authorized"] = True
        save_data(data)

    if SEND_NOW == "1":
        await broadcast_scheduled()

    await send_msg(
        f"🧠 ربات روانشناسی علمی v4.0 فعال شد!\n\n"
        f"⏰ گزارش پیش‌فرض: ساعت {SEND_HOUR}:00\n"
        f"👥 کاربران: /users\n\n"
        f"از دکمه‌های پایین استفاده کن 👇",
        chat_id=TELEGRAM_CHAT_ID, show_menu=True
    )

    scheduler = AsyncIOScheduler(timezone=TIMEZONE)
    # هر ۳۰ دقیقه چک کن
    scheduler.add_job(
        broadcast_scheduled,
        trigger="interval",
        minutes=30,
        id="scheduler",
        replace_existing=True
    )
    scheduler.start()

    await telegram_listener()


if __name__ == "__main__":
    asyncio.run(main())
