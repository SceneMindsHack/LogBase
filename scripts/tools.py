"""LogBase MCP server. Tool functions will be registered here."""

from mcp.server.fastmcp import FastMCP

try:
    from .top_problems import top_problems as rank_top_problems
except ImportError:
    from top_problems import top_problems as rank_top_problems

try:
    from .trend_tool import trend as _trend
except ImportError:
    from trend_tool import trend as _trend    

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



@mcp.tool()
def trend(dataset: str, interval: str, start: str, end: str,
          level: str | None = None, component: str | None = None) -> dict:
    """Count matching log lines per day or week over a time range.

    Reliable counts over time, not an anomaly detector. One row is one physical
    log line, not an incident, request, or affected user.

    Args:
        dataset: "bgl" or "openstack".
        interval: "day" or "week" (weeks start on Monday).
        start: Source-local ISO datetime, inclusive (no timezone offset).
        end: Source-local ISO datetime, exclusive (no timezone offset).
        level: Optional exact match on the level column (e.g. "ERROR").
        component: Optional exact match on the component column.
    """
    return _trend(dataset, interval, start, end, level, component)

if __name__ == "__main__":
    mcp.run(transport="stdio")
