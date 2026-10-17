"""Quick connectivity check for a local SereneDB instance.

SereneDB speaks the PostgreSQL wire protocol. Per the SereneDB docs:
  - Default port: 7890 (exposed by the Docker container)
  - Bootstrap superuser: "postgres"
  - Default database: "postgres"
  - "postgres" is trusted only on true loopback (127.0.0.1 / ::1). A host
    connection to the container's published port arrives from the Docker
    bridge gateway, so it needs a password (SCRAM). We set one with
    ALTER ROLE and read it here from a local .env file.

Credentials are loaded from a .env file (gitignored). See .env.example for
the expected keys. Nothing secret is hardcoded in this script.

Docs:
  https://serenedb.com/docs/installation/docker
  https://serenedb.com/docs/security/client_authentication#the-default-posture
  https://serenedb.com/docs/security#the-first-connection
"""

import os
import sys

import psycopg
from dotenv import load_dotenv


def main() -> int:
    load_dotenv()  # reads .env from the current directory into os.environ

    conninfo = {
        "host": os.getenv("SERENEDB_HOST", "127.0.0.1"),
        "port": int(os.getenv("SERENEDB_PORT", "7890")),
        "user": os.getenv("SERENEDB_USER", "postgres"),
        "dbname": os.getenv("SERENEDB_DBNAME", "postgres"),
        "password": os.getenv("SERENEDB_PASSWORD"),
    }

    if not conninfo["password"]:
        print(
            "SERENEDB_PASSWORD is not set. Copy .env.example to .env and fill it in.",
            file=sys.stderr,
        )
        return 1

    try:
        with psycopg.connect(**conninfo, connect_timeout=10) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1;")
                result = cur.fetchone()
        print(f"Connected to SereneDB. SELECT 1 returned: {result[0]}")
        return 0
    except Exception as exc:  # noqa: BLE001 - report any failure clearly
        print(f"Connection failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
