"""Tests for the hotel management additions: business days, ledger, rooms, closing."""

from __future__ import annotations

import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from arati import business_time as bt  # noqa: E402
from arati import daily_report, db, payments, rooms, scheduler  # noqa: E402
from arati.money import compute_totals, Line  # noqa: E402

NPT = timezone(timedelta(hours=5, minutes=45))


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
@pytest.fixture()
def conn(tmp_path) -> sqlite3.Connection:
    connection = db.connect(tmp_path / "test.db")
    db.bootstrap(connection)
    yield connection
    connection.close()


def make_bill(conn, *, total=1000.0, paid=0.0, method="Cash", bill_date=None, room=""):
    """Insert a bill with a single line, bypassing the billing form."""
    lines = [
        {
            "description": "Room 101 — 1 night(s)",
            "category": "room",
            "qty": 1,
            "unit_price": total,
            "taxable": True,
            "unit": "night",
            "item_id": None,
        }
    ]
    totals = compute_totals(
        [Line(description=lines[0]["description"], qty=1, unit_price=total)],
        discount=0.0,
        service_charge_rate=0.0,
        vat_rate=0.0,
        paid=paid,
    )
    bill_no = db.create_bill(
        conn,
        prefix="TEST",
        guest={"name": "Test Guest", "room_no": room},
        lines=lines,
        totals=totals.as_dict(),
        payment_method=method,
        user_id=None,
        bill_date=bill_date,
    )
    return bill_no, totals


# --------------------------------------------------------------------------- #
# business time
# --------------------------------------------------------------------------- #
def test_business_day_boundaries_are_midnight_to_midnight():
    zone = bt.get_zone("Asia/Kathmandu")
    just_before = datetime(2026, 10, 21, 23, 59, 59, tzinfo=zone)
    exactly_midnight = datetime(2026, 10, 22, 0, 0, 0, tzinfo=zone)

    assert bt.business_date_of(just_before) == "2026-10-21"
    assert bt.business_date_of(exactly_midnight) == "2026-10-22"

    start = bt.day_start("2026-10-21", zone)
    end = bt.day_end("2026-10-21", zone)
    assert start.isoformat() == "2026-10-21T00:00:00+05:45"
    assert end.isoformat() == "2026-10-22T00:00:00+05:45"
    assert (end - start).total_seconds() == 24 * 3600


def test_kathmandu_offset_is_utc_plus_545():
    zone = bt.get_zone("Asia/Kathmandu")
    moment = datetime(2026, 1, 1, 12, 0, tzinfo=zone)
    assert moment.utcoffset() == timedelta(hours=5, minutes=45)


def test_unknown_timezone_falls_back_to_kathmandu():
    assert bt.get_zone("Mars/Olympus") == bt.get_zone("Asia/Kathmandu")


def test_naive_timestamp_is_read_as_business_local():
    zone = bt.get_zone("Asia/Kathmandu")
    parsed = bt.parse_timestamp("2026-10-21 23:30:00", zone)
    assert parsed is not None
    assert parsed.utcoffset() == timedelta(hours=5, minutes=45)
    assert parsed.date().isoformat() == "2026-10-21"


def test_previous_and_next_day():
    assert bt.previous_day("2026-10-21") == "2026-10-20"
    assert bt.next_day("2026-10-21") == "2026-10-22"


# --------------------------------------------------------------------------- #
# payments ledger
# --------------------------------------------------------------------------- #
def test_payment_settles_the_balance(conn):
    bill_no, totals = make_bill(conn, total=1000.0)
    assert totals.balance == 1000.0

    payments.record_payment(conn, bill_no, 400.0, method="Cash")
    row = conn.execute("SELECT * FROM bills WHERE bill_no = ?", (bill_no,)).fetchone()
    assert row["paid"] == 400.0
    assert row["balance"] == 600.0

    payments.record_payment(conn, bill_no, 600.0, method="Card")
    row = conn.execute("SELECT * FROM bills WHERE bill_no = ?", (bill_no,)).fetchone()
    assert row["paid"] == 1000.0
    assert row["balance"] == 0.0


def test_payment_cannot_exceed_the_balance(conn):
    bill_no, _ = make_bill(conn, total=1000.0)
    with pytest.raises(payments.LedgerError):
        payments.record_payment(conn, bill_no, 1500.0)


def test_refund_cannot_exceed_what_was_collected(conn):
    bill_no, _ = make_bill(conn, total=1000.0, paid=1000.0)
    with pytest.raises(payments.LedgerError):
        payments.record_payment(conn, bill_no, 1.0)  # nothing outstanding
    payments.record_payment(conn, bill_no, 0.0) if False else None
    with pytest.raises(payments.LedgerError):
        payments.record_refund(conn, bill_no, 1500.0)


