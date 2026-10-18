# LogBase

Load, verify, export and search BGL/OpenStack logs in SereneDB. One shared parser
and schema serve both datasets. MCP tools and agent workflows are the next layer.

## Choose a connection

Copy `.env.example` to `.env`. Every Python command below reads this same file.
Environment variables already set in the terminal take precedence.

| Choice | Setting | Requirements | Recommended use |
|---|---|---|---|
| Local Docker | `SERENEDB_CONNECTION=docker` | Docker CLI and a running `serenedb` container; no password | Easiest local setup; default |
| Direct Python | `SERENEDB_CONNECTION=direct` | Host, port, database, user and configured password; uses psycopg | Direct application/database access |

Both choices use database `logbase`, the same schema and the same commands.
See [setup instructions](docs/database-setup.md) for password configuration,
existing-container handling and Windows/Linux/macOS environment commands.

## Quick start

From the repository root, with the Python environment active:

```sh
python -m pip install -r requirements.txt
python scripts/db.py --init
python scripts/db.py --check
python scripts/load_logs.py --data-root "PATH_TO_INPUT_FOLDER" --load
python scripts/db.py --file sql/ownership.sql
python scripts/db.py --file sql/verify.sql
python scripts/search_logs.py --setup
python scripts/search_logs.py --dataset openstack --query error --limit 5
```

`PATH_TO_INPUT_FOLDER` contains `BGL/BGL.log` and the three files inside
`OpenStack/`. Files can remain outside the repository. If your database is already
loaded, skip the import: it deliberately refuses to duplicate existing rows.

Optional CSV export (no database connection required):

```sh
python scripts/export_csv.py --data-root "PATH_TO_INPUT_FOLDER"
```

This writes `data/processed/bgl_full.csv` and `openstack_full.csv`, with headers
matching the shared schema. Choose a new `--output-dir` for another export;
existing exports are not overwritten. Null values become empty CSV fields;
booleans are `True`/`False`. The supported database import reads raw logs directly.

## Files

| Path | Purpose |
|---|---|
| `scripts/db.py` | Both connection adapters, initialization, connection check and SQL execution |
| `scripts/load_logs.py` | Single shared parser, full import and source/database verification |
| `scripts/export_csv.py` | Optional CSV export using that same parser |
| `scripts/search_logs.py` | Index setup and bounded full-text search with counts and evidence |
| `scripts/check_import.py` | Small real-database round-trip check |
| `sql/schema.sql` | The two full-corpus tables |
| `sql/ownership.sql` | Fictional component ownership |
| `sql/verify.sql` | Counts, date ranges and duplicate evidence checks |
| `compose.yaml` | Pinned SereneDB image, localhost port and persistent storage |
| `tests/` | Offline regression tests |

## Shared data contract

Use `bgl_logs` and `openstack_logs`. Common fields: `source_file`, `line_id`,
`event_time`, `level`, `component`, `content`, `raw_text`, `parse_ok`, `parse_error`,
`event_id`, `event_template`, `raw_text_base64`.

Evidence identity is **dataset + source_file + line_id**. A row is a physical
input line, not an incident. Timestamps retain source wall-clock time without
inventing a timezone. BGL and OpenStack cover different years.

Malformed headers remain with `parse_ok=false`. Records containing null bytes
show `\u0000` in readable text; `raw_text_base64` preserves the exact original
UTF-8 line. Other originals retain their text except the line terminator.
BGL also retains `epoch_seconds`, `label`, `node`, `log_type`. OpenStack retains
`log_record`, `pid`, `correlation_data`, `request_id`, `instance_id`; initial
bracketed context remains in `content`. `event_id`/`event_template` remain null
until a deliberate pattern-extraction step is added.

Ownership joins on `(dataset, component)`. Teams are fictional; unmatched
components should appear as `Unassigned`. Labels and filenames do not prove causes.

Search outputs include the executed SQL, total matches, bounded evidence and a
truncation flag. `content_preview` is limited to 500 characters; retrieve complete
evidence by source identity when needed. Time filters use source-local ISO dates,
inclusive `--since` and exclusive `--until`. Full-text tokens differ from substring
matching, so no misleading substring-versus-token speedup is claimed.

## Connect an agent (MCP server)

The tools listed in the tool catalog are exposed through an MCP server,
`scripts/tools.py` (stdio transport), so any MCP client (Claude Code, Codex,
Cursor, Kiro) can discover and call them.

