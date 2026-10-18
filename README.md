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

## MCP tool: `top_problems`

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

## MCP tool: `distinctive_terms`

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

## Tests

```sh
python -m unittest discover -s tests -v
python scripts/check_import.py
```

The second command needs the initialized database. The loader checks counts,
severity totals, date ranges and unique source identities. Local reports go to
ignored `reports/`. Raw logs, exports, environments and `.env` are not committed.

Data source: Loghub (Zhu et al., ISSRE 2023; BGL also Oliner and Stearley, DSN 2007).
