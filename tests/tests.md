# Running the tests

LogBase has three layers of checks: a fast offline unit suite, an optional live
database fixture test, and a real-database round-trip check. Run everything from
the repository root with the virtual environment active (see the
[README setup](../README.md#setup)). On Windows, if the venv is not activated,
substitute `.\.venv\Scripts\python.exe` for `python`.


## 1. Offline unit suite

The main suite. It runs fully offline — no database or Docker required — because
database access is mocked. It covers input validation, SQL shape, output
contracts, scoring, provenance, and MCP tool registration across all eight tools.

```sh
python -m unittest discover -s tests -v
```

Run a single module or test while developing:

```sh
python -m unittest tests.test_trend -v
python -m unittest tests.test_distinctive_terms.SqlShapeTests -v
```

The suite spans these modules:

| Module | Covers |
|---|---|
| `test_loader.py` | The shared parser, continuation handling, null-byte preservation |
| `test_export_search.py` | CSV export and the full-text search query builder |
| `test_search_logs.py` | `search` query building, `websearch_to_tsquery` phrase/AND/exclude syntax, rank-identity guidance |
| `test_data_overview.py` | `data_overview` SQL shape, validation, and output contract |
| `test_nearby_events.py` | `nearby_events` anchoring (time and identity), windowing, ordering |
| `test_get_event_details.py` | Complete-record retrieval, missing and duplicate identities |
| `test_trend.py` | Bucketing (hour/day/week), zero-fill, validation |
| `test_count_by.py` | Per-group counts, dimensions, filters |
| `test_top_problems.py` | Ranked hotspots, default problem levels, ownership join |
| `test_distinctive_terms.py` | Significant-terms SQL, scoring, window validation (offline parts) |
| `test_provenance.py` | Provenance capture, SQL extraction, and tool registration/signatures |


## 2. Live database fixture test (optional)

`test_distinctive_terms.py` includes a fixture test that proves the native SereneDB
term-dictionary aggregates (`ts_dict_agg` / `ts_dict_count`) actually produce the
expected document-frequency semantics. It builds its own uniquely named temporary
table and index, asserts the scores, and cleans up only its own resources — it
never touches the loaded datasets.

It is skipped by default and runs only when `LOGBASE_LIVE_TESTS=1` is set. It needs
the SereneDB container running (see README step 1).

```powershell
# Windows (PowerShell)
$env:LOGBASE_LIVE_TESTS = "1"
python -m unittest tests.test_distinctive_terms -v
Remove-Item Env:\LOGBASE_LIVE_TESTS
```

```sh
# Linux / macOS
LOGBASE_LIVE_TESTS=1 python -m unittest tests.test_distinctive_terms -v
```

When the gate is not set, the offline suite reports these as skipped — that is
expected, not a failure.


## 3. Real-database round-trip check

`scripts/check_import.py` verifies a live insert/read cycle against the initialized
database using a uniquely named temporary probe table, confirming original-text
preservation, then removes only that probe. It needs the database initialized
(README steps 1–2) but does not require the full datasets to be loaded.

```sh
python scripts/check_import.py
```


## Notes

- The offline suite (step 1) is the one to run routinely; it is fast and needs no
  services.
- Steps 2 and 3 require the SereneDB container running and are read-only against
  your data — they create and drop only their own temporary tables.
- Local test reports are written to the git-ignored `reports/`. Raw logs, exports,
  virtual environments, and `.env` are never committed.