Before connecting, finish the Quick start: Docker is running with SereneDB,
`.env` exists (copy `.env.example`), the data is loaded, and the full-text
indexes are built (`python scripts/search_logs.py --setup`).

**Server command**

| Field | Value |
|---|---|
| `command` | Python interpreter: `.venv/Scripts/python.exe` (Windows), `.venv/bin/python` (Linux/macOS), or plain `python` if the packages in `requirements.txt` are installed globally |
| `args` | `["scripts/tools.py"]` |

The server reads its database connection from `.env` in the repository root,
whatever directory it is started from.

**Quick add (run from the repository root)**

`--scope project` writes a shareable `.mcp.json` at the repo root, so the config
travels with the checkout.

```sh
# Claude Code (Linux/macOS)
claude mcp add logbase --scope project -- .venv/bin/python scripts/tools.py

# Claude Code (Windows PowerShell)
claude mcp add logbase --scope project -- .venv\Scripts\python.exe scripts\tools.py

# Codex (Linux/macOS)
codex mcp add logbase -- .venv/bin/python scripts/tools.py

# Codex (Windows PowerShell)
codex mcp add logbase -- .venv\Scripts\python.exe scripts\tools.py
```

The `--` separates the client's own flags from the server command.

**Other clients (Cursor, Kiro, ...)**

Add a stdio MCP server using the block in `mcp.example.json`, replacing
`ABSOLUTE_PATH_TO_REPO` with the full path to your checkout.

**Check that it works**

