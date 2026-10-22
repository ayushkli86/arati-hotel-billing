#!/usr/bin/env python3
"""Close a business day and write its Daily Sales and Operations Report.

This is the same job the application runs in its background thread, exposed
as a command line so a machine that keeps the till closed can still close
its days on a schedule.

Usage:
    python3 scripts/close_day.py                  # close yesterday
    python3 scripts/close_day.py --date 2026-03-14
    python3 scripts/close_day.py --catch-up        # close every missed day
    python3 scripts/close_day.py --force --date 2026-03-14

The job is idempotent: running it twice for the same business date does not
duplicate a sale, a payment or a report. The second run records a
``skipped`` entry in the scheduler history and stops.

For a cron entry (5 minutes after midnight, hotel time):

    5 0 * * * /path/to/venv/bin/python /path/to/app/scripts/close_day.py \\
        --catch-up >> /path/to/app/reports/close_day.log 2>&1
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from arati import db, scheduler

REPORT_DIR = Path(
    __import__("os").environ.get("ARATI_REPORT_DIR") or (ROOT / "reports")
)


def _factory() -> sqlite3.Connection:
    conn = sqlite3.connect(str(db.DB_PATH), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Close a business day and generate its report"
    )
    parser.add_argument(
        "--date",
        help="business date to close (YYYY-MM-DD); defaults to yesterday",
    )
    parser.add_argument(
        "--catch-up",
        action="store_true",
        help="close every business day that has no report yet",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="regenerate a day that was already closed, keeping the old version",
    )
    parser.add_argument(
        "--out", default=str(REPORT_DIR), help="directory for the report PDFs"
    )
    args = parser.parse_args()

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    worker = scheduler.Scheduler(
        _factory,
        Path(args.out),
        stop_event=None,
        owns_connection=True,
    )

    if args.catch_up:
        results = worker.catch_up()
        if not results:
            print("close-day: nothing to close — every traded day has a report.")
            return 0
        for result in results:
            print(
                f"close-day: {result['business_date']} -> {result['status']}"
            )
        return 0 if all(r["status"] == "generated" for r in results) else 1

    if args.force:
        conn = _factory()
        try:
            result = scheduler.regenerate(
                conn,
                args.date,
                Path(args.out),
                username="cron",
                user_id=None,
            )
        finally:
            conn.close()
        if result["status"] == "generated":
            print(f"close-day: regenerated {args.date} as v{result['version']}.")
            return 0
        print(
            "close-day: regeneration failed — "
            + "; ".join(result.get("problems", [])),
            file=sys.stderr,
        )
        return 1

    result = worker.run_once(args.date, force=False)
    if result["status"] == "generated":
        print(
            f"close-day: {result['business_date']} closed as v{result['version']}."
        )
        return 0
    if result["status"] == "skipped":
        print(f"close-day: {result['business_date']} was already closed.")
        return 0
    print(
        "close-day: failed — " + "; ".join(result.get("problems", [])),
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
