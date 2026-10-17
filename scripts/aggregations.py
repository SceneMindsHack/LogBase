"""Reusable, bounded aggregations for LogBase MCP tools."""

from datetime import datetime
import time

try:
    from .db import literal, records
except ImportError:
    from db import literal, records


DATASET_TABLES = {
    "bgl": {"logs": "bgl_logs", "full_text": "bgl_logs_fts"},
    "openstack": {
        "logs": "openstack_logs",
        "full_text": "openstack_logs_fts",
    },
}
GROUPS = ("component", "team")
DEFAULT_PROBLEM_LEVELS = (
    "FATAL",
    "WARNING",
    "SEVERE",
    "ERROR",
    "FAILURE",
    "WARN",
    "CRITICAL",
)


def _parse_time(value, name):
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise ValueError(f"{name} must be an ISO date/time string")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as error:
        raise ValueError(f"{name} must be a valid ISO date/time") from error
    if parsed.tzinfo is not None:
        raise ValueError("Use source-local timestamps without timezone offsets")
    return parsed


def _normalize_levels(levels):
    if levels is None:
        return list(DEFAULT_PROBLEM_LEVELS)
    if not isinstance(levels, list):
        raise ValueError("levels must be a list of exact log levels")
    if not levels:
        raise ValueError("levels must contain at least one exact log level")
    normalized = []
    for level in levels:
        if not isinstance(level, str) or not level.strip():
            raise ValueError("levels must contain non-empty strings")
        if level not in normalized:
            normalized.append(level)
    return normalized


def ranked_count_sql(
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
    """Validate inputs and build one bounded ranked-count query."""
    if dataset not in DATASET_TABLES:
        raise ValueError("dataset must be 'bgl' or 'openstack'")
    if group_by not in GROUPS:
        raise ValueError("group_by must be 'component' or 'team'")
    if isinstance(top_n, bool) or not isinstance(top_n, int) or not 1 <= top_n <= 50:
        raise ValueError("top_n must be an integer between 1 and 50")

    parsed_since = _parse_time(since, "since")
    parsed_until = _parse_time(until, "until")
    if parsed_since and parsed_until and parsed_since >= parsed_until:
        raise ValueError("since must precede until")

    normalized_levels = _normalize_levels(levels)
    for name, value in (("component", component), ("team", team)):
        if value is not None and not isinstance(value, str):
            raise ValueError(f"{name} must be a string")
        if isinstance(value, str) and not value.strip():
            raise ValueError(f"{name} must not be blank")
    if text is not None:
        if not isinstance(text, str) or not text.strip() or len(text) > 1000:
            raise ValueError("text must contain 1 to 1000 characters")

    table_key = "full_text" if text is not None else "logs"
    table = DATASET_TABLES[dataset][table_key]
    where = []
    if parsed_since is not None:
        where.append("l.event_time >= " + literal(parsed_since))
    if parsed_until is not None:
        where.append("l.event_time < " + literal(parsed_until))
    quoted_levels = ", ".join(literal(level) for level in normalized_levels)
    where.append(f"l.level IN ({quoted_levels})")
    if component is not None:
        where.append("l.component = " + literal(component))
    if team is not None:
        where.append("COALESCE(o.team, 'Unassigned') = " + literal(team))
    if text is not None:
        where.append("l.content @@ " + literal(text))
    where_sql = " AND ".join(where) if where else "TRUE"

    if group_by == "component":
        grouped_columns = "component AS group_value, team AS owning_team"
        group_clause = "component, team"
        ranked_columns = "group_value, owning_team, log_count"
        final_columns = (
            "group_value, owning_team, log_count, "
            "total_matching_rows, total_groups"
        )
        tie_breaker = "group_value ASC, owning_team ASC"
    else:
        grouped_columns = "team AS group_value"
        group_clause = "team"
        ranked_columns = "group_value, log_count"
        final_columns = "group_value, log_count, total_matching_rows, total_groups"
        tie_breaker = "group_value ASC"

    sql = (
        "WITH ownership AS (\n"
        "    SELECT dataset, component, MIN(team) AS team\n"
        "    FROM component_ownership\n"
        "    GROUP BY dataset, component\n"
        "), filtered AS (\n"
        "    SELECT COALESCE(l.component, 'Unknown') AS component,\n"
        "           COALESCE(o.team, 'Unassigned') AS team\n"
        f"    FROM {table} AS l\n"
        "    LEFT JOIN ownership AS o\n"
        f"      ON o.dataset = {literal(dataset)} AND o.component = l.component\n"
        f"    WHERE {where_sql}\n"
        "), grouped AS (\n"
        f"    SELECT {grouped_columns}, COUNT(*) AS log_count\n"
        "    FROM filtered\n"
        f"    GROUP BY {group_clause}\n"
        "), ranked AS (\n"
        f"    SELECT {ranked_columns},\n"
        "           SUM(log_count) OVER () AS total_matching_rows,\n"
        "           COUNT(*) OVER () AS total_groups\n"
        "    FROM grouped\n"
        ")\n"
        f"SELECT {final_columns}\n"
        "FROM ranked\n"
        f"ORDER BY log_count DESC, {tie_breaker}\n"
        f"LIMIT {top_n}"
    )
    filters = {
        "since_inclusive": parsed_since.isoformat() if parsed_since else None,
        "until_exclusive": parsed_until.isoformat() if parsed_until else None,
        "levels": normalized_levels,
        "component": component,
        "team": team,
        "text": text,
        "top_n": top_n,
    }
    return sql, filters


def ranked_log_rows(**parameters):
    """Execute a ranked-count query and return JSON-compatible result metadata."""
    sql, filters = ranked_count_sql(**parameters)
    started = time.perf_counter()
    rows = records(sql)
    elapsed_seconds = round(time.perf_counter() - started, 3)

    total_matching_rows = int(rows[0]["total_matching_rows"]) if rows else 0
    total_groups = int(rows[0]["total_groups"]) if rows else 0
    group_by = parameters.get("group_by", "component")
    results = []
    for rank, row in enumerate(rows, start=1):
        count = int(row["log_count"])
        result = {
            "rank": rank,
            group_by: row["group_value"],
            "count": count,
            "percentage": (
                round(count * 100 / total_matching_rows, 2)
                if total_matching_rows
                else 0.0
            ),
        }
        if group_by == "component":
            result["owning_team"] = row["owning_team"]
        results.append(result)

    return {
        "dataset": parameters["dataset"],
        "group_by": group_by,
        "filters": filters,
        "total_matching_rows": total_matching_rows,
        "returned": len(results),
        "truncated": total_groups > len(results),
        "results": results,
        "sql": sql,
        "elapsed_seconds": elapsed_seconds,
    }
