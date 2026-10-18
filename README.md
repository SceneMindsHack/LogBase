# LogBase

LogBase turns the massive BGL and OpenStack log corpora into evidence-grounded
answers. An AI agent calls a set of read-only MCP tools that search and aggregate
inside SereneDB and return only bounded evidence or exact counts — never the raw
corpus.

## Setup

The whole stack runs locally: a SereneDB database in Docker, a small Python
environment, and an MCP server any AI client can connect to. Follow the four steps
in order. Each command is run from the repository root.

### Prerequisites

- **Docker** — [Docker Desktop](https://www.docker.com/products/docker-desktop/)
  (Windows/macOS) or Docker Engine (Linux). Start it before step 1 and leave it
  running.
- **Python 3.12** — verify with `python --version` (Windows) or
  `python3 --version` (Linux/macOS).
- **Git** — to clone this repository.

### Step 1 — Start the database

From the repository root, launch SereneDB. The image, the localhost-only port
`7890`, and a persistent data volume are all pinned in `compose.yaml`, so this one
command is all you need:

```sh
docker compose up -d
```

Confirm the container is healthy (status should show `Up`):

```sh
docker ps
```

### Step 2 — Set up the Python environment

Create and activate a virtual environment, install the three dependencies, and
copy the environment file. The default `.env` targets the local Docker database
with no password, so no editing is needed.

**Windows (PowerShell)**

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

> If activation is blocked by execution policy, either run
> `Set-ExecutionPolicy -Scope Process RemoteSigned` for this session, or skip
> activation and call the venv Python directly as `.\.venv\Scripts\python.exe`
> in every command below.

**Linux / macOS (bash/zsh)**

```sh
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
```

Initialize the `logbase` database and confirm the connection works:

```sh
python scripts/db.py --init
python scripts/db.py --check
```

`--check` should print one row confirming the database and `connection_ok`.

### Step 3 — Load the datasets

Download the two official corpora and unpack them into a single input folder with
this exact layout (the loader looks for these precise names):

```text
input-data/
  BGL/BGL.log
  OpenStack/openstack_normal1.log
  OpenStack/openstack_normal2.log
  OpenStack/openstack_abnormal.log
```

Official downloads:

- **BGL** — <https://zenodo.org/records/8196385/files/BGL.zip?download=1>
- **OpenStack** — <https://zenodo.org/records/8196385/files/OpenStack.tar.gz?download=1>

Then load the data, apply the ownership table, and verify. Replace
`PATH_TO_INPUT_FOLDER` with the folder above (quote it if it contains spaces):

```sh
python scripts/load_logs.py --data-root "PATH_TO_INPUT_FOLDER" --load
python scripts/db.py --file sql/ownership.sql
python scripts/db.py --file sql/verify.sql
```

Finally, build the full-text indexes used by `search` and `distinctive_terms`:

```sh
python scripts/search_logs.py --setup
```

> Loading the full BGL corpus (~4.75M lines) takes a few minutes and is a
> one-time step. The loader refuses to duplicate rows, so it is safe to re-run; if
> the data is already loaded, skip straight to `--setup`.

Quick sanity check that everything is in place:

```sh
python scripts/search_logs.py --dataset openstack --query error --limit 5
```

### Step 4 — Connect an AI client (MCP)

The tools are exposed through an MCP server, `scripts/tools.py`, over stdio, so any
MCP client (Claude Code, Codex, Cursor, Kiro) can discover and call them. Run these
from the repository root; `--scope project` writes a shareable `.mcp.json` that
travels with the checkout.

```sh
# Claude Code — Linux/macOS
claude mcp add logbase --scope project -- .venv/bin/python scripts/tools.py
# Claude Code — Windows PowerShell
claude mcp add logbase --scope project -- .venv\Scripts\python.exe scripts\tools.py

# Codex — Linux/macOS
codex mcp add logbase -- .venv/bin/python scripts/tools.py
# Codex — Windows PowerShell
codex mcp add logbase -- .venv\Scripts\python.exe scripts\tools.py
```

For other clients (Cursor, Kiro, …), add a stdio server using the block in
`mcp.example.json`, replacing `ABSOLUTE_PATH_TO_REPO` with the full path to your
checkout. The server reads its database connection from `.env`, whatever directory
it starts from.

**Verify:** run `/mcp` (or your client's equivalent), confirm `logbase` is
connected, then ask the agent to call `data_overview` — it should return row counts
for BGL and OpenStack. You're ready.

## Tools

LogBase exposes eight read-only tools over MCP. Every result carries the exact
executed `sql`, `elapsed_seconds`, and — for bounded output — the total count and a
`truncated` flag, so a limited answer is never mistaken for the whole picture. For
full parameter tables, examples and returned fields, see
[docs/documentation.md](docs/documentation.md).

| Tool | What it does | Returns |
|---|---|---|
| `data_overview` | Discovery tool — shows what data exists. Call it first. | Row counts, time range, parse failures, valid levels, teams and components |
| `search` | Full-text search over log content with phrase, AND and exclude syntax | `total_matches` and ranked evidence rows |
| `nearby_events` | The lines immediately before and after a chosen event | Window lines in time order, anchor flagged |
| `get_event_details` | One complete log event by its stable identity | All fields, recoverable raw evidence, owning team |
| `trend` | Exact counts per hour, day or week | Zero-filled buckets in chronological order |
| `count_by` | Exact per-group counts over the whole dataset | Ranked groups with counts and percentages |
| `top_problems` | Ranked operational hotspots by component or team | Ranked groups with counts and percentages |
| `distinctive_terms` | Words over-represented in one period versus a baseline, powered by **SereneDB's native inverted-index term aggregates** (`ts_dict_agg` / `ts_dict_count`) — the counting happens entirely in the database | Terms with document counts, shares and change |

## Role-aware analysis

The same tools and the same corpus serve three distinct audiences, and LogBase
adapts to each one. A role changes the workflow, the evidence selected, the level
of detail and the recommended next steps — never the facts, the calculations,
database access or permissions. An engineer gets exact evidence identities,
surrounding context and the next technical check to run; a team lead gets totals,
trends and recurring-component patterns to coordinate around; a manager gets
concise hotspot rankings, ownership and decision-oriented tradeoffs. A clear,
specific question is answered directly, while a broad request ("Brief me on
OpenStack") first asks which perspective is wanted. Throughout, observed evidence
is kept separate from recommendations, and frequency or correlation is never
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