1. Run `/mcp` in Claude Code (or your client's equivalent) and confirm `logbase`
   is connected.
2. Ask the agent to call `data_overview`. It should return row counts for BGL
   and OpenStack.
3. If your client does not show server instructions, paste the guidance from
   `INSTRUCTIONS` in `scripts/tools.py` into the chat before asking questions.

The `logbase` server is separate from the SereneDB **docs** MCP
(`https://api.serenedb.com/mcp`) used during setup. Keep both configured if you
want the agent to answer SereneDB questions as well.

## Role-aware agent usage

Once the `logbase` MCP server is configured in a supported client, Codex,
Claude Code and Kiro can use its tools conversationally.
A clear question is answered directly; a broad request asks which perspective is
desired. Roles change the workflow, level of detail, recommended next steps and
useful follow-up questions, not the underlying facts, calculations, database
access or permissions.

| Request | Expected behavior |
|---|---|
| "What are the top five problems in the OpenStack logs?" | Answer directly with `top_problems`. |
| "Brief me on OpenStack." | Ask whether the user wants an engineer, team-lead, manager or general perspective. |
| "I'm an engineer; investigate authentication failures." | Search and retrieve exact evidence, then suggest the next technical check or nearby events to inspect. |
| "I'm a team lead; assess authentication failures." | Compare counts and trends, then suggest monitoring, component priorities or affected-team coordination. |
| "I'm a manager; brief me on OpenStack." | Give a concise overview and hotspot ranking, then suggest priorities, escalation questions or areas needing investigation. |

A drill-down can remain conversational: "Search for authentication failures," then
"Show details for result 2," then "Show what happened around that event." Search
results are numbered and retain `dataset`, `source_file` and `line_id`, allowing the
later requests to address the same evidence. Ownership mappings are fictional;
log-row frequency or correlation does not prove distinct incidents, causation or
root causes.

## Tool catalog

LogBase exposes eight read-only tools over MCP. All of them share these rules:

- Every result includes the executed `sql` and `elapsed_seconds`. Tools that bound their output also return the total count and a `truncated` flag, so a limited result is never mistaken for the full picture.
- Counts are physical log lines, not incidents, and frequency does not prove a cause.
- Team names come from a fictional ownership table. Unmapped components count as `Unassigned`.
- Timestamps are source-local ISO strings with no timezone. Start bounds are inclusive and end bounds are exclusive.
- BGL (2005 to 2006) and OpenStack (2017) cover different periods and are never merged.

| Tool | What it does | Key inputs | Returns |
|---|---|---|---|
| `data_overview` | Shows what data exists. Call it first. | `dataset` (default `all`) | Row counts, time range, parse failures, valid levels, teams and components |
| `search` | Full-text search on log content | `dataset`, `query`, `limit`, `since`, `until`, `levels` | `total_matches`, ranked evidence rows |
| `nearby_events` | Lines before and after a chosen line | `dataset`, anchor (`anchor_time` or `source_file` + `line_id`), `window_minutes`, `limit`, `node`, `component`, `all_nodes` | Window lines in time order, anchor flagged |
| `get_event_details` | One complete log event | `dataset`, `source_file`, `line_id` | All fields, raw evidence, fictional owning team |
| `trend` | Line counts per hour, day or week | `dataset`, `interval`, `start`, `end`, `level`, `component` | Zero-filled buckets in chronological order |
| `count_by` | Exact counts per group over the whole dataset | `dataset`, `dimension` (component, team or severity), filters, `limit` | Ranked groups with counts and percentages |
| `top_problems` | Ranks hotspots by component or team | `dataset`, `group_by`, filters, `top_n` | Ranked groups with counts and percentages |
| `distinctive_terms` | Words over-represented in one period compared with a baseline | `dataset`, foreground and baseline windows, filters, `top_n` | Terms with document counts, shares and change |

**Which tools each role typically uses.** Roles change the workflow and the recommendations, not access or facts.

- Engineer: `search`, `get_event_details`, `nearby_events`
- Team lead: `count_by`, `trend`, `distinctive_terms`
- Manager: `data_overview`, `top_problems`, `count_by`

### Things worth knowing

- **`search`** matches whole words, not substrings, and the word "error" is not the same as level `ERROR`. Use `levels` for the level. Each evidence row has a one-based `rank` plus its `dataset`, `source_file` and `line_id`, so "show result 2" can be resolved with `get_event_details` or `nearby_events`. `limit` is 1 to 100, and `content_preview` is cut at 500 characters.
- **`nearby_events`** returns half of `limit` from each side of the anchor, closest first, while `total_matches` counts the whole window. On BGL, anchoring by line limits results to that line's node unless `all_nodes` is set. Time proximity does not prove causation.
- **`trend`** zero-fills empty buckets, and the first and last buckets may be partial. `start` and `end` are required.
- **`count_by` and `top_problems`** report the full denominator in `total_matching_rows`. `count_by` groups by `dimension` (`component`, `team` or `severity`); `top_problems` groups by `group_by` (`component` or `team`). Both accept an optional `text` full-text filter (which needs the indexes built). `top_problems` defaults to the problem levels `FATAL`, `WARNING`, `SEVERE`, `ERROR`, `FAILURE`, `WARN` and `CRITICAL`, and an explicit `levels` list overrides that. `top_n` is 1 to 50.
- **`distinctive_terms`** compares document frequency (records containing a term) between two non-overlapping windows. `min_foreground_docs` (default 5) sets the minimum foreground support, and `exclude_terms` drops extra terms on top of a small default list. Each term reports its foreground and baseline document counts, both shares, `share_change_pp`, and `ratio` (null when the term is absent from the baseline, flagged by `new_in_baseline_comparison`). It suggests leads, not causes, and its score is a heuristic, not a significance test. `status` is `ok`, `no_distinctive_terms` or `insufficient_data`. It reflects the full-text index as last refreshed by `scripts/search_logs.py --setup`.

### Examples

`search`:

```json
{"dataset":"openstack","query":"error","levels":["ERROR"],"limit":5}
```

`nearby_events`:

```json
{"dataset":"openstack","source_file":"openstack_normal1.log","line_id":27179,"window_minutes":1,"limit":4}
```

`count_by`:

```json
{"dataset":"bgl","dimension":"team","limit":5}
```

`top_problems`:

```json
{"dataset":"openstack","group_by":"component","levels":["ERROR"],"since":"2017-05-16","until":"2017-05-17","top_n":5}
```

`distinctive_terms`:

```json
{"dataset":"openstack","foreground_start":"2017-05-16T00:00:00","foreground_end":"2017-05-16T01:00:00","baseline_start":"2017-05-16T01:00:00","baseline_end":"2017-05-16T02:00:00","min_foreground_docs":20,"top_n":5}
```

## Tests

```sh
python -m unittest discover -s tests -v
python scripts/check_import.py
```

The second command needs the initialized database. The loader checks counts,
severity totals, date ranges and unique source identities. Local reports go to
ignored `reports/`. Raw logs, exports, environments and `.env` are not committed.

Data source: Loghub (Zhu et al., ISSRE 2023; BGL also Oliner and Stearley, DSN 2007).
