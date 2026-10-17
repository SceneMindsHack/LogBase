# Setup

## 1. Database and Python

Start Docker Desktop with Linux containers. For an existing container:

```sh
docker start serenedb
```

On a fresh machine with no `serenedb` container, use `docker compose up -d` instead.
Do not run both alternatives. Compose uses a pinned image, localhost-only port
7890 and a persistent volume. It does not adopt a manually created container or
its volume. `docker compose down -v` erases its stored database; ordinary stops do not.

Windows PowerShell:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Do not overwrite an existing `.env`. If activation is restricted, use
`.\.venv\Scripts\python.exe` instead of `python` below. Linux/macOS can use
`python3.12 -m venv .venv`, `source .venv/bin/activate`, then the same pip command
and `cp .env.example .env`.

## 2. Choose exactly one connection mode

### A. Docker-local (default)

Keep `SERENEDB_CONNECTION=docker` in `.env`, set `SERENEDB_CONTAINER` to the
running container name, and keep `SERENEDB_DBNAME=logbase`. No password needed
under the default container-loopback authentication configuration. The scripts
use the standard container `psql`; no raw-data mount is required.

### B. Direct Python

Use `SERENEDB_CONNECTION=direct`, host `127.0.0.1`, port `7890`, database `logbase`,
user `postgres`, and your configured password in `.env`. The password must exist
on the database; putting a new value in `.env` alone does not configure it.

If a password is already configured, use it. Otherwise, open the local database
terminal and set one interactively, so it is not stored in command history:

```sh
docker exec -it serenedb psql -h 127.0.0.1 -p 7890 -U postgres -d postgres
```

At the psql prompt enter `\password postgres`, follow the hidden prompts, then
`\q`. Use that value only in your local `.env`. Do not commit it or send it to
teammates: each local instance can have its own password. This changes the
postgres account password on your own instance; coordinate first if it is shared.
Local Docker mode remains available under the default loopback trust configuration.

Direct mode uses psycopg, without launching Docker for each query. Both modes
read the same database and support all commands below. Other hosted databases
may need their own account/permissions configuration. Initialization requires
an account permitted to create the database; these local instructions use postgres.

## 3. Initialize and test

```sh
python scripts/db.py --init
python scripts/db.py --check
python -m unittest discover -s tests -v
python scripts/check_import.py
```

Initialization creates `logbase` if absent and preserves existing databases.
The import check creates a uniquely named probe table, checks original-text
preservation and removes only that probe.

## 4. Load and verify

Input layout:

```text
input-folder/
  BGL/BGL.log
  OpenStack/openstack_normal1.log
  OpenStack/openstack_normal2.log
  OpenStack/openstack_abnormal.log
```

```sh
python scripts/load_logs.py --data-root "PATH_TO_INPUT_FOLDER" --load
python scripts/db.py --file sql/ownership.sql
python scripts/db.py --file sql/verify.sql
```

Omit `--load` for offline validation only. Optional `--dataset bgl` or
`--dataset openstack` selects one dataset. Expected source baseline:

| Dataset | Rows | Parsed | Flagged headers |
|---|---:|---:|---:|
| BGL | 4,747,963 | 4,747,953 | 10 |
| OpenStack | 207,820 | 207,820 | 0 |

Compare hashes and summary counts from `reports/load-report.json` across machines.
The loader refuses populated tables rather than silently appending duplicates.
Each dataset commits separately, then verifies; failures after commit preserve
data for diagnosis. Run one importer at a time and leave input files unchanged.
An old incompatible schema fails before insertion; it is not auto-migrated.

Existing databases loaded with Omar's unified branch need no reload: the schema
is unchanged. Simply run the new search-index setup.

## 5. Index and search

```sh
python scripts/search_logs.py --setup
python scripts/search_logs.py --dataset openstack --query error --limit 5
python scripts/search_logs.py --dataset bgl --query parity --since 2005-06-03 --until 2005-06-04
```

Setup creates missing indexes and refreshes them without dropping tables or
existing indexes. Run it after imports. Index construction can take time and
additional disk space. Existing indexes with different definitions require an
explicit migration; setup does not silently replace them.

## 6. Optional CSV export

```sh
python scripts/export_csv.py --data-root "PATH_TO_INPUT_FOLDER"
```

Writes both full CSVs in `data/processed/`. Export needs no database and uses the
same parser, identity, columns, and malformed-row preservation as loading.
Use `--output-dir` to select another directory. Existing files cause refusal.
An interrupted export can leave a partial file; keep it separate or remove that
specific partial output before retrying. CSV is optional, not another import path.

The old 2,000-row sample-loader SQL and duplicate setup wrappers were removed to
leave one documented workflow. Previously loaded sample tables remain untouched.
