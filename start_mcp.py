import os, threading, asyncio, traceback, sys, uvicorn
from main import client, mcp


async def _telegram_runner():
    await client.start()
    await client.run_until_disconnected()


def _start_telegram():
    asyncio.run(_telegram_runner())


if __name__ == "__main__":
    threading.Thread(target=_start_telegram, name="tg-loop", daemon=True).start()

    try:
        uvicorn.run(
            mcp.app,                 # the FastAPI app
            host="0.0.0.0",
            port=int(os.environ["PORT"]),
            log_level="info",
        )
    except Exception:
        traceback.print_exc()
        sys.exit(1)
