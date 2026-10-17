# LogBase

Local BGL and OpenStack log preparation for SereneDB. Currently provides a
shared schema, full-data loader, validation and fictional ownership mapping.
MCP tools are not implemented yet.

See [database setup](docs/database-setup.md) for the complete workflow.

| File | Purpose |
|---|---|
| `compose.yaml` | Pinned SereneDB image and persistent storage |
| `scripts/init_db.py` | Creates a separate `logbase` database |
| `scripts/load_logs.py` | Validates raw files and optionally imports all records |
| `scripts/docker_db.py` | Docker/psql connection and streaming COPY |
| `scripts/check_import.py` | Small real-server round-trip test |
| `scripts/run_sql.py` | Runs trusted repository SQL files |
| `sql/schema.sql` | Shared full-corpus tables |
| `sql/load.sql` | Optional structured samples, in separate sample tables |
| `sql/verify.sql` | Full-corpus counts, dates, duplicate identities |
| `sql/verify_samples.sql` | Checks optional samples |
| `sql/ownership.sql` | Fictional component ownership |
| `tests/` | Offline parser tests |

## Data contract

Use `bgl_logs` and `openstack_logs` in database `logbase`. Common fields:
`source_file`, `line_id`, `event_time`, `level`, `component`, `content`, `raw_text`,
`parse_ok`, `parse_error`, `event_id`, `event_template`, and `raw_text_base64`.

Evidence identity is **dataset + source_file + line_id**. One row is a physical
input line, not an incident. Original text is retained except the line terminator.
For records containing null bytes, `raw_text` and `content` show the printable
sequence `\u0000`; `raw_text_base64` preserves the exact original UTF-8 text.
This avoids truncation by text clients. That field is null on ordinary records.
Malformed headers are kept with `parse_ok=false`. Time/component queries can
exclude these rows, but answers must state the limitation.

`event_time` preserves displayed source time, with no invented timezone. BGL
retains `epoch_seconds`, `label`, `node`, `log_type`. OpenStack retains `log_record`,
`pid`, `correlation_data`, `request_id`, `instance_id`. Its initial bracketed
context remains in `content` and is also extracted into `correlation_data`.

Full-data `event_id` and `event_template` remain null until pattern extraction is
implemented. Dataset labels and normal/abnormal filenames do not prove causes.
BGL and OpenStack cover different years; do not treat them as simultaneous.

Join `component_ownership` on `(dataset, component)`. Team names are explicitly
fictional. Use a left join and show unmatched components as `Unassigned`.

## Validation

```sh
python -m unittest discover -s tests -v
python scripts/check_import.py
python scripts/run_sql.py sql/verify.sql
```

The last two commands require an initialized running database. Full import checks
row/parsed counts, date ranges, severity totals and duplicate identities. Reports
remain local under ignored `reports/`. Indexes, MCP tools and agent workflows are
subsequent work.

Data source: Loghub (Zhu et al., ISSRE 2023; BGL also Oliner and Stearley, DSN 2007).
Download full archives from the supplied dataset links. Do not commit raw data,
virtual environments or secrets.
