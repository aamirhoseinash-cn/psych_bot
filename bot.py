"""
🧠 Psychology Daily Bot — v7.0
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
from queue_manager import ai_queue
import db

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID   = os.getenv("TELEGRAM_CHAT_ID",   "").strip()
GEMINI_API_KEY     = os.getenv("GEMINI_API_KEY",      "").strip()
MISTRAL_API_KEY    = os.getenv("MISTRAL_API_KEY",     "").strip()
GROQ_API_KEY       = os.getenv("GROQ_API_KEY",        "").strip()
SEND_HOUR          = int(os.getenv("SEND_HOUR", "8").strip().split()[0])
TIMEZONE           = os.getenv("TIMEZONE", "Asia/Tehran").strip()
SEND_NOW           = os.getenv("SEND_NOW", "0").strip()
REPORT_PASSWORD    = os.getenv("REPORT_PASSWORD", "psych123").strip()

# مدل‌های Gemini
GEMINI_MODELS = [
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite",
    "gemini-2.5-pro",
    "gemini-2.0-flash",
]

# مدل‌های Mistral (پشتیبان — 1 میلیارد توکن ماهانه رایگان)
MISTRAL_MODELS = [
    "mistral-small-latest",
    "open-mistral-nemo",
]

# مدل‌های Groq (پشتیبان — اگه سرور دسترسی داشت)
GROQ_MODELS = [
    "llama-3.3-70b-versatile",
    "llama-3.1-8b-instant",
]

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(message)s",
                    handlers=[logging.StreamHandler()])
log = logging.getLogger(__name__)

# ─────────────────────────────────────────
# پایگاه داده — از ماژول db استفاده می‌کند
# ─────────────────────────────────────────
def load_data() -> dict:
    return db.load_data()

def save_data(data: dict = None):
    db.save_data(data)

def default_user(chat_id: str, username: str = "", full_name: str = "") -> dict:
    return {
        "chat_id": chat_id, "username": username, "full_name": full_name,
        "level": "public", "language": "fa",
        "schedule_hours": None, "schedule_hour": None,
        "last_report_time": None, "last_report_id": None,
        "sent_topics": [],        # موضوعات ارسال‌شده — برای جلوگیری از تکرار
        "joined": datetime.now().isoformat(),
        "last_seen": datetime.now().isoformat(),
        "active": True, "authorized": False,
        "selected_persona": None,
    }

def update_last_seen(data: dict, chat_id: str):
    if chat_id in data["users"]:
        data["users"][chat_id]["last_seen"] = datetime.now().isoformat()

def mark_topic_sent(data: dict, chat_id: str, topic: str):
    """موضوع ارسال‌شده را ثبت می‌کند"""
    if chat_id in data["users"]:
        sent = data["users"][chat_id].get("sent_topics", [])
        if topic not in sent:
            sent.append(topic)
            # حداکثر ۵۰ موضوع آخر نگه می‌داریم
            data["users"][chat_id]["sent_topics"] = sent[-50:]

def pick_unsent_topic(data: dict, chat_id: str, pool: list) -> str:
    """موضوعی که قبلاً ارسال نشده رو انتخاب می‌کند"""
    sent = set(data.get("users", {}).get(chat_id, {}).get("sent_topics", []))
    unsent = [t for t in pool if t not in sent]
    if not unsent:
        # همه موضوعات قبلاً ارسال شده — reset کن
        data["users"][chat_id]["sent_topics"] = []
        unsent = pool
    return random.choice(unsent)

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
# پرامپت گزارش عمومی
# ─────────────────────────────────────────
def build_prompt(topic: str, level: str, language: str, source_pack: str) -> str:
    today = datetime.now().strftime("%Y/%m/%d")

    if language == "fa":
        lang_rule = """LANGUAGE — ABSOLUTE:
Write the ENTIRE report in Persian (Farsi) only.
Technical terms: Persian term + English in parentheses on first use. Example: سرکوب (Repression)
REFERENCES: Keep English references in English — do NOT translate titles or author names."""
    elif language == "en":
        lang_rule = "LANGUAGE — ABSOLUTE: Write the ENTIRE report in English only."
    else:
        lang_rule = """LANGUAGE — ABSOLUTE:
Each section: Persian first (complete), then English immediately after (complete parallel)."""

    if level == "expert":
        level_desc = """CONTENT LEVEL: EXPERT
Audience: psychologists, researchers, clinicians, graduate students.
— Trace the theoretical lineage and evolution of this concept
— Discuss what specific studies found and HOW (methodology matters)
— Where do studies contradict each other? What does that mean theoretically?
— Key unresolved questions and ongoing debates
— Clinical or applied implications
Style: collegial, precise, intellectually honest. No gratuitous statistics."""
    else:
        level_desc = """CONTENT LEVEL: GENERAL PUBLIC
Audience: curious intelligent adults with no psychology background.
— Open with a concrete relatable moment the reader has lived through
— Use specific everyday scenarios: work, relationships, family, habits
  GOOD: "وقتی هر بار با یک همکار خاص عصبانی می‌شوید اما نمی‌دانید چرا..."
  BAD: "این مفهوم در زندگی روزمره کاربرد فراوانی دارد"
— Teach one specific thing the reader can DO differently today
— Reveal one widely-held belief that science shows is wrong
Style: warm, curious, never condescending."""

    word_range = "400 تا 650 کلمه" if language != "bilingual" else "600 تا 900 کلمه"

    # بخش منابع — حرفه‌ای حتی وقتی منبعی نیست
    if source_pack and "No verified sources" not in source_pack:
        ref_instruction = """📚 منابع
List only sources you actually cited above. Keep each in its ORIGINAL language (English titles stay in English)."""
    else:
        ref_instruction = """📚 برای مطالعه بیشتر
Instead of a citations list (since no verified database sources were retrieved for this topic),
write 2–3 lines guiding the reader where to look:
— Name the key researchers in this area (e.g. "پژوهش‌های آرون بک در دهه ۱۹۷۰...")
— Suggest the type of literature to explore (e.g. "مقالات منتشرشده در مجلات Psychological Science و Journal of Consulting and Clinical Psychology")
— One general book recommendation if you are confident it exists
Do NOT fabricate specific paper titles or citation details."""

    return f"""You are a scientific psychology educator writing a Telegram report.

