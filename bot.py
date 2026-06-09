"""
🧠 Psychology Daily Bot — v5.0
محتوای علمی ناب، دو سطح واقعاً متفاوت، منابع تأییدشده
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
from sources import get_sources_for_topic, format_sources
from research import fetch_real_papers
from personas import (
    PERSONAS, get_persona, persona_keyboard,
    persona_from_button, build_persona_prompt
)

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID   = os.getenv("TELEGRAM_CHAT_ID",   "").strip()
GEMINI_API_KEY     = os.getenv("GEMINI_API_KEY",      "").strip()
SEND_HOUR          = int(os.getenv("SEND_HOUR", "8").strip().split()[0])
TIMEZONE           = os.getenv("TIMEZONE", "Asia/Tehran").strip()
SEND_NOW           = os.getenv("SEND_NOW", "0").strip()
REPORT_PASSWORD    = os.getenv("REPORT_PASSWORD", "psych123").strip()

# مدل‌ها به ترتیب اولویت + retry برای 503
MODELS = [
    "gemini-2.5-flash",       # اول Flash — پایدارتر، ۲۵۰/روز
    "gemini-2.5-flash-lite",  # دوم Lite — ۱۰۰۰/روز
    "gemini-2.5-pro",         # سوم Pro — فقط ۱۰۰/روز، آخر امتحان کن
    "gemini-2.0-flash",       # پشتیبان نهایی
]

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
        DATA_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        log.error(f"خطا در ذخیره: {e}")

def default_user(chat_id: str, username: str = "", full_name: str = "") -> dict:
    return {
        "chat_id": chat_id, "username": username, "full_name": full_name,
        "level": "public", "language": "fa",
        "schedule_hours": None, "schedule_hour": None,
        "last_report_time": None, "last_report_id": None,
        "joined": datetime.now().isoformat(),
        "last_seen": datetime.now().isoformat(),
        "active": True, "authorized": False,
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
    "بحران تکرارپذیری در روان‌شناسی",
    "نظریه ذهن و اوتیسم",
    "اثر هاله‌ای و سوگیری‌های شناختی",
    "آزمایش میلگرام و اطاعت از اقتدار",
    "نوروپلاستیسیتی مغز در بزرگسالی",
    "درمان EMDR برای تروما",
    "نظریه خودمختاری دسی و ریان",
    "پیاژه در مقابل ویگوتسکی",
    "اثر دانینگ-کروگر",
    "روان‌شناسی تکاملی",
    "ذهن‌آگاهی و پشتوانه علمی آن",
    "نظریه احساسات سازنده لیزا فلدمن بارت",
    "نقش ژنتیک و محیط در شخصیت",
]

# ─────────────────────────────────────────
# ساخت پرامپت
# ─────────────────────────────────────────
def build_prompt(topic: str, level: str, language: str, source_pack: str) -> str:
    today = datetime.now().strftime("%Y/%m/%d")

    # ── قانون زبان ──
    if language == "fa":
        lang_rule = """LANGUAGE RULE — ABSOLUTE:
▸ Write the ENTIRE report body in Persian (Farsi).
▸ For technical terms: write the Persian term, then the English in parentheses on first use only.
  Example: فرافکنی (Projection)، ناخودآگاه جمعی (Collective Unconscious)
▸ REFERENCES SECTION — critical rule:
  - If the paper/book authors wrote in English → keep the full reference in English exactly as it appears in SOURCE_PACK.
  - If the paper/book was originally written in Persian → write it in Persian.
  - Do NOT translate English titles or author names into Persian. Ever.
  - Write "منابع" as the section header."""

    elif language == "en":
        lang_rule = """LANGUAGE RULE — ABSOLUTE:
▸ Write the ENTIRE report in English only.
▸ References: keep exactly as in SOURCE_PACK, original language."""

    else:
        lang_rule = """LANGUAGE RULE — ABSOLUTE:
▸ Each section: Persian first (complete), then English immediately after (complete parallel).
▸ References: one list, keep each reference in its original language."""

    # ── تفاوت واقعی دو سطح ──
    if level == "expert":
        level_desc = """CONTENT LEVEL: EXPERT
Audience: psychologists, researchers, clinicians, graduate students.

