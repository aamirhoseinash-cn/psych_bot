"""
🧠 Psychology Daily Bot — v3.1
- سیستم رمز ورود (فقط با رمز میشه استفاده کرد)
- گزارش به همه کاربران فعال
- موضوع دلخواه، دو سطح، زمان‌بندی شخصی
- سیستم عنوان + شناسه
- لاگ کاربران و آخرین فعالیت
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
        "level": "public",
        "schedule_hours": None,
        "last_report_id": None,
        "joined": datetime.now().isoformat(),
        "last_seen": datetime.now().isoformat(),
        "active": True,
        "authorized": False,   # تا رمز نزده، False هست
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
def build_prompt(topic: str, level: str) -> str:
    today = datetime.now().strftime("%Y/%m/%d")

    if level == "expert":
        audience = """TARGET AUDIENCE: Researchers, clinicians, graduate students.
STYLE: Precise technical terminology. Include statistical details (effect sizes, p-values, CIs).
Write as a peer reviewing literature for a colleague."""
        fa_findings = """[فارسی — ۵ پاراگراف علمی دقیق]
• اصطلاحات تخصصی با معادل انگلیسی در پرانتز
• آمار دقیق: اندازه اثر، فاصله اطمینان، مقدار p
• روش‌شناسی مطالعات (RCT، meta-analysis، longitudinal)
• مکانیسم‌های نوروبیولوژیک"""
        en_findings = "[English — 3 technical paragraphs with full statistical details]"
        fa_life = """[فارسی — ۳ پاراگراف]
• کاربرد بالینی مستقیم
• پروتکل‌های درمانی مبتنی بر شواهد
• اشتباهات رایج در تفسیر بالینی"""
        en_life = "[English — 2 paragraphs on evidence-based clinical applications]"
    else:
        audience = """TARGET AUDIENCE: Curious general public, no psychology background.
STYLE: Like a knowledgeable friend explaining over coffee. Simple but never dumbed-down.
Every complex idea needs a vivid real-life example from daily situations."""
        fa_findings = """[فارسی — ۴ پاراگراف روان]
• هر اصطلاح فنی = مثال روزمره بلافاصله بعد از آن
  مثال: «کورتیزول — همان هورمونی که وقتی رئیست صدات می‌کنه معده‌ات فرو می‌ریزه»
• موقعیت‌های آشنا: سرکار، خانه، روابط، امتحان
• داستانی روایت کن: چطور این کشف اتفاق افتاد؟
• اعداد قابل فهم: نه «۰.۳۲ effect size»، بلکه «از هر ۱۰ نفر، ۳ نفر...»"""
        en_findings = "[English — 3 accessible paragraphs with vivid everyday examples]"
        fa_life = """[فارسی — ۳ پاراگراف عملی با مثال مشخص]
• یک سناریوی کاملاً مشخص از زندگی روزمره
• دقیقاً چه کاری انجام بده — گام‌به‌گام
• یک باور غلط رایج که علم خلافش را نشان داده"""
        en_life = "[English — 2 practical paragraphs with specific actionable steps]"

    return f"""You are a neuroscientist and clinical psychologist creating a scientific report.

{audience}

CRITICAL RULES:
1. Base EVERY claim on REAL peer-reviewed papers — cite author, journal, year
2. PRIORITIZE studies from 2019–2024
3. If a classic theory has recent updates, ALWAYS mention them
4. Complete the ENTIRE report — do not stop before [END OF REPORT]

━━━━━━━━━━━━━━━━━━━━━━━━
🧠 روانشناسی امروز | Today's Psychology
📅 {today}
━━━━━━━━━━━━━━━━━━━━━━━━

📌 موضوع: {topic}
📌 Topic: [English title]

━━━━━━━━━━━━━━━━━━━━━━━━
🔬 یافته‌های علمی | Scientific Findings
━━━━━━━━━━━━━━━━━━━━━━━━
{fa_findings}

{en_findings}

━━━━━━━━━━━━━━━━━━━━━━━━
⚡ نقد علمی | Critical Analysis
━━━━━━━━━━━━━━━━━━━━━━━━

