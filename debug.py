"""
فایل تشخیص مشکل — یک بار اجرا کن و نتیجه رو بفرست
"""
import os
import asyncio
import httpx

async def main():
    print("=" * 50)
    print("🔍 بررسی متغیرهای محیطی")
    print("=" * 50)
    
    vars_to_check = [
        "TELEGRAM_BOT_TOKEN",
        "TELEGRAM_CHAT_ID", 
        "GEMINI_API_KEY",
        "MISTRAL_API_KEY",
        "GROQ_API_KEY",
        "SEND_HOUR",
        "TIMEZONE",
    ]
    
    for var in vars_to_check:
        val = os.getenv(var, "")
        if val:
            # فقط چند کاراکتر اول رو نشون بده
            masked = val[:4] + "..." + val[-4:] if len(val) > 8 else "***"
            print(f"✅ {var}: {masked} (طول: {len(val)})")
        else:
            print(f"❌ {var}: خالی یا تنظیم نشده!")
    
    print()
    print("=" * 50)
    print("🔍 تست اتصال به سرویس‌ها")
    print("=" * 50)
    
    mistral_key = os.getenv("MISTRAL_API_KEY", "").strip()
    gemini_key = os.getenv("GEMINI_API_KEY", "").strip()
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    
    async with httpx.AsyncClient(timeout=15) as client:
        
        # تست Telegram
        if bot_token:
            try:
                resp = await client.get(
                    f"https://api.telegram.org/bot{bot_token}/getMe"
                )
                if resp.status_code == 200:
                    name = resp.json().get("result", {}).get("username", "?")
                    print(f"✅ Telegram: متصل (@{name})")
                else:
                    print(f"❌ Telegram: خطا {resp.status_code}")
            except Exception as e:
                print(f"❌ Telegram: {e}")
        else:
            print("❌ Telegram: توکن خالیه")
        
        # تست Gemini
        if gemini_key:
            try:
                url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-lite:generateContent?key={gemini_key}"
                resp = await client.post(url, json={
                    "contents": [{"parts": [{"text": "Hi"}]}],
                    "generationConfig": {"maxOutputTokens": 5}
                })
                if resp.status_code == 200:
                    print(f"✅ Gemini: کار می‌کند")
                else:
                    print(f"❌ Gemini: خطا {resp.status_code} — {resp.text[:100]}")
            except Exception as e:
                print(f"❌ Gemini: {e}")
        else:
            print("❌ Gemini: کلید خالیه")
        
        # تست Mistral
        if mistral_key:
            try:
                resp = await client.post(
                    "https://api.mistral.ai/v1/chat/completions",
                    headers={"Authorization": f"Bearer {mistral_key}"},
                    json={
                        "model": "mistral-small-latest",
                        "messages": [{"role": "user", "content": "Hi"}],
                        "max_tokens": 5
                    }
                )
                if resp.status_code == 200:
                    print(f"✅ Mistral: کار می‌کند")
                else:
                    print(f"❌ Mistral: خطا {resp.status_code} — {resp.text[:100]}")
            except Exception as e:
                print(f"❌ Mistral: {e}")
        else:
            print("❌ Mistral: کلید خالیه — متغیر MISTRAL_API_KEY تنظیم نشده")

    print()
    print("=" * 50)
    print("تموم شد!")
    print("=" * 50)

if __name__ == "__main__":
    asyncio.run(main())
