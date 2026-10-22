"""Daily sales and operations report.

The report is derived from the recorded transactions and nothing else. Every
figure can be traced back to a bill, a payment or a refund, and the report
refuses to save itself if the figures do not reconcile.

Measurements kept apart (they are *not* interchangeable):

``gross_sales``
    Value of the invoices issued during the business day.
``payments_received``
    Cash actually taken during the business day — including money collected
    against an invoice raised on an earlier day.
``cash_in_hand``
    Opening cash plus cash collected minus cash refunded.
``outstanding``
    Money still owed on invoices issued up to the end of the day.

A sale issued today and a payment received today against an older invoice
are therefore two separate lines, never added together.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path

from . import business_time as bt
from . import db, rooms

REPORT_TITLE = "Daily Sales and Operations Report"
REPORT_ID_PREFIX = "DSR"


# --------------------------------------------------------------------------- #
# figures
# --------------------------------------------------------------------------- #
def collect(conn: sqlite3.Connection, business_date: str, settings: dict) -> dict:
    """Gather every figure for one business day."""
    start, end = business_date, business_date
    invoices = _invoices(conn, start, end)
    payments = _payments(conn, start, end)
    refunds = _refunds(conn, start, end)

    gross_sales = round(sum(row["total"] for row in invoices), 2)
    subtotal = round(sum(row["subtotal"] for row in invoices), 2)
    discount = round(sum(row["discount"] for row in invoices), 2)
    taxable_sales = round(sum(row["taxable_net"] for row in invoices), 2)
    taxes = round(sum(row["vat"] for row in invoices), 2)
    service_charge = round(sum(row["service_charge"] for row in invoices), 2)
    net_sales = round(
        sum(row["total"] - row["vat"] for row in invoices), 2
    )

    payments_received = round(sum(row["amount"] for row in payments), 2)
    cash_collected = round(
        sum(row["amount"] for row in payments if row["method"] == "Cash"), 2
    )
    non_cash_collected = round(payments_received - cash_collected, 2)

    refund_total = round(sum(row["amount"] for row in refunds), 2)
    adjustment_total = round(
        sum(row["amount"] for row in refunds if row["kind"] == "adjustment"), 2
    )

    opening_cash = _opening_cash(conn, business_date)
    closing_cash = round(opening_cash + cash_collected - refund_total, 2)

    outstanding = round(
        conn.execute(
            "SELECT COALESCE(SUM(balance), 0) FROM bills WHERE status = 'issued' "
            "AND is_draft = 0 AND bill_date <= ? AND balance > 0",
            (business_date,),
        ).fetchone()[0],
        2,
    )

    by_category = _by_category(conn, start, end)
    by_method = _by_method(conn, start, end)
    room_revenue = rooms.room_revenue(conn, start, end)
    occupancy = rooms.occupancy(conn, business_date)

    figures = {
        "business_date": business_date,
        "timezone": settings.get("business_timezone") or bt.DEFAULT_TIMEZONE,
        "invoice_count": len(invoices),
        "subtotal": subtotal,
        "gross_sales": gross_sales,
        "discount": discount,
        "taxable_sales": taxable_sales,
        "taxes": taxes,
        "service_charge": service_charge,
        "net_sales": net_sales,
        "payments_received": payments_received,
        "cash_collected": cash_collected,
        "non_cash_collected": non_cash_collected,
        "refunds": refund_total,
        "adjustments": adjustment_total,
        "opening_cash": opening_cash,
        "closing_cash": closing_cash,
        "outstanding": outstanding,
        "room_revenue": room_revenue["total"],
        "food_revenue": by_category.get("food", 0.0),
        "service_revenue": by_category.get("service", 0.0) + by_category.get("other", 0.0),
        "by_category": by_category,
        "by_method": by_method,
        "occupancy": occupancy,
    }
    figures["invoices"] = invoices
    figures["payments"] = payments
    figures["refund_rows"] = refunds
    return figures


def _invoices(conn: sqlite3.Connection, start: str, end: str) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM bills WHERE status = 'issued' AND is_draft = 0 "
        "AND bill_date BETWEEN ? AND ? ORDER BY bill_no",
        (start, end),
    ).fetchall()
    invoices = []
    for row in rows:
        lines = list(
            conn.execute(
                "SELECT * FROM bill_items WHERE bill_id = ? ORDER BY line_id",
                (row["bill_id"],),
            )
        )
        collected = conn.execute(
            "SELECT COALESCE(SUM(amount), 0) FROM payments WHERE bill_no = ?",
            (row["bill_no"],),
        ).fetchone()[0]
        refunded = conn.execute(
            "SELECT COALESCE(SUM(amount), 0) FROM refunds WHERE bill_no = ? "
            "AND kind = 'refund'",
            (row["bill_no"],),
        ).fetchone()[0]
        invoices.append(
            {
                "bill_no": row["bill_no"],
                "bill_date": row["bill_date"],
                "created_at": row["created_at"],
                "guest_name": row["guest_name"],
                "room_no": row["room_no"],
                "check_in": row["check_in"] or "",
                "check_out": row["check_out"] or "",
                "nights": int(row["nights"] or 0),
                "cashier": row["prepared_by"] or "",
                "payment_method": row["payment_method"],
                "bill_type": row["bill_type"],
                "subtotal": round(float(row["subtotal"]), 2),
                "discount": round(float(row["discount"]), 2),
                "taxable_net": round(float(row["taxable_net"]), 2),
                "service_charge": round(float(row["service_charge"]), 2),
                "vat": round(float(row["vat"]), 2),
                "total": round(float(row["total"]), 2),
                "paid": round(float(row["paid"]), 2),
                "balance": round(float(row["balance"]), 2),
                "collected": round(float(collected), 2),
                "refunded": round(float(refunded), 2),
                "lines": [
                    {
                        "description": line["description"],
                        "category": line["category"],
                        "qty": float(line["qty"]),
                        "unit_price": round(float(line["unit_price"]), 2),
                        "line_total": round(float(line["line_total"]), 2),
                        "discount": round(float(line["discount"]), 2),
                    }
                    for line in lines
                ],
            }
        )
    return invoices


def _payments(conn: sqlite3.Connection, start: str, end: str) -> list[dict]:
    rows = conn.execute(
        "SELECT p.*, b.guest_name, b.room_no, b.prepared_by FROM payments p "
        "LEFT JOIN bills b ON b.bill_id = p.bill_id "
        "WHERE p.business_date BETWEEN ? AND ? ORDER BY p.paid_at, p.payment_id",
        (start, end),
    ).fetchall()
    return [
        {
            "payment_id": row["payment_id"],
            "bill_no": row["bill_no"],
            "paid_at": row["paid_at"],
            "business_date": row["business_date"],
            "method": row["method"],
            "amount": round(float(row["amount"]), 2),
            "note": row["note"],
            "guest_name": row["guest_name"] or "",
            "room_no": row["room_no"] or "",
            "cashier": row["prepared_by"] or "",
        }
        for row in rows
    ]


def _refunds(conn: sqlite3.Connection, start: str, end: str) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM refunds WHERE business_date BETWEEN ? AND ? "
        "ORDER BY refunded_at, refund_id",
        (start, end),
    ).fetchall()
    return [
        {
            "refund_id": row["refund_id"],
            "bill_no": row["bill_no"],
            "kind": row["kind"],
            "method": row["method"],
            "amount": round(float(row["amount"]), 2),
            "reason": row["reason"],
            "refunded_at": row["refunded_at"],
        }
        for row in rows
    ]


def _by_category(conn: sqlite3.Connection, start: str, end: str) -> dict[str, float]:
    rows = conn.execute(
        "SELECT bi.category, COALESCE(SUM(bi.line_total), 0) AS total "
        "FROM bill_items bi JOIN bills b ON b.bill_id = bi.bill_id "
        "WHERE b.status = 'issued' AND b.is_draft = 0 AND b.bill_date BETWEEN ? AND ? "
        "GROUP BY bi.category",
        (start, end),
    ).fetchall()
    return {row["category"]: round(float(row["total"]), 2) for row in rows}


def _by_method(conn: sqlite3.Connection, start: str, end: str) -> list[dict]:
    rows = conn.execute(
        "SELECT method, COUNT(*) AS entries, COALESCE(SUM(amount), 0) AS total "
        "FROM payments WHERE business_date BETWEEN ? AND ? "
        "GROUP BY method ORDER BY total DESC",
        (start, end),
    ).fetchall()
    return [
        {
            "method": row["method"],
            "entries": int(row["entries"]),
            "total": round(float(row["total"]), 2),
        }
        for row in rows
    ]


def _opening_cash(conn: sqlite3.Connection, business_date: str) -> float:
    """Cash in the drawer at the start of the business day.

    Opening cash is the cumulative net cash movement before the day began.
    The hotel's opening float is recorded in the ``cash_opening_balance``
    setting.
    """
    settings = db.get_settings(conn)
    try:
        float_balance = float(settings.get("cash_opening_balance", 0) or 0)
    except ValueError:
        float_balance = 0.0
    collected = conn.execute(
        "SELECT COALESCE(SUM(amount), 0) FROM payments WHERE method = 'Cash' "
        "AND business_date < ?",
        (business_date,),
    ).fetchone()[0]
    refunded = conn.execute(
        "SELECT COALESCE(SUM(amount), 0) FROM refunds WHERE method = 'Cash' "
        "AND kind = 'refund' AND business_date < ?",
        (business_date,),
    ).fetchone()[0]
    return round(float_balance + float(collected) - float(refunded), 2)


# --------------------------------------------------------------------------- #
# validation
# --------------------------------------------------------------------------- #
def validate(conn: sqlite3.Connection, business_date: str, figures: dict) -> list[str]:
    """Recalculate the report from the database and list every mismatch.

    An empty list means the report reconciles. A non-empty list means the
    report must be marked failed rather than published.
    """
    problems: list[str] = []

    # 1. Invoice count and totals must match a fresh query.
    row = conn.execute(
        "SELECT COUNT(*), COALESCE(SUM(total), 0), COALESCE(SUM(subtotal), 0), "
        "COALESCE(SUM(discount), 0), COALESCE(SUM(vat), 0), "
        "COALESCE(SUM(service_charge), 0), COALESCE(SUM(taxable_net), 0) "
        "FROM bills WHERE status = 'issued' AND is_draft = 0 AND bill_date = ?",
        (business_date,),
    ).fetchone()
    checks = (
        ("invoice count", figures["invoice_count"], int(row[0])),
        ("gross sales", figures["gross_sales"], round(float(row[1]), 2)),
        ("subtotal", figures["subtotal"], round(float(row[2]), 2)),
        ("discount", figures["discount"], round(float(row[3]), 2)),
        ("taxes", figures["taxes"], round(float(row[4]), 2)),
        ("service charge", figures["service_charge"], round(float(row[5]), 2)),
        ("taxable sales", figures["taxable_sales"], round(float(row[6]), 2)),
    )
    for label, reported, expected in checks:
        if abs(float(reported) - float(expected)) > 0.005:
            problems.append(
                f"{label}: report shows {reported:,.2f} but the ledger holds {expected:,.2f}"
            )

    # 2. Every invoice in the report must belong to the reporting day.
    for invoice in figures["invoices"]:
        if invoice["bill_date"] != business_date:
            problems.append(
                f"Invoice {invoice['bill_no']} dated {invoice['bill_date']} is outside "
                f"the reporting period {business_date}."
            )

    # 3. Payment totals must reconcile with the payment records.
    payment_total = conn.execute(
        "SELECT COALESCE(SUM(amount), 0) FROM payments WHERE business_date = ?",
        (business_date,),
    ).fetchone()[0]
    if abs(float(payment_total) - float(figures["payments_received"])) > 0.005:
        problems.append(
            f"payments received: report shows {figures['payments_received']:,.2f} but the "
            f"ledger holds {float(payment_total):,.2f}"
        )
    cash_total = conn.execute(
        "SELECT COALESCE(SUM(amount), 0) FROM payments WHERE business_date = ? "
        "AND method = 'Cash'",
        (business_date,),
    ).fetchone()[0]
    if abs(float(cash_total) - float(figures["cash_collected"])) > 0.005:
        problems.append(
            f"cash collections: report shows {figures['cash_collected']:,.2f} but the "
            f"ledger holds {float(cash_total):,.2f}"
        )

    # 4. Refunds must reconcile.
    refund_total = conn.execute(
        "SELECT COALESCE(SUM(amount), 0) FROM refunds WHERE business_date = ? "
        "AND kind = 'refund'",
        (business_date,),
    ).fetchone()[0]
    if abs(float(refund_total) - float(figures["refunds"])) > 0.005:
        problems.append(
            f"refunds: report shows {figures['refunds']:,.2f} but the ledger holds "
            f"{float(refund_total):,.2f}"
        )

    # 5. The cash roll-forward must be arithmetically true.
    expected_closing = round(
        float(figures["opening_cash"])
        + float(figures["cash_collected"])
        - float(figures["refunds"]),
        2,
    )
    if abs(expected_closing - float(figures["closing_cash"])) > 0.005:
        problems.append(
            f"closing cash: report shows {figures['closing_cash']:,.2f} but the "
            f"roll-forward gives {expected_closing:,.2f}"
        )

    # 6. Line totals must add up to the invoice totals.
    for invoice in figures["invoices"]:
        line_sum = round(sum(line["line_total"] for line in invoice["lines"]), 2)
        if not invoice["lines"]:
            problems.append(f"Invoice {invoice['bill_no']} has no line items.")
        elif abs(line_sum - invoice["subtotal"]) > 0.05:
            problems.append(
                f"Invoice {invoice['bill_no']}: lines total {line_sum:,.2f} but the "
                f"invoice subtotal is {invoice['subtotal']:,.2f}"
            )

    return problems


# --------------------------------------------------------------------------- #
# PDF
# --------------------------------------------------------------------------- #
def build_pdf(
    path: str | Path,
    figures: dict,
    settings: dict,
    report_id: str = "",
    version: int = 1,
    generated_by: str = "scheduler",
) -> Path:
    """Render the daily report to PDF."""
    from .daily_report_pdf import build_daily_pdf

    return build_daily_pdf(
        path,
        figures,
        settings,
        report_id=report_id,
        version=version,
        generated_by=generated_by,
    )


# --------------------------------------------------------------------------- #
# persistence
# --------------------------------------------------------------------------- #
def generate(
    conn: sqlite3.Connection,
    business_date: str,
    output_dir: str | Path,
    settings: dict | None = None,
    generated_by: str = "scheduler",
    username: str = "",
    user_id: int | None = None,
    version: int | None = None,
    report_id: str = "",
) -> dict:
    """Build, validate and store the daily report for ``business_date``.

    Returns a dict with ``status`` (``generated`` or ``failed``), the stored
    file path and the validation problems, if any.
    """
    settings = settings or db.get_settings(conn)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    figures = collect(conn, business_date, settings)
    problems = validate(conn, business_date, figures)

    generated_at = bt.now()
    figures["generated_at"] = generated_at.strftime("%Y-%m-%d %H:%M:%S")
    if version is None:
        version = next_version(conn, business_date)

    if problems:
        _store(
            conn,
            business_date,
            version,
            "failed",
            "",
            generated_at,
            generated_by,
            "; ".join(problems),
            {},
            username,
            user_id,
        )
        return {
            "status": "failed",
            "business_date": business_date,
            "version": version,
            "problems": problems,
            "path": "",
            "figures": figures,
        }

    file_name = f"daily-sales-{business_date}-v{version}.pdf"
    path = output_dir / file_name
    if not report_id:
        report_id = f"{REPORT_ID_PREFIX}-{business_date}-{version}"
    try:
        build_pdf(
            path,
            figures,
            settings,
            report_id=report_id,
            version=version,
            generated_by=generated_by,
        )
    except Exception as exc:  # noqa: BLE001 - a failed PDF is logged, not fatal
        _store(
            conn,
            business_date,
            version,
            "failed",
            "",
            generated_at,
            generated_by,
            f"PDF generation failed: {exc}",
            {},
            username,
            user_id,
        )
        return {
            "status": "failed",
            "business_date": business_date,
            "version": version,
            "problems": [f"PDF generation failed: {exc}"],
            "path": "",
            "figures": figures,
        }

    stored = _store(
        conn,
        business_date,
        version,
        "generated",
        str(path),
        generated_at,
        generated_by,
        "",
        _summarise(figures),
        username,
        user_id,
    )
    return {
        "status": "generated",
        "business_date": business_date,
        "version": version,
        "problems": [],
        "path": str(path),
        "report_id": report_id,
        "row_id": stored,
        "figures": figures,
    }


def _summarise(figures: dict) -> dict:
    """The headline figures kept with the report for quick listing."""
    return {
        "gross_sales": figures["gross_sales"],
        "net_sales": figures["net_sales"],
        "payments_received": figures["payments_received"],
        "cash_collected": figures["cash_collected"],
        "refunds": figures["refunds"],
        "outstanding": figures["outstanding"],
        "room_revenue": figures["room_revenue"],
        "invoice_count": figures["invoice_count"],
    }


def _store(
    conn: sqlite3.Connection,
    business_date: str,
    version: int,
    status: str,
    file_path: str,
    generated_at: datetime,
    generated_by: str,
    error: str,
    totals: dict,
    username: str,
    user_id: int | None,
) -> int:
    with conn:
        cursor = conn.execute(
            "INSERT INTO daily_reports (business_date, version, status, file_path, "
            "generated_at, generated_by, error, totals_json) VALUES (?,?,?,?,?,?,?,?)",
            (
                business_date,
                version,
                status,
                file_path,
                generated_at.strftime("%Y-%m-%d %H:%M:%S"),
                generated_by,
                error,
                json.dumps(totals, sort_keys=True),
            ),
        )
    db.log_audit(
        conn,
        "daily_report.generate",
        "daily_report",
        cursor.lastrowid,
        f"{business_date} v{version} → {status}",
        user_id,
        username,
    )
    return int(cursor.lastrowid)


def next_version(conn: sqlite3.Connection, business_date: str) -> int:
    row = conn.execute(
        "SELECT COALESCE(MAX(version), 0) FROM daily_reports WHERE business_date = ?",
        (business_date,),
    ).fetchone()
    return int(row[0]) + 1


def list_reports(conn: sqlite3.Connection, limit: int = 120) -> list[sqlite3.Row]:
    return list(
        conn.execute(
            "SELECT * FROM daily_reports ORDER BY business_date DESC, version DESC LIMIT ?",
            (limit,),
        )
    )


def get_report(conn: sqlite3.Connection, report_id: int) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM daily_reports WHERE report_id = ?", (report_id,)
    ).fetchone()


def latest_for_date(conn: sqlite3.Connection, business_date: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM daily_reports WHERE business_date = ? AND status = 'generated' "
        "ORDER BY version DESC LIMIT 1",
        (business_date,),
    ).fetchone()