Write as a knowledgeable colleague synthesizing the literature:
1. Trace the theoretical lineage: where did this concept come from, how has it evolved?
2. What do specific studies actually show — and how did they show it (methodology)?
3. Where do studies contradict each other, and what does that mean theoretically?
4. What are the key unresolved questions and ongoing debates?
5. What are the clinical or applied implications for a practitioner?

Style: precise, intellectually honest, collegial. No oversimplification, but no gratuitous statistics either.
Avoid: generic summaries, repetition, vague statements like "research shows"."""

    else:
        level_desc = """CONTENT LEVEL: GENERAL PUBLIC
Audience: curious, intelligent adults with no psychology background.

Write as a wise friend who genuinely wants the reader to understand something important:
1. Open with a concrete, relatable moment — something the reader has lived through — that this concept explains.
2. Use specific everyday scenarios to make abstract ideas tangible.
   GOOD: "فردی که همیشه از قطع‌کردن حرف دیگران عصبانی می‌شود، اغلب خودش همین کار را ناخودآگاه می‌کند"
   BAD: "این مفهوم در زندگی روزمره کاربرد فراوان دارد"
3. Teach one specific thing the reader can DO differently today — not generic advice.
4. Reveal one widely-held belief that the science shows is wrong or incomplete.
5. End with something that stays with the reader — a reframing, a paradox, a surprising truth.

Style: warm, curious, never condescending. Make the science feel personally relevant."""

    word_range = "400 تا 650 کلمه" if language != "bilingual" else "600 تا 900 کلمه"

    return f"""You are a scientific psychology educator writing a Telegram report.

{lang_rule}

{level_desc}

STRICT RULES — ALL MANDATORY:
1. SOURCE_PACK below contains real verified papers. Base your factual claims on them.
2. If SOURCE_PACK is empty or a claim cannot be traced to it: write "پژوهش‌ها نشان داده‌اند" or "according to research" WITHOUT a fabricated citation.
3. NEVER invent a paper title, author name, year, or journal. Readers will search for these.
4. References section: list ONLY sources you actually cited. Keep them in their ORIGINAL language.
5. NO emojis inside body paragraphs. Emojis allowed ONLY in section headers (1 per header max).
6. NO therapy advice, diagnosis, or medication recommendations.
7. NO exaggerated, motivational, or pseudoscientific language.
8. Length: {word_range}. Substantive but not padded.
9. Write the COMPLETE report. Do NOT stop before [END OF REPORT].
10. Do NOT write "[در این بخش منابع لیست می‌شوند]" or any placeholder text.

TODAY: {today}
TOPIC: {topic}
{source_pack if source_pack else "SOURCE_PACK: Empty — describe scientific consensus without fabricating citations."}

━━━━━━━━━━━━━━━━━━━━━━━━
🧠 {"روانشناسی امروز" if language != "en" else "Today's Psychology"} | {today}
━━━━━━━━━━━━━━━━━━━━━━━━

{"📌 موضوع: " + topic if language != "en" else "📌 Topic: " + topic}

━━━━━━━━━━━━━━━━━━━━━━━━
🔬 {"یافته‌های علمی" if language == "fa" else ("Scientific Findings" if language == "en" else "یافته‌های علمی | Scientific Findings")}
━━━━━━━━━━━━━━━━━━━━━━━━

[Write this section fully per level instructions — NO emojis in body text]

━━━━━━━━━━━━━━━━━━━━━━━━
⚡ {"نقد و چالش‌های علمی" if language == "fa" else ("Critical Analysis" if language == "en" else "نقد علمی | Critical Analysis")}
━━━━━━━━━━━━━━━━━━━━━━━━

[Honest about limitations, contradictions, unresolved debates — NO emojis in body text]

━━━━━━━━━━━━━━━━━━━━━━━━
💡 {"از دانش به عمل" if language == "fa" else ("From Knowledge to Action" if language == "en" else "از دانش به عمل | From Knowledge to Action")}
━━━━━━━━━━━━━━━━━━━━━━━━

[Specific and grounded — NO emojis in body text]

━━━━━━━━━━━━━━━━━━━━━━━━
📚 {"منابع" if language == "fa" else ("References" if language == "en" else "منابع | References")}
━━━━━━━━━━━━━━━━━━━━━━━━

[List only sources actually cited above. Keep each in its ORIGINAL language. No placeholders.]

