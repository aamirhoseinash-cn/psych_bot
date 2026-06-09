from dotenv import load_dotenv
load_dotenv()

import asyncio
import sys
from bot import main, broadcast_scheduled

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "test":
        print("🧪 ارسال فوری...")
        asyncio.run(broadcast_scheduled())
    else:
        asyncio.run(main())
