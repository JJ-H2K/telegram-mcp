import threading, asyncio, traceback, sys
from main import client, mcp


async def _telegram_runner():
    await client.start()
    await client.run_until_disconnected()


def _start_telegram():
    asyncio.run(_telegram_runner())


if __name__ == "__main__":
    threading.Thread(target=_start_telegram, name="tg-loop", daemon=True).start()
    try:
        mcp.run()              # blocks
    except Exception:          # <-- catch whatever kills the app
        traceback.print_exc()  #   print full stack trace
        sys.exit(1)
