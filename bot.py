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
        "interest_tags": [],      # تگ‌های علاقه‌مندی استخراج‌شده از موضوعات
        "topic_history": [],      # تاریخچه موضوعات با تاریخ (برای پیشنهاد هوشمند)
        "joined": datetime.now().isoformat(),
        "last_seen": datetime.now().isoformat(),
        "active": True, "authorized": False,
        "selected_persona": None,
        "last_concept_date": "",
        "last_manual_concept_date": "",
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

    has_sources = source_pack and "No verified sources" not in source_pack

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
📚 {"منابع" if language == "fa" else ("References" if language == "en" else "منابع | References")}
━━━━━━━━━━━━━━━━━━━━━━━━

REFERENCES RULES — READ CAREFULLY:
{"IF you cited real papers/books above: list ONLY those you actually used. Format: Author(s) (Year). Title. Journal/Publisher. Keep English titles in English — do NOT translate. Maximum 3 references." if has_sources else "NO database sources were available. Instead write 2-3 SHORT guidance sentences in the report language: mention the main researchers in this field by name, suggest relevant journal types, recommend one well-known book if you are certain it exists. NEVER fabricate a specific paper title, author name, year, or journal name."}

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
        ["🧬 پروفایل من", "🌅 مفهوم امروز"],
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
    "🧬 پروفایل من", "🌅 مفهوم امروز",
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
    "waiting_persona_topic_clarified": "🧑‍💼 انتخاب موضوع شخصیت",
    "waiting_level": "🎚 تغییر سطح",
    "waiting_language": "🌐 تغییر زبان",
    "waiting_schedule": "⏰ زمان‌بندی",
    "waiting_topic_confirm": "✏️ تأیید موضوع",
}

async def send_read_button(chat_id: str, report_id: str, topic: str):
    """
    ارسال دکمه علاقه‌سنجی زیر گزارش.
    برای جلوگیری از جهت‌گیری سریع، بعد از ۵ گزارش ارسال میشه.
    """
    data = load_data()
    # شمارش کل گزارش‌های این کاربر
    total_reports = sum(
        1 for r in data.get("reports", {}).values()
        if r.get("chat_id") == chat_id
    )
    # قبل از ۵ گزارش، دکمه نشون نده — کاربر هنوز در حال کشف هست
    if total_reports < 5:
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    async with httpx.AsyncClient(timeout=10) as client:
        await client.post(url, json={
            "chat_id": chat_id,
            "text": "این موضوع رو می‌خوای بیشتر دنبال کنی؟",
            "reply_markup": {
                "inline_keyboard": [[
                    {"text": "⭐ بله، بیشتر می‌خوام", "callback_data": f"read:{report_id}"},
                    {"text": "🚫 نه، موضوع دیگه‌ای", "callback_data": f"skip:{report_id}"},
                ]]
            }
        })


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

    # بررسی rate limit
    allowed, msg_err = check_rate_limit(chat_id)
    if not allowed:
        await send_msg(msg_err, chat_id=chat_id, show_menu=True)
        return None

    # بررسی تکراری بودن موضوع — اگه تکراری بود موضوع جدید از AI بگیر
    fresh_data = load_data()
    if is_topic_already_sent(fresh_data, chat_id, topic):
        topic = await generate_unique_topic(chat_id)
        await send_msg(
            f"📌 موضوع جدید انتخاب شد: {topic}",
            chat_id=chat_id
        )

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
            update_user_interests(data, chat_id, topic)
        save_data(data)

        footer = (
            f"\n\n{'━'*24}\n"
            f"🆔 #{report_id} | {level_label} | {lang_label}\n"
            f"📝 {title}\n"
            f"برای دریافت مجدد: #{report_id}"
        )
        await send_msg(content + footer, chat_id=chat_id, show_menu=True)
        log.info(f"🎉 #{report_id} ارسال شد")
        
        # دکمه تأیید خواندن
        await asyncio.sleep(1)
        await send_read_button(chat_id, report_id, topic)
        
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

        # دکمه علاقه‌سنجی — همان منطق send_report
        await asyncio.sleep(1)
        await send_read_button(chat_id, report_id, chosen_topic)

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



