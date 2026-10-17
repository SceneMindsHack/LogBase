# Database setup

## Start the database

Start Docker Desktop with Linux containers. If you already have a container named
`serenedb`, keep it and run `docker start serenedb`. On a fresh machine without
that container, run `docker compose up -d` from the repository root instead.
These are alternatives; do not start both on the same port. Compose does not
adopt existing manually created containers or their volumes.

Compose pins the tested image by digest, exposes port 7890 on localhost only, and
uses persistent storage. Do not run `docker compose down -v` unless you intend
to erase its database. Existing containers keep their original storage.

## Prepare Python

Use Python 3.12. In Windows PowerShell:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

If activation is restricted, substitute `.\.venv\Scripts\python.exe` for
`python` below; no policy change is necessary. On Linux/macOS use
`python3.12 -m venv .venv` and `source .venv/bin/activate`.

## Initialize and check

```sh
python scripts/init_db.py
python -m unittest discover -s tests -v
python scripts/check_import.py
```

This creates database `logbase`, preserving existing samples in `postgres`.
The scripts run the container's standard `psql` against its loopback interface,
where the default local postgres login works. Host TCP can require a password;
the scripts do not change authentication. Docker CLI and container `psql` are
required. Export `SERENEDB_CONTAINER` if the container has another name.
Python scripts do not automatically load `.env`.

## Load full datasets

Your input directory must contain:

```text
input-folder/
  BGL/BGL.log
  OpenStack/openstack_normal1.log
  OpenStack/openstack_normal2.log
  OpenStack/openstack_abnormal.log
```

Replace the placeholder with your own absolute folder path:

```sh
python scripts/load_logs.py --data-root "PATH_TO_INPUT_FOLDER"
python scripts/load_logs.py --data-root "PATH_TO_INPUT_FOLDER" --load
python scripts/run_sql.py sql/ownership.sql
python scripts/run_sql.py sql/verify.sql
```

The first command is optional offline validation. The second validates again
then streams the files directly into SereneDB. No input-file Docker mount is
needed. Reports and SHA-256 input hashes go to `reports/load-report.json`.

| Dataset | Rows | Parsed | Flagged headers |
|---|---:|---:|---:|
| BGL | 4,747,963 | 4,747,953 | 10 |
| OpenStack | 207,820 | 207,820 | 0 |

Compare hashes, counts, severity totals and date ranges across machines.
Malformed rows are retained. Line IDs restart in each source file.

The loader refuses nonempty selected tables. Use `--dataset bgl` or
`--dataset openstack` to load only an unloaded dataset. Each dataset COPY commits
separately, followed by verification. Failed post-commit checks leave data for
inspection, never automatically delete it. If the second dataset fails, the
first may already be committed. Run only one loader and keep input files stable.

Existing incompatible tables in `logbase` cause a failure before insertion.
`CREATE TABLE IF NOT EXISTS` cannot migrate an old schema. Review/migrate that
database explicitly rather than replacing existing data.

## Optional structured samples

The previous contributor documented successful imports of 2,000 BGL and 2,000
OpenStack sample rows with valid timestamps and unique IDs. That workflow is
preserved, but now writes only `sample_bgl_logs` and `sample_openstack_logs`.

Place `BGL_2k.log_structured.csv` and `OpenStack_2k.log_structured.csv` inside the
ignored `data/` folder. Compose mounts it read-only at `/data`. Existing manually
created containers need an equivalent mount or files copied into `/data`.

```sh
python scripts/run_sql.py sql/load.sql
python scripts/run_sql.py sql/verify_samples.sql
```

This optional SQL replaces only sample tables. It depends on sample CSV type
inference, including OpenStack date/time types. Check the verification output
for the files used. Samples are not required for the default full-data workflow.
