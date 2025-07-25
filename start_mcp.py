import asyncio
import os

from main import client, mcp

async def main():
    await client.start()
    await mcp.run()

asyncio.run(main())
