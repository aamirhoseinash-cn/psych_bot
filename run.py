from dotenv import load_dotenv
load_dotenv()

import asyncio
import sys
from bot import main, broadcast_daily

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "test":
        print("🧪 حالت تست: یک گزارش فوری ارسال می‌شود...")
        asyncio.run(broadcast_daily())
    else:
        asyncio.run(main())
