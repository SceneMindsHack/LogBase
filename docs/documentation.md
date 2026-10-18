# LogBase documentation

Deep reference for the LogBase project: what it is, how a tool call flows through
the system, and a full description of each MCP tool with its inputs, examples and
returned fields. For a quick overview and setup, see the [README](../README.md);
this document is the detailed companion to the README's **Tool catalog**.

## Overview

LogBase turns the BGL and OpenStack log corpora into focused answers for three
roles — an engineer investigating a failure, a team lead tracking recurring
problems, and a manager deciding what to prioritise. Millions of log lines cannot
fit in one prompt, so the agent never reads the raw corpus. Instead it calls a
small set of read-only tools that search and aggregate inside SereneDB and return
only bounded evidence or calculated summaries. The workflow is always
**question → evidence → recommendation**: every number an answer relies on comes
from a query that actually ran, and observed facts are kept separate from
hypotheses and recommended next steps.

The same tools and the same base corpus serve all three roles. A role changes the
workflow, the evidence selected, the level of detail and the recommended next
steps — never the facts, the calculations, database access or permissions.

### Shared data contract

- Two tables, `bgl_logs` and `openstack_logs`, share a common set of fields
  (`source_file`, `line_id`, `event_time`, `level`, `component`, `content`,
  `raw_text`, `parse_ok`, `parse_error`, `event_id`, `event_template`,
  `raw_text_base64`) plus dataset-specific columns.
- Evidence identity is **dataset + source_file + line_id**. A row is one physical
  input line, not an incident. Timestamps alone are not unique.
- Timestamps keep source wall-clock time with no invented timezone. BGL
  (2005-2006) and OpenStack (2017) cover different periods and are never merged.
- Ownership joins on `(dataset, component)`. Teams are **fictional** demonstration
  data; unmapped components appear as `Unassigned`. Frequency or correlation never
  proves a distinct incident, causation or a root cause.
- Counts are physical log rows (or document frequency for `distinctive_terms`),
  never incidents, requests, affected users or failure rates.

## Architecture

A tool call flows through four layers:

1. **MCP server** — `scripts/tools.py` registers the eight tools with FastMCP and
   serves them over stdio. Each tool's docstring and type-hinted signature become
   the description and input schema the agent sees; the server also advertises a
   long `INSTRUCTIONS` block covering tool selection, the role-aware workflow and
   the faithfulness/causation caveats.
2. **Tool modules** — one module per tool (`search_logs.py`, `nearby_events.py`,
   `get_event_details.py`, `trend_tool.py`, `count_by_tool.py`, `top_problems.py`,
   `data_overview.py`, `distinctive_terms.py`). They validate inputs, build one or
   more parameterized SQL statements, execute them and shape a JSON-serialisable
   result. `top_problems` and `count_by` share query builders in `aggregations.py`.
3. **Connection adapter** — `scripts/db.py` runs every query through one of two
   interchangeable modes selected by `SERENEDB_CONNECTION`: `docker` (the default,
   using the container's `psql`) or `direct` (psycopg over the PostgreSQL wire
   protocol). All data values are quoted through `literal()`; identifiers come from
   fixed allowlists, so no user text is interpolated into SQL unsafely.
4. **SereneDB** — does all the search and aggregation. Tools send back a limited
   set of relevant rows or calculated counts, never the raw corpus.

Every tool returns the executed `sql` and `elapsed_seconds`, and every bounded
result returns the total count behind it and a `truncated` flag, so a limited
answer is never mistaken for the full picture and every figure can be rechecked.

Full-text search and `distinctive_terms` require the inverted indexes built by
`python scripts/search_logs.py --setup`.

## Tools

The eight tools are ordered by typical use: discovery first (`data_overview`), then
retrieval of individual evidence (`search`, `nearby_events`, `get_event_details`),
then aggregation and summaries (`trend`, `count_by`, `top_problems`,
`distinctive_terms`).

### MCP tool: `data_overview`

`data_overview` is the discovery tool to call first. It summarizes what data
exists so later tools are called with real values instead of guesses, such as a
component name that does not exist. It only reads data; it never changes anything.

| Parameter | Meaning |
|---|---|
| `dataset` | `all` (default), `bgl`, or `openstack` |

Example:

```json
{"dataset":"openstack"}
```

The result has `datasets` (one entry per dataset) and `elapsed_seconds`. Each
dataset entry reports `row_count`, `first_event` and `last_event` (source-local
time range), `invalid_timestamps`, `parse_failures`, `source_files`,
`distinct_components`, `has_node_column` (true for BGL, false for OpenStack),
`levels` (row count per severity), `teams` (row count per owning team),
`components` (every component with its owning team and row count), explanatory
`notes`, and the exact `sql` that produced the numbers. One row is one physical
log line, not an incident, and BGL and OpenStack cover different periods.

### MCP tool: `search`

`search` runs full-text **token** matching on log content (not substring
matching) and returns the total number of matches plus a bounded, ranked set of
evidence rows. Level filtering is a separate exact match on the `level` column,
applied in addition to the full-text query. It needs the full-text indexes built
by `scripts/search_logs.py --setup`.

