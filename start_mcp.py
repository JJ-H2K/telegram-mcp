import os
import asyncio
from main import client, mcp

async def main():
    await client.start()
    mcp.run(transport="http", host="0.0.0.0", port=int(os.environ["PORT"]))

asyncio.run(main())
