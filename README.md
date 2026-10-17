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

## Tests

```sh
python -m unittest discover -s tests -v
python scripts/check_import.py
```

The second command needs the initialized database. The loader checks counts,
severity totals, date ranges and unique source identities. Local reports go to
ignored `reports/`. Raw logs, exports, environments and `.env` are not committed.

Data source: Loghub (Zhu et al., ISSRE 2023; BGL also Oliner and Stearley, DSN 2007).