━━━━━━━━━━━━━━━━━━━━━━━━
🔎 {"یک نکته ماندگار" if language == "fa" else ("One Lasting Insight" if language == "en" else "یک نکته ماندگار | One Lasting Insight")}
━━━━━━━━━━━━━━━━━━━━━━━━

[One genuinely surprising, memorable finding — changes how the reader sees something]

{"#روانشناسی_علمی #علم_روانشناسی #سلامت_روان #Psychology" if language == "fa" else ("#Psychology #Neuroscience #MentalHealth #Science" if language == "en" else "#روانشناسی_علمی #Psychology #سلامت_روان #Science")}
[END OF REPORT]"""


async def generate_content(topic: str, level: str, language: str) -> str:
    # ۱. جستجوی مقالات واقعی از پایگاه‌های داده
    log.info(f"🔍 جستجوی مقالات برای: {topic[:30]}")
    live_papers = await fetch_real_papers(topic)

    # ۲. منابع ثابت تأییدشده
    static_sources = get_sources_for_topic(topic)
    static_formatted = format_sources(static_sources)

    # اولویت: مقالات زنده؛ پشتیبان: منابع ثابت
    source_pack = live_papers if live_papers else static_formatted
    if not source_pack:
        source_pack = "\n\nNOTE: No verified sources found in databases for this specific topic. Describe the scientific consensus accurately without fabricating citations. Use 'طبق پژوهش‌های موجود' or 'researchers have found' without specific citations when uncertain."

    prompt = build_prompt(topic, level, language, source_pack)
    errors = []

    async with httpx.AsyncClient(timeout=120) as client:
        for model in MODELS:
            try:
                log.info(f"⏳ {model} | {level} | {language}")
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
                log.info(f"✅ تولید شد با {model} (finish={finish})")
                return content
            except httpx.HTTPStatusError as e:
                code = e.response.status_code
                body = e.response.text[:150]
                err = f"{model}: {code} — {body}"
                log.warning(f"⚠️ {err}")
                errors.append(err)
                if code == 503:
                    # سرور شلوغ — صبر بیشتر و دوباره امتحان همین مدل
                    log.info(f"⏳ 503 — ۱۵ ثانیه صبر...")
                    await asyncio.sleep(15)
                    try:
                        resp2 = await client.post(url, json={
                            "contents": [{"parts": [{"text": prompt}]}],
                            "generationConfig": {"maxOutputTokens": 8192, "temperature": 0.3, "stopSequences": ["[END OF REPORT]"]},
                        })
                        resp2.raise_for_status()
                        data2 = resp2.json()
                        content = data2["candidates"][0]["content"]["parts"][0]["text"]
                        log.info(f"✅ retry موفق با {model}")
                        return content
                    except Exception:
                        pass
                elif code == 429:
                    await asyncio.sleep(5)
                else:
                    await asyncio.sleep(3)
            except Exception as e:
                err = f"{model}: {type(e).__name__}: {str(e)[:100]}"
                log.warning(f"⚠️ {err}")
                errors.append(err)
                await asyncio.sleep(3)

    raise RuntimeError("همه مدل‌ها خطا:\n" + "\n".join(errors))


async def generate_persona_content(persona_key: str, topic: str | None, language: str) -> str:
    """تولید محتوا برای شخصیت‌های روانشناسی"""
    prompt = build_persona_prompt(persona_key, topic, language)
    errors = []

    async with httpx.AsyncClient(timeout=120) as client:
        for model in MODELS:
            try:
                log.info(f"⏳ {model} | persona={persona_key}")
                url = (
                    f"https://generativelanguage.googleapis.com/v1beta/models/"
                    f"{model}:generateContent?key={GEMINI_API_KEY}"
                )
                resp = await client.post(url, json={
                    "contents": [{"parts": [{"text": prompt}]}],
                    "generationConfig": {
                        "maxOutputTokens": 4096,
                        "temperature": 0.4,
                        "stopSequences": ["[END]"],
                    },
                })
                resp.raise_for_status()
                data = resp.json()
                candidate = data["candidates"][0]
                finish = candidate.get("finishReason", "")
                content = candidate["content"]["parts"][0]["text"]
                log.info(f"✅ persona محتوا تولید شد (finish={finish})")
                return content
            except httpx.HTTPStatusError as e:
                code = e.response.status_code
                body = e.response.text[:100]
                err = f"{model}: {code} — {body}"
                errors.append(err)
                log.warning(f"⚠️ {err}")
                if code == 503:
                    await asyncio.sleep(15)
                    try:
                        resp2 = await client.post(url, json={
                            "contents": [{"parts": [{"text": prompt}]}],
                            "generationConfig": {"maxOutputTokens": 4096, "temperature": 0.4, "stopSequences": ["[END]"]},
                        })
                        resp2.raise_for_status()
                        return resp2.json()["candidates"][0]["content"]["parts"][0]["text"]
                    except Exception:
                        pass
                else:
                    await asyncio.sleep(5)
            except Exception as e:
                err = f"{model}: {str(e)[:80]}"
                errors.append(err)
                log.warning(f"⚠️ {err}")
                await asyncio.sleep(3)

    raise RuntimeError("همه مدل‌ها خطا:\n" + "\n".join(errors))


async def send_persona_report(chat_id: str, persona_key: str, topic: str | None, language: str) -> None:
    """ارسال گزارش شخصیت به کاربر"""
    p = get_persona(persona_key)
    if not p:
        return

    await send_msg(
        f"⏳ در حال تهیه محتوا از دیدگاه {p['name_fa']}...\n(۲۰–۴۰ ثانیه)",
        chat_id=chat_id
    )
    try:
        content = await generate_persona_content(persona_key, topic, language)
        report_id = datetime.now().strftime("%m%d%H%M")

        data = load_data()
        data["reports"][report_id] = {
            "id": report_id,
            "title": f"{p['name_fa']} — {topic or 'موضوع تصادفی'}",
            "topic": topic or "persona",
            "level": "persona",
            "language": language,
            "content": content,
            "date": datetime.now().isoformat(),
            "chat_id": chat_id,
            "persona": persona_key,
        }
        if chat_id in data["users"]:
            data["users"][chat_id]["last_report_id"] = report_id
            data["users"][chat_id]["last_report_time"] = datetime.now().isoformat()
        save_data(data)

        footer = (
            f"\n\n{'━'*24}\n"
            f"🆔 #{report_id} | {p['emoji']} {p['name_fa']}\n"
            f"برای دریافت مجدد: #{report_id}"
        )
        # نمایش منو شخصیت‌ها بعد از گزارش
        await send_msg(content + footer, chat_id=chat_id, show_menu=True)

    except Exception as e:
        log.error(f"❌ persona error: {e}")
        await send_msg(
            "⏳ در حال حاضر سرویس مشغول است.\nلطفاً چند دقیقه دیگر دوباره امتحان کنید.",
            chat_id=chat_id, show_menu=True
        )
        if TELEGRAM_CHAT_ID and chat_id != TELEGRAM_CHAT_ID:
            try:
                await send_msg(f"⚠️ خطا persona {persona_key} — {chat_id}:\n{str(e)[:200]}", chat_id=TELEGRAM_CHAT_ID)
            except Exception:
                pass


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
        ["🧑‍💼 شخصیت‌های روانشناسی", "📚 گزارش‌های قبلی"],
        ["⏰ زمان‌بندی", "❓ راهنما"],
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
        f"⏳ در حال تهیه گزارش...\n{level_label} | {lang_label}\n📌 {topic}\n(۳۰–۹۰ ثانیه)",
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
        log.info(f"🎉 #{report_id} ارسال شد")
        return report_id
    except Exception as e:
        log.error(f"❌ خطا در تولید گزارش برای {chat_id}: {e}")
        user_msg = "⏳ در حال حاضر سرویس مشغول است.\n\nلطفاً چند دقیقه دیگر دوباره امتحان کنید."
        await send_msg(user_msg, chat_id=chat_id, show_menu=True)
        if TELEGRAM_CHAT_ID and chat_id != TELEGRAM_CHAT_ID:
            try:
                await send_msg(
                    f"⚠️ خطا — کاربر {chat_id}:\nموضوع: {topic}\nخطا: {str(e)[:300]}",
                    chat_id=TELEGRAM_CHAT_ID
                )
            except Exception:
                pass
        return None

async def broadcast_scheduled():
    data = load_data()
    now = datetime.now()
    day_of_year = now.timetuple().tm_yday
    default_topic = TOPIC_POOL[day_of_year % len(TOPIC_POOL)]

    for user in data["users"].values():
        if not user.get("active") or not user.get("authorized"):
            continue
        chat_id = user["chat_id"]
        schedule_hours = user.get("schedule_hours")
        schedule_hour = user.get("schedule_hour")
        last_report_time = user.get("last_report_time")
        should_send = False
        topic = random.choice(TOPIC_POOL)

        if schedule_hours:
            if last_report_time:
                try:
                    last_dt = datetime.fromisoformat(last_report_time)
                    if (now - last_dt).total_seconds() / 3600 >= schedule_hours:
                        should_send = True
                except Exception:
                    should_send = True
            else:
                should_send = True
        elif schedule_hour is not None:
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
            try:
                await send_report(chat_id, topic, user.get("level","public"), user.get("language","fa"))
                await asyncio.sleep(3)
            except Exception as e:
                log.error(f"❌ خطا ارسال به {chat_id}: {e}")


# ─────────────────────────────────────────
# وضعیت انتظار
# ─────────────────────────────────────────
waiting_state: dict[str, str] = {}


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
            log.info(f"📩 {chat_id}: '{text[:60]}'")

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
                "🧑‍💼 شخصیت‌های روانشناسی": "/personas",
                "⏰ زمان‌بندی": "/schedule",
                "📚 گزارش‌های قبلی": "/history",
                "❓ راهنما": "/help",
                "🔙 بازگشت به منو اصلی": "/start",
            }
            if text in menu_map:
                text = menu_map[text]

            # دکمه‌های شخصیت
            persona_key = persona_from_button(text)
            if persona_key and is_authorized:
                data["users"][chat_id]["selected_persona"] = persona_key
                save_data(data)
                p = get_persona(persona_key)
                lang = user.get("language", "fa")
                topics_list = "\n".join(f"• {t}" for t in p["topics"])

                # منو مخصوص شخصیت انتخاب‌شده
                persona_action_keyboard = {
                    "keyboard": [
                        [f"📖 موضوع دلخواه از {p['name_fa']}", f"🎲 موضوع تصادفی از {p['name_fa']}"],
                        ["🔙 بازگشت به منو اصلی"],
                    ],
                    "resize_keyboard": True,
                }
                url_kb = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
                async with httpx.AsyncClient(timeout=10) as cl:
                    await cl.post(url_kb, json={
                        "chat_id": chat_id,
                        "text": (
                            f"{p['emoji']} {p['name_fa']} ({p['name_en']})\n"
                            f"دوره: {p['years']}\n"
                            f"محورها: {p['tagline']}\n\n"
                            f"موضوعات پیشنهادی:\n{topics_list}\n\n"
                            f"یک موضوع بنویس یا گزینه زیر را انتخاب کن 👇"
                        ),
                        "reply_markup": persona_action_keyboard,
                    })
                waiting_state[chat_id] = "waiting_persona_topic"
                continue

            # /start
            if text in ["/start", "start"]:
                if is_authorized:
                    level_t = "🌍 عمومی" if user.get("level") == "public" else "🎓 تخصصی"
                    lang_t = {"fa":"🇮🇷 فارسی","en":"🇬🇧 English","bilingual":"🌐 دوزبانه"}.get(user.get("language","fa"),"")
                    await send_msg(
                        f"سلام {first_name}! 👋\n\n🎚 سطح: {level_t} | {lang_t}\n\nاز دکمه‌های پایین استفاده کن 👇",
                        chat_id=chat_id, show_menu=True
                    )
                else:
                    await send_msg("سلام! 👋\n\nاین ربات خصوصی است.\nرمز عبور را وارد کن:", chat_id=chat_id)
                continue

            # کاربر unauthorized
            if not is_authorized:
                if text == REPORT_PASSWORD:
                    data["users"][chat_id]["authorized"] = True
                    save_data(data)
                    if TELEGRAM_CHAT_ID and chat_id != TELEGRAM_CHAT_ID:
                        await send_msg(
                            f"🔔 کاربر جدید:\n👤 {full_name} (@{username})\n🆔 {chat_id}\n📅 {datetime.now().strftime('%Y/%m/%d %H:%M')}",
                            chat_id=TELEGRAM_CHAT_ID
                        )
                    await send_msg(
                        f"✅ خوش آمدی {first_name}! 🎉\n\n🎚 سطح پیش‌فرض: 🌍 عمومی\n🌐 زبان پیش‌فرض: 🇮🇷 فارسی\n\nاز دکمه‌های پایین استفاده کن 👇",
                        chat_id=chat_id, show_menu=True
                    )
                else:
                    await send_msg("🔒 رمز اشتباه است. دوباره وارد کن:", chat_id=chat_id)
                continue

            # وضعیت انتظار
            state = waiting_state.get(chat_id)

            if state == "waiting_persona_topic":
                waiting_state.pop(chat_id, None)
                persona_key = user.get("selected_persona", "jung")
                lang = user.get("language", "fa")
                p = get_persona(persona_key)
                # موضوع تصادفی
                if text in ["/persona_random", "تصادفی"] or (p and f"موضوع تصادفی از {p['name_fa']}" in text):
                    await send_persona_report(chat_id, persona_key, None, lang)
                elif p and f"موضوع دلخواه از {p['name_fa']}" in text:
                    # دوباره منتظر موضوع بمان
                    waiting_state[chat_id] = "waiting_persona_topic"
                    await send_msg(f"موضوع مورد نظرت را بنویس:", chat_id=chat_id)
                else:
                    await send_persona_report(chat_id, persona_key, text, lang)
                continue

            elif state == "waiting_topic":
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
                lang_options = {"1":"fa","fa":"fa","فارسی":"fa","2":"en","en":"en","انگلیسی":"en","3":"bilingual","bilingual":"bilingual","دوزبانه":"bilingual"}
                chosen = lang_options.get(text.lower())
                if chosen:
                    data["users"][chat_id]["language"] = chosen
                    save_data(data)
                    label = {"fa":"🇮🇷 فارسی","en":"🇬🇧 English","bilingual":"🌐 دوزبانه"}[chosen]
                    await send_msg(f"✅ زبان به {label} تغییر کرد.", chat_id=chat_id, show_menu=True)
                else:
                    await send_msg("لطفاً 1، 2 یا 3 بنویس.", chat_id=chat_id)
                continue
            elif state == "waiting_topic_confirm":
                pending = waiting_state.pop(f"{chat_id}_pending_topic", None)
                waiting_state.pop(chat_id, None)
                if text.strip() in ["بله","yes","آره","1"]:
                    if pending:
                        await send_report(chat_id, pending, user.get("level","public"), user.get("language","fa"))
                else:
                    await send_msg("باشه! از دکمه 📊 گزارش بگیر.", chat_id=chat_id, show_menu=True)
                continue

            # دستورات اصلی
            if text == "/personas":
                selected = user.get("selected_persona")
                p_selected = get_persona(selected) if selected else None
                current_text = f"\n\n📌 انتخاب فعلی تو: {p_selected['emoji']} {p_selected['name_fa']}" if p_selected else ""
                url_kb = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
                async with httpx.AsyncClient(timeout=10) as cl:
                    await cl.post(url_kb, json={
                        "chat_id": chat_id,
                        "text": (
                            f"🧑‍💼 شخصیت‌های روانشناسی{current_text}\n\n"
                            f"🛋 فروید — ناخودآگاه، رؤیا، سرکوب\n"
                            f"🌑 یونگ — کهن‌الگو، سایه، فردیت‌یابی\n"
                            f"🕯 یالوم — مرگ، آزادی، معنای زندگی\n"
                            f"🕊 فرانکل — رنج، معنا، امید\n\n"
                            f"یکی را انتخاب کن 👇"
                        ),
                        "reply_markup": persona_keyboard(),
                    })

            elif text == "/persona_random":
                persona_key = user.get("selected_persona", "jung")
                lang = user.get("language", "fa")
                await send_persona_report(chat_id, persona_key, None, lang)

            elif text == "/report":
                topic = random.choice(TOPIC_POOL)
                await send_report(chat_id, topic, user.get("level","public"), user.get("language","fa"))

            elif text == "/topic":
                waiting_state[chat_id] = "waiting_topic"
                await send_msg(
                    "✏️ موضوع مورد نظرت را بنویس:\n\n"
                    "مثال‌ها:\n• اضطراب اجتماعی\n• تأثیر خواب بر حافظه\n"
                    "• روان‌شناسی تصمیم‌گیری\n• افسردگی و التهاب\n• اعتیاد و سیستم پاداش\n"
                    "• سوگ و از دست دادن\n• وسواس فکری\n• بی‌خوابی و مغز",
                    chat_id=chat_id
                )

            elif text == "/level":
                cur = "🌍 عمومی" if user.get("level","public") == "public" else "🎓 تخصصی"
                await send_msg(
                    f"🎚 سطح فعلی: {cur}\n\n"
                    f"1️⃣ عمومی — با مثال‌های روزمره، برای همه\n"
                    f"2️⃣ تخصصی — با عمق نظری، برای متخصصان\n\n"
                    f"عدد انتخابت را بنویس:",
                    chat_id=chat_id
                )
                waiting_state[chat_id] = "waiting_level"

            elif text == "/language":
                lang_map = {"fa":"🇮🇷 فارسی","en":"🇬🇧 English","bilingual":"🌐 دوزبانه"}
                cur = lang_map.get(user.get("language","fa"),"")
                await send_msg(
                    f"🌐 زبان فعلی: {cur}\n\n1️⃣ فارسی\n2️⃣ English\n3️⃣ دوزبانه\n\nعدد انتخابت را بنویس:",
                    chat_id=chat_id
                )
                waiting_state[chat_id] = "waiting_language"

            elif text == "/schedule":
                sh = user.get("schedule_hours")
                shr = user.get("schedule_hour")
                cur = f"هر {sh} ساعت" if sh else (f"ساعت {shr}:00" if shr is not None else f"ساعت {SEND_HOUR}:00 (پیش‌فرض)")
                await send_msg(
                    f"⏰ زمان‌بندی فعلی: {cur}\n\n"
                    f"• i8 ← هر ۸ ساعت (حداقل)\n"
                    f"• i12 ← هر ۱۲ ساعت\n"
                    f"• i24 ← هر ۲۴ ساعت\n"
                    f"• h7 ← هر روز ساعت ۷ صبح\n"
                    f"• h20 ← هر روز ساعت ۸ شب\n"
                    f"• 0 ← پیش‌فرض (ساعت {SEND_HOUR})",
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
                    li = {"expert":"🎓","public":"🌍"}
                    la = {"fa":"🇮🇷","en":"🇬🇧","bilingual":"🌐"}
                    h = "📚 آخرین گزارش‌های تو:\n\n"
                    for r in user_reports:
                        h += f"{li.get(r.get('level','public'),'')}{la.get(r.get('language','fa'),'')} #{r['id']} — {r.get('date','')[:10]}\n📝 {r.get('title','')}\n\n"
                    h += "برای دریافت مجدد: #شناسه را بفرست"
                    await send_msg(h, chat_id=chat_id, show_menu=True)

            elif text == "/help":
                await send_msg(
                    "📖 راهنما\n\n"
                    "📊 گزارش جدید — موضوع تصادفی\n"
                    "✏️ موضوع دلخواه — هر موضوعی در روانشناسی\n"
                    "🎚 سطح محتوا — عمومی یا تخصصی\n"
                    "🌐 زبان — فارسی / انگلیسی / دوزبانه\n"
                    "🧑‍💼 شخصیت‌ها — فروید، یونگ، یالوم، فرانکل\n"
                    "⏰ زمان‌بندی — فاصله دریافت گزارش\n"
                    "📚 گزارش‌های قبلی — ۱۰ گزارش آخر\n\n"
                    "🔁 #شناسه — دریافت گزارش قبلی\n"
                    "🔍 کلیدواژه — جستجو در گزارش‌ها",
                    chat_id=chat_id, show_menu=True
                )

            elif text == "/users" and is_owner:
                users = data.get("users", {})
                active = [u for u in users.values() if u.get("authorized")]
                la = {"fa":"🇮🇷","en":"🇬🇧","bilingual":"🌐"}
                li = {"expert":"🎓","public":"🌍"}
                t = f"👥 کاربران مجاز: {len(active)}\n\n"
                for u in sorted(active, key=lambda x: x.get("last_seen",""), reverse=True):
                    name = u.get("full_name","") or u.get("username","ناشناس")
                    uname = f"@{u['username']}" if u.get("username") else ""
                    last = u.get("last_seen","")[:16].replace("T"," ")
                    sh = u.get("schedule_hours")
                    shr = u.get("schedule_hour")
                    sched = f"هر {sh}ساعت" if sh else (f"ساعت {shr}" if shr is not None else "پیش‌فرض")
                    t += f"{li.get(u.get('level','public'),'')}{la.get(u.get('language','fa'),'')} {name} {uname}\n   🆔 {u['chat_id']} | ⏰ {sched} | 🕐 {last}\n\n"
                await send_msg(t, chat_id=chat_id)

            elif text.startswith("#"):
                report_id = text[1:]
                reports = data.get("reports", {})
                if report_id in reports:
                    stored = reports[report_id]
                    li = {"expert":"🎓","public":"🌍"}
                    la = {"fa":"🇮🇷","en":"🇬🇧","bilingual":"🌐"}
                    footer = f"\n\n{'━'*24}\n🆔 #{report_id} {li.get(stored.get('level',''),'')}{la.get(stored.get('language',''),'')}\n📝 {stored.get('title','')}"
                    await send_msg("📂 ارسال گزارش قبلی...", chat_id=chat_id)
                    await send_msg(stored["content"] + footer, chat_id=chat_id, show_menu=True)
                else:
                    await send_msg(f"گزارش #{report_id} پیدا نشد.", chat_id=chat_id, show_menu=True)

            elif len(text) > 3 and not text.startswith("/"):
                reports = data.get("reports", {})
                q = text.lower()
                best, best_score = None, 0
                for r in reports.values():
                    s = 3 if q in r.get("title","").lower() else (2 if q in r.get("topic","").lower() else sum(1 for w in q.split() if w in r.get("title","").lower() or w in r.get("topic","").lower()))
                    if s > best_score:
                        best_score, best = s, r
                if best and best_score > 0:
                    la = {"fa":"🇮🇷","en":"🇬🇧","bilingual":"🌐"}
                    footer = f"\n\n{'━'*24}\n🆔 #{best['id']}\n📝 {best.get('title','')}"
                    await send_msg(f"🔍 پیدا شد: {best.get('title','')}", chat_id=chat_id)
                    await send_msg(best["content"] + footer, chat_id=chat_id, show_menu=True)
                else:
                    waiting_state[chat_id] = "waiting_topic_confirm"
                    waiting_state[f"{chat_id}_pending_topic"] = text
                    await send_msg(f"گزارشی پیدا نشد.\n\nروی «{text}» گزارش جدید تهیه شود?\nبله / خیر", chat_id=chat_id)

        except Exception as e:
            log.error(f"❌ خطا: {e}")


async def handle_schedule_input(chat_id: str, text: str, data: dict):
    text = text.strip().lower()
    try:
        if text == "0":
            data["users"][chat_id]["schedule_hours"] = None
            data["users"][chat_id]["schedule_hour"] = None
            save_data(data)
            await send_msg(f"✅ پیش‌فرض: ساعت {SEND_HOUR}:00", chat_id=chat_id, show_menu=True)
        elif text.startswith("i"):
            hours = int(text[1:])
            if hours < 8 or hours > 168:
                await send_msg("⚠️ حداقل ۸ ساعت، حداکثر ۱۶۸.", chat_id=chat_id)
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
            await send_msg("فرمت: i8 یا h9 یا 0", chat_id=chat_id)
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
    log.info(f"🤖 ربات v5.0 | ساعت پیش‌فرض: {SEND_HOUR}:00")

    data = load_data()
    if TELEGRAM_CHAT_ID:
        if TELEGRAM_CHAT_ID not in data["users"]:
            data["users"][TELEGRAM_CHAT_ID] = default_user(TELEGRAM_CHAT_ID)
        data["users"][TELEGRAM_CHAT_ID]["authorized"] = True
        save_data(data)

    if SEND_NOW == "1":
        await broadcast_scheduled()

    await send_msg(
        f"🧠 ربات روانشناسی علمی v5.0 فعال شد!\n\n"
        f"⏰ گزارش پیش‌فرض: ساعت {SEND_HOUR}:00\n"
        f"👥 مدیریت کاربران: /users\n\n"
        f"از دکمه‌های پایین استفاده کن 👇",
        chat_id=TELEGRAM_CHAT_ID, show_menu=True
    )

    scheduler = AsyncIOScheduler(timezone=TIMEZONE)
    scheduler.add_job(broadcast_scheduled, trigger="interval", minutes=30,
                      id="scheduler", replace_existing=True)
    scheduler.start()

    await telegram_listener()


if __name__ == "__main__":
    asyncio.run(main())