def test_refund_puts_the_money_back_on_the_balance(conn):
    bill_no, _ = make_bill(conn, total=1000.0, paid=1000.0)
    payments.record_refund(conn, bill_no, 250.0, reason="Service not delivered")
    row = conn.execute("SELECT * FROM bills WHERE bill_no = ?", (bill_no,)).fetchone()
    assert row["paid"] == 750.0
    assert row["balance"] == 250.0


def test_payment_taken_at_sale_lands_in_the_ledger(conn):
    bill_no, _ = make_bill(conn, total=500.0, paid=500.0)
    rows = payments.list_payments(conn)
    assert len(rows) == 1
    assert rows[0]["bill_no"] == bill_no
    assert rows[0]["amount"] == 500.0


def test_payment_against_an_older_invoice_keeps_its_own_date(conn):
    bill_no, _ = make_bill(conn, total=1000.0, bill_date="2026-10-01")
    payments.record_payment(
        conn,
        bill_no,
        1000.0,
        paid_at=datetime(2026, 10, 21, 10, 0, tzinfo=NPT),
    )
    rows = payments.list_payments(conn)
    assert rows[0]["business_date"] == "2026-10-21"


# --------------------------------------------------------------------------- #
# rooms
# --------------------------------------------------------------------------- #
def test_twenty_five_rooms_exist_on_a_new_installation(conn):
    numbers = {row["room_no"] for row in conn.execute("SELECT room_no FROM rooms")}
    assert len(numbers) == 25
    assert "101" in numbers and "125" in numbers


def test_inventory_does_not_duplicate_on_restart(conn):
    rooms.ensure_inventory(conn)
    second = rooms.ensure_inventory(conn)
    assert second["created"] == []
    count = conn.execute("SELECT COUNT(*) FROM rooms").fetchone()[0]
    assert count == 25


def test_existing_rooms_are_never_overwritten(conn):
    rooms.ensure_inventory(conn)
    item_id = conn.execute(
        "SELECT item_id FROM rooms WHERE room_no = '101'"
    ).fetchone()["item_id"]
    rooms.ensure_inventory(conn, ["101", "999"])
    row = conn.execute("SELECT * FROM rooms WHERE room_no = '101'").fetchone()
    assert row["item_id"] == item_id


def test_room_number_range_parsing():
    assert rooms.parse_room_numbers("101-105") == ["101", "102", "103", "104", "105"]
    assert rooms.parse_room_numbers("101, 102 ,103") == ["101", "102", "103"]
    assert rooms.parse_room_numbers("101-103, 200") == ["101", "102", "103", "200"]


def test_overlapping_reservation_is_rejected(conn):
    rooms.ensure_inventory(conn)
    rooms.create_reservation(
        conn, "101", "Alice", "2026-10-20", "2026-10-23", nightly_rate=3000
    )
    with pytest.raises(rooms.RoomError):
        rooms.create_reservation(
            conn, "101", "Bob", "2026-10-22", "2026-10-25", nightly_rate=3000
        )


def test_adjacent_reservations_are_allowed(conn):
    rooms.ensure_inventory(conn)
    rooms.create_reservation(
        conn, "101", "Alice", "2026-10-20", "2026-10-23", nightly_rate=3000
    )
    reservation_id = rooms.create_reservation(
        conn, "101", "Bob", "2026-10-23", "2026-10-25", nightly_rate=3000
    )
    assert reservation_id > 0


def test_check_out_before_check_in_is_rejected(conn):
    rooms.ensure_inventory(conn)
    with pytest.raises(rooms.RoomError):
        rooms.create_reservation(
            conn, "101", "Alice", "2026-10-25", "2026-10-20", nightly_rate=3000
        )


def test_double_check_in_is_rejected(conn):
    rooms.ensure_inventory(conn)
    rooms.check_in(conn, "101", "Alice", check_in_at="2026-10-20 14:00")
    with pytest.raises(rooms.RoomError):
        rooms.check_in(conn, "101", "Bob", check_in_at="2026-10-20 15:00")


def test_room_under_maintenance_cannot_be_assigned(conn):
    rooms.ensure_inventory(conn)
    rooms.set_housekeeping(conn, "101", "maintenance")
    with pytest.raises(rooms.RoomError):
        rooms.check_in(conn, "101", "Alice")
    with pytest.raises(rooms.RoomError):
        rooms.create_reservation(
            conn, "101", "Alice", "2026-10-20", "2026-10-22", nightly_rate=3000
        )