| Parameter | Meaning |
|---|---|
| `dataset` | Required: `bgl` or `openstack` |
| `query` | Full-text query, 1 to 1000 characters |
| `limit` | Max evidence rows returned, 1 to 100; default 10 |
| `since`, `until` | Optional source-local ISO bounds; inclusive then exclusive |
| `levels` | Optional non-empty exact level list (separate from the text query) |

Example:

```json
{"dataset":"openstack","query":"error","levels":["ERROR"],"limit":5}
```

The result echoes the `dataset`, `query`, `since_inclusive`, `until_exclusive` and
`levels` it ran with, then reports `total_matches` (the unlimited count),
`returned`, `truncated`, `content_preview_limit` (500), the two executed statements
in `sql`, `elapsed_seconds`, and `evidence`. Each evidence
row carries a one-based `rank` and its `dataset`, `source_file`, `line_id`,
`event_time`, `level`, `component`, and a `content_preview` truncated to 500
characters. Preserve the rank-to-identity mapping so a follow-up such as
"show result 2" can be resolved with `get_event_details` or `nearby_events`.
Full-text `"error"` is not the same as level `ERROR`.

### MCP tool: `nearby_events`

`nearby_events` shows the log lines before and after a chosen point, answering
"what happened just before and after?". Anchor either by `anchor_time`, or by the
`source_file` + `line_id` identity. If more lines fall in the window than `limit`,
you get half from each side, closest first; `total_matches` still counts every
line in the window and `truncated` flags that some were omitted.

| Parameter | Meaning |
|---|---|
| `dataset` | Required: `bgl` or `openstack` |
| `window_minutes` | Minutes each side of the anchor, 1 to 1440; default 5 |
| `limit` | Max rows returned, 2 to 100; default 10, split before/after |
| `anchor_time` | Source-local ISO anchor (use this OR `source_file` + `line_id`) |
| `source_file`, `line_id` | Anchor by identity |
| `node` | Filter by node (bgl only) |
| `component` | Optional exact component filter |
| `all_nodes` | On bgl identity anchoring, show all nodes instead of just the anchor's |

Example:

```json
{"dataset":"openstack","source_file":"openstack_normal1.log","line_id":27179,"window_minutes":1,"limit":4}
```

The result reports `anchor_time`, `anchor_source_file`, `anchor_line_id`,
`window_minutes`, `window_bounds_inclusive`, `node`, `component`, `total_matches`,
`returned`, `truncated`, `content_preview_limit`, the executed `sql`,
`elapsed_seconds`, and `evidence` in chronological order. The anchor row is flagged
`is_anchor: true`. For BGL, lines are limited to the anchor's node unless
`all_nodes` is set. Temporal proximity does not establish causality or prove events
belong to the same request.

### MCP tool: `get_event_details`

`get_event_details` retrieves one complete log event by its stable evidence
identity, for use after `search` or an aggregation points at a specific line. It
only reads data.

| Parameter | Meaning |
|---|---|
| `dataset` | Required: `bgl` or `openstack` |
| `source_file` | Exact source filename returned by another tool |
| `line_id` | Positive physical line number within that file |

Example:

```json
{"dataset":"openstack","source_file":"openstack_normal1.log","line_id":27179}
```

The result reports `requested_identity`, `found`, and `event`. When found, `event`
holds all common fields plus the dataset-specific fields (BGL: `label`,
`epoch_seconds`, `node`, `log_type`; OpenStack: `log_record`, `pid`, `request_id`,
`instance_id`, `correlation_data`), the recoverable raw evidence (`raw_text`,
`raw_text_base64`), and the fictional `owning_team`. It also reports
`ownership_is_fictional`, the executed `sql`, `elapsed_seconds`, and a `caveat`.
The identity is dataset + source_file + line_id; timestamps alone are not unique.

### MCP tool: `trend`

`trend` counts matching log lines per time bucket over a range, for recurrence over
a stated period. It gives reliable counts, not anomaly detection. Missing buckets
are zero-filled, and rows with a null `event_time` are excluded from the time
aggregation.

| Parameter | Meaning |
|---|---|
| `dataset` | Required: `bgl` or `openstack` |
| `interval` | `hour`, `day`, or `week` (weeks start Monday) |
| `start`, `end` | Required source-local ISO bounds; inclusive then exclusive |
| `level` | Optional exact match on the level column |
| `component` | Optional exact match on the component column |

Example:

```json
{"dataset":"openstack","interval":"hour","start":"2017-05-16T03:00:00","end":"2017-05-16T06:00:00","level":"ERROR"}
```

The result reports `interval`, `start_inclusive`, `end_exclusive`,
`effective_filters`, `buckets` (each `bucket_start` with its `count`, in
chronological order), `total_timed_matches`, `bucket_count`, the executed `sql`,
`elapsed_seconds`, and a `limitations` list. The bucket counts are reconciled
against a separate total before returning. The first and last buckets may be
partial when the range starts or ends mid-interval. A zero bucket means no matching
lines were observed, not that a service was healthy.

