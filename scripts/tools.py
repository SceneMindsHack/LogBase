"""LogBase MCP server. Tool functions will be registered here."""

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("LogBase")

# Add tool functions with @mcp.tool() above the startup block.

if __name__ == "__main__":
    mcp.run(transport="stdio")