def test_dirty_room_is_not_reported_as_available(conn):
    rooms.ensure_inventory(conn)
    rooms.set_housekeeping(conn, "101", "needs_cleaning")
    state = rooms.room_state(conn, "101")
    assert state["status"] == rooms.STATUS_NEEDS_CLEANING
    assert state["status"] != rooms.STATUS_AVAILABLE


def test_room_status_reports_occupied_after_check_in(conn):
    rooms.ensure_inventory(conn)
    rooms.check_in(conn, "101", "Alice", check_in_at="2026-10-20 14:00")
    state = rooms.room_state(conn, "101")
    assert state["status"] == rooms.STATUS_OCCUPIED
    assert state["guest_name"] == "Alice"


def test_checkout_raises_one_invoice_and_marks_the_room_dirty(conn):
    rooms.ensure_inventory(conn)
    stay_id = rooms.check_in(
        conn, "101", "Alice", check_in_at="2026-10-20 14:00",
        expected_checkout="2026-10-22 11:00", nightly_rate=3000,
    )
    rooms.add_charge(conn, stay_id, "Breakfast", 250.0, category="food")
    # Two nights at 3,000 plus a 250 breakfast, with the hotel's default
    # 10% service charge and 13% VAT.
    subtotal = 2 * 3000 + 250
    service = round(subtotal * 0.10, 2)
    vat = round((subtotal + service) * 0.13, 2)
    total = round(subtotal + service + vat, 2)

    bill_no = rooms.check_out(conn, stay_id, paid=total)

    bill = conn.execute("SELECT * FROM bills WHERE bill_no = ?", (bill_no,)).fetchone()
    assert bill is not None
    assert bill["room_no"] == "101"
    assert bill["nights"] == 2
    assert bill["subtotal"] == pytest.approx(subtotal)
    assert bill["total"] == pytest.approx(total)
    assert bill["balance"] == 0.0

    state = rooms.room_state(conn, "101")
    assert state["housekeeping"] == "needs_cleaning"

    with pytest.raises(rooms.RoomError):
        rooms.check_out(conn, stay_id)


def test_room_invoice_uses_the_shared_billing_tables(conn):
    rooms.ensure_inventory(conn)
    stay_id = rooms.check_in(
        conn, "101", "Alice", check_in_at="2026-10-20 14:00",
        expected_checkout="2026-10-21 11:00", nightly_rate=3000,
    )
    bill_no = rooms.check_out(conn, stay_id, paid=3729.0)
    lines = conn.execute(
        "SELECT * FROM bill_items WHERE bill_id = "
        "(SELECT bill_id FROM bills WHERE bill_no = ?)",
        (bill_no,),
    ).fetchall()
    assert any(line["category"] == "room" for line in lines)
    payments_rows = conn.execute(
        "SELECT * FROM payments WHERE bill_no = ?", (bill_no,)
    ).fetchall()
    assert len(payments_rows) == 1


# --------------------------------------------------------------------------- #
# daily closing
# --------------------------------------------------------------------------- #
def test_daily_report_splits_sales_from_collections(conn):
    # A sale yesterday, collected today.
    make_bill(conn, total=2000.0, bill_date="2026-10-20")
    bill_no, _ = make_bill(conn, total=1000.0, bill_date="2026-10-21")

    settings = db.get_settings(conn)
    yesterday = daily_report.collect(conn, "2026-10-20", settings)
    today = daily_report.collect(conn, "2026-10-21", settings)

    assert yesterday["gross_sales"] == 2000.0
    assert yesterday["payments_received"] == 0.0
    assert today["gross_sales"] == 1000.0

    payments.record_payment(
        conn, bill_no, 1000.0, paid_at=datetime(2026, 10, 21, 9, 0, tzinfo=NPT)
    )
    today = daily_report.collect(conn, "2026-10-21", settings)
    assert today["payments_received"] == 1000.0
    # The collection is not counted as extra sales.
    assert today["gross_sales"] == 1000.0


def test_daily_report_reconciles_and_generates_a_pdf(conn, tmp_path):
    make_bill(conn, total=2000.0, paid=2000.0, bill_date="2026-10-21")
    settings = db.get_settings(conn)

    figures = daily_report.collect(conn, "2026-10-21", settings)
    assert daily_report.validate(conn, "2026-10-21", figures) == []

    result = daily_report.generate(
        conn, "2026-10-21", tmp_path / "reports", settings=settings
    )
    assert result["status"] == "generated"
    assert Path(result["path"]).exists()
    assert Path(result["path"]).stat().st_size > 1000