# ─────────────────────────────────────────
# Rate Limiting و جلوگیری از سوءاستفاده
# ─────────────────────────────────────────

# ذخیره زمان آخرین درخواست هر کاربر
_last_request: dict[str, float] = {}
_request_count: dict[str, list] = {}  # لیست زمان‌های درخواست در ۱۰ دقیقه اخیر

def check_rate_limit(chat_id: str) -> tuple[bool, str]:
    """
    Rate limiting پلکانی:
    ۱→۲: ۶۰ ثانیه
    ۲→۳: ۵ دقیقه
    ۳→۴: ۱۰ دقیقه
    ۵+: فردا
    """
    import time
    now = time.time()
    day_start = now - (now % 86400)  # شروع روز جاری (UTC)
    
    requests = _request_count.get(chat_id, [])
    # فقط درخواست‌های امروز
    today_requests = [t for t in requests if t >= day_start]
    
    count = len(today_requests)
    
    # ۵+ گزارش در روز — فردا بیا
    if count >= 5:
        seconds_to_tomorrow = int(86400 - (now % 86400))
        hours = seconds_to_tomorrow // 3600
        return False, f"⏳ امروز ۵ گزارش گرفتی — سهمیه روزانه تموم شد. فردا ساعت {hours} ساعت دیگه دوباره می‌تونی."
    
    # بررسی فاصله پلکانی
    last = _last_request.get(chat_id, 0)
    elapsed = now - last
    
    if count == 0:
        min_wait = 0
    elif count == 1:
        min_wait = 60      # ۶۰ ثانیه
    elif count == 2:
        min_wait = 300     # ۵ دقیقه
    elif count == 3:
        min_wait = 600     # ۱۰ دقیقه
    else:
        min_wait = 600
    
    if elapsed < min_wait:
        remaining = int(min_wait - elapsed)
        if remaining >= 60:
            return False, f"⏳ {remaining//60} دقیقه دیگر می‌توانی گزارش جدید بگیری."
        else:
            return False, f"⏳ {remaining} ثانیه دیگر می‌توانی گزارش جدید بگیری."
    
    # ثبت درخواست جدید
    today_requests.append(now)
    _last_request[chat_id] = now
    _request_count[chat_id] = today_requests
    return True, ""


def is_topic_already_sent(data: dict, chat_id: str, topic: str) -> bool:
    """بررسی اینکه این موضوع قبلاً به کاربر داده شده یا نه"""
    sent = set(data.get("users", {}).get(chat_id, {}).get("sent_topics", []))
    # بررسی مستقیم
    if topic in sent:
        return True
    # بررسی شباهت (موضوعات مشابه)
    topic_lower = topic.lower().strip()
    for s in sent:
        if s.lower().strip() == topic_lower:
            return True
    return False