[فارسی — ۳ پاراگراف: انتقادات جدی، مطالعات متناقض (۲۰۲۰+)، محدودیت‌های روش‌شناختی]

[English — 2 paragraphs with specific critical studies]

━━━━━━━━━━━━━━━━━━━━━━━━
💡 از آزمایشگاه تا زندگی | From Lab to Life
━━━━━━━━━━━━━━━━━━━━━━━━

{fa_life}

{en_life}

━━━━━━━━━━━━━━━━━━━━━━━━
📚 منابع کلیدی | Key References
━━━━━━━━━━━━━━━━━━━━━━━━

[۳ مقاله peer-reviewed واقعی — فرمت: عنوان — نویسنده — مجله — سال]
[اولویت ۲۰۱۹–۲۰۲۴]

━━━━━━━━━━━━━━━━━━━━━━━━
🔎 جمله‌ای که ارزش دارد بدانید
━━━━━━━━━━━━━━━━━━━━━━━━

[یک یافته شگفت‌انگیز واقعی — فارسی و انگلیسی]

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
    raise RuntimeError("همه مدل‌ها خطا:\n" + "\n".join(errors))


def extract_title(content: str, topic: str) -> str:
    for line in content.split("\n"):
        if "📌 موضوع:" in line:
            t = line.replace("📌 موضوع:", "").strip()
            if t:
                return t[:60]
    return topic[:60]