def test_daily_report_with_no_transactions_says_so(conn, tmp_path):
    settings = db.get_settings(conn)
    result = daily_report.generate(
        conn, "2026-10-21", tmp_path / "reports", settings=settings
    )
    assert result["status"] == "generated"
    assert result["figures"]["invoice_count"] == 0
    assert result["figures"]["gross_sales"] == 0.0


def test_scheduler_is_idempotent(conn, tmp_path):
    make_bill(conn, total=1500.0, paid=1500.0, bill_date="2026-10-21")

    job = scheduler.Scheduler(lambda: conn, tmp_path / "reports")
    first = job.run_once("2026-10-21")
    second = job.run_once("2026-10-21")

    assert first["status"] == "generated"
    assert second["status"] == "skipped"

    reports = daily_report.list_reports(conn)
    generated = [r for r in reports if r["status"] == "generated"]
    assert len(generated) == 1

    bills = conn.execute("SELECT COUNT(*) FROM bills").fetchone()[0]
    assert bills == 1
    payments_count = conn.execute("SELECT COUNT(*) FROM payments").fetchone()[0]
    assert payments_count == 1


def test_scheduler_recovers_a_missed_day(conn, tmp_path):
    make_bill(conn, total=900.0, paid=900.0, bill_date="2026-10-20")
    make_bill(conn, total=700.0, paid=700.0, bill_date="2026-10-21")

    job = scheduler.Scheduler(lambda: conn, tmp_path / "reports")
    results = job.catch_up(lookback_days=5)
    assert results

    dates = {
        row["business_date"]
        for row in daily_report.list_reports(conn)
        if row["status"] == "generated"
    }
    assert {"2026-10-20", "2026-10-21"} <= dates


def test_missing_report_days_are_detected(conn):
    make_bill(conn, total=900.0, paid=900.0, bill_date="2026-10-21")
    missing = scheduler.missing_report_days(conn, lookback_days=30)
    assert "2026-10-21" in missing


def test_regeneration_creates_a_new_version_and_keeps_the_old(conn, tmp_path):
    make_bill(conn, total=1200.0, paid=1200.0, bill_date="2026-10-21")
    settings = db.get_settings(conn)
    first = daily_report.generate(
        conn, "2026-10-21", tmp_path / "reports", settings=settings
    )
    assert first["status"] == "generated"

    regenerated = scheduler.regenerate(
        conn, "2026-10-21", tmp_path / "reports", settings=settings, username="admin"
    )
    assert regenerated["status"] == "generated"
    assert regenerated["version"] == first["version"] + 1

    rows = {row["version"]: row for row in daily_report.list_reports(conn)}
    assert rows[first["version"]]["status"] == "superseded"
    assert rows[regenerated["version"]]["status"] == "generated"

    audit = conn.execute(
        "SELECT * FROM audit_log WHERE action = 'daily_report.regenerate'"
    ).fetchall()
    assert audit


def test_failed_report_is_recorded_and_logged(conn, tmp_path, monkeypatch):
    make_bill(conn, total=1200.0, paid=1200.0, bill_date="2026-10-21")

    def boom(*_args, **_kwargs):
        raise RuntimeError("disk full")

    monkeypatch.setattr(daily_report, "build_pdf", boom)
    result = daily_report.generate(
        conn, "2026-10-21", tmp_path / "reports", settings=db.get_settings(conn)
    )
    assert result["status"] == "failed"
    row = daily_report.list_reports(conn)[0]
    assert row["status"] == "failed"
    assert "disk full" in row["error"]


def test_scheduler_run_history_is_recorded(conn, tmp_path):
    make_bill(conn, total=100.0, paid=100.0, bill_date="2026-10-21")
    job = scheduler.Scheduler(lambda: conn, tmp_path / "reports")
    job.run_once("2026-10-21")
    runs = scheduler.list_runs(conn)
    assert runs
    assert runs[0]["status"] in {"ok", "skipped"}


# --------------------------------------------------------------------------- #
# occupancy
# --------------------------------------------------------------------------- #
def test_occupancy_reports_both_measures(conn):
    rooms.ensure_inventory(conn)
    stay_id = rooms.check_in(
        conn, "101", "Alice", check_in_at="2026-10-20 14:00",
        expected_checkout="2026-10-22 11:00", nightly_rate=3000,
    )
    rooms.check_out(conn, stay_id, paid=6000.0)

    result = rooms.occupancy(conn, "2026-10-21")
    assert result["sellable_rooms"] == 25
    assert result["occupied_across_day"] == 1
    assert 0 < result["occupancy_rate"] < 100
