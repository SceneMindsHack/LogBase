"""Stream the ENTIRE BGL.log into SereneDB, in batches, into bgl_logs.

Unlike load_logs.py (which loads a 10k sample of both datasets), this script
loads every line of data/BGL/BGL.log. It never builds a full in-memory list:
lines are parsed and pushed straight into a single COPY stream, so memory stays
flat regardless of file size (~4.7M lines).

Reuses the bgl_logs schema and the BGL parser from load_logs.py so the table
layout stays identical to the sample loader.

Credentials come from .env (see .env.example). Nothing secret is hardcoded.

Docs:
  https://serenedb.com/docs/clients/python
"""

import os
import sys
import time

import psycopg
from dotenv import load_dotenv

from load_logs import BGL_DDL, BGL_LOG, parse_bgl

BGL_COLUMNS = [
    "id", "label", "is_alert", "epoch", "event_date", "node",
    "event_time", "msg_type", "component", "severity", "message",
]

PROGRESS_EVERY = 500_000  # print a heartbeat every N parsed lines


def stream_load(conn):
    """Parse BGL.log line by line and COPY rows straight into bgl_logs.

    Returns (loaded, skipped). One COPY = one transaction's worth of work,
    which suits SereneDB (no SAVEPOINT, one unit of work per transaction).
    """
    collist = ", ".join(BGL_COLUMNS)
    loaded = 0
    skipped = 0
    row_id = 0
    start = time.time()

    with conn.cursor() as cur:
        cur.execute("DROP TABLE IF EXISTS bgl_logs")
        cur.execute(BGL_DDL)
        with open(BGL_LOG, "r", encoding="utf-8", errors="replace") as fh:
            with cur.copy(f"COPY bgl_logs ({collist}) FROM STDIN") as copy:
                for line in fh:
                    row_id += 1
                    row = parse_bgl(line, row_id)
                    if row is None:
                        skipped += 1
                        continue
                    copy.write_row(row)
                    loaded += 1
                    if row_id % PROGRESS_EVERY == 0:
                        rate = row_id / max(time.time() - start, 1e-9)
                        print(f"  ...{row_id:>9,} lines read ({rate:,.0f}/s)", flush=True)
    conn.commit()
    return loaded, skipped


def main() -> int:
    load_dotenv()
    password = os.getenv("SERENEDB_PASSWORD")
    if not password:
        print("SERENEDB_PASSWORD is not set. Copy .env.example to .env.", file=sys.stderr)
        return 1

    conninfo = {
        "host": os.getenv("SERENEDB_HOST", "127.0.0.1"),
        "port": int(os.getenv("SERENEDB_PORT", "7890")),
        "user": os.getenv("SERENEDB_USER", "postgres"),
        "dbname": os.getenv("SERENEDB_DBNAME", "postgres"),
        "password": password,
    }

    print(f"Loading all of {BGL_LOG} into bgl_logs (streaming COPY)...")
    start = time.time()
    with psycopg.connect(**conninfo, connect_timeout=10) as conn:
        loaded, skipped = stream_load(conn)
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM bgl_logs")
            count = cur.fetchone()[0]

    elapsed = time.time() - start
    print(f"Done in {elapsed:,.1f}s. Loaded {loaded:,} rows, skipped {skipped:,} unparseable.")
    print(f"SELECT COUNT(*) FROM bgl_logs -> {count:,}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
