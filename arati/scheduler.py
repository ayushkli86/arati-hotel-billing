"""Daily closing scheduler.

The scheduler closes the previous business day at the configured local time
(default 00:05, Asia/Kathmandu) and writes that day's Daily Sales and
Operations Report.

Design rules that keep it safe:

* **Idempotent** — a business day is closed at most once. Running the job
  twice for the same day does not duplicate sales, payments, room charges or
  reports; the second run records a ``skipped`` entry and stops.
* **Recoverable** — every run is recorded in ``scheduler_runs``. If the app
  was closed over midnight, the next start finds the missing days and
  generates their reports.
* **Non-destructive** — closing a day never deletes or edits an invoice. It
  only reads the ledger and writes a report.
* **Auditable** — regenerating a report bumps the version, supersedes the old
  row and leaves a line in the audit log.

The scheduler runs inside the application as a background thread, so it does
not depend on a browser tab staying open. :mod:`scripts.close_day` offers the
same job as a command line for cron-style scheduling.
"""

from __future__ import annotations

import os
import sqlite3
import threading
import time
import traceback
from datetime import date, datetime, timedelta
from pathlib import Path

from . import business_time as bt
from . import daily_report, db

JOB_DAILY_CLOSE = "daily_close"


class Scheduler:
    """Background worker that closes business days on schedule."""

    def __init__(
        self,
        conn_factory,
        output_dir: str | Path,
        settings: dict | None = None,
        stop_event: threading.Event | None = None,
        owns_connection: bool = False,
    ):
        self.conn_factory = conn_factory
        self.output_dir = Path(output_dir)
        self.settings = settings or {}
        self.stop_event = stop_event or threading.Event()
        # True when the factory hands out a fresh connection each call and the
        # scheduler is responsible for closing it.
        self.owns_connection = owns_connection
        self.thread: threading.Thread | None = None
        self.last_result: dict | None = None

    # ------------------------------------------------------------------ run
    def run_once(self, business_date: str | None = None, force: bool = False) -> dict:
        """Close one business day. Safe to call repeatedly."""
        conn = self.conn_factory()
        try:
            settings = db.get_settings(conn)
            zone = bt.get_zone(settings.get("business_timezone"))
            day = business_date or bt.previous_day(bt.today(zone))
            run_id = self._begin(conn, day)
            try:
                if self._already_closed(conn, day) and not force:
                    self._finish(conn, run_id, "skipped", f"{day} already closed")
                    self.last_result = {
                        "status": "skipped",
                        "business_date": day,
                        "reason": "already closed",
                    }
                    return self.last_result

                result = daily_report.generate(
                    conn,
                    day,
                    self.output_dir,
                    settings=settings,
                    generated_by="scheduler",
                )
                status = "ok" if result["status"] == "generated" else "failed"
                message = (
                    f"{day} v{result['version']} → {result['status']}"
                    if status == "ok"
                    else "; ".join(result.get("problems", []))
                )
                self._finish(conn, run_id, status, message)
                self.last_result = result
                return result
            except Exception as exc:  # noqa: BLE001 - a failed run must be logged
                self._finish(conn, run_id, "failed", str(exc))
                self.last_result = {
                    "status": "failed",
                    "business_date": day,
                    "problems": [str(exc)],
                }
                return self.last_result
        finally:
            if self.owns_connection:
                conn.close()

    def catch_up(self, lookback_days: int = 14) -> list[dict]:
        """Generate any report that should exist but does not.

        Called on start-up so a machine that was off over midnight still ends
        up with a report for every business day it traded.
        """
        conn = self.conn_factory()
        try:
            settings = db.get_settings(conn)
            zone = bt.get_zone(settings.get("business_timezone"))
            today = bt.today(zone)
            results = []
            for offset in range(1, lookback_days + 1):
                day = bt.previous_day(today - timedelta(days=offset - 1))
                if not self._has_activity(conn, day):
                    continue
                if self._already_closed(conn, day):
                    continue
                results.append(self.run_once(day))
            return results
        finally:
            if self.owns_connection:
                conn.close()

    # -------------------------------------------------------------- threads
    def start(self) -> None:
        """Start the background thread."""
        if self.thread and self.thread.is_alive():
            return
        self.thread = threading.Thread(
            target=self._loop, name="daily-close-scheduler", daemon=True
        )
        self.thread.start()

    def stop(self) -> None:
        self.stop_event.set()

    def _loop(self) -> None:
        while not self.stop_event.is_set():
            try:
                self.catch_up()
            except Exception:  # noqa: BLE001 - the thread must survive
                traceback.print_exc()
            delay = self._seconds_until_next_close()
            if self.stop_event.wait(delay):
                return
            try:
                self.run_once()
            except Exception:  # noqa: BLE001
                traceback.print_exc()

    def _seconds_until_next_close(self) -> float:
        conn = self.conn_factory()
        try:
            settings = db.get_settings(conn)
            zone = bt.get_zone(settings.get("business_timezone"))
            close_time = settings.get("close_time", "00:05")
        finally:
            if self.owns_connection:
                conn.close()
        hour, _, minute = close_time.partition(":")
        try:
            target_hour = int(hour)
            target_minute = int(minute or 0)
        except ValueError:
            target_hour, target_minute = 0, 5
        now = bt.now(zone)
        target = now.replace(
            hour=target_hour, minute=target_minute, second=0, microsecond=0
        )
        if target <= now:
            target += timedelta(days=1)
        return max(30.0, (target - now).total_seconds())

    # ------------------------------------------------------------ internals
    def _already_closed(self, conn: sqlite3.Connection, day: str) -> bool:
        row = conn.execute(
            "SELECT status FROM daily_reports WHERE business_date = ? "
            "ORDER BY version DESC LIMIT 1",
            (day,),
        ).fetchone()
        return bool(row) and row["status"] == "generated"

    def _has_activity(self, conn: sqlite3.Connection, day: str) -> bool:
        row = conn.execute(
            "SELECT (SELECT COUNT(*) FROM bills WHERE status = 'issued' AND is_draft = 0 "
            "AND bill_date = ?) + (SELECT COUNT(*) FROM payments WHERE business_date = ?)",
            (day, day),
        ).fetchone()
        return bool(row[0])

    def _begin(self, conn: sqlite3.Connection, day: str) -> int:
        with conn:
            cursor = conn.execute(
                "INSERT INTO scheduler_runs (job_name, business_date, started_at, status) "
                "VALUES (?,?,?,'running')",
                (JOB_DAILY_CLOSE, day, datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
            )
        return int(cursor.lastrowid)

    def _finish(self, conn: sqlite3.Connection, run_id: int, status: str, message: str) -> None:
        conn.execute(
            "UPDATE scheduler_runs SET finished_at = ?, status = ?, message = ? "
            "WHERE run_id = ?",
            (
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                status,
                message[:2000],
                run_id,
            ),
        )
        conn.commit()


# --------------------------------------------------------------------------- #
# manual regeneration
# --------------------------------------------------------------------------- #
def regenerate(
    conn: sqlite3.Connection,
    business_date: str,
    output_dir: str | Path,
    settings: dict | None = None,
    username: str = "",
    user_id: int | None = None,
) -> dict:
    """Rebuild a report after a correction, keeping the previous version.

    The old row is marked ``superseded`` and points at the new one, so the
    audit trail shows what was replaced and why.
    """
    settings = settings or db.get_settings(conn)
    previous = conn.execute(
        "SELECT * FROM daily_reports WHERE business_date = ? "
        "ORDER BY version DESC LIMIT 1",
        (business_date,),
    ).fetchone()

    result = daily_report.generate(
        conn,
        business_date,
        output_dir,
        settings=settings,
        generated_by=username or "administrator",
        username=username,
        user_id=user_id,
    )
    if result["status"] == "generated" and previous is not None:
        conn.execute(
            "UPDATE daily_reports SET status = 'superseded', superseded_by = ? "
            "WHERE report_id = ?",
            (result["row_id"], previous["report_id"]),
        )
        conn.commit()
        db.log_audit(
            conn,
            "daily_report.regenerate",
            "daily_report",
            result["row_id"],
            f"{business_date}: v{previous['version']} superseded by v{result['version']}",
            user_id,
            username,
        )
    return result


def list_runs(conn: sqlite3.Connection, limit: int = 50) -> list[sqlite3.Row]:
    return list(
        conn.execute(
            "SELECT * FROM scheduler_runs ORDER BY run_id DESC LIMIT ?", (limit,)
        )
    )


def missing_report_days(conn: sqlite3.Connection, lookback_days: int = 14) -> list[str]:
    """Business days that traded but have no report yet."""
    settings = db.get_settings(conn)
    zone = bt.get_zone(settings.get("business_timezone"))
    today = bt.today(zone)
    missing: list[str] = []
    for offset in range(1, lookback_days + 1):
        day = bt.previous_day(today - timedelta(days=offset - 1))
        row = conn.execute(
            "SELECT (SELECT COUNT(*) FROM bills WHERE status = 'issued' AND is_draft = 0 "
            "AND bill_date = ?) + (SELECT COUNT(*) FROM payments WHERE business_date = ?)",
            (day, day),
        ).fetchone()
        if not row[0]:
            continue
        report = conn.execute(
            "SELECT status FROM daily_reports WHERE business_date = ? "
            "ORDER BY version DESC LIMIT 1",
            (day,),
        ).fetchone()
        if not report or report["status"] != "generated":
            missing.append(day)
    return missing
