"""Load the first N lines of the BGL and OpenStack raw logs into SereneDB.

SereneDB speaks the PostgreSQL wire protocol, so we use psycopg 3. Rows are
bulk-loaded with COPY (the fast path), and we keep one transaction per table
since SereneDB has no SAVEPOINT (see the SereneDB Python client docs).

Credentials come from .env (see .env.example). Nothing secret is hardcoded.

Docs:
  https://serenedb.com/docs/clients/python
  https://serenedb.com/docs/sql/data_types
"""

import os
import sys
from datetime import datetime

import psycopg
from dotenv import load_dotenv

LIMIT = 10_000

BGL_LOG = "data/BGL/BGL.log"
OPENSTACK_LOGS = [
    "data/OpenStack/openstack_normal1.log",
    "data/OpenStack/openstack_normal2.log",
    "data/OpenStack/openstack_abnormal.log",
]

# --- Schema -----------------------------------------------------------------
# BGL line (space-separated), e.g.:
#   - 1117838570 2005.06.03 R02-M1-N0-C:J12-U11 2005-06-03-15.42.50.363779 \
#     R02-M1-N0-C:J12-U11 RAS KERNEL INFO <message...>
# "-" in the label column means a non-alert line; anything else is an alert tag.
BGL_DDL = """
CREATE TABLE IF NOT EXISTS bgl_logs (
    id            BIGINT,
    label         VARCHAR,        -- "-" = non-alert, else the alert category
    is_alert      BOOLEAN,        -- convenience flag derived from label
    epoch         BIGINT,         -- unix seconds
    event_date    VARCHAR,        -- raw YYYY.MM.DD field
    node          VARCHAR,        -- e.g. R02-M1-N0-C:J12-U11
    event_time    TIMESTAMP,      -- parsed from the YYYY-MM-DD-HH.MM.SS.ffffff field
    msg_type      VARCHAR,        -- e.g. RAS
    component     VARCHAR,        -- e.g. KERNEL / APP / HARDWARE
    severity      VARCHAR,        -- e.g. INFO / WARNING / FATAL
    message       VARCHAR
)
"""

# OpenStack line (space-separated), e.g.:
#   nova-api.log.1.2017-05-16_13:53:08 2017-05-16 00:00:00.008 25746 INFO \
#     nova.osapi_compute.wsgi.server [req-...] <message...>
OPENSTACK_DDL = """
CREATE TABLE IF NOT EXISTS openstack_logs (
    id            BIGINT,
    source_file   VARCHAR,        -- the nova-*.log.* token
    event_time    TIMESTAMP,      -- date + time combined
    pid           INTEGER,
    severity      VARCHAR,        -- INFO / WARNING / ERROR
    component     VARCHAR,        -- e.g. nova.osapi_compute.wsgi.server
    message       VARCHAR
)
"""


def parse_bgl(line, row_id):
    """Return a tuple for bgl_logs, or None if the line can't be parsed."""
    # Some BGL lines carry stray NUL (0x00) bytes, which PostgreSQL text
    # columns reject. Strip them before parsing.
    parts = line.rstrip("\n").replace("\x00", "").split(" ", 9)
    # A valid line has 9 fixed fields; the 10th (message) may be absent when a
    # record has no message body (common for FATAL alerts). Treat a missing
    # message as an empty string rather than dropping the row.
    if len(parts) == 9:
        parts.append("")
    if len(parts) < 10:
        return None
    label, epoch, event_date, node, datetime_str, _node2, msg_type, component, severity, message = parts
    try:
        epoch_val = int(epoch)
    except ValueError:
        epoch_val = None
    event_time = None
    try:
        # e.g. 2005-06-03-15.42.50.363779
        event_time = datetime.strptime(datetime_str, "%Y-%m-%d-%H.%M.%S.%f")
    except ValueError:
        pass
    return (
        row_id,
        label,
        label != "-",
        epoch_val,
        event_date,
        node,
        event_time,
        msg_type,
        component,
        severity,
        message,
    )


def parse_openstack(line, row_id):
    """Return a tuple for openstack_logs, or None if the line can't be parsed."""
    parts = line.rstrip("\n").replace("\x00", "").split(" ", 6)
    # Like BGL, a record may have 6 fixed fields and no message body. Treat a
    # missing message as an empty string rather than dropping the row.
    if len(parts) == 6:
        parts.append("")
    if len(parts) < 7:
        return None
    source_file, date_str, time_str, pid, severity, component, message = parts
    event_time = None
    try:
        event_time = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M:%S.%f")
    except ValueError:
        pass
    try:
        pid_val = int(pid)
    except ValueError:
        pid_val = None
    return (row_id, source_file, event_time, pid_val, severity, component, message)


def read_rows(paths, parser, limit):
    """Parse up to `limit` lines total across the given file paths."""
    rows = []
    row_id = 0
    for path in paths if isinstance(paths, list) else [paths]:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                if len(rows) >= limit:
                    return rows
                row_id += 1
                parsed = parser(line, row_id)
                if parsed is not None:
                    rows.append(parsed)
    return rows


def load_table(conn, ddl, table, columns, rows):
    """Create the table fresh and COPY the rows in. Returns the row count."""
    with conn.cursor() as cur:
        cur.execute(f"DROP TABLE IF EXISTS {table}")
        cur.execute(ddl)
        collist = ", ".join(columns)
        with cur.copy(f"COPY {table} ({collist}) FROM STDIN") as copy:
            for row in rows:
                copy.write_row(row)
    conn.commit()
    with conn.cursor() as cur:
        cur.execute(f"SELECT COUNT(*) FROM {table}")
        return cur.fetchone()[0]


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

    bgl_rows = read_rows(BGL_LOG, parse_bgl, LIMIT)
    os_rows = read_rows(OPENSTACK_LOGS, parse_openstack, LIMIT)

    bgl_cols = [
        "id", "label", "is_alert", "epoch", "event_date", "node",
        "event_time", "msg_type", "component", "severity", "message",
    ]
    os_cols = [
        "id", "source_file", "event_time", "pid", "severity", "component", "message",
    ]

    with psycopg.connect(**conninfo, connect_timeout=10) as conn:
        bgl_count = load_table(conn, BGL_DDL, "bgl_logs", bgl_cols, bgl_rows)
        os_count = load_table(conn, OPENSTACK_DDL, "openstack_logs", os_cols, os_rows)

    print(f"bgl_logs:       {bgl_count:>6} rows loaded")
    print(f"openstack_logs: {os_count:>6} rows loaded")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
