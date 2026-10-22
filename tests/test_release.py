"""Release checks: concurrency, immutability, configuration and print safety."""

import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from arati import db, invoice
from arati.money import Line, amount_in_words, compute_totals

APP_DIR = Path(__file__).resolve().parent.parent


def _payload(totals, *, payment_method="Cash", description="Lunch"):
    return dict(
        prefix="ARH",
        guest={"name": "Concurrent Guest", "phone": "9800000000"},
        lines=[{"description": description, "qty": 1, "unit_price": 1000.0,
                "line_total": 1000.0, "category": "food", "taxable": True}],
        totals=totals.as_dict(),
        payment_method=payment_method,
        user_id=1,
    )


def test_concurrent_writers_never_duplicate_numbers(tmp_path):
    path = tmp_path / "concurrent.db"
    setup = db.connect(path)
    db.bootstrap(setup)
    setup.close()
    totals = compute_totals([Line("Lunch", 1, 1000.0)])

    def issue(_):
        conn = db.connect(path)
        try:
            return db.create_bill(conn, **_payload(totals))
        finally:
            conn.close()

    with ThreadPoolExecutor(max_workers=8) as pool:
        numbers = list(pool.map(issue, range(20)))

    assert len(numbers) == 20
    assert len(set(numbers)) == 20, "duplicate invoice number issued"
    conn = db.connect(path)
    assert conn.execute("SELECT COUNT(*) FROM bills").fetchone()[0] == 20
    conn.close()


def test_repeated_save_creates_distinct_bills(tmp_path):
    conn = db.connect(tmp_path / "repeat.db")
    db.bootstrap(conn)
    totals = compute_totals([Line("Lunch", 1, 1000.0)])
    first = db.create_bill(conn, **_payload(totals))
    second = db.create_bill(conn, **_payload(totals))
    assert first != second


def test_finalized_bill_totals_never_change(tmp_path):
    conn = db.connect(tmp_path / "immutable.db")
    db.bootstrap(conn)
    totals = compute_totals([Line("Lunch", 2, 500.0)])
    bill_no = db.create_bill(conn, **_payload(totals))

    before, _ = db.get_bill(conn, bill_no)
    db.void_bill(conn, bill_no)
    after, lines = db.get_bill(conn, bill_no)

    assert after["status"] == "void"
    for field in ("subtotal", "discount", "service_charge", "vat", "total", "paid"):
        assert after[field] == before[field], field
    assert len(lines) == 1


def test_payment_status_scenarios_persist(tmp_path):
    conn = db.connect(tmp_path / "status.db")
    db.bootstrap(conn)
    totals = compute_totals([Line("Lunch", 1, 1000.0)], paid=400)
    bill_no = db.create_bill(conn, **_payload(totals))
    bill, _ = db.get_bill(conn, bill_no)
    assert bill["total"] == 1243.00
    assert bill["paid"] == 400.00
    assert bill["balance"] == 843.00

    from arati.money import payment_status
    assert payment_status(1243.00, 400.00) == "Partially Paid"


def test_env_overrides_database_location(tmp_path):
    target = tmp_path / "custom" / "shop.db"
    env = {**os.environ, "ARATI_DB": str(target), "PYTHONPATH": str(APP_DIR)}
    result = subprocess.run(
        [sys.executable, "-c", "from arati import db; print(db.DB_PATH)"],
        env=env, cwd=APP_DIR, capture_output=True, text=True, timeout=60, check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == str(target)


def test_env_overrides_invoice_directory(tmp_path):
    env = {**os.environ, "ARATI_INVOICE_DIR": str(tmp_path / "pdfs"),
           "PYTHONPATH": str(APP_DIR)}
    result = subprocess.run(
        [sys.executable, "-c", "import app; print(app.INVOICE_DIR)"],
        env=env, cwd=APP_DIR, capture_output=True, text=True, timeout=60, check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == str(tmp_path / "pdfs")


def _page_count(path: Path) -> int:
    """Pages in a PDF, whether the objects are plain or inside compressed streams."""
    import re
    import zlib

    data = path.read_bytes()
    count = data.count(b"/Type /Page") - data.count(b"/Type /Pages")
    if count:
        return count
    for match in re.finditer(rb"stream\r?\n", data):
        start = match.end()
        end = data.find(b"endstream", start)
        if end < 0:
            continue
        try:
            raw = zlib.decompress(data[start:end])
        except zlib.error:
            continue
        count += raw.count(b"/Type /Page") - raw.count(b"/Type /Pages")
    return count


def test_multi_page_invoice_and_repeated_totals(tmp_path):
    bill = {
        "bill_no": "ARH0000999", "bill_date": "2026-10-22", "created_at": "2026-10-22 10:00:00",
        "guest_name": "Long Bill", "guest_phone": "9800000000", "guest_address": "Khandbari",
        "guest_pan": "", "room_no": "", "check_in": None, "check_out": None, "nights": 0,
        "subtotal": 6000.0, "discount": 0.0, "net_subtotal": 6000.0, "taxable_net": 6000.0,
        "service_charge_rate": 10.0, "service_charge": 600.0, "vat_rate": 13.0, "vat": 858.0,
        "total": 7458.0, "paid": 7458.0, "balance": 0.0, "payment_method": "Cash",
        "bill_type": "tax", "customer_type": "individual", "payment_terms": "", "notes": "",
    }
    lines = [{"description": f"Item {i}", "qty": 1, "unit": "pcs", "unit_price": 100.0,
              "line_total": 100.0, "taxable": 1, "code": f"SKU-{i}"} for i in range(1, 61)]
    path = invoice.build_a4_pdf(tmp_path / "multi.pdf", bill, lines, {})
    assert _page_count(path) >= 2
    assert amount_in_words(7458.0) == "Nepalese Rupees Seven Thousand Four Hundred Fifty-Eight Only"


def test_supply_bill_never_stores_vat(tmp_path):
    conn = db.connect(tmp_path / "supply.db")
    db.bootstrap(conn)
    totals = compute_totals([Line("Lunch", 1, 1000.0)], bill_type="supply")
    payload = _payload(totals)
    payload["bill_type"] = "supply"
    bill_no = db.create_bill(conn, **payload)
    bill, _ = db.get_bill(conn, bill_no)
    assert bill["vat"] == 0
    assert bill["bill_type"] == "supply"


def test_invalid_bill_type_is_rejected_before_insert(tmp_path):
    conn = db.connect(tmp_path / "invalid.db")
    db.bootstrap(conn)
    with pytest.raises(ValueError):
        compute_totals([Line("x", 1, 10)], bill_type="proforma")
    assert conn.execute("SELECT COUNT(*) FROM bills").fetchone()[0] == 0
