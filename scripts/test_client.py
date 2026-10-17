"""Minimal MCP stdio client: spawns tools.py, lists tools, calls data_overview."""
import asyncio
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

SERVER = Path(__file__).resolve().parent / "tools.py"


async def main():
    params = StdioServerParameters(command=sys.executable, args=[str(SERVER)])
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            print("Tools:", [t.name for t in tools.tools])
            result = await session.call_tool("data_overview", {"dataset": "all"})
            for block in result.content:
                print(getattr(block, "text", block))


if __name__ == "__main__":
    asyncio.run(main())
