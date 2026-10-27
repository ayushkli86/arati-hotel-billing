"""Versioned daily-close reports and their in-process scheduler."""

from __future__ import annotations

import json
import logging
import os
import threading
from datetime import datetime, time, timedelta
from pathlib import Path
from typing import Callable
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session
from weasyprint import HTML

from . import reporting
from .models import AuditLog, DailyReport, HotelSetting, Invoice, Payment, Refund, SchedulerRun, User, utcnow
from .services import local_now

logger = logging.getLogger(__name__)
JOB_DAILY_CLOSE = "daily_close"
DEFAULT_REPORT_DIRECTORY = Path(__file__).resolve().parent / "data" / "daily-reports"


def report_directory() -> Path:
    return Path(os.getenv("ARATI_WEB_REPORT_DIRECTORY", str(DEFAULT_REPORT_DIRECTORY))).resolve()


def _setting(db: Session, key: str, default: str = "") -> str:
    row = db.get(HotelSetting, key)
    return row.value if row is not None else default


def _validate_business_date(value: str) -> str:
    first, _last = reporting.validate_period(value, value)
    if first > local_now().date():
        raise ValueError("A daily-close report cannot be generated for a future date.")
    return first.isoformat()


def list_reports(db: Session, limit: int = 120) -> list[DailyReport]:
    return list(db.scalars(
        select(DailyReport)
        .order_by(DailyReport.business_date.desc(), DailyReport.version.desc())
        .limit(limit)
    ))


def list_runs(db: Session, limit: int = 80) -> list[SchedulerRun]:
    return list(db.scalars(
        select(SchedulerRun).order_by(SchedulerRun.id.desc()).limit(limit)
    ))


def _daily_report_document(db: Session, report: dict) -> str:
    from .main import _billing_settings, money, templates

    return templates.get_template("report_print.html").render(
        report=report,
        hotel_settings=_billing_settings(db),
        money=money,
    )


def generate_report(
    db: Session,
    business_date: str,
    *,
    generated_by: str,
    user_id: int | None = None,
    directory: Path | None = None,
) -> DailyReport:
    day = _validate_business_date(business_date)
    version = (db.scalar(
        select(func.max(DailyReport.version)).where(DailyReport.business_date == day)
    ) or 0) + 1
    generated_at = local_now().replace(tzinfo=None)
    entry = DailyReport(
        business_date=day,
        version=version,
        status="failed",
        generated_at=generated_at,
        generated_by=generated_by[:80],
        totals_json="{}",
    )
    db.add(entry)
    db.flush()

    try:
        report = reporting.build_report(db, "operations_summary", day, day)
        summary_keys = (
            "gross_sales", "net_sales", "collected", "cash_collected", "refunds",
            "adjustments", "outstanding", "opening_cash", "closing_cash",
            "room_revenue", "invoices", "occupied_rooms", "available_rooms",
            "sellable_rooms", "occupancy_rate",
        )
        summary = {key: report["totals"].get(key, 0) for key in summary_keys}
        summary["generated_at"] = generated_at.isoformat(timespec="seconds")
        report["generated_at"] = generated_at.strftime("%Y-%m-%d %H:%M:%S")

        # Complete daily sales detail: every invoice of the day with guest names,
        # plus the payment-method breakdown from the ledger.
        try:
            detail = reporting.build_report(db, "daily_full", day, day)
            report["transactions"] = detail["rows"]
            report["transactions_columns"] = detail["columns"]
            report["transactions_totals"] = detail["totals"]
            summary["cash_collected"] = detail["totals"].get("cash", summary.get("cash_collected", 0))
            # Complete analysis: every ledger slice available for the day.
            report["sections"] = reporting.daily_close_sections(db, day)
            report["analysis_metrics"] = reporting.analysis_data(db, day, day, "day")["metrics"]
        except Exception:
            logger.exception("Daily transaction listing failed for %s", day)
            report["transactions"] = []
        output_dir = (directory or report_directory()).resolve()
        output_dir.mkdir(parents=True, exist_ok=True)
        filename = f"daily-sales-{day}-v{version}.pdf"
        destination = output_dir / filename
        temporary = output_dir / f".{filename}.tmp"
        pdf = HTML(string=_daily_report_document(db, report)).write_pdf()
        try:
            temporary.write_bytes(pdf)
            temporary.replace(destination)
        finally:
            temporary.unlink(missing_ok=True)

        entry.status = "generated"
        entry.file_path = str(destination)
        entry.totals_json = json.dumps(summary, sort_keys=True)
        db.add(AuditLog(
            user_id=user_id,
            username=generated_by[:80],
            action="daily_report.generate",
            entity="daily_report",
            entity_id=str(entry.id),
            detail=f"{day} v{version} generated",
        ))
        db.flush()
        return entry
    except Exception as exc:
        logger.exception("Daily report generation failed for %s v%s", day, version)
        entry.status = "failed"
        entry.error = str(exc)[:4000]
        entry.file_path = ""
        db.add(AuditLog(
            user_id=user_id,
            username=generated_by[:80],
            action="daily_report.generate",
            entity="daily_report",
            entity_id=str(entry.id),
            detail=f"{day} v{version} failed: {entry.error}",
        ))
        db.flush()
        return entry


def regenerate_report(
    db: Session,
    previous: DailyReport,
    *,
    user: User,
    directory: Path | None = None,
) -> DailyReport:
    new_report = generate_report(
        db,
        previous.business_date,
        generated_by=user.full_name or user.username,
        user_id=user.id,
        directory=directory,
    )
    if new_report.status == "generated":
        previous.status = "superseded"
        previous.superseded_by = new_report.id
        db.add(AuditLog(
            user_id=user.id,
            username=user.username,
            action="daily_report.regenerate",
            entity="daily_report",
            entity_id=str(new_report.id),
            detail=f"{previous.business_date}: v{previous.version} superseded by v{new_report.version}",
        ))
        db.flush()
    return new_report


