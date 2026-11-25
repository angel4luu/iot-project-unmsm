"""Readiness probe: `python -m energy_ingestion.health.ready` exits 0 when ready.

Ready means the service is connected to the broker (fresh heartbeat file) and the
SQLite database opens with the migrated schema.
"""

from __future__ import annotations

import os
import sqlite3
import sys
import time
from pathlib import Path

HEARTBEAT_FILE = Path(os.environ.get("HEARTBEAT_FILE", "/tmp/energy-ingestion.heartbeat"))  # noqa: S108
MAX_AGE_S = 30


def beat() -> None:
    HEARTBEAT_FILE.write_text(str(time.time()), encoding="ascii")


def check() -> list[str]:
    problems: list[str] = []
    try:
        age = time.time() - float(HEARTBEAT_FILE.read_text(encoding="ascii"))
        if age > MAX_AGE_S:
            problems.append(f"heartbeat stale ({age:.0f} s)")
    except OSError, ValueError:
        problems.append("no broker heartbeat")
    path = os.environ.get("SQLITE_PATH", "energy.sqlite")
    try:
        with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as conn:
            conn.execute("SELECT 1 FROM alembic_version").fetchone()
    except sqlite3.Error as exc:
        problems.append(f"sqlite: {exc.__class__.__name__}")
    return problems


def main() -> int:
    problems = check()
    print("ready" if not problems else "not ready: " + "; ".join(problems))
    return 0 if not problems else 1


if __name__ == "__main__":
    sys.exit(main())