{lang_rule}

{level_desc}

STRICT RULES:
1. {source_pack if source_pack and "No verified" not in source_pack else "No verified database sources available — describe scientific consensus accurately without fabricating any citation."}
2. NEVER invent a paper title, author name, year, or journal. Readers will search these.
3. NO emojis inside body paragraphs. Only in section headers (max 1 each).
4. NO therapy advice, diagnosis, or medication recommendations.
5. NO exaggerated or pseudoscientific language.
6. Length: {word_range}. Complete and substantive.
7. You MUST write the COMPLETE report. Do NOT stop before [END OF REPORT].

TODAY: {today} | TOPIC: {topic}

━━━━━━━━━━━━━━━━━━━━━━━━
🧠 {"روانشناسی امروز" if language != "en" else "Today's Psychology"} | {today}
━━━━━━━━━━━━━━━━━━━━━━━━

{"📌 موضوع: " + topic if language != "en" else "📌 Topic: " + topic}

━━━━━━━━━━━━━━━━━━━━━━━━
🔬 {"یافته‌های علمی" if language == "fa" else ("Scientific Findings" if language == "en" else "یافته‌های علمی | Scientific Findings")}
━━━━━━━━━━━━━━━━━━━━━━━━

[Write fully per level instructions — NO emojis in body]

━━━━━━━━━━━━━━━━━━━━━━━━
⚡ {"نقد و چالش‌های علمی" if language == "fa" else ("Critical Analysis" if language == "en" else "نقد علمی | Critical Analysis")}
━━━━━━━━━━━━━━━━━━━━━━━━

[Honest about limitations, contradictions, debates — NO emojis in body]

━━━━━━━━━━━━━━━━━━━━━━━━
💡 {"از دانش به عمل" if language == "fa" else ("From Knowledge to Action" if language == "en" else "از دانش به عمل | From Knowledge to Action")}
━━━━━━━━━━━━━━━━━━━━━━━━

[Specific and grounded — NO emojis in body]

━━━━━━━━━━━━━━━━━━━━━━━━
{ref_instruction}
━━━━━━━━━━━━━━━━━━━━━━━━

🔎 {"یک نکته ماندگار" if language == "fa" else ("One Lasting Insight" if language == "en" else "یک نکته ماندگار | One Lasting Insight")}
━━━━━━━━━━━━━━━━━━━━━━━━

[One genuinely surprising memorable finding]

{"#روانشناسی_علمی #علم_روانشناسی #سلامت_روان #Psychology" if language == "fa" else ("#Psychology #Neuroscience #MentalHealth #Science" if language == "en" else "#روانشناسی_علمی #Psychology #سلامت_روان #Science")}
[END OF REPORT]"""


# ─────────────────────────────────────────
# تابع مرکزی Gemini با retry هوشمند
# ─────────────────────────────────────────
async def _try_gemini(prompt: str, max_tokens: int, stop: list, client: httpx.AsyncClient) -> str | None:
    """تلاش با مدل‌های Gemini"""
    for model in GEMINI_MODELS:
        for attempt in range(3):
            try:
                log.info(f"⏳ Gemini/{model} | تلاش {attempt+1}/3")
                url = (
                    f"https://generativelanguage.googleapis.com/v1beta/models/"
                    f"{model}:generateContent?key={GEMINI_API_KEY}"
                )
                resp = await client.post(url, json={
                    "contents": [{"parts": [{"text": prompt}]}],
                    "generationConfig": {"maxOutputTokens": max_tokens, "temperature": 0.35, "stopSequences": stop},
                })
                if resp.status_code == 503:
                    wait = 20 * (attempt + 1)
                    log.warning(f"⚠️ Gemini 503 — {wait}s صبر...")
                    await asyncio.sleep(wait)
                    continue
                if resp.status_code == 429:
                    log.warning(f"⚠️ Gemini 429 — مدل بعدی")
                    break
                resp.raise_for_status()
                candidate = resp.json()["candidates"][0]
                content = candidate["content"]["parts"][0]["text"]
                finish = candidate.get("finishReason", "")
                if finish == "MAX_TOKENS" and "منابع" not in content and "📚" not in content:
                    break
                log.info(f"✅ Gemini/{model} موفق")
                return content
            except (httpx.HTTPStatusError, httpx.ReadTimeout):
                await asyncio.sleep(10 if isinstance(Exception, httpx.ReadTimeout) else 5)
                if attempt < 2:
                    continue
                break
            except Exception as e:
                log.warning(f"⚠️ Gemini/{model}: {e}")
                break
    return None


async def _try_mistral(prompt: str, max_tokens: int, client: httpx.AsyncClient) -> str | None:
    """تلاش با مدل‌های Mistral — پشتیبان اول"""
    mistral_key = os.getenv("MISTRAL_API_KEY", "").strip()
    if not mistral_key:
        return None
    for model in MISTRAL_MODELS:
        try:
            log.info(f"⏳ Mistral/{model}")
            resp = await client.post(
                "https://api.mistral.ai/v1/chat/completions",
                headers={"Authorization": f"Bearer {mistral_key}", "Content-Type": "application/json"},
                json={
                    "model": model,
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": max_tokens,
                    "temperature": 0.35,
                },
            )
            if resp.status_code in [429, 503]:
                log.warning(f"⚠️ Mistral {resp.status_code}")
                await asyncio.sleep(10)
                continue
            resp.raise_for_status()
            content = resp.json()["choices"][0]["message"]["content"]
            log.info(f"✅ Mistral/{model} موفق")
            return content
        except Exception as e:
            log.warning(f"⚠️ Mistral/{model}: {e}")
    return None


async def _try_groq(prompt: str, max_tokens: int, client: httpx.AsyncClient) -> str | None:
    """تلاش با مدل‌های Groq — پشتیبان دوم"""
    if not GROQ_API_KEY:
        return None
    for model in GROQ_MODELS:
        try:
            log.info(f"⏳ Groq/{model}")
            resp = await client.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"},
                json={
                    "model": model,
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": min(max_tokens, 6000),
                    "temperature": 0.35,
                },
            )
            if resp.status_code in [429, 503]:
                log.warning(f"⚠️ Groq {resp.status_code}")
                continue
            resp.raise_for_status()
            content = resp.json()["choices"][0]["message"]["content"]
            log.info(f"✅ Groq/{model} موفق")
            return content
        except Exception as e:
            log.warning(f"⚠️ Groq/{model}: {e}")
    return None


async def call_ai(prompt: str, max_tokens: int = 8192, stop: list = None) -> str:
    """
    تابع مرکزی — Gemini اول، Mistral پشتیبان، Groq آخرین تلاش
    هر سه رایگان، بدون کارت بانکی
    """
    if stop is None:
        stop = ["[END OF REPORT]", "[END]"]

    async with httpx.AsyncClient(timeout=130) as client:
        # ۱. Gemini
        result = await _try_gemini(prompt, max_tokens, stop, client)
        if result:
            return result
        log.warning("⚠️ همه مدل‌های Gemini خطا دادند — سراغ Mistral...")

        # ۲. Mistral (پشتیبان)
        result = await _try_mistral(prompt, max_tokens, client)
        if result:
            return result
        log.warning("⚠️ Mistral هم خطا داد — سراغ Groq...")

        # ۳. Groq (آخرین تلاش)
        result = await _try_groq(prompt, max_tokens, client)
        if result:
            return result

    raise RuntimeError("هیچ سرویس AI‌ای در دسترس نیست. لطفاً چند دقیقه دیگر امتحان کنید.")


async def generate_content(topic: str, level: str, language: str) -> str:
    log.info(f"🔍 جستجوی مقالات: {topic[:30]}")
    live_papers = await fetch_real_papers(topic)
    static_sources = get_sources_for_topic(topic)
    static_formatted = format_sources(static_sources)
    source_pack = live_papers if live_papers else static_formatted
    if not source_pack:
        source_pack = "No verified sources — describe scientific consensus without fabricating citations."
    prompt = build_prompt(topic, level, language, source_pack)
    return await call_ai(prompt, max_tokens=8192, stop=["[END OF REPORT]"])


async def generate_persona_content(persona_key: str, topic, language: str) -> str:
    prompt = build_persona_prompt(persona_key, topic, language)
    return await call_ai(prompt, max_tokens=4096, stop=["[END]"])


# ─────────────────────────────────────────
# بررسی ابهام موضوع با Gemini
# ─────────────────────────────────────────
async def check_topic_clarity(topic: str) -> dict:
    """
    بررسی می‌کند آیا موضوع کافی واضح است یا نیاز به سوال دارد.
    Returns: {"clear": bool, "question": str | None, "refined_topic": str | None}
    """
    prompt = f"""A user wants a psychology report on: "{topic}"

