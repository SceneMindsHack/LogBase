# SceneMinds Database Setup

Updated: 17 October 2026

## Current status

The local SereneDB sample-data workflow is working.

Completed:

- SereneDB runs locally in Docker.
- The local `data/` folder is mounted inside the container at `/data`.
- BGL and OpenStack structured samples are available.
- `schema.sql`, `load.sql`, and `verify.sql` were created.
- Both samples were loaded successfully.
- Timestamps were parsed correctly.
- No invalid timestamps or duplicate line IDs were found.

## Project files

```text
LogBase/
  data/                    # Local data; ignored by Git
  sql/
    schema.sql
    load.sql
    verify.sql
  docs/
    database-setup.md
```

## Start SereneDB

Start Docker Desktop, then:

```powershell
docker start serenedb
```

Check that it is running:

```powershell
docker ps --filter name=serenedb
```

## Load the sample data

```powershell
docker cp .\sql\schema.sql serenedb:/tmp/schema.sql
docker exec serenedb psql -h 127.0.0.1 -p 7890 -U postgres -d postgres -f /tmp/schema.sql

docker cp .\sql\load.sql serenedb:/tmp/load.sql
docker exec serenedb psql -h 127.0.0.1 -p 7890 -U postgres -d postgres -f /tmp/load.sql
```

## Verify the data

```powershell
docker cp .\sql\verify.sql serenedb:/tmp/verify.sql
docker exec serenedb psql -h 127.0.0.1 -p 7890 -U postgres -d postgres -f /tmp/verify.sql
```

Current sample results:

| Dataset | Rows | First event | Last event | Invalid timestamps | Duplicate IDs |
|---|---:|---|---|---:|---:|
| BGL | 2,000 | 2005-06-03 15:42:50.675872 | 2006-01-03 07:13:09.127918 | 0 | 0 |
| OpenStack | 2,000 | 2017-05-16 00:00:00.008 | 2017-05-16 00:14:47.687 | 0 | 0 |

## Important notes

- Use the standard `psql` client inside the container for table queries.
- The built-in `serened psql` client produced a `ctid` error with these tables.
- Do not commit anything inside `data/`.
- These 2,000-row files are development samples, not the final challenge corpus.
- The final workflow must load and analyze the complete BGL and OpenStack datasets.

## Still to do

- Download and prepare the complete datasets.
- Adapt the loader for the full raw formats.
- Create `ownership.sql`.
- Verify complete dataset counts and date ranges.
- Build full-text search and aggregation queries.
- Expose the queries through the SceneMinds MCP server.