"""Execution provenance for LogBase MCP tool calls.

Wraps a tool function so its JSON result gains a `provenance` field describing
the actual invocation: a unique call_id, the tool name, the arguments used
(including defaults the wrapper passes), UTC start/complete timestamps, and the
exact SQL statements the tool reported executing.

This is execution provenance surfaced to the client, not a tamper-proof audit
log. Execution timestamps are UTC with an explicit offset; log-event times stay
source-local. Those are different clocks and are never conflated. SQL strings are
taken from the tool's own returned output (the statements it sent to the shared
db layer); this module does not rebuild SQL from query builders. On error, the
exception propagates unchanged -- no fabricated success or empty data.

STDIO MCP: this module prints nothing to stdout.
"""
import uuid
from datetime import datetime, timezone


def new_call_id():
    """A unique, sortable-enough identifier for one tool invocation."""
    return "call_" + uuid.uuid4().hex


def _extract_queries(result):
    """Pull the exact executed SQL out of a tool result into provenance queries.

    Handles the field shapes actually used by LogBase tools:
      - top-level "sql" as a string (count_by, top_problems, get_event_details)
      - top-level "sql" as a list of strings (trend, search, nearby_events, and
        distinctive_terms, which runs its main query plus a separate denominator
        query)
      - data_overview: no top-level "sql"; each item of "datasets" carries its own
        "sql" list, tagged with that dataset.
    Order is preserved as the tool reported it. A tool that returns no SQL (an
    unusual or non-query result) yields an empty list rather than an error.
    """
    queries = []
    sequence = 1

    def add(sql, dataset=None):
        nonlocal sequence
        if not isinstance(sql, str) or not sql.strip():
            return
        entry = {"sequence": sequence, "sql": sql}
        if dataset is not None:
            entry["dataset"] = dataset
        queries.append(entry)
        sequence += 1

    if not isinstance(result, dict):
        return queries

    top_level_dataset = result.get("dataset")

    if "sql" in result:
        sql = result["sql"]
        if isinstance(sql, str):
            add(sql, top_level_dataset)
        elif isinstance(sql, list):
            for statement in sql:
                add(statement, top_level_dataset)

    # data_overview nests a per-dataset sql list inside each datasets[] item and
    # has no top-level sql field.
    if "sql" not in result and isinstance(result.get("datasets"), list):
        for item in result["datasets"]:
            if not isinstance(item, dict):
                continue
            item_dataset = item.get("dataset")
            item_sql = item.get("sql")
            if isinstance(item_sql, list):
                for statement in item_sql:
                    add(statement, item_dataset)
            elif isinstance(item_sql, str):
                add(item_sql, item_dataset)

    return queries


def record_call(tool_name, arguments, function):
    """Invoke `function` (a zero-arg callable) and return its result with a
    `provenance` field appended.

    `arguments` is the resolved invocation mapping (actual values including
    defaults). An exception from the function is re-raised unchanged; no
    provenance is attached to a failed call, and no success is fabricated.
    """
    call_id = new_call_id()
    started_at = datetime.now(timezone.utc).isoformat()
    result = function()
    completed_at = datetime.now(timezone.utc).isoformat()

    provenance = {
        "call_id": call_id,
        "tool": tool_name,
        "arguments": dict(arguments),
        "started_at": started_at,
        "completed_at": completed_at,
        "queries": _extract_queries(result),
    }

    if isinstance(result, dict):
        # Additive: never remove or overwrite existing output fields.
        enriched = dict(result)
        enriched["provenance"] = provenance
        return enriched
    # Non-dict results are returned unchanged with provenance alongside.
    return {"result": result, "provenance": provenance}