Assess if this topic is clear enough to write a focused scientific report.

Respond in JSON only, no other text:
{{
  "clear": true/false,
  "confidence": "high/medium/low",
  "question": "clarifying question in Persian if needed, else null",
  "refined_topic": "more specific version of the topic if you can infer it, else null",
  "reason": "brief reason"
}}

Examples:
- "اضطراب" → not clear enough (too broad) → ask what aspect
- "اضطراب اجتماعی در نوجوانان" → clear
- "فروید" → not clear (just a name) → ask what aspect of Freud's work
- "اثر دارونما بر درد" → clear"""

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            url = (
                f"https://generativelanguage.googleapis.com/v1beta/models/"
                f"gemini-2.5-flash-lite:generateContent?key={GEMINI_API_KEY}"
            )
            resp = await client.post(url, json={
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {"maxOutputTokens": 200, "temperature": 0.1},
            })
            if resp.status_code != 200:
                return {"clear": True, "question": None, "refined_topic": None}
            text = resp.json()["candidates"][0]["content"]["parts"][0]["text"]
            # پاک‌سازی markdown
            text = text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
            result = json.loads(text)
            return result
    except Exception as e:
        log.warning(f"⚠️ topic clarity check خطا: {e}")
        return {"clear": True, "question": None, "refined_topic": None}


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

# کیبورد حالت انتظار — فقط دکمه لغو
CANCEL_KEYBOARD = {
    "keyboard": [["❌ لغو"]],
    "resize_keyboard": True,
    "one_time_keyboard": True,
}

# دکمه‌های منو که اگه در حالت انتظار زده شوند، حالت لغو می‌شود
MENU_BUTTONS = {
    "📊 گزارش جدید", "✏️ موضوع دلخواه", "🎚 سطح محتوا",
    "🌐 زبان", "🧑‍💼 شخصیت‌های روانشناسی", "📚 گزارش‌های قبلی",
    "⏰ زمان‌بندی", "❓ راهنما", "🔙 بازگشت به منو اصلی",
    "🛋 فروید", "🌑 یونگ", "🕯 یالوم", "🕊 فرانکل",
}

def cancel_waiting_state(chat_id: str) -> str | None:
    """حالت انتظار را لغو می‌کند و نام حالت لغوشده را برمی‌گرداند"""
    state = waiting_state.get(chat_id)
    if state:
        waiting_state.pop(chat_id, None)
        waiting_state.pop(f"{chat_id}_original_topic", None)
        waiting_state.pop(f"{chat_id}_pending_topic", None)
    return state

STATE_LABELS = {
    "waiting_topic": "✏️ موضوع دلخواه",
    "waiting_topic_clarified": "✏️ موضوع دلخواه",
    "waiting_persona_topic": "🧑‍💼 انتخاب موضوع شخصیت",
    "waiting_level": "🎚 تغییر سطح",
    "waiting_language": "🌐 تغییر زبان",
    "waiting_schedule": "⏰ زمان‌بندی",
    "waiting_topic_confirm": "✏️ تأیید موضوع",
}

async def send_msg(text: str, chat_id: str, show_menu: bool = False, show_cancel: bool = False) -> bool:
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
            elif show_cancel and i == total:
                payload["reply_markup"] = CANCEL_KEYBOARD
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
        content = await ai_queue.run(
            generate_content(topic, level, language),
            timeout=180
        )
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
            mark_topic_sent(data, chat_id, topic)
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
        log.error(f"❌ خطا برای {chat_id}: {e}")
        await send_msg(
            "⏳ در حال حاضر سرویس مشغول است.\nلطفاً چند دقیقه دیگر دوباره امتحان کنید.",
            chat_id=chat_id, show_menu=True
        )
        if TELEGRAM_CHAT_ID and chat_id != TELEGRAM_CHAT_ID:
            try:
                await send_msg(
                    f"⚠️ خطا — کاربر {chat_id}:\nموضوع: {topic}\nخطا: {str(e)[:300]}",
                    chat_id=TELEGRAM_CHAT_ID
                )
            except Exception:
                pass
        return None


async def send_persona_report(chat_id: str, persona_key: str, topic, language: str) -> None:
    p = get_persona(persona_key)
    if not p:
        return

    import random as _random
    chosen_topic = topic
    if not chosen_topic:
        data = load_data()
        sent = set(data.get("users", {}).get(chat_id, {}).get("sent_topics", []))
        persona_topics = [f"{persona_key}:{t}" for t in p["topics"]]
        unsent = [t for t in p["topics"] if f"{persona_key}:{t}" not in sent]
        if not unsent:
            unsent = p["topics"]
        chosen_topic = _random.choice(unsent)

    await send_msg(
        f"⏳ در حال تهیه محتوا از دیدگاه {p['name_fa']}...\n📌 {chosen_topic}\n(۲۰–۵۰ ثانیه)",
        chat_id=chat_id
    )
    try:
        content = await ai_queue.run(
            generate_persona_content(persona_key, chosen_topic, language),
            timeout=120
        )
        report_id = datetime.now().strftime("%m%d%H%M")

        data = load_data()
        data["reports"][report_id] = {
            "id": report_id,
            "title": f"{p['name_fa']} — {chosen_topic}",
            "topic": chosen_topic, "level": "persona", "language": language,
            "content": content, "date": datetime.now().isoformat(),
            "chat_id": chat_id, "persona": persona_key,
        }
        if chat_id in data["users"]:
            data["users"][chat_id]["last_report_id"] = report_id
            data["users"][chat_id]["last_report_time"] = datetime.now().isoformat()
            mark_topic_sent(data, chat_id, f"{persona_key}:{chosen_topic}")
        save_data(data)

        footer = (
            f"\n\n{'━'*24}\n"
            f"🆔 #{report_id} | {p['emoji']} {p['name_fa']}\n"
            f"برای دریافت مجدد: #{report_id}"
        )
        await send_msg(content + footer, chat_id=chat_id, show_menu=True)
    except Exception as e:
        log.error(f"❌ persona error: {e}")
        await send_msg(
            "⏳ در حال حاضر سرویس مشغول است.\nلطفاً چند دقیقه دیگر دوباره امتحان کنید.",
            chat_id=chat_id, show_menu=True
        )
        if TELEGRAM_CHAT_ID and chat_id != TELEGRAM_CHAT_ID:
            try:
                await send_msg(
                    f"⚠️ خطا persona {persona_key} — {chat_id}:\n{str(e)[:200]}",
                    chat_id=TELEGRAM_CHAT_ID
                )
            except Exception:
                pass


# ─────────────────────────────────────────
# گزارش روزانه فعالیت
# ─────────────────────────────────────────
async def send_daily_activity_report():
    if not TELEGRAM_CHAT_ID:
        return
    data = load_data()
    now = datetime.now()
    today_str = now.strftime("%Y/%m/%d")
    today_date = now.strftime("%Y-%m-%d")

    users = data.get("users", {})
    authorized = [u for u in users.values() if u.get("authorized")]
    active_today = [u for u in authorized if u.get("last_seen", "")[:10] == today_date]
    reports = data.get("reports", {})
    today_reports = [r for r in reports.values() if r.get("date", "")[:10] == today_date]

    lang_icons = {"fa": "🇮🇷", "en": "🇬🇧", "bilingual": "🌐"}
    level_icons = {"public": "🌍", "expert": "🎓"}

    msg = (
        f"📊 گزارش روزانه ربات — {today_str}\n"
        f"{'━'*24}\n\n"
        f"👥 کل کاربران مجاز: {len(authorized)}\n"
        f"✅ فعال امروز: {len(active_today)}\n"
        f"📄 گزارش‌های ارسالی امروز: {len(today_reports)}\n\n"
    )

    if active_today:
        msg += "📋 کاربران فعال امروز:\n"
        for u in sorted(active_today, key=lambda x: x.get("last_seen", ""), reverse=True):
            name = u.get("full_name", "") or u.get("username", "ناشناس")
            uname = f"@{u['username']}" if u.get("username") else ""
            last = u.get("last_seen", "")[:16].replace("T", " ")
            li = level_icons.get(u.get("level", "public"), "")
            la = lang_icons.get(u.get("language", "fa"), "")
            sh = u.get("schedule_hours")
            shr = u.get("schedule_hour")
            sched = f"هر {sh}h" if sh else (f"ساعت {shr}" if shr is not None else "پیش‌فرض")
            persona = u.get("selected_persona", "")
            persona_txt = f" | 🧑‍💼{persona}" if persona else ""
            msg += f"  {li}{la} {name} {uname}{persona_txt}\n  ⏰ {sched} | 🕐 {last}\n"
    else:
        msg += "⚠️ هیچ کاربری امروز فعال نبود.\n"

    if today_reports:
        msg += f"\n📈 موضوعات گزارش‌های امروز:\n"
        for r in today_reports[-8:]:
            li = "🎓" if r.get("level") == "expert" else ("🧑‍💼" if r.get("level") == "persona" else "🌍")
            msg += f"  {li} {r.get('title', '')[:45]}\n"

    await send_msg(msg, chat_id=TELEGRAM_CHAT_ID)
    log.info("📊 گزارش روزانه فعالیت ارسال شد")


# ─────────────────────────────────────────
# ارسال خودکار زمان‌بندی‌شده
# ─────────────────────────────────────────

async def generate_daily_concept() -> str:
    """تولید مفهوم روز — یک جمله کوتاه علمی"""
    import random
    topics = [
        "cognitive biases", "attachment theory", "neuroplasticity",
        "emotional regulation", "unconscious mind", "stress and cortisol",
        "social psychology", "memory and forgetting", "decision making",
        "mindfulness neuroscience", "trauma and the brain", "motivation psychology",
        "sleep and memory", "placebo effect", "confirmation bias",
    ]
    topic = random.choice(topics)
    
    prompt = f"""Generate ONE single sentence (max 40 words) in Persian about a surprising scientific finding related to: {topic}

