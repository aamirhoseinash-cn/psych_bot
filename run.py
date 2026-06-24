from dotenv import load_dotenv
load_dotenv()

import asyncio
import os

# اگه DEBUG_MODE=1 باشه، فایل تشخیص رو اجرا کن
if os.getenv("DEBUG_MODE", "0") == "1":
    from debug import main
else:
    from bot import main

if __name__ == "__main__":
    asyncio.run(main())
