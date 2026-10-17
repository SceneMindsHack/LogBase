"""Retrieve one complete log event by its stable evidence identity."""

import time

try:
    from .db import literal, records
except ImportError:
    from db import literal, records


DATASET_TABLES = {
    "bgl": "bgl_logs",
    "openstack": "openstack_logs",
}
COMMON_FIELDS = (
    "source_file",
    "line_id",
    "event_time",
    "level",
    "component",
    "content",
    "raw_text",
    "parse_ok",
    "parse_error",
    "event_id",
    "event_template",
    "raw_text_base64",
)
DATASET_FIELDS = {
    "bgl": ("label", "epoch_seconds", "node", "log_type"),
    "openstack": (
        "log_record",
        "pid",
        "request_id",
        "instance_id",
        "correlation_data",
    ),
}
INTEGER_FIELDS = {"line_id", "epoch_seconds", "pid"}
CAVEAT = (
    "This event is evidence from one physical log line. Fictional ownership and "
    "log correlation do not prove a distinct incident or root cause."
)


def _validate_identity(dataset, source_file, line_id):
    if dataset not in DATASET_TABLES:
        raise ValueError("dataset must be 'bgl' or 'openstack'")
    if not isinstance(source_file, str) or not source_file.strip():
        raise ValueError("source_file must be a non-blank string")
    if isinstance(line_id, bool) or not isinstance(line_id, int) or line_id <= 0:
        raise ValueError("line_id must be a positive integer")


def event_details_sql(dataset, source_file, line_id):
    """Validate an evidence identity and build its bounded lookup SQL."""
    _validate_identity(dataset, source_file, line_id)
    table = DATASET_TABLES[dataset]
    selected = ", ".join(f"l.{field}" for field in COMMON_FIELDS + DATASET_FIELDS[dataset])
    return (
        "WITH ownership AS (\n"
        "    SELECT dataset, component, MIN(team) AS team\n"
        "    FROM component_ownership\n"
        "    GROUP BY dataset, component\n"
        ")\n"
        f"SELECT {selected}, COALESCE(o.team, 'Unassigned') AS owning_team\n"
        f"FROM {table} AS l\n"
        "LEFT JOIN ownership AS o\n"
        f"  ON o.dataset = {literal(dataset)} AND o.component = l.component\n"
        f"WHERE l.source_file = {literal(source_file)} AND l.line_id = {literal(line_id)}\n"
        "ORDER BY l.source_file, l.line_id\n"
        "LIMIT 2"
    )


def _optional(value):
    return value if value not in (None, "") else None


def _integer(value):
    return int(value) if value not in (None, "") else None


def _boolean(value):
    if isinstance(value, bool):
        return value
    normalized = str(value).lower()
    if normalized in ("t", "true", "1"):
        return True
    if normalized in ("f", "false", "0"):
        return False
    raise RuntimeError(f"Unexpected database boolean value: {value!r}")


def _shape_event(dataset, row):
    event = {}
    for field in COMMON_FIELDS + DATASET_FIELDS[dataset]:
        value = row.get(field)
        if field in INTEGER_FIELDS:
            event[field] = _integer(value)
        elif field == "parse_ok":
            event[field] = _boolean(value)
        elif field in ("content", "raw_text"):
            event[field] = "" if value is None else value
        else:
            event[field] = _optional(value)
    event["owning_team"] = row.get("owning_team") or "Unassigned"
    return event


def get_event_details(dataset, source_file, line_id):
    """Return one exact event, or a clear not-found result, without modifying data."""
    sql = event_details_sql(dataset, source_file, line_id)
    started = time.perf_counter()
    rows = records(sql)
    elapsed_seconds = round(time.perf_counter() - started, 3)
    identity = {
        "dataset": dataset,
        "source_file": source_file,
        "line_id": line_id,
    }
    result = {
        "tool": "get_event_details",
        "dataset": dataset,
        "requested_identity": identity,
        "found": bool(rows),
        "event": None,
        "ownership_is_fictional": True,
        "sql": sql,
        "elapsed_seconds": elapsed_seconds,
        "caveat": CAVEAT,
    }
    if not rows:
        return result
    if len(rows) > 1:
        raise RuntimeError(
            "Duplicate log identity detected for "
            f"{dataset}/{source_file}/{line_id}; expected exactly one row"
        )
    result["event"] = _shape_event(dataset, rows[0])
    return result