# LogBase
# LogBase

LogBase turns the massive BGL and OpenStack log corpora into evidence-grounded
answers. An AI agent calls a set of read-only MCP tools that search and aggregate
inside SereneDB and return only bounded evidence or exact counts — never the raw
corpus.


## Setup

Everything runs locally. You need **Docker** (running), **Python 3.12**, and
**Git**. Run all commands from the repository root, in order.


### 1. Start the database

`compose.yaml` pins the SereneDB image, the localhost port `7890`, and a persistent
volume, so one command does it:

```sh
docker compose up -d      # then `docker ps` to confirm it shows "Up"
```


### 2. Set up Python

Create the environment, install the three dependencies, and copy the default
`.env` (which targets the local Docker database — no editing needed).

**Windows (PowerShell)**

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1    # if blocked: Set-ExecutionPolicy -Scope Process RemoteSigned
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

**Linux / macOS (bash/zsh)**

```sh
python3.12 -m venv .venv && source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
```

Then initialize and check the connection:

```sh
python scripts/db.py --init
python scripts/db.py --check    # prints one row with connection_ok
```


### 3. Load the datasets

Download the two corpora and unpack them into one folder with this **exact**
layout (the loader looks for these names):

```text
input-data/
  BGL/BGL.log
  OpenStack/openstack_normal1.log
  OpenStack/openstack_normal2.log
  OpenStack/openstack_abnormal.log
```

- **BGL** — <https://zenodo.org/records/8196385/files/BGL.zip?download=1>
- **OpenStack** — <https://zenodo.org/records/8196385/files/OpenStack.tar.gz?download=1>

Load, apply ownership, verify, then build the full-text indexes. Replace
`PATH_TO_INPUT_FOLDER` with the folder above (quote it if it has spaces):

```sh
python scripts/load_logs.py --data-root "PATH_TO_INPUT_FOLDER" --load
python scripts/db.py --file sql/ownership.sql
python scripts/db.py --file sql/verify.sql
python scripts/search_logs.py --setup
```

> Loading the full BGL corpus (~4.75M lines) takes a few minutes — a one-time
> step. The loader refuses to duplicate rows, so re-running is safe; if the data
> is already loaded, skip straight to `--setup`.


### 4. Connect an AI client (MCP)

The tools are served over stdio by `scripts/tools.py`, so any MCP client (Claude
Code, Codex, Cursor, Kiro) can use them. `--scope project` writes a shareable
`.mcp.json` at the repo root:

```sh
# Claude Code
claude mcp add logbase --scope project -- .venv/bin/python scripts/tools.py          # Linux/macOS
claude mcp add logbase --scope project -- .venv\Scripts\python.exe scripts\tools.py  # Windows

# Codex
codex mcp add logbase -- .venv/bin/python scripts/tools.py          # Linux/macOS
codex mcp add logbase -- .venv\Scripts\python.exe scripts\tools.py  # Windows
```

For other clients, use the block in `mcp.example.json`, replacing
`ABSOLUTE_PATH_TO_REPO` with your checkout path.

**Verify:** run `/mcp` (or your client's equivalent), confirm `logbase` is
connected, then ask the agent to call `data_overview` — it should return BGL and
OpenStack row counts. You're ready.


## Tools

LogBase exposes eight read-only tools over MCP. All searching and counting runs
**inside SereneDB** — the agent never pulls the raw corpus into the model. Every
result carries the executed `sql`, `elapsed_seconds`, and (for bounded output) the
total count and a `truncated` flag, so a limited answer is never mistaken for the
whole picture. For full parameter tables, examples and returned fields, see
[docs/documentation.md](docs/documentation.md).

| Tool | What it does | Returns |
|---|---|---|
| `data_overview` | Discovery tool — shows what data exists. Call it first. | Row counts, time range, parse failures, valid levels, teams and components |
| `search` | Full-text search on SereneDB's inverted index, with phrase, AND and exclude syntax | `total_matches` and ranked evidence rows |
| `nearby_events` | The lines immediately before and after a chosen event | Window lines in time order, anchor flagged |
| `get_event_details` | One complete log event by its stable identity | All fields, recoverable raw evidence, owning team |
| `trend` | Exact counts per hour, day or week | Zero-filled buckets in chronological order |
| `count_by` | Exact per-group counts over the whole dataset | Ranked groups with counts and percentages |
| `top_problems` | Ranked operational hotspots by component or team | Ranked groups with counts and percentages |
| `distinctive_terms` | Terms over-represented in a period versus a baseline, via SereneDB's native term-dictionary aggregates | Terms with document counts, shares and change |

Two tools lean on SereneDB capabilities most teams never reach for: `search` uses
its inverted full-text index for real phrase queries, and `distinctive_terms`
computes document-frequency comparisons with the native `ts_dict_agg` /
`ts_dict_count` aggregates — entirely in the database, with no corpus scan in Python.


## Role-aware analysis

The same tools and the same corpus serve three distinct audiences, and LogBase
tailors its workflow, evidence and next steps to each — never the facts,
calculations or database access, which stay identical for everyone.

| Role | Focus | Tools it leans on |
|---|---|---|
| **Engineer** | Exact evidence identities, surrounding context, and the next technical check to run | `search`, `get_event_details`, `nearby_events` |
| **Team lead** | Totals, trends and recurring-component patterns to coordinate around | `count_by`, `trend`, `distinctive_terms` |
| **Manager** | Concise hotspot rankings, ownership and decision-oriented tradeoffs | `data_overview`, `top_problems`, `count_by` |

A clear, specific question is answered directly; a broad request ("Brief me on
OpenStack") first asks which perspective is wanted. Throughout, observed evidence
stays separate from recommendations, and frequency or correlation is never
presented as a confirmed cause.


## Extra features

- **Data visualisation** — numerical answers (trends, category counts, rankings,
  distinctive-term shares) are charted automatically, with no need to ask.
- **Investigation summary** — at a natural stopping point the agent can produce an
  opt-in recap: the investigation story, the full cited evidence, and an appendix
  of every query that actually ran.
- **Phrase matching** — `search` understands real query syntax: multi-word
  phrases, implicit AND, exclusions and alternatives, not just single keywords.

For the full architecture, per-tool reference and these features in depth, see
[docs/documentation.md](docs/documentation.md).


## Tests

```sh
python -m unittest discover -s tests -v
python scripts/check_import.py
```

The second command needs the initialized database. Local reports go to the ignored
`reports/`; raw logs, exports, environments and `.env` are never committed.

Data source: Loghub (Zhu et al., ISSRE 2023; BGL also Oliner and Stearley, DSN 2007).
