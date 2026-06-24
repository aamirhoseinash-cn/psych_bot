"""
فایل تشخیص — نتیجه را به تلگرام می‌فرستد
"""
import os
import asyncio
import httpx

async def main():
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    gemini_key = os.getenv("GEMINI_API_KEY", "").strip()
    mistral_key = os.getenv("MISTRAL_API_KEY", "").strip()

    lines = ["🔍 گزارش تشخیص\n"]

    # بررسی متغیرها
    for name, val in [
        ("TELEGRAM_BOT_TOKEN", bot_token),
        ("TELEGRAM_CHAT_ID", chat_id),
        ("GEMINI_API_KEY", gemini_key),
        ("MISTRAL_API_KEY", mistral_key),
    ]:
        if val:
            lines.append(f"✅ {name}: {val[:4]}...{val[-4:]} (len={len(val)})")
        else:
            lines.append(f"❌ {name}: خالی!")

    # تست Mistral
    if mistral_key:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(
                    "https://api.mistral.ai/v1/chat/completions",
                    headers={"Authorization": f"Bearer {mistral_key}"},
                    json={"model": "mistral-small-latest",
                          "messages": [{"role": "user", "content": "Hi"}],
                          "max_tokens": 5}
                )
                if resp.status_code == 200:
                    lines.append("\n✅ Mistral API: کار می‌کند")
                else:
                    lines.append(f"\n❌ Mistral API: {resp.status_code}\n{resp.text[:200]}")
        except Exception as e:
            lines.append(f"\n❌ Mistral API خطا: {e}")
    else:
        lines.append("\n❌ Mistral: کلید خالیه")

    # ارسال به تلگرام
    msg = "\n".join(lines)
    print(msg)

    if bot_token and chat_id:
        async with httpx.AsyncClient(timeout=10) as client:
            await client.post(
                f"https://api.telegram.org/bot{bot_token}/sendMessage",
                json={"chat_id": chat_id, "text": msg}
            )
        print("✅ نتیجه به تلگرام فرستاده شد")

if __name__ == "__main__":
    asyncio.run(main())
