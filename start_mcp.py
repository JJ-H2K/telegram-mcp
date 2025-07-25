import os
import asyncio
from main import client, mcp

async def start():
    await client.start()
    mcp.run()

asyncio.run(start())
