from dotenv import load_dotenv
load_dotenv()

import asyncio
import sys

if len(sys.argv) > 1 and sys.argv[1] == "debug":
    from debug import main
else:
    from bot import main, broadcast_scheduled
    if len(sys.argv) > 1 and sys.argv[1] == "test":
        main = broadcast_scheduled

if __name__ == "__main__":
    asyncio.run(main())