# ─────────────────────────────────────────
# ارسال پیام با کیبورد منو
# ─────────────────────────────────────────
MENU_KEYBOARD = {
    "keyboard": [
        ["📊 گزارش جدید", "✏️ موضوع دلخواه"],
        ["🎚 تغییر سطح", "⏰ زمان‌بندی"],
        ["📚 گزارش‌های قبلی", "❓ راهنما"],
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
async def send_report(chat_id: str, topic: str, level: str = "public") -> str | None:
    level_label = "🎓 تخصصی" if level == "expert" else "🌍 عمومی"
    await send_msg(
        f"⏳ در حال تهیه گزارش {level_label}...\n📌 {topic}\n(۳۰–۶۰ ثانیه)",
        chat_id=chat_id
    )
    try:
        content = await generate_content(topic, level)
        report_id = datetime.now().strftime("%m%d%H%M")
        title = extract_title(content, topic)

        data = load_data()
        data["reports"][report_id] = {
            "id": report_id, "title": title, "topic": topic,
            "level": level, "content": content,
            "date": datetime.now().isoformat(), "chat_id": chat_id,
        }
        if chat_id in data["users"]:
            data["users"][chat_id]["last_report_id"] = report_id
            data["users"][chat_id]["last_seen"] = datetime.now().isoformat()
        save_data(data)

        footer = (
            f"\n\n{'━'*24}\n"
            f"🆔 شناسه: #{report_id}\n"
            f"📝 عنوان: {title}\n"
            f"🎚 سطح: {level_label}\n"
            f"برای دریافت مجدد: #{report_id} را بفرست"
        )
        await send_msg(content + footer, chat_id=chat_id, show_menu=True)
        log.info(f"🎉 گزارش #{report_id} ارسال شد به {chat_id}")
        return report_id
    except Exception as e:
        log.error(f"❌ خطا: {e}")
        await send_msg(f"❌ خطا:\n{str(e)}", chat_id=chat_id)
        return None


async def broadcast_daily():
    log.info("📢 ارسال روزانه...")
    data = load_data()
    day_of_year = datetime.now().timetuple().tm_yday
    topic = TOPIC_POOL[day_of_year % len(TOPIC_POOL)]
    for user in data["users"].values():
        if user.get("active") and user.get("authorized"):
            try:
                await send_report(user["chat_id"], topic, user.get("level", "public"))
                await asyncio.sleep(2)
            except Exception as e:
                log.error(f"❌ خطا ارسال به {user['chat_id']}: {e}")


# ─────────────────────────────────────────
# وضعیت انتظار کاربران
# ─────────────────────────────────────────
waiting_state: dict[str, str] = {}


# ─────────────────────────────────────────
# پردازش پیام‌ها
# ─────────────────────────────────────────
async def handle_updates(updates: list):
    for update in updates:
        try:
            log.info(f"🔄 update_id: {update.get('update_id')}")
            msg = update.get("message", {})
            text = msg.get("text", "").strip()
            chat_id = str(msg.get("chat", {}).get("id", ""))
            username = msg.get("from", {}).get("username", "")
            first_name = msg.get("from", {}).get("first_name", "")
            last_name = msg.get("from", {}).get("last_name", "")
            full_name = f"{first_name} {last_name}".strip()

            if not text or not chat_id:
                continue

            log.info(f"📩 از {chat_id} (@{username}): '{text[:60]}'")

            data = load_data()

            # ثبت کاربر جدید (هنوز unauthorized)
            if chat_id not in data["users"]:
                data["users"][chat_id] = default_user(chat_id, username, full_name)
                save_data(data)
                log.info(f"👤 کاربر جدید ثبت شد: {chat_id}")

            # بروزرسانی اطلاعات کاربر
            data["users"][chat_id]["username"] = username
            data["users"][chat_id]["full_name"] = full_name
            update_last_seen(data, chat_id)
            save_data(data)

            user = data["users"][chat_id]
            is_authorized = user.get("authorized", False)
            is_owner = (chat_id == TELEGRAM_CHAT_ID)

            # ── نگاشت دکمه‌های منو ──
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

            # ── /start — همیشه قابل دسترس ──
            if text in ["/start", "start"]:
                if is_authorized:
                    level_text = "🌍 عمومی" if user.get("level") == "public" else "🎓 تخصصی"
                    await send_msg(
                        f"سلام {first_name}! 👋\n\n"
                        f"🎚 سطح فعلی: {level_text}\n\n"
                        f"از دکمه‌های پایین استفاده کن 👇",
                        chat_id=chat_id, show_menu=True
                    )
                else:
                    await send_msg(
                        "سلام! 👋\n\n"
                        "این ربات خصوصی است.\n"
                        "برای دسترسی، رمز عبور را وارد کن:",
                        chat_id=chat_id
                    )
                continue

            # ── بررسی رمز (برای کاربران unauthorized) ──
            if not is_authorized:
                if text == REPORT_PASSWORD:
                    data["users"][chat_id]["authorized"] = True
                    save_data(data)
                    log.info(f"✅ کاربر {chat_id} (@{username}) تأیید شد")

                    # اطلاع به سازنده
                    if TELEGRAM_CHAT_ID and chat_id != TELEGRAM_CHAT_ID:
                        await send_msg(
                            f"🔔 کاربر جدید وارد شد:\n"
                            f"👤 {full_name} (@{username})\n"
                            f"🆔 {chat_id}\n"
                            f"📅 {datetime.now().strftime('%Y/%m/%d %H:%M')}",
                            chat_id=TELEGRAM_CHAT_ID
                        )

                    level_text = "🌍 عمومی" if user.get("level") == "public" else "🎓 تخصصی"
                    await send_msg(
                        f"✅ رمز صحیح! خوش آمدی {first_name} 🎉\n\n"
                        f"🎚 سطح فعلی: {level_text}\n\n"
                        f"از دکمه‌های پایین استفاده کن 👇",
                        chat_id=chat_id, show_menu=True
                    )
                else:
                    await send_msg(
                        "🔒 رمز عبور اشتباه است.\nلطفاً رمز را وارد کن:",
                        chat_id=chat_id
                    )
                continue

            # ── از اینجا به بعد فقط کاربران authorized ──

            # بررسی وضعیت انتظار
            state = waiting_state.get(chat_id)

            if state == "waiting_topic":
                waiting_state.pop(chat_id, None)
                topic = text
                level = user.get("level", "public")
                await send_report(chat_id=chat_id, topic=topic, level=level)
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
                    await send_msg(
                        "✅ سطح به 🌍 عمومی تغییر کرد!\n"
                        "گزارش‌ها با زبان ساده و مثال‌های روزمره.",
                        chat_id=chat_id, show_menu=True
                    )
                elif text.lower() in ["expert", "تخصصی", "2"]:
                    data["users"][chat_id]["level"] = "expert"
                    save_data(data)
                    await send_msg(
                        "✅ سطح به 🎓 تخصصی تغییر کرد!\n"
                        "گزارش‌ها با جزئیات آماری و اصطلاحات تخصصی.",
                        chat_id=chat_id, show_menu=True
                    )
                else:
                    await send_msg("لطفاً public یا expert بنویس.", chat_id=chat_id)
                continue

            elif state == "waiting_topic_confirm":
                pending = waiting_state.pop(f"{chat_id}_pending_topic", None)
                waiting_state.pop(chat_id, None)
                if text.strip() in ["بله", "yes", "آره"]:
                    if pending:
                        await send_report(chat_id=chat_id, topic=pending,
                                          level=user.get("level", "public"))
                else:
                    await send_msg(
                        "باشه! برای گزارش جدید دکمه 📊 را بزن.",
                        chat_id=chat_id, show_menu=True
                    )
                continue

            # ── دستورات اصلی ──

            if text == "/report":
                topic = random.choice(TOPIC_POOL)
                level = user.get("level", "public")
                await send_report(chat_id=chat_id, topic=topic, level=level)

            elif text == "/topic":
                waiting_state[chat_id] = "waiting_topic"
                await send_msg(
                    "✏️ موضوع مورد نظرت را بنویس:\n\n"
                    "مثال‌ها:\n"
                    "• اضطراب اجتماعی\n"
                    "• تأثیر خواب بر حافظه\n"
                    "• روان‌شناسی تصمیم‌گیری\n"
                    "• افسردگی و التهاب مغز\n"
                    "• اعتیاد و سیستم پاداش مغز",
                    chat_id=chat_id
                )

            elif text == "/level":
                current = user.get("level", "public")
                current_text = "🌍 عمومی" if current == "public" else "🎓 تخصصی"
                await send_msg(
                    f"🎚 سطح فعلی: {current_text}\n\n"
                    f"برای تغییر بنویس:\n"
                    f"• public یا عمومی — برای همه\n"
                    f"• expert یا تخصصی — برای متخصصان",
                    chat_id=chat_id
                )
                waiting_state[chat_id] = "waiting_level"

            elif text == "/schedule":
                schedule = user.get("schedule_hours")
                current_text = f"هر {schedule} ساعت" if schedule else f"فقط روزانه ساعت {SEND_HOUR}"
                await send_msg(
                    f"⏰ زمان‌بندی فعلی: {current_text}\n\n"
                    f"عدد ساعت را بنویس:\n"
                    f"• 8 ← هر ۸ ساعت\n"
                    f"• 12 ← هر ۱۲ ساعت\n"
                    f"• 24 ← روزی یک بار\n"
                    f"• 0 ← فقط گزارش روزانه ساعت {SEND_HOUR}",
                    chat_id=chat_id
                )
                waiting_state[chat_id] = "waiting_schedule"

            elif text == "/history":
                reports = data.get("reports", {})
                user_reports = sorted(
                    [r for r in reports.values() if r.get("chat_id") == chat_id],
                    key=lambda x: x.get("date", ""), reverse=True
                )[:10]
                if not user_reports:
                    await send_msg(
                        "هنوز گزارشی دریافت نکردی!\nدکمه 📊 را بزن.",
                        chat_id=chat_id, show_menu=True
                    )
                else:
                    history_text = "📚 آخرین گزارش‌های تو:\n\n"
                    for r in user_reports:
                        date = r.get("date", "")[:10]
                        level_icon = "🎓" if r.get("level") == "expert" else "🌍"
                        history_text += (
                            f"{level_icon} #{r['id']} — {date}\n"
                            f"📝 {r.get('title', r.get('topic', ''))}\n\n"
                        )
                    history_text += "برای دریافت مجدد: #شناسه را بفرست"
                    await send_msg(history_text, chat_id=chat_id, show_menu=True)

            elif text == "/help":
                await send_msg(
                    "📖 راهنمای ربات روانشناسی علمی\n\n"
                    "📊 گزارش جدید — موضوع تصادفی\n"
                    "✏️ موضوع دلخواه — هر موضوعی\n"
                    "🎚 تغییر سطح — عمومی یا تخصصی\n"
                    "⏰ زمان‌بندی — فاصله گزارش‌ها\n"
                    "📚 گزارش‌های قبلی — ۱۰ گزارش آخر\n\n"
                    "🔁 گزارش قبلی: #شناسه را بفرست\n"
                    "🔍 جستجو: عنوان یا کلیدواژه",
                    chat_id=chat_id, show_menu=True
                )

            # ── دستور مخصوص سازنده: لیست کاربران ──
            elif text == "/users" and is_owner:
                users = data.get("users", {})
                active = [u for u in users.values() if u.get("authorized")]
                msg_text = f"👥 کاربران فعال: {len(active)}\n\n"
                for u in sorted(active, key=lambda x: x.get("last_seen", ""), reverse=True):
                    last = u.get("last_seen", "")[:16].replace("T", " ")
                    name = u.get("full_name", "") or u.get("username", "ناشناس")
                    uname = f"@{u['username']}" if u.get("username") else ""
                    level_icon = "🎓" if u.get("level") == "expert" else "🌍"
                    msg_text += (
                        f"{level_icon} {name} {uname}\n"
                        f"   🆔 {u['chat_id']}\n"
                        f"   🕐 آخرین فعالیت: {last}\n\n"
                    )
                await send_msg(msg_text, chat_id=chat_id)

            # ── شناسه گزارش ──
            elif text.startswith("#"):
                report_id = text[1:]
                reports = data.get("reports", {})
                if report_id in reports:
                    stored = reports[report_id]
                    footer = (
                        f"\n\n{'━'*24}\n"
                        f"🆔 #{report_id} | 📝 {stored.get('title', '')}"
                    )
                    await send_msg("📂 ارسال گزارش قبلی...", chat_id=chat_id)
                    await send_msg(stored["content"] + footer,
                                   chat_id=chat_id, show_menu=True)
                else:
                    await send_msg(
                        f"گزارشی با شناسه #{report_id} پیدا نشد.\n"
                        f"از 📚 گزارش‌های قبلی لیست را ببین.",
                        chat_id=chat_id, show_menu=True
                    )

            # ── جستجو با کلیدواژه ──
            elif len(text) > 3:
                reports = data.get("reports", {})
                query_lower = text.lower()
                best, best_score = None, 0
                for r in reports.values():
                    score = 0
                    if query_lower in r.get("title", "").lower():
                        score = 3
                    elif query_lower in r.get("topic", "").lower():
                        score = 2
                    else:
                        score = sum(1 for w in query_lower.split()
                                    if w in r.get("title","").lower()
                                    or w in r.get("topic","").lower())
                    if score > best_score:
                        best_score, best = score, r

                if best and best_score > 0:
                    footer = f"\n\n{'━'*24}\n🆔 #{best['id']} | 📝 {best.get('title','')}"
                    await send_msg(f"🔍 گزارش پیدا شد:\n📝 {best.get('title','')}\n\nارسال می‌شود...",
                                   chat_id=chat_id)
                    await send_msg(best["content"] + footer,
                                   chat_id=chat_id, show_menu=True)
                else:
                    waiting_state[chat_id] = "waiting_topic_confirm"
                    waiting_state[f"{chat_id}_pending_topic"] = text
                    await send_msg(
                        f"گزارشی با این کلیدواژه پیدا نشد.\n\n"
                        f"آیا روی «{text}» گزارش جدید تهیه شود?\n\nبله / خیر",
                        chat_id=chat_id
                    )

        except Exception as e:
            log.error(f"❌ خطا در پردازش: {e}")


async def handle_schedule_input(chat_id: str, text: str, data: dict):
    try:
        hours = int(text.strip())
        if hours == 0:
            data["users"][chat_id]["schedule_hours"] = None
            save_data(data)
            await send_msg(
                f"✅ زمان‌بندی شخصی حذف شد.\nفقط گزارش روزانه ساعت {SEND_HOUR}.",
                chat_id=chat_id, show_menu=True
            )
        elif 1 <= hours <= 168:
            data["users"][chat_id]["schedule_hours"] = hours
            save_data(data)
            await send_msg(
                f"✅ هر {hours} ساعت یک گزارش دریافت خواهی کرد.",
                chat_id=chat_id, show_menu=True
            )
        else:
            await send_msg("عدد باید بین ۱ تا ۱۶۸ باشد.", chat_id=chat_id)
    except ValueError:
        await send_msg("لطفاً فقط عدد بنویس (مثلاً: 8 یا 12).", chat_id=chat_id)


# ─────────────────────────────────────────
# گزارش‌های شخصی بر اساس زمان‌بندی
# ─────────────────────────────────────────
async def check_personal_schedules():
    data = load_data()
    now = datetime.now()
    for user in data["users"].values():
        if not user.get("active") or not user.get("authorized"):
            continue
        hours = user.get("schedule_hours")
        if not hours:
            continue
        last_id = user.get("last_report_id")
        if last_id and last_id in data.get("reports", {}):
            try:
                last_date = datetime.fromisoformat(
                    data["reports"][last_id].get("date", "")
                )
                if (now - last_date).total_seconds() / 3600 < hours:
                    continue
            except Exception:
                pass
        topic = random.choice(TOPIC_POOL)
        await send_report(user["chat_id"], topic, user.get("level", "public"))
        await asyncio.sleep(2)


# ─────────────────────────────────────────
# Polling
# ─────────────────────────────────────────
async def poll_telegram_updates(offset: int = 0) -> tuple[list, int]:
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getUpdates"
    async with httpx.AsyncClient(timeout=40) as client:
        try:
            resp = await client.get(url, params={
                "offset": offset, "timeout": 30,
                "allowed_updates": ["message"],
            })
            data = resp.json()
            if not data.get("ok"):
                log.error(f"❌ Telegram error: {data.get('description','')}")
                await asyncio.sleep(5)
                return [], offset
            updates = data.get("result", [])
            if updates:
                log.info(f"📩 {len(updates)} پیام دریافت شد")
                offset = updates[-1]["update_id"] + 1
            return updates, offset
        except httpx.ReadTimeout:
            return [], offset
        except Exception as e:
            log.error(f"❌ خطا در poll: {e}")
            await asyncio.sleep(5)
            return [], offset


async def telegram_listener():
    log.info("👂 شروع listener...")
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
                log.info(f"⏭ offset: {offset}")
    except Exception as e:
        log.warning(f"⚠️ offset اولیه: {e}")

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
    log.info(f"🤖 ربات v3.1 | ساعت {SEND_HOUR}:00 | رمز: {REPORT_PASSWORD}")

    # ثبت سازنده به عنوان authorized
    data = load_data()
    if TELEGRAM_CHAT_ID and TELEGRAM_CHAT_ID not in data["users"]:
        data["users"][TELEGRAM_CHAT_ID] = default_user(TELEGRAM_CHAT_ID)
    if TELEGRAM_CHAT_ID:
        data["users"][TELEGRAM_CHAT_ID]["authorized"] = True
    save_data(data)

    if SEND_NOW == "1":
        await broadcast_daily()

    # فقط به سازنده اطلاع بده (نه رمز)
    await send_msg(
        f"🧠 ربات روانشناسی علمی v3.1 فعال شد!\n\n"
        f"📅 گزارش روزانه: ساعت {SEND_HOUR}:00\n"
        f"👥 مدیریت کاربران: /users\n\n"
        f"از دکمه‌های پایین استفاده کن 👇",
        chat_id=TELEGRAM_CHAT_ID,
        show_menu=True
    )

    scheduler = AsyncIOScheduler(timezone=TIMEZONE)
    scheduler.add_job(broadcast_daily, trigger="cron",
                      hour=SEND_HOUR, minute=0,
                      id="daily_broadcast", replace_existing=True)
    scheduler.add_job(check_personal_schedules,
                      trigger=IntervalTrigger(hours=1),
                      id="personal_schedules", replace_existing=True)
    scheduler.start()

    await telegram_listener()


if __name__ == "__main__":
    asyncio.run(main())