Rules:
- Must be a genuine scientific finding
- Must be surprising or counterintuitive
- Include the researcher name or journal if possible
- No fabrication — only real findings you are confident about
- Format: [جمله علمی جالب]. منبع: [نام محقق یا مجله]

Example:
«تحقیقات نشان می‌دهد که مغز تصمیم‌های ما را ۷ ثانیه قبل از آنکه آگاهانه تصمیم بگیریم، می‌گیرد.» منبع: Soon et al., Nature Neuroscience, 2008

Output ONLY the Persian sentence and source, nothing else."""

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            url = (
                f"https://generativelanguage.googleapis.com/v1beta/models/"
                f"gemini-2.5-flash-lite:generateContent?key={GEMINI_API_KEY}"
            )
            resp = await client.post(url, json={
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {"maxOutputTokens": 150, "temperature": 0.7},
            })
            if resp.status_code == 200:
                return resp.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
    except Exception as e:
        log.warning(f"⚠️ مفهوم روز خطا: {e}")
    
    return None


async def send_daily_concept_to_all():
    """
    ارسال مفهوم روز به کاربرانی که نیم ساعت دیگر گزارش دارند.
    هر ۳۰ دقیقه یک بار چک می‌شود — مثل broadcast_scheduled.
    """
    log.info("🌅 چک ارسال مفهوم روز...")
    data = load_data()
    now = datetime.now()

    users_to_send = []
    for user in data.get("users", {}).values():
        if not user.get("authorized") or not user.get("active"):
            continue

        schedule_hours = user.get("schedule_hours")
        schedule_hour = user.get("schedule_hour")
        last_report_time = user.get("last_report_time")
        last_concept_date = user.get("last_concept_date", "")

        # جلوگیری از ارسال دوباره در همان روز
        if last_concept_date == now.strftime("%Y-%m-%d"):
            continue

        should_send = False

        if schedule_hours:
            # interval: نیم ساعت قبل از گزارش بعدی
            if last_report_time:
                try:
                    last_dt = datetime.fromisoformat(last_report_time)
                    hours_passed = (now - last_dt).total_seconds() / 3600
                    time_to_next = schedule_hours - hours_passed
                    if 0.4 <= time_to_next <= 0.6:  # ۲۴ تا ۳۶ دقیقه مانده
                        should_send = True
                except Exception:
                    pass
            else:
                should_send = True

        elif schedule_hour is not None:
            # ساعت مشخص: نیم ساعت قبل
            target_minute = schedule_hour * 60 - 30
            current_minute = now.hour * 60 + now.minute
            if abs(current_minute - target_minute) <= 15:
                should_send = True

        else:
            # پیش‌فرض: نیم ساعت قبل از SEND_HOUR
            target_minute = SEND_HOUR * 60 - 30
            current_minute = now.hour * 60 + now.minute
            if abs(current_minute - target_minute) <= 15:
                should_send = True

        if should_send:
            users_to_send.append(user)

    if not users_to_send:
        return

    log.info(f"🌅 ارسال مفهوم روز به {len(users_to_send)} کاربر")
    concept = await generate_daily_concept()
    if not concept:
        return

    msg = "🌅 مفهوم امروز\n\n" + concept + "\n\n─────────────\n💡 گزارش کامل را با 📊 دریافت کن"

    for user in users_to_send:
        try:
            await send_msg(msg, chat_id=user["chat_id"])
            # ثبت تاریخ ارسال
            data["users"][user["chat_id"]]["last_concept_date"] = now.strftime("%Y-%m-%d")
            save_data(data)
            await asyncio.sleep(1)
        except Exception as e:
            log.error(f"❌ خطا ارسال مفهوم به {user['chat_id']}: {e}")

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
                    except Exception:
                        should_send = True
                else:
                    should_send = True
        else:
            if now.hour == SEND_HOUR and now.minute < 30:
                if last_report_time:
                    try:
                        last_dt = datetime.fromisoformat(last_report_time)
                        if (now - last_dt).total_seconds() > 3600:
                            should_send = True
                    except Exception:
                        should_send = True
                else:
                    should_send = True

        if should_send:
            try:
                # انتخاب موضوع جدید (بدون تکرار)
                fresh_data = load_data()
                topic = pick_unsent_topic(fresh_data, chat_id, TOPIC_POOL)
                log.info(f"📤 ارسال خودکار به {chat_id} — موضوع: {topic[:30]}")
                await send_report(chat_id, topic, user.get("level", "public"), user.get("language", "fa"))
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

            # ── مدیریت حالت انتظار + دکمه لغو ──
            current_state = waiting_state.get(chat_id)

            # دکمه «❌ لغو» صریح
            if text == "❌ لغو" and current_state:
                state_label = STATE_LABELS.get(current_state, "عملیات جاری")
                cancel_waiting_state(chat_id)
                await send_msg(
                    f"❌ {state_label} لغو شد.",
                    chat_id=chat_id, show_menu=True
                )
                continue

            # کاربر در حالت انتظار بود و یه دکمه منو زد
            if current_state and (text in MENU_BUTTONS or text in menu_map):
                state_label = STATE_LABELS.get(current_state, "عملیات قبلی")
                cancel_waiting_state(chat_id)
                await send_msg(
                    f"↩️ {state_label} لغو شد.",
                    chat_id=chat_id
                )
                # ادامه پردازش دستور جدید

            if text in menu_map:
                text = menu_map[text]

            # دکمه‌های شخصیت
            persona_key = persona_from_button(text)
            if persona_key and is_authorized:
                data["users"][chat_id]["selected_persona"] = persona_key
                save_data(data)
                p = get_persona(persona_key)
                topics_list = "\n".join(f"• {t}" for t in p["topics"])
                persona_action_keyboard = {
                    "keyboard": [
                        [f"📖 موضوع دلخواه از {p['name_fa']}", f"🎲 موضوع تصادفی از {p['name_fa']}"],
                        ["🔙 بازگشت به منو اصلی"],
                    ],
                    "resize_keyboard": True,
                }
                async with httpx.AsyncClient(timeout=10) as cl:
                    await cl.post(
                        f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
                        json={
                            "chat_id": chat_id,
                            "text": (
                                f"{p['emoji']} {p['name_fa']} ({p['name_en']})\n"
                                f"دوره: {p['years']} | محورها: {p['tagline']}\n\n"
                                f"موضوعات پیشنهادی:\n{topics_list}\n\n"
                                f"یک موضوع بنویس یا گزینه زیر را انتخاب کن 👇\n(برای لغو: ❌)"
                            ),
                            "reply_markup": persona_action_keyboard,
                        }
                    )
                waiting_state[chat_id] = "waiting_persona_topic"
                continue

            # /start
            if text in ["/start", "start"]:
                if is_authorized:
                    level_t = "🌍 عمومی" if user.get("level") == "public" else "🎓 تخصصی"
                    lang_t = {"fa": "🇮🇷 فارسی", "en": "🇬🇧 English", "bilingual": "🌐 دوزبانه"}.get(user.get("language", "fa"), "")
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
                        f"✅ خوش آمدی {first_name}! 🎉\n\n🎚 سطح: 🌍 عمومی\n🌐 زبان: 🇮🇷 فارسی\n\nاز دکمه‌های پایین استفاده کن 👇",
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
                if text in ["/persona_random", "تصادفی"] or (p and f"موضوع تصادفی از {p['name_fa']}" in text):
                    await send_persona_report(chat_id, persona_key, None, lang)
                elif p and f"موضوع دلخواه از {p['name_fa']}" in text:
                    waiting_state[chat_id] = "waiting_persona_topic"
                    await send_msg("موضوع مورد نظرت را بنویس:", chat_id=chat_id)
                else:
                    await send_persona_report(chat_id, persona_key, text, lang)
                continue

            elif state == "waiting_topic":
                waiting_state.pop(chat_id, None)
                lang = user.get("language", "fa")
                level = user.get("level", "public")

                # بررسی وضوح موضوع
                await send_msg("🔍 در حال بررسی موضوع...", chat_id=chat_id)
                clarity = await check_topic_clarity(text)

                if not clarity.get("clear", True) and clarity.get("question"):
                    # موضوع مبهم است — سوال بپرس
                    refined = clarity.get("refined_topic")
                    waiting_state[chat_id] = "waiting_topic_clarified"
                    waiting_state[f"{chat_id}_original_topic"] = refined or text
                    await send_msg(
                        f"برای تهیه گزارش دقیق‌تر، یک سوال دارم:\n\n"
                        f"❓ {clarity['question']}\n\n"
                        f"(یا اگر همان موضوع کافی است، بنویس: همین)",
                        chat_id=chat_id
                    )
                else:
                    # موضوع واضح یا قابل استنتاج
                    final_topic = clarity.get("refined_topic") or text
                    await send_report(chat_id, final_topic, level, lang)
                continue

            elif state == "waiting_topic_clarified":
                original = waiting_state.pop(f"{chat_id}_original_topic", text)
                waiting_state.pop(chat_id, None)
                lang = user.get("language", "fa")
                level = user.get("level", "public")
                if text.strip() in ["همین", "بله", "yes", "ok", "اوکی"]:
                    final_topic = original
                else:
                    final_topic = f"{original} — {text}"
                await send_report(chat_id, final_topic, level, lang)
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
                    await send_msg("لطفاً 1 یا 2 بنویس.", chat_id=chat_id)
                continue

            elif state == "waiting_language":
                waiting_state.pop(chat_id, None)
                lang_options = {"1": "fa", "fa": "fa", "فارسی": "fa",
                                "2": "en", "en": "en", "انگلیسی": "en",
                                "3": "bilingual", "bilingual": "bilingual", "دوزبانه": "bilingual"}
                chosen = lang_options.get(text.lower())
                if chosen:
                    data["users"][chat_id]["language"] = chosen
                    save_data(data)
                    label = {"fa": "🇮🇷 فارسی", "en": "🇬🇧 English", "bilingual": "🌐 دوزبانه"}[chosen]
                    await send_msg(f"✅ زبان به {label} تغییر کرد.", chat_id=chat_id, show_menu=True)
                else:
                    await send_msg("لطفاً 1، 2 یا 3 بنویس.", chat_id=chat_id)
                continue

            elif state == "waiting_topic_confirm":
                pending = waiting_state.pop(f"{chat_id}_pending_topic", None)
                waiting_state.pop(chat_id, None)
                if text.strip() in ["بله", "yes", "آره", "1"] and pending:
                    await send_report(chat_id, pending, user.get("level", "public"), user.get("language", "fa"))
                else:
                    await send_msg("باشه! از دکمه 📊 گزارش بگیر.", chat_id=chat_id, show_menu=True)
                continue

            # دستورات اصلی
            if text == "/personas":
                selected = user.get("selected_persona")
                p_selected = get_persona(selected) if selected else None
                current_text = f"\n\n📌 انتخاب فعلی: {p_selected['emoji']} {p_selected['name_fa']}" if p_selected else ""
                async with httpx.AsyncClient(timeout=10) as cl:
                    await cl.post(
                        f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
                        json={
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
                        }
                    )

            elif text == "/persona_random":
                persona_key = user.get("selected_persona", "jung")
                lang = user.get("language", "fa")
                await send_persona_report(chat_id, persona_key, None, lang)

            elif text == "/report":
                fresh_data = load_data()
                topic = pick_unsent_topic(fresh_data, chat_id, TOPIC_POOL)
                await send_report(chat_id, topic, user.get("level", "public"), user.get("language", "fa"))

            elif text == "/topic":
                waiting_state[chat_id] = "waiting_topic"
                await send_msg(
                    "✏️ موضوع مورد نظرت را بنویس:\n\n"
                    "مثال‌ها:\n• اضطراب اجتماعی\n• تأثیر خواب بر حافظه\n"
                    "• روان‌شناسی تصمیم‌گیری\n• افسردگی و التهاب\n"
                    "• اعتیاد و سیستم پاداش\n• سوگ و از دست دادن\n\n"
                    "برای لغو: دکمه ❌ را بزن",
                    chat_id=chat_id, show_cancel=True
                )

            elif text == "/level":
                cur = "🌍 عمومی" if user.get("level", "public") == "public" else "🎓 تخصصی"
                await send_msg(
                    f"🎚 سطح فعلی: {cur}\n\n1️⃣ عمومی — با مثال‌های روزمره\n2️⃣ تخصصی — برای متخصصان\n\nعدد انتخابت را بنویس:\n(برای لغو: ❌)",
                    chat_id=chat_id, show_cancel=True
                )
                waiting_state[chat_id] = "waiting_level"

            elif text == "/language":
                lang_map = {"fa": "🇮🇷 فارسی", "en": "🇬🇧 English", "bilingual": "🌐 دوزبانه"}
                cur = lang_map.get(user.get("language", "fa"), "")
                await send_msg(
                    f"🌐 زبان فعلی: {cur}\n\n1️⃣ فارسی\n2️⃣ English\n3️⃣ دوزبانه\n\nعدد انتخابت را بنویس:\n(برای لغو: ❌)",
                    chat_id=chat_id, show_cancel=True
                )
                waiting_state[chat_id] = "waiting_language"

            elif text == "/schedule":
                sh = user.get("schedule_hours")
                shr = user.get("schedule_hour")
                cur = f"هر {sh} ساعت" if sh else (f"ساعت {shr}:00" if shr is not None else f"ساعت {SEND_HOUR}:00 (پیش‌فرض)")
                await send_msg(
                    f"⏰ زمان‌بندی فعلی: {cur}\n\n"
                    f"• i8 ← هر ۸ ساعت (حداقل)\n• i12 ← هر ۱۲ ساعت\n• i24 ← هر ۲۴ ساعت\n"
                    f"• h7 ← هر روز ساعت ۷ صبح\n• h20 ← هر روز ساعت ۸ شب\n"
                    f"• 0 ← پیش‌فرض (ساعت {SEND_HOUR})\n\n(برای لغو: ❌)",
                    chat_id=chat_id, show_cancel=True
                )
                waiting_state[chat_id] = "waiting_schedule"

            elif text == "/history":
                reports = data.get("reports", {})
                user_reports = sorted(
                    [r for r in reports.values() if r.get("chat_id") == chat_id],
                    key=lambda x: x.get("date", ""), reverse=True
                )[:10]
                if not user_reports:
                    await send_msg("هنوز گزارشی نداری! دکمه 📊 را بزن.", chat_id=chat_id, show_menu=True)
                else:
                    li = {"expert": "🎓", "public": "🌍", "persona": "🧑‍💼"}
                    la = {"fa": "🇮🇷", "en": "🇬🇧", "bilingual": "🌐"}
                    h = "📚 آخرین گزارش‌های تو:\n\n"
                    for r in user_reports:
                        h += f"{li.get(r.get('level','public'),'')}{la.get(r.get('language','fa'),'')} #{r['id']} — {r.get('date','')[:10]}\n📝 {r.get('title','')}\n\n"
                    h += "برای دریافت مجدد: #شناسه را بفرست"
                    await send_msg(h, chat_id=chat_id, show_menu=True)

            elif text == "/help":
                await send_msg(
                    "📖 راهنما\n\n"
                    "📊 گزارش جدید — موضوع جدید (بدون تکرار)\n"
                    "✏️ موضوع دلخواه — هر موضوعی با راهنمای هوشمند\n"
                    "🎚 سطح محتوا — عمومی یا تخصصی\n"
                    "🌐 زبان — فارسی / انگلیسی / دوزبانه\n"
                    "🧑‍💼 شخصیت‌ها — فروید، یونگ، یالوم، فرانکل\n"
                    "⏰ زمان‌بندی — فاصله دریافت گزارش\n"
                    "📚 گزارش‌های قبلی — ۱۰ گزارش آخر\n\n"
                    "🔁 #شناسه — دریافت گزارش قبلی\n"
                    "🔍 کلیدواژه — جستجو در گزارش‌ها",
                    chat_id=chat_id, show_menu=True
                )

            elif text == "/status" and is_owner:
                stats = ai_queue.stats()
                # مستقیم از دیسک بخون تا کش اثر نگذاره
                data_info = db._load_from_disk() if hasattr(db, '_load_from_disk') else load_data()
                users_count = len([u for u in data_info.get("users",{}).values() if u.get("authorized")])
                reports_count = len(data_info.get("reports", {}))
                today_count = sum(1 for r in data_info.get("reports",{}).values() if r.get("date","")[:10] == datetime.now().strftime("%Y-%m-%d"))
                await send_msg(
                    f"📡 وضعیت سرور v7.0\n\n"
                    f"🤖 AI Queue:\n"
                    f"  فعال: {stats['active']}/3\n"
                    f"  صف: {stats['queued']}\n"
                    f"  پردازش‌شده: {stats['processed']}\n"
                    f"  خطا: {stats['errors']}\n\n"
                    f"👥 کاربران مجاز: {users_count}\n"
                    f"📄 کل گزارش‌ها: {reports_count}\n"
                    f"📊 گزارش امروز: {today_count}\n\n"
                    f"🧠 مدل‌های AI:\n"
                    f"  Gemini: Flash/Lite/Pro/2.0\n"
                    f"  Mistral: {'✅' if os.getenv('MISTRAL_API_KEY','').strip() else '❌'}\n"
                    f"  Groq: {'✅' if os.getenv('GROQ_API_KEY','').strip() else '❌'}",
                    chat_id=chat_id
                )

            elif text == "/concept" and is_owner:
                # تست فوری مفهوم روز
                concept = await generate_daily_concept()
                if concept:
                    await send_msg(f"🌅 مفهوم امروز\n\n{concept}", chat_id=chat_id)
                else:
                    await send_msg("❌ خطا در تولید مفهوم", chat_id=chat_id)

            elif text == "/concept_all" and is_owner:
                # ارسال مفهوم روز به همه — برای تست
                await send_daily_concept_to_all()
                await send_msg("✅ مفهوم روز به همه ارسال شد", chat_id=chat_id)

            elif text == "/activity" and is_owner:
                await send_daily_activity_report()

            elif text == "/users" and is_owner:
                users = data.get("users", {})
                active = [u for u in users.values() if u.get("authorized")]
                la = {"fa": "🇮🇷", "en": "🇬🇧", "bilingual": "🌐"}
                li = {"expert": "🎓", "public": "🌍"}
                t = f"👥 کاربران مجاز: {len(active)}\n\n"
                for u in sorted(active, key=lambda x: x.get("last_seen", ""), reverse=True):
                    name = u.get("full_name", "") or u.get("username", "ناشناس")
                    uname = f"@{u['username']}" if u.get("username") else ""
                    last = u.get("last_seen", "")[:16].replace("T", " ")
                    sh = u.get("schedule_hours")
                    shr = u.get("schedule_hour")
                    sched = f"هر {sh}h" if sh else (f"ساعت {shr}" if shr is not None else "پیش‌فرض")
                    t += f"{li.get(u.get('level','public'),'')}{la.get(u.get('language','fa'),'')} {name} {uname}\n   🆔 {u['chat_id']} | ⏰ {sched} | 🕐 {last}\n\n"
                await send_msg(t, chat_id=chat_id)

            elif text.startswith("#"):
                report_id = text[1:]
                reports = data.get("reports", {})
                if report_id in reports:
                    stored = reports[report_id]
                    li = {"expert": "🎓", "public": "🌍", "persona": "🧑‍💼"}
                    la = {"fa": "🇮🇷", "en": "🇬🇧", "bilingual": "🌐"}
                    footer = f"\n\n{'━'*24}\n🆔 #{report_id} {li.get(stored.get('level',''),'')}{la.get(stored.get('language',''),'')}\n📝 {stored.get('title','')}"
                    await send_msg("📂 ارسال گزارش قبلی...", chat_id=chat_id)
                    await send_msg(stored["content"] + footer, chat_id=chat_id, show_menu=True)
                else:
                    await send_msg(f"گزارش #{report_id} پیدا نشد.", chat_id=chat_id, show_menu=True)

            elif len(text) > 3 and not text.startswith("/"):
                # جستجو در گزارش‌های قبلی
                reports = data.get("reports", {})
                q = text.lower()
                best, best_score = None, 0
                for r in reports.values():
                    s = 3 if q in r.get("title", "").lower() else (2 if q in r.get("topic", "").lower() else sum(1 for w in q.split() if w in r.get("title", "").lower() or w in r.get("topic", "").lower()))
                    if s > best_score:
                        best_score, best = s, r
                if best and best_score > 0:
                    la = {"fa": "🇮🇷", "en": "🇬🇧", "bilingual": "🌐"}
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
            log.error(f"❌ خطا در پردازش: {e}")


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

    # حل Conflict: صبر کن تا نسخه قبلی کاملاً بسته بشه
    await asyncio.sleep(3)

    # deleteWebhook برای پاک کردن هر webhook احتمالی
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            await client.post(
                f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/deleteWebhook",
                json={"drop_pending_updates": False}
            )
    except Exception:
        pass

    # گرفتن آخرین offset
    offset = 0
    for attempt in range(5):
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getUpdates",
                    params={"offset": -1, "timeout": 0}
                )
                data = resp.json()
                if data.get("ok"):
                    results = data.get("result", [])
                    if results:
                        offset = results[-1]["update_id"] + 1
                        log.info(f"⏭ offset={offset}")
                    break
                elif data.get("error_code") == 409:
                    log.warning(f"⚠️ Conflict هنوز هست — {3*(attempt+1)}s صبر...")
                    await asyncio.sleep(3 * (attempt + 1))
                else:
                    break
        except Exception as e:
            log.warning(f"offset اولیه attempt {attempt}: {e}")
            await asyncio.sleep(2)

    log.info(f"✅ listener آماده | offset={offset}")

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
    log.info(f"🤖 ربات v7.0 | ساعت پیش‌فرض: {SEND_HOUR}:00")

    data = load_data()
    if TELEGRAM_CHAT_ID:
        if TELEGRAM_CHAT_ID not in data["users"]:
            data["users"][TELEGRAM_CHAT_ID] = default_user(TELEGRAM_CHAT_ID)
        data["users"][TELEGRAM_CHAT_ID]["authorized"] = True
        save_data(data)

    if SEND_NOW == "1":
        await broadcast_scheduled()

    await send_msg(
        f"🧠 ربات روانشناسی علمی v7.0 فعال شد!\n\n"
        f"⏰ گزارش پیش‌فرض: ساعت {SEND_HOUR}:00\n"
        f"📊 گزارش فعالیت: /activity\n"
        f"👥 کاربران: /users\n\n"
        f"از دکمه‌های پایین استفاده کن 👇",
        chat_id=TELEGRAM_CHAT_ID, show_menu=True
    )

    # شروع ذخیره دوره‌ای دیتابیس
    asyncio.create_task(db.periodic_save())

    scheduler = AsyncIOScheduler(timezone=TIMEZONE)
    scheduler.add_job(broadcast_scheduled, trigger="interval", minutes=30,
                      id="scheduler", replace_existing=True)
    scheduler.add_job(send_daily_activity_report, trigger="cron",
                      hour=23, minute=0,
                      id="daily_activity_report", replace_existing=True)

    # مفهوم روز — هر ۳۰ دقیقه چک می‌کنه چه کسی نیم ساعت دیگر گزارش دارد
    scheduler.add_job(send_daily_concept_to_all, trigger="interval",
                      minutes=30,
                      id="daily_concept", replace_existing=True)
    scheduler.start()

    await telegram_listener()


if __name__ == "__main__":
    asyncio.run(main())