async def generate_unique_topic(chat_id: str) -> str:
    """
    تولید موضوع کاملاً جدید از AI که قبلاً به این کاربر داده نشده.
    اگه AI خطا داد، از TOPIC_POOL موضوع نخورده برمیداره.
    """
    data = load_data()
    sent_topics = data.get("users", {}).get(chat_id, {}).get("sent_topics", [])
    interests = data.get("users", {}).get(chat_id, {}).get("interest_tags", [])
    
    # ساخت لیست موضوعات قبلی برای ارسال به AI
    recent_sent = sent_topics[-30:] if sent_topics else []
    sent_text = "\n".join(f"- {t}" for t in recent_sent) if recent_sent else "هیچ"
    interest_hint = ", ".join(interests[:5]) if interests else "روانشناسی عمومی"
    
    prompt = f"""You are generating a psychology topic for a Telegram bot report.

Topics already sent to this user (DO NOT repeat these or similar ones):
{sent_text}

User's interests: {interest_hint}

Generate ONE new, specific psychology topic in Persian that:
1. Has NOT been covered in the list above
2. Is based on real peer-reviewed research
3. Is specific enough for a focused report
4. Relates to the user's interests if possible

Output ONLY the topic name in Persian, nothing else. No explanation, no numbering.

Examples of good topics:
- نقش میکروبیوم روده در اضطراب و افسردگی
- روانشناسی پشیمانی و نظریه تأسف پیش‌بینی‌شده
- اثر موسیقی بر عملکرد شناختی و حافظه"""

    try:
        async with httpx.AsyncClient(timeout=20) as client:
            url = (
                f"https://generativelanguage.googleapis.com/v1beta/models/"
                f"gemini-2.5-flash-lite:generateContent?key={GEMINI_API_KEY}"
            )
            resp = await client.post(url, json={
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {"maxOutputTokens": 50, "temperature": 0.9},
            })
            if resp.status_code == 200:
                topic = resp.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
                topic = topic.strip("- ").strip()
                if topic and len(topic) > 5 and topic not in sent_topics:
                    log.info(f"🆕 موضوع جدید از AI: {topic[:40]}")
                    return topic
    except Exception as e:
        log.warning(f"⚠️ تولید موضوع از AI خطا: {e}")
    
    # fallback: از TOPIC_POOL موضوع نخورده
    sent_set = set(sent_topics)
    import random
    unsent = [t for t in TOPIC_POOL if t not in sent_set]
    if unsent:
        return random.choice(unsent)
    
    # اگه همه TOPIC_POOL هم رفته — قدیمی‌ترین‌ها رو فراموش کن
    data["users"][chat_id]["sent_topics"] = sent_topics[len(sent_topics)//2:]
    save_data(data)
    return random.choice(TOPIC_POOL)

# ─────────────────────────────────────────
# حافظه هوشمند
# ─────────────────────────────────────────

def update_user_interests(data: dict, chat_id: str, topic: str):
    """ذخیره تاریخچه موضوع — تگ‌ها از AI استخراج میشن نه لیست ثابت"""
    if chat_id not in data["users"]:
        return
    history = data["users"][chat_id].get("topic_history", [])
    history.append({"topic": topic, "date": datetime.now().strftime("%Y-%m-%d")})
    data["users"][chat_id]["topic_history"] = history[-50:]


async def extract_tags_from_topics(topics: list[str]) -> list[str]:
    """استخراج هوشمند تگ‌های علاقه‌مندی از موضوعات با AI"""
    if not topics:
        return []
    topics_text = chr(10).join(f"- {t}" for t in topics[-15:])
    prompt = f"""These are psychology topics a user has been interested in:
{topics_text}

Extract 5-8 core interest themes/tags in English (single words or short phrases).
Output ONLY comma-separated tags, nothing else.
Example: trauma, neuroscience, relationships, decision-making, mindfulness"""
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            url = (
                f"https://generativelanguage.googleapis.com/v1beta/models/"
                f"gemini-2.5-flash-lite:generateContent?key={GEMINI_API_KEY}"
            )
            resp = await client.post(url, json={
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {"maxOutputTokens": 60, "temperature": 0.3},
            })
            if resp.status_code == 200:
                text = resp.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
                tags = [t.strip().lower() for t in text.split(",") if t.strip()]
                return tags[:8]
    except Exception as e:
        log.warning(f"⚠️ tag extraction خطا: {e}")
    return []


async def get_smart_suggestion(chat_id: str) -> str | None:
    """پیشنهاد هوشمند بعد از علاقه‌گذاری — موضوعی که قبلاً نگرفته"""
    data = load_data()
    user = data.get("users", {}).get(chat_id, {})
    liked = [
        r.get("topic", "") for r in data.get("reports", {}).values()
        if r.get("chat_id") == chat_id and r.get("read") and r.get("topic")
    ]
    if len(liked) < 3:
        return None
    sent_topics = set(user.get("sent_topics", []))
    recent_liked = liked[-5:]
    prompt = f"""Psychology bot user liked these topics:
{chr(10).join(f"- {t}" for t in recent_liked)}

Topics already sent (do NOT suggest these): {", ".join(list(sent_topics)[-10:])}

Generate ONE short Persian suggestion (1 sentence max 20 words) for a related new topic.
Format exactly: "چون به [موضوع قبلی] علاقه داشتی — [موضوع پیشنهادی] رو هم دوست داری؟"
Must be a topic NOT in the already-sent list."""
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            url = (
                f"https://generativelanguage.googleapis.com/v1beta/models/"
                f"gemini-2.5-flash-lite:generateContent?key={GEMINI_API_KEY}"
            )
            resp = await client.post(url, json={
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {"maxOutputTokens": 80, "temperature": 0.7},
            })
            if resp.status_code == 200:
                return resp.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
    except Exception as e:
        log.warning(f"⚠️ پیشنهاد هوشمند خطا: {e}")
    return None


async def generate_user_profile(chat_id: str) -> str:
    """
    پروفایل روانشناختی هوشمند:
    - تگ‌ها از AI استخراج میشن
    - پیشنهادها با sent_topics چک میشن
    - cache 24 ساعته دارد
    """
    data = load_data()
    user = data.get("users", {}).get(chat_id, {})

    liked_topics = [
        r.get("topic", "") for r in data.get("reports", {}).values()
        if r.get("chat_id") == chat_id and r.get("read") and r.get("topic")
    ]
    liked_count = len(liked_topics)

    if liked_count == 0:
        return (
            "🧬 پروفایل روانشناختی\n\n"
            "هنوز داده‌ای برای تحلیل نداریم.\n\n"
            "چطور کار می‌کنه:\n"
            "• گزارش بگیر و با موضوعات مختلف آشنا شو\n"
            "• اگه موضوعی جذابت بود، ⭐ بزن\n"
            "• بعد از ۵ تا ⭐، پروفایل شخصی‌ات آماده میشه\n\n"
            "عجله نکن — هرچه بیشتر کاوش کنی، پروفایل دقیق‌تر میشه."
        )
    if liked_count < 5:
        remaining = 5 - liked_count
        bar = "⭐" * liked_count + "☆" * remaining
        return (
            f"🧬 پروفایل روانشناختی\n\n"
            f"پیشرفت: {bar}\n"
            f"({liked_count} از ۵)\n\n"
            f"{remaining} تا ⭐ دیگه کافیه.\n\n"
            f"ادامه بده — هر موضوع جدیدی که می‌خونی و ⭐ میزنی "
            f"پروفایلت رو دقیق‌تر می‌کنه."
        )

    # چک cache — اگه امروز پروفایل ساخته شده، همونو بده
    cached = user.get("profile_cache", {})
    today = datetime.now().strftime("%Y-%m-%d")
    if cached.get("date") == today and cached.get("text"):
        log.info(f"📋 پروفایل از cache برای {chat_id}")
        return cached["text"]

    # استخراج هوشمند تگ‌ها از AI
    all_liked = liked_topics[-15:]
    tags = await extract_tags_from_topics(all_liked)

    # لیست موضوعات ارسال‌شده (برای جلوگیری از پیشنهاد تکراری)
    sent_topics = user.get("sent_topics", [])
    sent_text = chr(10).join(f"- {t}" for t in sent_topics[-20:]) if sent_topics else "هیچ"

    liked_text = chr(10).join(f"- {t}" for t in all_liked)

    prompt = f"""A psychology bot user starred (liked) these topics:
{liked_text}

Their extracted interest themes: {", ".join(tags) if tags else "general psychology"}

Topics already sent to them (your recommendations must NOT include these):
{sent_text}

Write a warm, insightful psychological curiosity profile in Persian (180-220 words).
Be personal and specific — not generic.

STRICT FORMAT (use exactly):
🧬 پروفایل روانشناختی تو

[2-3 sentences describing their specific interests based on what they liked]

💡 این درباره‌ات می‌گوید:
[2 sentences of genuine psychological insight about what these interests reveal]

📚 سه موضوع که احتمالاً دوست داری:
• [completely new topic 1 — NOT in sent list]
• [completely new topic 2 — NOT in sent list]  
• [completely new topic 3 — NOT in sent list]

Note: make the 3 recommendations very specific psychology research topics, not generic titles."""

    try:
        async with httpx.AsyncClient(timeout=40) as client:
            url = (
                f"https://generativelanguage.googleapis.com/v1beta/models/"
                f"gemini-2.5-flash:generateContent?key={GEMINI_API_KEY}"
            )
            resp = await client.post(url, json={
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {"maxOutputTokens": 500, "temperature": 0.5},
            })
            if resp.status_code == 200:
                profile_text = resp.json()["candidates"][0]["content"]["parts"][0]["text"].strip()

                # ذخیره cache
                data["users"][chat_id]["profile_cache"] = {
                    "date": today,
                    "text": profile_text,
                    "tags": tags,
                }
                # آپدیت تگ‌ها
                data["users"][chat_id]["interest_tags"] = tags
                save_data(data)

                return profile_text
    except Exception as e:
        log.warning(f"⚠️ پروفایل خطا: {e}")

    return "⏳ در حال حاضر سرویس مشغول است. بعداً دوباره امتحان کن."


async def generate_daily_concept(chat_id: str = None) -> str:
    """تولید مفهوم روز — یک جمله علمی جدید و غیرتکراری"""
    import random

    # لیست کانسپت‌های قبلی این کاربر
    sent_concepts = []
    if chat_id:
        data = load_data()
        sent_concepts = data.get("users", {}).get(chat_id, {}).get("sent_concepts", [])

    all_topics = [
        "cognitive biases and decision-making", "attachment theory in adults",
        "neuroplasticity and learning", "emotional regulation strategies",
        "unconscious mind and behavior", "stress hormones and health",
        "social influence and conformity", "memory consolidation during sleep",
        "intrinsic vs extrinsic motivation", "mindfulness and the brain",
        "trauma and nervous system", "placebo effect mechanisms",
        "confirmation bias in everyday life", "sleep deprivation effects",
        "growth mindset neuroscience", "loneliness and physical health",
        "mirror neurons and empathy", "self-control and glucose",
        "fear conditioning and phobias", "flow state psychology",
        "psychological safety at work", "grief and cognitive function",
        "awe and wellbeing", "procrastination neuroscience",
        "body language and emotions", "music and memory",
    ]
    # حذف موضوعاتی که قبلاً فرستاده شده
    available = [t for t in all_topics if t not in sent_concepts]
    if not available:
        available = all_topics  # reset

    topic = random.choice(available)
    
    prompt = f"""You are writing a daily psychology insight for a Persian-speaking audience.

Topic area: {topic}

Write a SHORT Persian message (2-4 sentences, max 60 words total) that:

1. Opens with a real, verified scientific finding — stated simply and clearly
2. Immediately explains WHY it matters in everyday life with one concrete example
3. Leaves the reader thinking "interesting — I can actually use this"

RULES:
- Only write findings you are highly confident are real and well-established
- No jargon without explanation
- No heavy academic language
- The example must be from daily life (work, relationships, decisions, habits)
- Do NOT add a title, emoji, or source — just the 2-4 sentences

GOOD example output:
«مغز انسان وقتی یک کار را فقط تصور می‌کند، تقریباً همان مسیرهای عصبی را فعال می‌کند که موقع انجام واقعی آن. به همین دلیل ورزشکاران حرفه‌ای تمرین ذهنی می‌کنند — و تو هم می‌توانی قبل از یک مکالمه سخت، آن را در ذهنت مرور کنی تا واقعاً آماده‌تر باشی.»

BAD example (too vague):
«تحقیقات نشان می‌دهد که ذهن انسان قدرتمند است و می‌توان از آن استفاده کرد.»

Output ONLY the Persian sentences. Nothing else."""

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
                result = resp.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
                # ذخیره موضوع استفاده‌شده برای این کاربر
                if chat_id and result:
                    data = load_data()
                    if chat_id in data["users"]:
                        sc = data["users"][chat_id].get("sent_concepts", [])
                        if topic not in sc:
                            sc.append(topic)
                            data["users"][chat_id]["sent_concepts"] = sc[-30:]
                            save_data(data)
                return result
    except Exception as e:
        log.warning(f"⚠️ مفهوم روز خطا: {e}")

    return None


async def send_daily_concept_to_all():
    """
    ارسال مفهوم روز به همه کاربران — هر روز ساعت ۸ صبح.
    هر کاربر فقط یک کانسپت در روز دریافت می‌کند.
    """
    log.info("🌅 ارسال مفهوم روز به همه...")
    data = load_data()
    today = datetime.now().strftime("%Y-%m-%d")

    users_to_send = [
        u for u in data.get("users", {}).values()
        if u.get("authorized") and u.get("active")
        and u.get("last_concept_date", "") != today
    ]

    if not users_to_send:
        log.info("🌅 همه کاربران امروز کانسپت دریافت کرده‌اند")
        return

    log.info(f"🌅 ارسال مفهوم روز به {len(users_to_send)} کاربر")

    for user in users_to_send:
        try:
            chat_id = user["chat_id"]
            concept = await generate_daily_concept(chat_id=chat_id)
            if not concept:
                continue
            msg = "🌅 مفهوم امروز\n\n" + concept + "\n\n─────────────\n💡 گزارش کامل را با 📊 دریافت کن"
            await send_msg(msg, chat_id=chat_id)
            data["users"][chat_id]["last_concept_date"] = today
            save_data(data)
            await asyncio.sleep(2)
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
                topic = await generate_unique_topic(chat_id)
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
            
            # پردازش callback_query (دکمه‌های inline)
            if "callback_query" in update:
                await handle_callback(update["callback_query"])
                continue
            
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
                "🧬 پروفایل من": "/profile",
                "🌅 مفهوم امروز": "/concept_now",
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
                persona_key = user.get("selected_persona", "jung")
                lang = user.get("language", "fa")
                p = get_persona(persona_key)

                if text in ["/persona_random", "تصادفی"] or (p and f"موضوع تصادفی از {p['name_fa']}" in text):
                    waiting_state.pop(chat_id, None)
                    await send_persona_report(chat_id, persona_key, None, lang)
                elif p and f"موضوع دلخواه از {p['name_fa']}" in text:
                    # کاربر خواست موضوع بنویسه — منتظر بمون
                    await send_msg(
                        "✏️ موضوع مورد نظرت را بنویس:\n\n"
                        f"مثال‌هایی از حوزه {p['name_fa']}:\n"
                        + chr(10).join(f"• {t}" for t in (p["topics"][:4] if p else []))
                        + "\n\n(برای لغو: ❌)",
                        chat_id=chat_id, show_cancel=True
                    )
                else:
                    # کاربر موضوع نوشته — بررسی وضوح
                    waiting_state.pop(chat_id, None)
                    await send_msg("🔍 در حال بررسی موضوع...", chat_id=chat_id)
                    clarity = await check_topic_clarity(text)

                    if not clarity.get("clear", True) and clarity.get("question"):
                        waiting_state[chat_id] = "waiting_persona_topic_clarified"
                        waiting_state[f"{chat_id}_persona_topic"] = clarity.get("refined_topic") or text
                        await send_msg(
                            f"برای گزارش دقیق‌تر از دیدگاه {p['name_fa']} یک سوال دارم:\n\n"
                            f"❓ {clarity['question']}\n\n"
                            f"(یا بنویس: همین)",
                            chat_id=chat_id
                        )
                    else:
                        final_topic = clarity.get("refined_topic") or text
                        await send_persona_report(chat_id, persona_key, final_topic, lang)
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

            elif state == "waiting_persona_topic_clarified":
                original = waiting_state.pop(f"{chat_id}_persona_topic", text)
                waiting_state.pop(chat_id, None)
                persona_key = user.get("selected_persona", "jung")
                lang = user.get("language", "fa")
                if text.strip() in ["همین", "بله", "yes", "ok", "اوکی"]:
                    final_topic = original
                else:
                    final_topic = f"{original} — {text}"
                await send_persona_report(chat_id, persona_key, final_topic, lang)
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
                topic = await generate_unique_topic(chat_id)
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

            elif text == "/profile":
                profile = await generate_user_profile(chat_id)
                await send_msg(profile, chat_id=chat_id, show_menu=True)

            elif text == "/help":
                await send_msg(
                    "📖 راهنما\n\n"
                    "📊 گزارش جدید — موضوع جدید (هیچ‌وقت تکرار نمیشه)\n"
                    "✏️ موضوع دلخواه — هر موضوعی با راهنمای هوشمند\n"
                    "🎚 سطح محتوا — عمومی یا تخصصی\n"
                    "🌐 زبان — فارسی / انگلیسی / دوزبانه\n"
                    "🧑‍💼 شخصیت‌ها — فروید، یونگ، یالوم، فرانکل\n"
                    "🧬 پروفایل من — تحلیل علاقه‌مندی‌هات\n"
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

            elif text in ["/concept_now", "/concept"]:
                # کاربر می‌خواد مفهوم بگیره
                # قانون: ۱ خودکار (ساعت ۸) + ۱ دستی = حداکثر ۲ در روز
                today = datetime.now().strftime("%Y-%m-%d")
                auto_done = user.get("last_concept_date", "") == today
                manual_done = user.get("last_manual_concept_date", "") == today

                if manual_done:
                    await send_msg(
                        "🌅 امروز سهمیه مفهومت تموم شده!\n\n"
                        "هر روز ۲ مفهوم دریافت می‌کنی:\n"
                        "• یکی ساعت ۸ صبح (خودکار)\n"
                        "• یکی با فشردن این دکمه\n\n"
                        "فردا صبح ساعت ۸ مفهوم جدید میاد! ☀️",
                        chat_id=chat_id, show_menu=True
                    )
                else:
                    concept = await generate_daily_concept(chat_id=chat_id)
                    if concept:
                        msg = "🌅 مفهوم امروز\n\n" + concept + "\n\n─────────────\n💡 گزارش کامل را با 📊 دریافت کن"
                        await send_msg(msg, chat_id=chat_id, show_menu=True)
                        data["users"][chat_id]["last_manual_concept_date"] = today
                        if not auto_done:
                            data["users"][chat_id]["last_concept_date"] = today
                        save_data(data)
                    else:
                        await send_msg("⏳ در حال حاضر سرویس مشغول است.", chat_id=chat_id)

            elif text == "/concept_all" and is_owner:
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
async def handle_callback(callback: dict):
    """پردازش دکمه‌های inline (خوندم / بعداً)"""
    try:
        cdata = callback.get("data", "")
        chat_id = str(callback.get("from", {}).get("id", ""))
        callback_id = callback.get("id", "")
        message_id = callback.get("message", {}).get("message_id")
        
        # پاسخ به تلگرام که دکمه پردازش شد
        async with httpx.AsyncClient(timeout=10) as client:
            await client.post(
                f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/answerCallbackQuery",
                json={"callback_query_id": callback_id}
            )
        
        if cdata.startswith("read:"):
            report_id = cdata.split(":", 1)[1]
            data = load_data()
            report = data.get("reports", {}).get(report_id, {})
            topic = report.get("topic", "")
            
            if topic and chat_id:
                # ثبت در حافظه هوشمند
                update_user_interests(data, chat_id, topic)
                
                # علامت‌گذاری گزارش به عنوان خوانده‌شده
                data["reports"][report_id]["read"] = True
                data["reports"][report_id]["read_at"] = datetime.now().isoformat()
                save_data(data)
                
                # ویرایش پیام دکمه
                async with httpx.AsyncClient(timeout=10) as client:
                    await client.post(
                        f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/editMessageText",
                        json={
                            "chat_id": chat_id,
                            "message_id": message_id,
                            "text": "⭐ ثبت شد!",
                        }
                    )
                
                # اگه اولین ⭐ کاربره، توضیح بده
                if read_count == 1:
                    await asyncio.sleep(1)
                    await send_msg(
                        "⭐ اولین علامت‌گذاری ثبت شد!\n\n"
                        "هر ⭐ که میزنی، ربات یاد می‌گیره به چه حوزه‌هایی علاقه داری.\n\n"
                        "بعد از ۵ تا ⭐، پروفایل روانشناختی شخصی‌ات آماده میشه — "
                        "موضوعاتی که احتمالاً دوست داری، و بینشی درباره کنجکاوی‌هات.",
                        chat_id=chat_id
                    )
                
                # پیشنهاد هوشمند — فقط بعد از خواندن
                read_count = sum(
                    1 for r in data.get("reports", {}).values()
                    if r.get("chat_id") == chat_id and r.get("read")
                )
                # پیشنهاد هوشمند فقط بعد از ۵ علاقه‌گذاری — نه سریع‌تر
                if read_count >= 5:
                    suggestion = await get_smart_suggestion(chat_id)
                    if suggestion:
                        await asyncio.sleep(1)
                        await send_msg(f"💡 {suggestion}", chat_id=chat_id)
                elif read_count == 5:
                    # اولین بار که به ۵ رسید — اطلاع‌رسانی
                    await asyncio.sleep(1)
                    await send_msg(
                        "🧬 حالا که ۵ موضوع رو علامت‌گذاری کردی، "
                        "پروفایل روانشناختی‌ات آماده‌ست!\n"
                        "با /profile ببینش.",
                        chat_id=chat_id
                    )
                
                log.info(f"✅ گزارش #{report_id} خوانده‌شده ثبت شد")
        
        elif cdata.startswith("skip:"):
            # کاربر بعداً می‌خونه — فعلاً چیزی ثبت نمیشه
            async with httpx.AsyncClient(timeout=10) as client:
                await client.post(
                    f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/editMessageText",
                    json={
                        "chat_id": chat_id,
                        "message_id": message_id,
                        "text": "🚫 باشه — موضوعات متنوع‌تری پیشنهاد می‌شه.",
                    }
                )
    except Exception as e:
        log.error(f"❌ خطا در callback: {e}")


async def poll_telegram_updates(offset: int = 0) -> tuple[list, int]:
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getUpdates"
    async with httpx.AsyncClient(timeout=40) as client:
        try:
            resp = await client.get(url, params={"offset": offset, "timeout": 30, "allowed_updates": ["message", "callback_query"]})
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

    # مفهوم روز — هر روز ساعت ۸ صبح برای همه کاربران
    scheduler.add_job(send_daily_concept_to_all, trigger="cron",
                      hour=SEND_HOUR, minute=0,
                      id="daily_concept", replace_existing=True)
    scheduler.start()

    await telegram_listener()


if __name__ == "__main__":
    asyncio.run(main())
