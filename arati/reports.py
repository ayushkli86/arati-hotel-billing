"""The ten hotel reports, computed from the recorded transactions.

Every figure in here comes from a query over the invoice, payment and refund
tables. Nothing is estimated and nothing is invented: when the data needed
for a figure does not exist, the report says so instead of guessing.

The three money columns are kept apart on purpose:

``sales``
    What the hotel *earned* — invoiced on the business date.
``collections``
    Cash that actually changed hands on the business date. A payment
    received today against an invoice raised last month is a collection
    today and a sale last month.
``outstanding``
    What guests still owe on invoices issued up to the end of the period.

All sums are accumulated in integer paisa and only converted back to
rupees for display, so the totals always tie out to the lines above them.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field

from . import business_time as bt
from .money import from_paisa, to_paisa

# --------------------------------------------------------------------------- #
# report container
# --------------------------------------------------------------------------- #


@dataclass
class Report:
    """One report: a title, a table, its totals and the formulas behind them."""

    key: str
    title: str
    subtitle: str = ""
    columns: list[tuple[str, str, int]] = field(default_factory=list)
    rows: list[dict] = field(default_factory=list)
    totals: dict = field(default_factory=dict)
    formulas: list[str] = field(default_factory=list)
    period: str = ""
    generated_at: str = ""
    empty_message: str = "No transactions recorded for this period."

    def as_dict(self) -> dict:
        return {
            "key": self.key,
            "title": self.title,
            "subtitle": self.subtitle,
            "columns": self.columns,
            "rows": self.rows,
            "totals": self.totals,
            "formulas": self.formulas,
            "period": self.period,
            "generated_at": self.generated_at,
            "empty_message": self.empty_message,
        }


# The formulas, written down once so every screen can show them.
FORMULAS = {
    "gross_sales": "Gross sales = Σ invoice total for issued, non-draft invoices dated in the period.",
    "net_sales": "Net sales = gross sales − discounts − refunds and reversals posted in the period.",
    "collections": "Payments received = Σ payment rows dated in the period (cash in hand on that day).",
    "cash_in_hand": "Closing cash = opening balance + cash collections − cash refunds for the period.",
    "outstanding": "Outstanding = Σ balance of issued invoices dated on or before the period end.",
    "average_invoice": "Average invoice value = eligible sales value ÷ number of eligible invoices.",
    "occupancy": "Occupancy rate = occupied sellable rooms ÷ total sellable rooms × 100.",
    "average_room_revenue": "Average room revenue = room revenue ÷ number of invoices with room revenue.",
    "net_sales_ledger": "Net sales = Σ invoice total − Σ refund and reversal rows dated in the period.",
    "voided": "Voided invoices are excluded from every sales figure.",
}

REPORT_KEYS = (
    "daily_sales",
    "monthly_sales",
    "custom_range",
    "payment_collection",
    "outstanding_invoices",
    "refunds_adjustments",
    "employee_sales",
    "room_occupancy",
    "room_revenue",
    "operations_summary",
)

REPORT_TITLES = {
    "daily_sales": "Daily Sales Report",
    "monthly_sales": "Monthly Sales Report",
    "custom_range": "Custom Date Range Report",
    "payment_collection": "Payment Collection Report",
    "outstanding_invoices": "Outstanding Invoice Report",
    "refunds_adjustments": "Refund and Adjustment Report",
    "employee_sales": "Employee / Cashier Sales Report",
    "room_occupancy": "Room Occupancy Report",
    "room_revenue": "Room Revenue Report",
    "operations_summary": "Hotel Operations Summary",
}


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _paisa_sum(rows, key: str) -> int:
    return sum((to_paisa(row[key] if isinstance(row, dict) else row[key]) for row in rows), 0)


def _sum_field(rows: list, key: str) -> float:
    """Sum a column of rows in paisa, then convert back to rupees."""
    total = 0
    for row in rows:
        value = row[key] if isinstance(row, dict) else row[key]
        total += to_paisa(value or 0)
    return from_paisa(total)


def _period_label(start: str, end: str) -> str:
    if start == end:
        return f"Business date {start} (Asia/Kathmandu)"
    return f"Business dates {start} to {end} (Asia/Kathmandu)"


def _generated() -> str:
    return bt.now().strftime("%Y-%m-%d %H:%M:%S")


def _bill_filters(filters: dict) -> tuple[str, list]:
    """Turn the filter dict into a WHERE fragment for the bills table."""
    clauses = ["b.status = 'issued'", "b.is_draft = 0"]
    params: list = []
    employee = (filters.get("employee") or "").strip()
    if employee and employee != "All":
        clauses.append("b.prepared_by = ?")
        params.append(employee)
    method = (filters.get("payment_method") or "").strip()
    if method and method != "All":
        clauses.append("b.payment_method = ?")
        params.append(method)
    room = (filters.get("room_no") or "").strip()
    if room:
        clauses.append("b.room_no = ?")
        params.append(room)
    invoice = (filters.get("invoice_no") or "").strip()
    if invoice:
        clauses.append("b.bill_no LIKE ?")
        params.append(f"%{invoice}%")
    kind = (filters.get("transaction_type") or "").strip()
    if kind == "Room" :
        clauses.append("b.room_no <> ''")
    elif kind == "Non-room":
        clauses.append("b.room_no = ''")
    return " AND ".join(clauses), params


def _invoice_rows(
    conn: sqlite3.Connection, start: str, end: str, filters: dict
) -> list[dict]:
    """Every eligible invoice in the period, with its settled amounts."""
    where, params = _bill_filters(filters)
    sql = (
        "SELECT b.bill_id, b.bill_no, b.bill_date, b.created_at, b.guest_name, "
        "b.guest_phone, b.room_no, b.nights, b.prepared_by, b.payment_method, "
        "b.subtotal, b.discount, b.item_discount, b.net_subtotal, b.service_charge, "
        "b.vat, b.total, b.paid, b.balance, b.bill_type, b.status "
        "FROM bills b WHERE " + where + " AND b.bill_date BETWEEN ? AND ? "
        "ORDER BY b.bill_date, b.created_at, b.bill_id"
    )
    rows = [dict(row) for row in conn.execute(sql, [*params, start, end])]
    for row in rows:
        row["room_nights"] = int(row.get("nights") or 0)
        row["time"] = str(row.get("created_at") or "")[11:19]
    return rows


def _refund_rows(
    conn: sqlite3.Connection, start: str, end: str, filters: dict | None = None
) -> list[dict]:
    filters = filters or {}
    clauses = ["r.business_date BETWEEN ? AND ?"]
    params: list = [start, end]
    invoice = (filters.get("invoice_no") or "").strip()
    if invoice:
        clauses.append("r.bill_no LIKE ?")
        params.append(f"%{invoice}%")
    method = (filters.get("payment_method") or "").strip()
    if method and method != "All":
        clauses.append("r.method = ?")
        params.append(method)
    kind = (filters.get("transaction_type") or "").strip()
    if kind in ("Refund", "Adjustment"):
        clauses.append("r.kind = ?")
        params.append(kind.lower())
    sql = (
        "SELECT r.*, b.guest_name, b.room_no, b.prepared_by FROM refunds r "
        "LEFT JOIN bills b ON b.bill_id = r.bill_id WHERE " + " AND ".join(clauses)
    )
    return [dict(row) for row in conn.execute(sql, params)]


# --------------------------------------------------------------------------- #
# 1. daily sales
# --------------------------------------------------------------------------- #
def daily_sales(conn, start: str, end: str, filters: dict | None = None) -> Report:
    filters = filters or {}
    invoices = _invoice_rows(conn, start, end, filters)
    days = bt.date_range(start, end)
    by_day: dict[str, list[dict]] = {day: [] for day in days}
    for invoice in invoices:
        by_day.setdefault(invoice["bill_date"], []).append(invoice)

    rows = []
    for day in days:
        day_invoices = by_day.get(day, [])
        rows.append(
            {
                "date": day,
                "invoices": len(day_invoices),
                "gross_sales": _sum_field(day_invoices, "total"),
                "discount": _sum_field(day_invoices, "discount"),
                "tax": _sum_field(day_invoices, "vat"),
                "service_charge": _sum_field(day_invoices, "service_charge"),
                "net_sales": _sum_field(day_invoices, "net_subtotal"),
                "collected": _sum_field(day_invoices, "paid"),
                "outstanding": _sum_field(day_invoices, "balance"),
            }
        )
    return Report(
        key="daily_sales",
        title=REPORT_TITLES["daily_sales"],
        subtitle="Sales earned per business day",
        columns=[
            ("date", "Business date", 120),
            ("invoices", "Invoices", 70),
            ("gross_sales", "Gross sales", 110),
            ("discount", "Discounts", 90),
            ("tax", "VAT", 90),
            ("net_sales", "Net sales", 105),
            ("collected", "Paid", 100),
            ("outstanding", "Outstanding", 100),
        ],
        rows=rows,
        totals={
            "invoices": len(invoices),
            "gross_sales": _sum_field(invoices, "total"),
            "discount": _sum_field(invoices, "discount"),
            "tax": _sum_field(invoices, "vat"),
            "service_charge": _sum_field(invoices, "service_charge"),
            "net_sales": _sum_field(invoices, "net_subtotal"),
            "collected": _sum_field(invoices, "paid"),
            "outstanding": _sum_field(invoices, "balance"),
        },
        formulas=[FORMULAS["gross_sales"], FORMULAS["net_sales"], FORMULAS["voided"]],
        period=_period_label(start, end),
        generated_at=_generated(),
    )


# --------------------------------------------------------------------------- #
# 2. monthly sales
# --------------------------------------------------------------------------- #
def monthly_sales(conn, start: str, end: str, filters: dict | None = None) -> Report:
    filters = filters or {}
    invoices = _invoice_rows(conn, start, end, filters)
    months: dict[str, list[dict]] = {}
    for invoice in invoices:
        months.setdefault(str(invoice["bill_date"])[:7], []).append(invoice)

    rows = []
    for month in sorted(months):
        month_invoices = months[month]
        rows.append(
            {
                "month": month,
                "invoices": len(month_invoices),
                "gross_sales": _sum_field(month_invoices, "total"),
                "discount": _sum_field(month_invoices, "discount"),
                "tax": _sum_field(month_invoices, "vat"),
                "net_sales": _sum_field(month_invoices, "net_subtotal"),
                "collected": _sum_field(month_invoices, "paid"),
                "outstanding": _sum_field(month_invoices, "balance"),
            }
        )
    return Report(
        key="monthly_sales",
        title=REPORT_TITLES["monthly_sales"],
        subtitle="Sales earned per calendar month in the period",
        columns=[
            ("month", "Month", 100),
            ("invoices", "Invoices", 70),
            ("gross_sales", "Gross sales", 110),
            ("discount", "Discounts", 90),
            ("tax", "VAT", 90),
            ("net_sales", "Net sales", 105),
            ("collected", "Paid", 100),
            ("outstanding", "Outstanding", 100),
        ],
        rows=rows,
        totals={
            "invoices": len(invoices),
            "gross_sales": _sum_field(invoices, "total"),
            "discount": _sum_field(invoices, "discount"),
            "tax": _sum_field(invoices, "vat"),
            "net_sales": _sum_field(invoices, "net_subtotal"),
            "collected": _sum_field(invoices, "paid"),
            "outstanding": _sum_field(invoices, "balance"),
        },
        formulas=[FORMULAS["gross_sales"], FORMULAS["net_sales"]],
        period=_period_label(start, end),
        generated_at=_generated(),
    )


# --------------------------------------------------------------------------- #
# 3. custom date range (invoice detail)
# --------------------------------------------------------------------------- #
def custom_range(conn, start: str, end: str, filters: dict | None = None) -> Report:
    filters = filters or {}
    invoices = _invoice_rows(conn, start, end, filters)
    refunds = _refund_rows(conn, start, end, filters)
    refund_total = _sum_field(refunds, "amount")

    rows = []
    for invoice in invoices:
        rows.append(
            {
                "bill_no": invoice["bill_no"],
                "date": invoice["bill_date"],
                "time": invoice["time"],
                "guest": invoice["guest_name"] or "Walk-in guest",
                "room": invoice["room_no"],
                "cashier": invoice["prepared_by"],
                "subtotal": invoice["subtotal"],
                "discount": invoice["discount"],
                "tax": invoice["vat"],
                "total": invoice["total"],
                "method": invoice["payment_method"],
                "paid": invoice["paid"],
                "balance": invoice["balance"],
            }
        )
    return Report(
        key="custom_range",
        title=REPORT_TITLES["custom_range"],
        subtitle="Every invoice in the selected period",
        columns=[
            ("bill_no", "Invoice no.", 100),
            ("date", "Date", 85),
            ("time", "Time", 60),
            ("guest", "Guest", 130),
            ("room", "Room", 55),
            ("cashier", "Cashier", 90),
            ("subtotal", "Subtotal", 95),
            ("discount", "Discount", 85),
            ("tax", "VAT", 80),
            ("total", "Total", 100),
            ("method", "Method", 85),
            ("paid", "Paid", 95),
            ("balance", "Balance", 95),
        ],
        rows=rows,
        totals={
            "invoices": len(invoices),
            "subtotal": _sum_field(invoices, "subtotal"),
            "discount": _sum_field(invoices, "discount"),
            "tax": _sum_field(invoices, "vat"),
            "total": _sum_field(invoices, "total"),
            "paid": _sum_field(invoices, "paid"),
            "balance": _sum_field(invoices, "balance"),
            "refunds": refund_total,
            "net_sales": from_paisa(
                to_paisa(_sum_field(invoices, "total")) - to_paisa(refund_total)
            ),
        },
        formulas=[FORMULAS["gross_sales"], FORMULAS["net_sales_ledger"], FORMULAS["voided"]],
        period=_period_label(start, end),
        generated_at=_generated(),
    )


# --------------------------------------------------------------------------- #
# 4. payment collection
# --------------------------------------------------------------------------- #
def payment_collection(conn, start: str, end: str, filters: dict | None = None) -> Report:
    filters = filters or {}
    clauses = ["p.business_date BETWEEN ? AND ?"]
    params: list = [start, end]
    method = (filters.get("payment_method") or "").strip()
    if method and method != "All":
        clauses.append("p.method = ?")
        params.append(method)
    invoice = (filters.get("invoice_no") or "").strip()
    if invoice:
        clauses.append("p.bill_no LIKE ?")
        params.append(f"%{invoice}%")
    employee = (filters.get("employee") or "").strip()
    if employee and employee != "All":
        clauses.append("b.prepared_by = ?")
        params.append(employee)

    payments = [
        dict(row)
        for row in conn.execute(
            "SELECT p.*, b.guest_name, b.room_no, b.prepared_by, b.bill_date "
            "FROM payments p LEFT JOIN bills b ON b.bill_id = p.bill_id "
            "WHERE " + " AND ".join(clauses)
            + " ORDER BY p.business_date, p.paid_at, p.payment_id",
            params,
        )
    ]
    rows = [
        {
            "date": payment["business_date"],
            "time": str(payment.get("paid_at") or "")[11:19],
            "bill_no": payment["bill_no"],
            "guest": payment.get("guest_name") or "Walk-in guest",
            "room": payment.get("room_no") or "",
            "method": payment["method"],
            "amount": payment["amount"],
            "note": payment.get("note") or "",
        }
        for payment in payments
    ]

    by_method: dict[str, float] = {}
    for payment in payments:
        by_method[payment["method"]] = round(
            by_method.get(payment["method"], 0.0) + float(payment["amount"]), 2
        )
    totals = {
        "entries": len(payments),
        "collected": _sum_field(payments, "amount"),
        "by_method": by_method,
    }
    return Report(
        key="payment_collection",
        title=REPORT_TITLES["payment_collection"],
        subtitle="Cash received, by the day the money changed hands",
        columns=[
            ("date", "Business date", 110),
            ("time", "Time", 60),
            ("bill_no", "Invoice no.", 100),
            ("guest", "Guest", 130),
            ("room", "Room", 55),
            ("method", "Method", 95),
            ("amount", "Amount", 105),
            ("note", "Note", 180),
        ],
        rows=rows,
        totals=totals,
        formulas=[
            FORMULAS["collections"],
            "A payment received today against an older invoice counts as a collection today, not as a sale today.",
        ],
        period=_period_label(start, end),
        generated_at=_generated(),
    )


# --------------------------------------------------------------------------- #
# 5. outstanding invoices
# --------------------------------------------------------------------------- #
def outstanding_invoices(
    conn, start: str, end: str, filters: dict | None = None
) -> Report:
    filters = filters or {}
    where, params = _bill_filters(filters)
    extra = ["b.balance > 0", "b.bill_date <= ?"]
    sql = (
        "SELECT b.bill_no, b.bill_date, b.guest_name, b.guest_phone, b.room_no, "
        "b.prepared_by, b.payment_method, b.total, b.paid, b.balance, b.nights "
        "FROM bills b WHERE " + where + " AND " + " AND ".join(extra)
        + " ORDER BY b.bill_date, b.bill_no"
    )
    invoices = [dict(row) for row in conn.execute(sql, [*params, end])]
    rows = [
        {
            "bill_no": invoice["bill_no"],
            "date": invoice["bill_date"],
            "guest": invoice["guest_name"] or "Walk-in guest",
            "phone": invoice["guest_phone"],
            "room": invoice["room_no"],
            "cashier": invoice["prepared_by"],
            "total": invoice["total"],
            "paid": invoice["paid"],
            "balance": invoice["balance"],
            "age_days": _age_days(invoice["bill_date"], end),
        }
        for invoice in invoices
    ]
    return Report(
        key="outstanding_invoices",
        title=REPORT_TITLES["outstanding_invoices"],
        subtitle="Money still owed on invoices issued up to the period end",
        columns=[
            ("bill_no", "Invoice no.", 100),
            ("date", "Issued", 85),
            ("guest", "Guest", 130),
            ("phone", "Phone", 100),
            ("room", "Room", 55),
            ("total", "Total", 100),
            ("paid", "Paid", 95),
            ("balance", "Balance", 100),
            ("age_days", "Age (days)", 90),
        ],
        rows=rows,
        totals={
            "invoices": len(invoices),
            "total": _sum_field(invoices, "total"),
            "paid": _sum_field(invoices, "paid"),
            "balance": _sum_field(invoices, "balance"),
        },
        formulas=[FORMULAS["outstanding"]],
        period=_period_label(start, end),
        generated_at=_generated(),
    )


def _age_days(bill_date: str, end: str) -> int:
    try:
        from datetime import date

        return max(0, (date.fromisoformat(end) - date.fromisoformat(bill_date)).days)
    except ValueError:
        return 0


# --------------------------------------------------------------------------- #
# 6. refunds and adjustments
# --------------------------------------------------------------------------- #
def refunds_adjustments(
    conn, start: str, end: str, filters: dict | None = None
) -> Report:
    filters = filters or {}
    refunds = _refund_rows(conn, start, end, filters)
    rows = [
        {
            "date": refund["business_date"],
            "bill_no": refund["bill_no"],
            "guest": refund.get("guest_name") or "Walk-in guest",
            "room": refund.get("room_no") or "",
            "kind": "Refund" if refund["kind"] == "refund" else "Adjustment",
            "method": refund["method"],
            "amount": refund["amount"],
            "reason": refund.get("reason") or "",
        }
        for refund in refunds
    ]
    refund_total = _sum_field(
        [r for r in refunds if r["kind"] == "refund"], "amount"
    )
    adjustment_total = _sum_field(
        [r for r in refunds if r["kind"] == "adjustment"], "amount"
    )
    return Report(
        key="refunds_adjustments",
        title=REPORT_TITLES["refunds_adjustments"],
        subtitle="Money returned and authorised corrections",
        columns=[
            ("date", "Business date", 110),
            ("bill_no", "Invoice no.", 100),
            ("guest", "Guest", 130),
            ("room", "Room", 55),
            ("kind", "Type", 90),
            ("method", "Method", 90),
            ("amount", "Amount", 100),
            ("reason", "Reason", 220),
        ],
        rows=rows,
        totals={
            "entries": len(refunds),
            "refunds": refund_total,
            "adjustments": adjustment_total,
            "total": _sum_field(refunds, "amount"),
        },
        formulas=[
            "Refunds and adjustments are separate ledger rows; they never delete or edit the original invoice.",
            FORMULAS["net_sales_ledger"],
        ],
        period=_period_label(start, end),
        generated_at=_generated(),
    )


# --------------------------------------------------------------------------- #
# 7. employee / cashier sales
# --------------------------------------------------------------------------- #
def employee_sales(conn, start: str, end: str, filters: dict | None = None) -> Report:
    filters = filters or {}
    invoices = _invoice_rows(conn, start, end, filters)
    payments = [
        dict(row)
        for row in conn.execute(
            "SELECT p.*, b.prepared_by FROM payments p "
            "LEFT JOIN bills b ON b.bill_id = p.bill_id "
            "WHERE p.business_date BETWEEN ? AND ?",
            (start, end),
        )
    ]
    by_staff: dict[str, dict] = {}
    for invoice in invoices:
        name = invoice["prepared_by"] or "Unassigned"
        entry = by_staff.setdefault(
            name, {"invoices": 0, "sales": 0, "discount": 0, "paid": 0, "balance": 0}
        )
        entry["invoices"] += 1
        entry["sales"] = from_paisa(
            to_paisa(entry["sales"]) + to_paisa(invoice["total"])
        )
        entry["discount"] = from_paisa(
            to_paisa(entry["discount"]) + to_paisa(invoice["discount"])
        )
        entry["paid"] = from_paisa(
            to_paisa(entry["paid"]) + to_paisa(invoice["paid"])
        )
        entry["balance"] = from_paisa(
            to_paisa(entry["balance"]) + to_paisa(invoice["balance"])
        )

    collections: dict[str, float] = {}
    for payment in payments:
        name = payment.get("prepared_by") or "Unassigned"
        collections[name] = round(
            collections.get(name, 0.0) + float(payment["amount"]), 2
        )

    rows = []
    for name in sorted(by_staff):
        entry = by_staff[name]
        rows.append(
            {
                "employee": name,
                "invoices": entry["invoices"],
                "sales": entry["sales"],
                "discount": entry["discount"],
                "collected": collections.get(name, 0.0),
                "balance": entry["balance"],
                "average": from_paisa(
                    to_paisa(entry["sales"]) // max(1, entry["invoices"])
                )
                if entry["invoices"]
                else 0.0,
            }
        )
    return Report(
        key="employee_sales",
        title=REPORT_TITLES["employee_sales"],
        subtitle="Sales and collections by the cashier who raised the invoice",
        columns=[
            ("employee", "Employee", 140),
            ("invoices", "Invoices", 70),
            ("sales", "Sales", 110),
            ("discount", "Discounts", 95),
            ("collected", "Collected", 105),
            ("balance", "Outstanding", 100),
            ("average", "Average invoice", 110),
        ],
        rows=rows,
        totals={
            "invoices": len(invoices),
            "sales": _sum_field(invoices, "total"),
            "collected": _sum_field(payments, "amount"),
            "balance": _sum_field(invoices, "balance"),
        },
        formulas=[
            FORMULAS["average_invoice"],
            "Collections are attributed to the cashier who raised the invoice the payment settles.",
        ],
        period=_period_label(start, end),
        generated_at=_generated(),
    )


# --------------------------------------------------------------------------- #
# 8. room occupancy
# --------------------------------------------------------------------------- #
def room_occupancy(conn, start: str, end: str, filters: dict | None = None) -> Report:
    from . import rooms

    days = bt.date_range(start, end)
    rows = []
    for day in days:
        figures = rooms.occupancy(conn, day)
        rows.append(
            {
                "date": day,
                "sellable": figures["sellable_rooms"],
                "occupied_end": figures["occupied_end_of_day"],
                "occupied_across": figures["occupied_across_day"],
                "available": figures["available_now"],
                "nights": figures["occupied_nights"],
                "rate": figures["occupancy_rate"],
            }
        )
    today_figures = rooms.occupancy(conn, bt.today().isoformat())
    return Report(
        key="room_occupancy",
        title=REPORT_TITLES["room_occupancy"],
        subtitle="Occupancy per business day",
        columns=[
            ("date", "Business date", 110),
            ("sellable", "Sellable rooms", 105),
            ("occupied_end", "Occupied at day end", 120),
            ("occupied_across", "Occupied during day", 120),
            ("available", "Available now", 100),
            ("nights", "Occupied nights", 110),
            ("rate", "Occupancy %", 100),
        ],
        rows=rows,
        totals={
            "sellable": today_figures["sellable_rooms"],
            "occupied_end": today_figures["occupied_end_of_day"],
            "occupied_across": today_figures["occupied_across_day"],
            "available": today_figures["available_now"],
            "occupancy_rate": today_figures["occupancy_rate"],
        },
        formulas=[
            FORMULAS["occupancy"],
            "End-of-day occupancy counts guests still in house at midnight; occupancy across the day counts every guest who was in house at any point.",
        ],
        period=_period_label(start, end),
        generated_at=_generated(),
    )


# --------------------------------------------------------------------------- #
# 9. room revenue
# --------------------------------------------------------------------------- #
def room_revenue(conn, start: str, end: str, filters: dict | None = None) -> Report:
    filters = filters or {}
    room = (filters.get("room_no") or "").strip()
    clauses = [
        "bi.category = 'room'",
        "b.status = 'issued'",
        "b.is_draft = 0",
        "b.bill_date BETWEEN ? AND ?",
    ]
    params: list = [start, end]
    if room:
        clauses.append("b.room_no = ?")
        params.append(room)
    invoices = [
        dict(row)
        for row in conn.execute(
            "SELECT b.bill_no, b.bill_date, b.guest_name, b.room_no, b.nights, "
            "b.prepared_by, SUM(bi.line_total) AS revenue, SUM(bi.qty) AS nights "
            "FROM bill_items bi JOIN bills b ON b.bill_id = bi.bill_id "
            "WHERE " + " AND ".join(clauses) + " GROUP BY b.bill_id "
            "ORDER BY revenue DESC, b.bill_date",
            params,
        )
    ]
    by_room: dict[str, float] = {}
    for invoice in invoices:
        key = invoice["room_no"] or "—"
        by_room[key] = from_paisa(
            to_paisa(by_room.get(key, 0.0)) + to_paisa(invoice["revenue"])
        )
    rows = [
        {
            "bill_no": invoice["bill_no"],
            "date": invoice["bill_date"],
            "guest": invoice["guest_name"] or "Walk-in guest",
            "room": invoice["room_no"],
            "nights": int(invoice["nights"] or 0),
            "cashier": invoice["prepared_by"],
            "revenue": invoice["revenue"],
        }
        for invoice in invoices
    ]
    total = _sum_field(invoices, "revenue")
    return Report(
        key="room_revenue",
        title=REPORT_TITLES["room_revenue"],
        subtitle="Revenue earned from room charges",
        columns=[
            ("bill_no", "Invoice no.", 100),
            ("date", "Date", 85),
            ("guest", "Guest", 130),
            ("room", "Room", 60),
            ("nights", "Nights", 65),
            ("cashier", "Cashier", 95),
            ("revenue", "Room revenue", 115),
        ],
        rows=rows,
        totals={
            "total": total,
            "invoices": len(invoices),
            "by_room": by_room,
            "average": from_paisa(to_paisa(total) // len(invoices)) if invoices else 0.0,
        },
        formulas=[
            "Room revenue = Σ line total of invoice lines in the 'room' category.",
            FORMULAS["average_room_revenue"],
        ],
        period=_period_label(start, end),
        generated_at=_generated(),
    )


# --------------------------------------------------------------------------- #
# 10. operations summary
# --------------------------------------------------------------------------- #
def operations_summary(conn, start: str, end: str, filters: dict | None = None) -> Report:
    filters = filters or {}
    invoices = _invoice_rows(conn, start, end, filters)
    payments = [
        dict(row)
        for row in conn.execute(
            "SELECT * FROM payments WHERE business_date BETWEEN ? AND ?", (start, end)
        )
    ]
    refunds = _refund_rows(conn, start, end)
    from . import rooms

    gross = _sum_field(invoices, "total")
    discount = _sum_field(invoices, "discount")
    tax = _sum_field(invoices, "vat")
    service = _sum_field(invoices, "service_charge")
    collected = _sum_field(payments, "amount")
    refunded = _sum_field([r for r in refunds if r["kind"] == "refund"], "amount")
    adjustments = _sum_field([r for r in refunds if r["kind"] == "adjustment"], "amount")
    opening_cash = _opening_cash(conn, start)
    cash_collected = from_paisa(
        to_paisa(collected) - to_paisa(sum(float(p["amount"]) for p in payments if p["method"] != "Cash"))
    )
    cash_refunded = from_paisa(
        to_paisa(sum(float(r["amount"]) for r in refunds if r["kind"] == "refund" and r["method"] == "Cash"))
    )
    closing_cash = from_paisa(
        to_paisa(opening_cash) + to_paisa(cash_collected) - to_paisa(cash_refunded)
    )
    room_figures = rooms.room_revenue(conn, start, end)
    occupancy_figures = rooms.occupancy(conn, end)
    outstanding = from_paisa(
        to_paisa(
            conn.execute(
                "SELECT COALESCE(SUM(balance), 0) FROM bills WHERE status = 'issued' "
                "AND is_draft = 0 AND balance > 0 AND bill_date <= ?",
                (end,),
            ).fetchone()[0]
        )
    )

    by_method = {}
    for payment in payments:
        by_method[payment["method"]] = from_paisa(
            to_paisa(by_method.get(payment["method"], 0.0)) + to_paisa(payment["amount"])
        )
    by_category = {}
    for row in conn.execute(
        "SELECT bi.category, SUM(bi.line_total) AS total FROM bill_items bi "
        "JOIN bills b ON b.bill_id = bi.bill_id WHERE b.status = 'issued' "
        "AND b.is_draft = 0 AND b.bill_date BETWEEN ? AND ? GROUP BY bi.category",
        (start, end),
    ):
        by_category[row["category"]] = round(float(row["total"] or 0), 2)

    totals = {
        "invoices": len(invoices),
        "gross_sales": gross,
        "discount": discount,
        "tax": tax,
        "service_charge": service,
        "net_sales": from_paisa(to_paisa(gross) - to_paisa(discount) - to_paisa(refunded)),
        "collected": collected,
        "cash_collected": cash_collected,
        "by_method": by_method,
        "refunds": refunded,
        "adjustments": adjustments,
        "outstanding": outstanding,
        "opening_cash": opening_cash,
        "closing_cash": closing_cash,
        "room_revenue": room_figures["total"],
        "other_revenue": from_paisa(
            to_paisa(by_category.get("food", 0.0))
            + to_paisa(by_category.get("service", 0.0))
            + to_paisa(by_category.get("other", 0.0))
        ),
        "by_category": by_category,
        "occupied_rooms": occupancy_figures["occupied_across_day"],
        "available_rooms": occupancy_figures["available_now"],
        "sellable_rooms": occupancy_figures["sellable_rooms"],
        "occupancy_rate": occupancy_figures["occupancy_rate"],
        "average_invoice": from_paisa(to_paisa(gross) // len(invoices)) if invoices else 0.0,
    }
    rows = [
        {"metric": label, "value": value, "note": note}
        for label, value, note in (
            ("Gross sales", totals["gross_sales"], "Invoiced in the period"),
            ("Discounts", totals["discount"], "Line and bill discounts"),
            ("Taxable sales", totals["net_sales"], "After discounts, before tax"),
            ("Service charge", totals["service_charge"], "Hotel service charge"),
            ("VAT", totals["tax"], "VAT charged in the period"),
            ("Net sales", totals["net_sales"], "Gross sales − discounts − refunds"),
            ("Payments received", totals["collected"], "Cash changed hands in the period"),
            ("Cash collections", totals["cash_collected"], "Cash method only"),
            ("Refunds and reversals", totals["refunds"], "Money returned to guests"),
            ("Adjustments", totals["adjustments"], "Authorised balance corrections"),
            ("Outstanding receivables", totals["outstanding"], "Still owed on invoices to date"),
            ("Opening cash", totals["opening_cash"], "Cash carried into the period"),
            ("Closing cash", totals["closing_cash"], "Opening + cash in − cash out"),
            ("Room revenue", totals["room_revenue"], "Room category lines"),
            ("Other service revenue", totals["other_revenue"], "Food, service and other lines"),
            ("Invoices issued", totals["invoices"], "Count of issued invoices"),
            ("Average invoice value", totals["average_invoice"], "Gross sales ÷ invoices"),
            ("Occupied rooms", totals["occupied_rooms"], "Occupied during the period"),
            ("Available rooms", totals["available_rooms"], "Available right now"),
        )
    ]
    return Report(
        key="operations_summary",
        title=REPORT_TITLES["operations_summary"],
        subtitle="Everything the front desk and the owner look at",
        columns=[
            ("metric", "Measure", 230),
            ("value", "Value", 150),
            ("note", "How it is measured", 320),
        ],
        rows=rows,
        totals=totals,
        formulas=[
            FORMULAS["gross_sales"],
            FORMULAS["collections"],
            FORMULAS["cash_in_hand"],
            FORMULAS["outstanding"],
            FORMULAS["average_invoice"],
            FORMULAS["occupancy"],
        ],
        period=_period_label(start, end),
        generated_at=_generated(),
    )


def _opening_cash(conn: sqlite3.Connection, start: str) -> float:
    """Cash in the drawer at the start of the period."""
    from . import db

    settings = db.get_settings(conn)
    try:
        opening = float(settings.get("cash_opening_balance") or 0)
    except (TypeError, ValueError):
        opening = 0.0
    carried = conn.execute(
        "SELECT COALESCE(SUM(amount), 0) FROM payments WHERE business_date < ? AND method = 'Cash'",
        (start,),
    ).fetchone()[0]
    returned = conn.execute(
        "SELECT COALESCE(SUM(amount), 0) FROM refunds WHERE business_date < ? "
        "AND kind = 'refund' AND method = 'Cash'",
        (start,),
    ).fetchone()[0]
    return from_paisa(to_paisa(opening) + to_paisa(carried) - to_paisa(returned))


# --------------------------------------------------------------------------- #
# dispatcher
# --------------------------------------------------------------------------- #
BUILDERS = {
    "daily_sales": daily_sales,
    "monthly_sales": monthly_sales,
    "custom_range": custom_range,
    "payment_collection": payment_collection,
    "outstanding_invoices": outstanding_invoices,
    "refunds_adjustments": refunds_adjustments,
    "employee_sales": employee_sales,
    "room_occupancy": room_occupancy,
    "room_revenue": room_revenue,
    "operations_summary": operations_summary,
}


def build(
    conn: sqlite3.Connection,
    key: str,
    start: str,
    end: str,
    filters: dict | None = None,
) -> Report:
    """Build one report by key."""
    builder = BUILDERS.get(key)
    if builder is None:
        raise ValueError(f"Unknown report: {key}")
    return builder(conn, start, end, filters or {})


def dashboard_cards(conn: sqlite3.Connection, day: str | None = None) -> dict:
    """The summary cards at the top of the Reports dashboard.

    Every card is labelled with the measurement it shows, so a collection is
    never mistaken for a sale.
    """
    from . import db, rooms

    day = day or bt.today().isoformat()
    summary = operations_summary(conn, day, day)
    totals = summary.totals
    occupancy = rooms.occupancy(conn, day)
    settings = db.get_settings(conn)
    return {
        "business_date": day,
        "timezone": settings.get("business_timezone", bt.DEFAULT_TIMEZONE),
        "gross_sales": totals["gross_sales"],
        "net_sales": totals["net_sales"],
        "collected": totals["collected"],
        "cash_collected": totals["cash_collected"],
        "outstanding": totals["outstanding"],
        "room_revenue": totals["room_revenue"],
        "invoices": totals["invoices"],
        "occupied_rooms": occupancy["occupied_across_day"],
        "available_rooms": occupancy["available_now"],
        "sellable_rooms": occupancy["sellable_rooms"],
        "average_invoice": totals["average_invoice"],
        "occupancy_rate": occupancy["occupancy_rate"],
    }
