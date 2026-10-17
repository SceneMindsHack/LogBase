"""Severity rollup + full-text index demo on bgl_logs (all ~4.75M rows).

Shows, for the message column:
  1. a severity count,
  2. a baseline ILIKE substring search for 'error' (no index), timed,
  3. a SereneDB inverted full-text index + @@ search for 'error', timed.

SereneDB full-text search model (per the docs):
  CREATE TEXT SEARCH DICTIONARY <d> AS split_text(...) | normalize_tokens(...)
  CREATE INDEX <idx> ON <table> USING inverted (<key>, <col> <d>)
  VACUUM (REFRESH_TABLE) <table>          -- build/refresh the index
  SELECT ... FROM <idx> WHERE <col> @@ 'error'

Docs:
  https://serenedb.com/docs/sql/functions/search/full-text
  https://serenedb.com/docs/quick-start#index-for-full-text-and-vector-search
"""

import os
import sys
import time

import psycopg
from dotenv import load_dotenv

# --- Exact SQL used, kept as named constants so we can print them verbatim ---

SQL_SEVERITY = """
SELECT severity, COUNT(*) AS n
FROM bgl_logs
GROUP BY severity
ORDER BY n DESC
""".strip()

SQL_ILIKE_COUNT = "SELECT COUNT(*) FROM bgl_logs WHERE message ILIKE '%error%'"

SQL_CREATE_DICT = """
CREATE TEXT SEARCH DICTIONARY bgl_en AS
    split_text(case := 'lower') | normalize_tokens('en_US.UTF-8', accent := false)
    WITH (frequency, position, offset)
""".strip()

SQL_CREATE_INDEX = """
CREATE INDEX bgl_logs_idx ON bgl_logs
    USING inverted (id, message bgl_en)
""".strip()

SQL_REFRESH = "VACUUM (REFRESH_TABLE) bgl_logs"

SQL_FTS_COUNT = "SELECT COUNT(*) FROM bgl_logs_idx WHERE message @@ 'error'"


def timed(cur, sql):
    """Run a scalar query, return (value, elapsed_seconds)."""
    start = time.perf_counter()
    cur.execute(sql)
    row = cur.fetchone()
    elapsed = time.perf_counter() - start
    return (row[0] if row else None), elapsed


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

    with psycopg.connect(**conninfo, connect_timeout=10) as conn:
        conn.autocommit = True
        with conn.cursor() as cur:
            # 1) Severity rollup -------------------------------------------------
            print("=== severity count ===")
            print(SQL_SEVERITY + ";\n")
            cur.execute(SQL_SEVERITY)
            for sev, n in cur.fetchall():
                print(f"  {sev:<10} {n:>10,}")

            # 2) Baseline ILIKE (no index) --------------------------------------
            print("\n=== ILIKE substring search (no index) ===")
            print(SQL_ILIKE_COUNT + ";")
            ilike_count, ilike_t = timed(cur, SQL_ILIKE_COUNT)
            print(f"  matches: {ilike_count:,}   time: {ilike_t*1000:,.1f} ms")

            # 3) Build the inverted full-text index -----------------------------
            print("\n=== build full-text index ===")
            cur.execute("DROP INDEX IF EXISTS bgl_logs_idx")
            cur.execute("DROP TEXT SEARCH DICTIONARY IF EXISTS bgl_en")
            print(SQL_CREATE_DICT + ";")
            cur.execute(SQL_CREATE_DICT)
            print(SQL_CREATE_INDEX + ";")
            cur.execute(SQL_CREATE_INDEX)
            print(SQL_REFRESH + ";")
            build_start = time.perf_counter()
            cur.execute(SQL_REFRESH)
            print(f"  index built in {time.perf_counter()-build_start:,.1f} s")

            # 4) FTS @@ search (uses the index) ---------------------------------
            print("\n=== full-text @@ search (indexed) ===")
            print(SQL_FTS_COUNT + ";")
            fts_count, fts_t = timed(cur, SQL_FTS_COUNT)
            print(f"  matches: {fts_count:,}   time: {fts_t*1000:,.1f} ms")

            # 5) Comparison -----------------------------------------------------
            print("\n=== comparison ===")
            print(f"  ILIKE : {ilike_count:,} matches in {ilike_t*1000:,.1f} ms")
            print(f"  @@    : {fts_count:,} matches in {fts_t*1000:,.1f} ms")
            if fts_t > 0:
                print(f"  speedup: {ilike_t/fts_t:,.1f}x faster with the FTS index")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