### MCP tool: `count_by`

`count_by` returns exact per-group counts over the **whole** dataset (not a sample),
grouped by one dimension. Unlike `top_problems`, it counts over all levels by
default; pass `levels` to restrict. Counts are physical log rows, and the team
dimension uses fictional ownership mappings.

| Parameter | Meaning |
|---|---|
| `dataset` | Required: `bgl` or `openstack` |
| `dimension` | `component` (default), `team`, or `severity` (maps to the level column) |
| `since`, `until` | Optional source-local ISO bounds; inclusive then exclusive |
| `levels` | Optional non-empty exact level list |
| `component`, `team` | Optional exact filters |
| `text` | Optional full-text filter on content (needs the indexes built) |
| `limit` | Max groups returned, 1 to 100; default 100 |

Example:

```json
{"dataset":"bgl","dimension":"team","limit":5}
```

The result reports `dimension`, `grouped_column`, `counted_metric`, normalized
`filters`, `total_matching_rows` (the full denominator), `total_groups`,
`returned`, `truncated`, ranked `results` (each with its group value, `count` and
`percentage`), the executed `sql`, `ownership_is_fictional`, a `caveat`, and
`elapsed_seconds`. Unmapped components count under `Unassigned`.

### MCP tool: `top_problems`

`top_problems` gives managers a bounded ranking of operational log hotspots. It
counts physical log rows, not distinct incidents, and frequency or correlation does
not prove a root cause.

| Parameter | Meaning |
|---|---|
| `dataset` | Required: `bgl` or `openstack` |
| `group_by` | `component` (default) or fictional owner `team` |
| `since`, `until` | Optional source-local ISO bounds; inclusive then exclusive |
| `levels` | Optional non-empty exact list; defaults to `FATAL`, `WARNING`, `SEVERE`, `ERROR`, `FAILURE`, `WARN`, and `CRITICAL` |
| `component`, `team` | Optional non-blank exact filters |
| `text` | Optional full-text filter; requires the existing full-text indexes to be initialized |
| `top_n` | Number of groups to return, from 1 to 50; default 10 |

Component example:

```json
{"dataset":"openstack","group_by":"component","levels":["ERROR"],"since":"2017-05-16","until":"2017-05-17","top_n":5}
```

Team example:

```json
{"dataset":"bgl","group_by":"team","levels":["FATAL","ERROR"],"top_n":10}
```

The result reports normalized `filters`, `counted_metric`, `total_matching_rows`,
`returned`, `truncated`, ranked `results` with percentages, the exact executed
`sql`, and `elapsed_seconds`. `ownership_is_fictional` and `caveat` make the
demonstration-only ownership and causation limits explicit. Unmapped components
belong to `Unassigned`.

### MCP tool: `distinctive_terms`

`distinctive_terms` answers "what words became unusually common during this period
compared with a baseline?" It uses SereneDB's native inverted-index term dictionary
(`ts_dict_agg(content)` and `ts_dict_count(content)`) to count, per term, how many
records contain it. This is document frequency: a line containing a word several
times counts once for that term. All counting happens in the database.

| Parameter | Meaning |
|---|---|
| `dataset` | Required: `bgl` or `openstack` |
| `foreground_start`, `foreground_end` | Required source-local ISO bounds, inclusive then exclusive |
| `baseline_start`, `baseline_end` | Required baseline window; must not overlap the foreground (adjacent is allowed) |
| `component` | Optional exact component filter, applied to both windows |
| `levels` | Optional non-empty exact level list, applied to both windows (all levels if omitted) |
| `min_foreground_docs` | Minimum foreground support, positive; default 5 |
| `top_n` | Number of terms to return, 1 to 50; default 10 |
| `exclude_terms` | Optional extra exact terms to drop, added to a small default list |

Example (compare two OpenStack hours on a day with data):

```json
{"dataset":"openstack","foreground_start":"2017-05-16T00:00:00","foreground_end":"2017-05-16T01:00:00","baseline_start":"2017-05-16T01:00:00","baseline_end":"2017-05-16T02:00:00","min_foreground_docs":20,"top_n":5}
```

For each term the result gives `foreground_docs`, `baseline_docs`, both shares
(0-1 proportions of eligible records), `share_change_pp`, `excess_documents`
(`foreground_docs - foreground_total * baseline_share`), `ratio` (null when the
term is absent from the baseline, with `new_in_baseline_comparison` true), and
window denominators. `method` names the native functions and the score definition.
The score orders terms by over-representation; it is a transparent heuristic, not a
p-value. Shares are proportions of log records, not failure rates, and terms are
investigative leads, not proven causes. `status` is `ok`, `no_distinctive_terms`,
or `insufficient_data` (a window with no eligible records). Eligible records are
timed rows with non-null content matching the filters. Results reflect the index
as last refreshed by `scripts/search_logs.py --setup`.
