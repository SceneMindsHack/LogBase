"""Manager-focused operational-hotspot ranking for the LogBase MCP server."""

try:
    from .aggregations import ranked_log_rows
except ImportError:
    from aggregations import ranked_log_rows


CAVEAT = (
    "These are counts of physical log rows and operational hotspots; frequency "
    "and correlation do not establish distinct problems or confirmed root causes."
)


def top_problems(
    dataset,
    group_by="component",
    since=None,
    until=None,
    levels=None,
    component=None,
    team=None,
    text=None,
    top_n=10,
):
    """Rank matching physical log rows by component or fictional owner team."""
    ranked = ranked_log_rows(
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
    return {
        "tool": "top_problems",
        "dataset": ranked["dataset"],
        "group_by": ranked["group_by"],
        "filters": ranked["filters"],
        "counted_metric": "log_rows",
        "total_matching_rows": ranked["total_matching_rows"],
        "returned": ranked["returned"],
        "truncated": ranked["truncated"],
        "results": ranked["results"],
        "sql": ranked["sql"],
        "ownership_is_fictional": True,
        "caveat": CAVEAT,
        "elapsed_seconds": ranked["elapsed_seconds"],
    }