"""LogBase MCP server. Tool functions will be registered here."""

from mcp.server.fastmcp import FastMCP

try:
    from .top_problems import top_problems as rank_top_problems
except ImportError:
    from top_problems import top_problems as rank_top_problems

mcp = FastMCP("LogBase")


@mcp.tool()
def top_problems(
    dataset: str,
    group_by: str = "component",
    since: str | None = None,
    until: str | None = None,
    levels: list[str] | None = None,
    component: str | None = None,
    team: str | None = None,
    text: str | None = None,
    top_n: int = 10,
) -> dict:
    """Rank matching log-record hotspots by component or fictional owner team.

    Counts physical log rows, not distinct incidents or confirmed root causes.
    Omitting levels applies the supported problem levels; an explicit non-empty
    list overrides that default. Ownership labels are fictional demonstration data.
    """
    return rank_top_problems(
        dataset=dataset,
        group_by=group_by,
        since=since,
        until=until,
        levels=levels,
        component=component,
        team=team,
        text=text,
        top_n=top_n,
    )

if __name__ == "__main__":
    mcp.run(transport="stdio")
