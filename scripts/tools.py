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

try:
    from .count_by_tool import count_by as _count_by
except ImportError:
    from count_by_tool import count_by as _count_by

try:
    from .data_overview import overview as _overview
except ImportError:
    from data_overview import overview as _overview

try:
    from .search_logs import search as _search
except ImportError:
    from search_logs import search as _search

try:
    from .nearby_events import nearby as _nearby
except ImportError:
    from nearby_events import nearby as _nearby

try:
    from .get_event_details import get_event_details as _get_event_details
except ImportError:
    from get_event_details import get_event_details as _get_event_details

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
    """Count matching log lines per hour, day, or week over a time range.

    Reliable counts over time, not an anomaly detector. One row is one physical
    log line, not an incident, request, or affected user.

    Args:
        dataset: "bgl" or "openstack".
        interval: "hour", "day", or "week" (weeks start on Monday).
        start: Source-local ISO datetime, inclusive (no timezone offset).
        end: Source-local ISO datetime, exclusive (no timezone offset).
        level: Optional exact match on the level column (e.g. "ERROR").
        component: Optional exact match on the component column.
    """
    return _trend(dataset, interval, start, end, level, component)


@mcp.tool()
def count_by(dataset: str, dimension: str = "component",
             since: str | None = None, until: str | None = None,
             levels: list[str] | None = None, component: str | None = None,
             team: str | None = None, text: str | None = None,
             limit: int = 100) -> dict:
    """Exact per-group counts of matching log rows over the whole dataset.

    Counts physical log rows, not incidents or confirmed root causes. Counts over
    all levels by default; pass `levels` to restrict. Ownership (team) is fictional.

    Args:
        dataset: "bgl" or "openstack".
        dimension: "component", "team", or "severity" (severity maps to the level column).
        since: Optional source-local ISO datetime, inclusive (no timezone offset).
        until: Optional source-local ISO datetime, exclusive (no timezone offset).
        levels: Optional list of exact levels to restrict to (e.g. ["ERROR"]).
        component: Optional exact match on the component column.
        team: Optional exact match on the fictional owner team.
        text: Optional full-text match on content.
        limit: Max groups returned, 1-100 (default 100).
    """
    return _count_by(dataset, dimension, since, until, levels, component, team,
                     text, limit)


@mcp.tool()
def data_overview(dataset: str = "all") -> dict:
    """Summarize what data exists before searching or counting.

    Call this first. Returns, per dataset, the row count, time range, parse and
    timestamp-failure counts, source-file count, and the exact valid filter
    values (levels, teams, components with owning team and row count). Use these
    real values when calling the other tools instead of guessing. One row is one
    physical log line, not an incident; this tool only reads data.

    Args:
        dataset: "all" (default), "bgl", or "openstack".
    """
    return _overview(dataset)


@mcp.tool()
def search(dataset: str, query: str, limit: int = 10,
           since: str | None = None, until: str | None = None) -> dict:
    """Full-text search returning a total match count and bounded evidence.

    Full-text token matching on log content (not substring matching, and
    separate from level/severity filtering). total_matches is the unlimited
    count; limit bounds only the returned evidence rows. content_preview is
    truncated to 500 characters.

    Args:
        dataset: "bgl" or "openstack".
        query: Full-text query, 1 to 1000 characters.
        limit: Max evidence rows returned, 1 to 100 (default 10).
        since: Optional source-local ISO datetime, inclusive (no timezone offset).
        until: Optional source-local ISO datetime, exclusive (no timezone offset).
    """
    return _search(dataset, query, limit, since, until)


@mcp.tool()
def nearby_events(dataset: str, window_minutes: int = 5, limit: int = 10,
                  anchor_time: str | None = None, source_file: str | None = None,
                  line_id: int | None = None, node: str | None = None,
                  component: str | None = None, all_nodes: bool = False) -> dict:
    """Show log lines before and after a chosen line, for context around an event.

    Anchor either by time, or by (source_file, line_id). Returns lines within
    +/- window_minutes of the anchor; if more than limit match, you get half from
    each side, closest first. total_matches counts every line in the window;
    truncated indicates some were omitted. For BGL, lines are limited to the
    anchor's node unless all_nodes is set.

    Args:
        dataset: "bgl" or "openstack".
        window_minutes: Minutes each side of the anchor, 1 to 1440 (default 5).
        limit: Max rows returned, 2 to 100 (default 10), split before/after.
        anchor_time: Source-local ISO datetime anchor (use this OR source_file+line_id).
        source_file: Anchor by identity, with line_id.
        line_id: Anchor by identity, with source_file.
        node: Filter by node (bgl only).
        component: Optional exact match on the component column.
        all_nodes: On bgl identity anchoring, show all nodes instead of just the anchor's.
    """
    return _nearby(dataset, window_minutes, limit, anchor_time=anchor_time,
                   source_file=source_file, line_id=line_id, node=node,
                   component=component, all_nodes=all_nodes)


@mcp.tool()
def get_event_details(dataset: str, source_file: str, line_id: int) -> dict:
    """Retrieve one complete log event by its stable evidence identity.

    Use this after search or aggregation tools when complete evidence is needed.
    The identity is dataset + source_file + line_id; timestamps alone are not
    unique. Returns all common fields, dataset-specific fields, recoverable raw
    evidence, and the fictional owning team without modifying stored data.

    Args:
        dataset: "bgl" or "openstack".
        source_file: Exact source filename returned by another LogBase tool.
        line_id: Positive physical line number within the source file.
    """
    return _get_event_details(dataset, source_file, line_id)


if __name__ == "__main__":
    mcp.run(transport="stdio")