def report_file_path(report: DailyReport, directory: Path | None = None) -> Path:
    root = (directory or report_directory()).resolve()
    candidate = Path(report.file_path).resolve()
    if not candidate.is_relative_to(root) or candidate.suffix.lower() != ".pdf":
        raise ValueError("The stored report file is outside the configured report directory.")
    return candidate


class DailyCloseScheduler:
    """Runs a recoverable, idempotent daily close without a browser session."""

    def __init__(
        self,
        session_factory: Callable[[], Session],
        *,
        directory: Path | None = None,
        close_time: str = "00:05",
        timezone_name: str = "Asia/Kathmandu",
        lookback_days: int = 14,
    ):
        self.session_factory = session_factory
        self.directory = directory or report_directory()
        self.close_time = close_time
        self.timezone_name = timezone_name
        self.lookback_days = lookback_days
        self.stop_event = threading.Event()
        self.thread: threading.Thread | None = None

    def _configuration(self) -> tuple[str, str]:
        db = self.session_factory()
        try:
            return _setting(db, "close_time", self.close_time), self.timezone_name
        finally:
            db.close()

    @staticmethod
    def _zone(name: str) -> ZoneInfo:
        try:
            return ZoneInfo(name)
        except (KeyError, ValueError) as exc:
            raise ValueError(f"Invalid business timezone: {name}") from exc

    def _already_closed(self, db: Session, day: str) -> bool:
        latest = db.scalar(
            select(DailyReport).where(DailyReport.business_date == day)
            .order_by(DailyReport.version.desc()).limit(1)
        )
        return latest is not None and latest.status == "generated"

    def _has_activity(self, db: Session, day: str) -> bool:
        invoices = db.scalar(select(func.count(Invoice.id)).where(
            Invoice.status.in_(("issued", "paid")), Invoice.bill_date == day
        )) or 0
        payments = db.scalar(select(func.count(Payment.id)).where(
            Payment.business_date == day
        )) or 0
        refunds = db.scalar(select(func.count(Refund.id)).where(
            Refund.business_date == day
        )) or 0
        return bool(invoices or payments or refunds)

    def run_once(self, business_date: str | None = None, force: bool = False) -> dict:
        db = self.session_factory()
        day = business_date
        run = None
        try:
            _close_time, timezone_name = self._configuration()
            zone = self._zone(timezone_name)
            day = day or (datetime.now(zone).date() - timedelta(days=1)).isoformat()
            day = _validate_business_date(day)
            run = SchedulerRun(
                job_name=JOB_DAILY_CLOSE,
                business_date=day,
                started_at=utcnow(),
                status="running",
            )
            db.add(run)
            db.flush()
            if self._already_closed(db, day) and not force:
                run.status = "skipped"
                run.message = f"{day} already closed"
                run.finished_at = utcnow()
                db.commit()
                return {"status": "skipped", "business_date": day, "reason": "already closed"}

            report = generate_report(
                db, day, generated_by="scheduler", directory=self.directory
            )
            run.status = "ok" if report.status == "generated" else "failed"
            run.message = (
                f"{day} v{report.version} → {report.status}"
                if report.status == "generated"
                else report.error
            )
            run.finished_at = utcnow()
            db.commit()
            return {
                "status": report.status,
                "business_date": day,
                "version": report.version,
                "error": report.error,
            }
        except Exception as exc:
            db.rollback()
            if run is not None:
                run.status = "failed"
                run.message = str(exc)[:2000]
                run.finished_at = utcnow()
                db.add(run)
                db.commit()
            logger.exception("Daily close scheduler failed for %s", day or "next business day")
            return {"status": "failed", "business_date": day, "error": str(exc)}
        finally:
            db.close()

    def catch_up(self) -> list[dict]:
        _close_time, timezone_name = self._configuration()
        today = datetime.now(self._zone(timezone_name)).date()
        results = []
        for offset in range(1, self.lookback_days + 1):
            day = (today - timedelta(days=offset)).isoformat()
            db = self.session_factory()
            try:
                if not self._has_activity(db, day) or self._already_closed(db, day):
                    continue
            finally:
                db.close()
            results.append(self.run_once(day))
        return results

    def seconds_until_close(self) -> float:
        close_time, timezone_name = self._configuration()
        try:
            parsed = time.fromisoformat(close_time)
        except ValueError as exc:
            raise ValueError(f"Invalid daily close time: {close_time}") from exc
        zone = self._zone(timezone_name)
        now = datetime.now(zone)
        target = now.replace(
            hour=parsed.hour, minute=parsed.minute, second=0, microsecond=0
        )
        if target <= now:
            target += timedelta(days=1)
        return max(1.0, (target - now).total_seconds())

    def start(self) -> None:
        if self.thread and self.thread.is_alive():
            return
        self.stop_event.clear()
        self.thread = threading.Thread(
            target=self._loop, name="web-daily-close-scheduler", daemon=True
        )
        self.thread.start()

    def stop(self) -> None:
        self.stop_event.set()
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=5)

    def _loop(self) -> None:
        try:
            self.catch_up()
        except Exception:
            logger.exception("Daily close catch-up failed")
        while not self.stop_event.is_set():
            try:
                delay = self.seconds_until_close()
            except Exception:
                logger.exception("Could not determine next daily close time")
                delay = 60.0
            if self.stop_event.wait(delay):
                return
            self.run_once()
