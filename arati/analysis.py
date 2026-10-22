"""Sales analysis over the recorded transactions.

Nothing here is a prediction and nothing here is generated: every series is
a SQL aggregate over the invoice, payment and refund tables, and every
metric carries the formula it was computed with, so a number on a chart can
always be traced back to the rows behind it.

The analysis is deliberately separate from :mod:`arati.reports`. Reports
answer "what happened"; analysis answers "how did it move and why", and it
needs a different shape of output — series for charts, deltas for
comparisons.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field

from . import business_time as bt
from .money import from_paisa, to_paisa

# The formulas, written down once so the Analysis screen can show them.
FORMULAS = {
    "average_invoice": "Average invoice value = eligible sales value ÷ number of eligible invoices.",
    "occupancy": "Room occupancy rate = occupied sellable rooms ÷ total sellable rooms × 100.",
    "occupancy_end_of_day": "End-of-day occupancy = guests still in house at midnight ÷ sellable rooms × 100.",
    "occupancy_across_day": "Occupancy across the day = rooms occupied at any point ÷ sellable rooms × 100.",
    "average_room_revenue": "Average room revenue = room revenue ÷ number of invoices carrying room revenue.",
    "net_sales": "Net sales = Σ invoice totals − Σ refunds and reversals in the period.",
    "outstanding": "Outstanding receivables = Σ balance of issued invoices dated on or before the period end.",
    "collection_ratio": "Collection ratio = payments received ÷ gross sales × 100.",
    "discount_ratio": "Discount ratio = Σ discounts ÷ Σ subtotals × 100.",
    "refund_ratio": "Refund ratio = Σ refunds ÷ gross sales × 100.",
    "growth": "Period change = (current period value − comparison period value) ÷ comparison period value × 100.",
    "voided": "Voided invoices are excluded from every figure.",
    "payment_date": "Payments are grouped by the business date the cash changed hands, not by the invoice date.",
}

CATEGORY_LABELS = {
    "room": "Room revenue",
    "food": "Food & beverage",
    "service": "Services",
    "other": "Other",
}


@dataclass
class Series:
    """A named series of points, ready to be plotted."""

    key: str
    label: str
    points: list[tuple[str, float]] = field(default_factory=list)
    total: float = 0.0
    formula: str = ""

    def as_dict(self) -> dict:
        return {
            "key": self.key,
            "label": self.label,
            "points": list(self.points),
            "total": self.total,
            "formula": self.formula,
        }


@dataclass
class Metric:
    """One headline number with the formula that produced it."""

    key: str
    label: str
    value: float
    unit: str = "amount"
    formula: str = ""
    comparison: float | None = None

    def as_dict(self) -> dict:
        return {
            "key": self.key,
            "label": self.label,
            "value": self.value,
            "unit": self.unit,
            "formula": self.formula,
            "comparison": self.comparison,
        }


def _sum(rows, key: str) -> float:
    total = 0
    for row in rows:
        value = row[key] if isinstance(row, dict) else row[key]
        total += to_paisa(value or 0)
    return from_paisa(total)


# --------------------------------------------------------------------------- #
# trends
# --------------------------------------------------------------------------- #
def sales_trend(
    conn: sqlite3.Connection, start: str, end: str, bucket: str = "day"
) -> Series:
    """Sales over time, bucketed by day, ISO week or month.

    Buckets are calendar buckets in the business timezone: a week runs
    Monday to Sunday, a month runs from the 1st to the last day.
    """
    rows = list(
        conn.execute(
            "SELECT bill_date, total, net_subtotal FROM bills WHERE status = 'issued' "
            "AND is_draft = 0 AND bill_date BETWEEN ? AND ? ORDER BY bill_date",
            (start, end),
        )
    )
    grouped: dict[str, list] = {}
    for row in rows:
        key = _bucket_key(row["bill_date"], bucket)
        grouped.setdefault(key, []).append(row)
    points = [
        (key, _sum(grouped[key], "total")) for key in sorted(grouped)
    ]
    return Series(
        key=f"sales_{bucket}",
        label=f"Sales by {bucket}",
        points=points,
        total=_sum(rows, "total"),
        formula="Sales = Σ invoice total, grouped into calendar buckets in the business timezone.",
    )


def collection_trend(
    conn: sqlite3.Connection, start: str, end: str, bucket: str = "day"
) -> Series:
    """Cash collected over time, bucketed the same way as the sales trend."""
    rows = list(
        conn.execute(
            "SELECT business_date, amount FROM payments WHERE business_date BETWEEN ? AND ?",
            (start, end),
        )
    )
    grouped: dict[str, list] = {}
    for row in rows:
        grouped.setdefault(_bucket_key(row["business_date"], bucket), []).append(row)
    return Series(
        key=f"collections_{bucket}",
        label=f"Collections by {bucket}",
        points=[(key, _sum(grouped[key], "amount")) for key in sorted(grouped)],
        total=_sum(rows, "amount"),
        formula=FORMULAS["payment_date"],
    )


def _bucket_key(business_date: str, bucket: str) -> str:
    from datetime import date

    try:
        parsed = date.fromisoformat(str(business_date)[:10])
    except ValueError:
        return str(business_date)[:10]
    if bucket == "month":
        return parsed.strftime("%Y-%m")
    if bucket == "week":
        year, week, _ = parsed.isocalendar()
        return f"{year}-W{week:02d}"
    return parsed.isoformat()


# --------------------------------------------------------------------------- #
# breakdowns
# --------------------------------------------------------------------------- #
def revenue_by_category(
    conn: sqlite3.Connection, start: str, end: str
) -> Series:
    """Revenue split by the category on each invoice line."""
    rows = list(
        conn.execute(
            "SELECT bi.category, SUM(bi.line_total) AS total FROM bill_items bi "
            "JOIN bills b ON b.bill_id = bi.bill_id WHERE b.status = 'issued' "
            "AND b.is_draft = 0 AND b.bill_date BETWEEN ? AND ? GROUP BY bi.category",
            (start, end),
        )
    )
    points = [
        (CATEGORY_LABELS.get(row["category"], row["category"].title()), round(float(row["total"] or 0), 2))
        for row in sorted(rows, key=lambda r: -(r["total"] or 0))
    ]
    return Series(
        key="revenue_by_category",
        label="Revenue by category",
        points=points,
        total=round(sum(point[1] for point in points), 2),
        formula="Revenue by category = Σ line total of invoice lines in each category.",
    )


def revenue_by_room(conn: sqlite3.Connection, start: str, end: str) -> Series:
    """Room revenue per room number."""
    rows = list(
        conn.execute(
            "SELECT b.room_no, SUM(bi.line_total) AS total FROM bill_items bi "
            "JOIN bills b ON b.bill_id = bi.bill_id WHERE bi.category = 'room' "
            "AND b.status = 'issued' AND b.is_draft = 0 AND b.bill_date BETWEEN ? AND ? "
            "GROUP BY b.room_no ORDER BY total DESC",
            (start, end),
        )
    )
    points = [
        (row["room_no"] or "—", round(float(row["total"] or 0), 2))
        for row in rows
    ]
    return Series(
        key="revenue_by_room",
        label="Revenue by room",
        points=points,
        total=round(sum(point[1] for point in points), 2),
        formula="Revenue by room = Σ room-category line totals, grouped by the room number on the invoice.",
    )


def revenue_by_method(conn: sqlite3.Connection, start: str, end: str) -> Series:
    """Cash collected per payment method."""
    rows = list(
        conn.execute(
            "SELECT method, SUM(amount) AS total FROM payments "
            "WHERE business_date BETWEEN ? AND ? GROUP BY method ORDER BY total DESC",
            (start, end),
        )
    )
    points = [
        (row["method"], round(float(row["total"] or 0), 2))
        for row in rows
    ]
    return Series(
        key="revenue_by_method",
        label="Collections by payment method",
        points=points,
        total=round(sum(point[1] for point in points), 2),
        formula="Collections by method = Σ payment rows in the period, grouped by the payment method.",
    )


def sales_by_employee(conn: sqlite3.Connection, start: str, end: str) -> Series:
    """Sales raised by each cashier."""
    rows = list(
        conn.execute(
            "SELECT COALESCE(NULLIF(prepared_by, ''), 'Unassigned') AS who, "
            "SUM(total) AS total, COUNT(*) AS invoices FROM bills "
            "WHERE status = 'issued' AND is_draft = 0 AND bill_date BETWEEN ? AND ? "
            "GROUP BY who ORDER BY total DESC",
            (start, end),
        )
    )
    points = [(row["who"], round(float(row["total"] or 0), 2)) for row in rows]
    return Series(
        key="sales_by_employee",
        label="Sales by employee",
        points=points,
        total=round(sum(point[1] for point in points), 2),
        formula="Sales by employee = Σ invoice totals, grouped by the cashier recorded on the invoice.",
    )


def refund_trend(
    conn: sqlite3.Connection, start: str, end: str, bucket: str = "day"
) -> Series:
    """Refunds and reversals over time."""
    rows = list(
        conn.execute(
            "SELECT business_date, amount FROM refunds WHERE business_date BETWEEN ? AND ?",
            (start, end),
        )
    )
    grouped: dict[str, list] = {}
    for row in rows:
        grouped.setdefault(_bucket_key(row["business_date"], bucket), []).append(row)
    return Series(
        key="refund_trend",
        label=f"Refunds by {bucket}",
        points=[(key, _sum(grouped[key], "amount")) for key in sorted(grouped)],
        total=_sum(rows, "amount"),
        formula="Refunds = Σ refund and adjustment ledger rows dated in the period.",
    )


def discount_trend(
    conn: sqlite3.Connection, start: str, end: str, bucket: str = "day"
) -> Series:
    """Discounts given over time."""
    rows = list(
        conn.execute(
            "SELECT bill_date, discount FROM bills WHERE status = 'issued' "
            "AND is_draft = 0 AND bill_date BETWEEN ? AND ?",
            (start, end),
        )
    )
    grouped: dict[str, list] = {}
    for row in rows:
        grouped.setdefault(_bucket_key(row["bill_date"], bucket), []).append(row)
    return Series(
        key="discount_trend",
        label=f"Discounts by {bucket}",
        points=[(key, _sum(grouped[key], "discount")) for key in sorted(grouped)],
        total=_sum(rows, "discount"),
        formula="Discounts = Σ invoice discount columns (line discounts plus bill discount).",
    )


# --------------------------------------------------------------------------- #
# headline metrics
# --------------------------------------------------------------------------- #
def headline_metrics(conn: sqlite3.Connection, start: str, end: str) -> list[Metric]:
    """The numbers shown as cards above the charts."""
    from . import rooms

    bills = list(
        conn.execute(
            "SELECT total, subtotal, discount, net_subtotal, vat, service_charge, paid, balance "
            "FROM bills WHERE status = 'issued' AND is_draft = 0 AND bill_date BETWEEN ? AND ?",
            (start, end),
        )
    )
    payments = list(
        conn.execute(
            "SELECT amount FROM payments WHERE business_date BETWEEN ? AND ?", (start, end)
        )
    )
    refunds = list(
        conn.execute(
            "SELECT amount, kind FROM refunds WHERE business_date BETWEEN ? AND ?", (start, end)
        )
    )
    gross = _sum(bills, "total")
    count = len(bills)
    collected = _sum(payments, "amount")
    refunded = _sum([r for r in refunds if r["kind"] == "refund"], "amount")
    subtotal = _sum(bills, "subtotal")
    discount = _sum(bills, "discount")
    outstanding = from_paisa(
        to_paisa(
            conn.execute(
                "SELECT COALESCE(SUM(balance), 0) FROM bills WHERE status = 'issued' "
                "AND is_draft = 0 AND balance > 0 AND bill_date <= ?",
                (end,),
            ).fetchone()[0]
        )
    )
    occupancy = rooms.occupancy(conn, end)
    room_figures = rooms.room_revenue(conn, start, end)
    room_invoices = conn.execute(
        "SELECT COUNT(DISTINCT b.bill_id) FROM bill_items bi JOIN bills b "
        "ON b.bill_id = bi.bill_id WHERE bi.category = 'room' AND b.status = 'issued' "
        "AND b.is_draft = 0 AND b.bill_date BETWEEN ? AND ?",
        (start, end),
    ).fetchone()[0]

    metrics = [
        Metric(
            "gross_sales",
            "Gross sales",
            gross,
            formula="Σ invoice totals for issued invoices in the period.",
        ),
        Metric(
            "net_sales",
            "Net sales",
            from_paisa(to_paisa(gross) - to_paisa(refunded)),
            formula=FORMULAS["net_sales"],
        ),
        Metric(
            "transactions",
            "Transactions",
            float(count),
            unit="count",
            formula="Number of issued, non-draft invoices dated in the period.",
        ),
        Metric(
            "average_invoice",
            "Average invoice value",
            from_paisa(to_paisa(gross) // count) if count else 0.0,
            formula=FORMULAS["average_invoice"],
        ),
        Metric(
            "collected",
            "Payments received",
            collected,
            formula=FORMULAS["payment_date"],
        ),
        Metric(
            "collection_ratio",
            "Collection ratio",
            round(collected / gross * 100, 2) if gross else 0.0,
            unit="percent",
            formula=FORMULAS["collection_ratio"],
        ),
        Metric(
            "discount_ratio",
            "Discount ratio",
            round(discount / subtotal * 100, 2) if subtotal else 0.0,
            unit="percent",
            formula=FORMULAS["discount_ratio"],
        ),
        Metric(
            "refunds",
            "Refunds and reversals",
            refunded,
            formula="Σ refund rows dated in the period.",
        ),
        Metric(
            "outstanding",
            "Outstanding receivables",
            outstanding,
            formula=FORMULAS["outstanding"],
        ),
        Metric(
            "occupancy_rate",
            "Room occupancy rate",
            occupancy["occupancy_rate"],
            unit="percent",
            formula=FORMULAS["occupancy"],
        ),
        Metric(
            "occupied_end_of_day",
            "Occupied at end of day",
            float(occupancy["occupied_end_of_day"]),
            unit="count",
            formula=FORMULAS["occupancy_end_of_day"],
        ),
        Metric(
            "occupied_across_day",
            "Occupied during the day",
            float(occupancy["occupied_across_day"]),
            unit="count",
            formula=FORMULAS["occupancy_across_day"],
        ),
        Metric(
            "room_revenue",
            "Room revenue",
            room_figures["total"],
            formula="Σ room-category line totals in the period.",
        ),
        Metric(
            "average_room_revenue",
            "Average room revenue",
            from_paisa(to_paisa(room_figures["total"]) // room_invoices)
            if room_invoices
            else 0.0,
            formula=FORMULAS["average_room_revenue"],
        ),
    ]
    return metrics


# --------------------------------------------------------------------------- #
# period comparison
# --------------------------------------------------------------------------- #
def compare_periods(
    conn: sqlite3.Connection,
    current: tuple[str, str],
    previous: tuple[str, str],
) -> dict:
    """Compare two periods metric by metric.

    The two periods must be the same length for the percentages to mean
    anything; when they are not, the day counts are reported so the reader
    can judge.
    """
    current_metrics = {m.key: m for m in headline_metrics(conn, *current)}
    previous_metrics = {m.key: m for m in headline_metrics(conn, *previous)}

    comparisons = []
    for key, metric in current_metrics.items():
        before = previous_metrics.get(key)
        previous_value = before.value if before else 0.0
        change = None
        if previous_value:
            change = round((metric.value - previous_value) / abs(previous_value) * 100, 2)
        comparisons.append(
            {
                "key": key,
                "label": metric.label,
                "unit": metric.unit,
                "current": metric.value,
                "previous": previous_value,
                "change": change,
                "formula": metric.formula,
            }
        )

    def _days(period: tuple[str, str]) -> int:
        return len(bt.date_range(period[0], period[1]))

    return {
        "current_period": current,
        "previous_period": previous,
        "current_days": _days(current),
        "previous_days": _days(previous),
        "same_length": _days(current) == _days(previous),
        "comparisons": comparisons,
        "formula": FORMULAS["growth"],
    }


def full_analysis(
    conn: sqlite3.Connection,
    start: str,
    end: str,
    bucket: str = "day",
    comparison: tuple[str, str] | None = None,
) -> dict:
    """Everything the Analysis screen needs, in one call."""
    result = {
        "period": (start, end),
        "bucket": bucket,
        "timezone": bt.DEFAULT_TIMEZONE,
        "metrics": [m.as_dict() for m in headline_metrics(conn, start, end)],
        "series": [
            sales_trend(conn, start, end, bucket).as_dict(),
            collection_trend(conn, start, end, bucket).as_dict(),
            revenue_by_category(conn, start, end).as_dict(),
            revenue_by_room(conn, start, end).as_dict(),
            revenue_by_method(conn, start, end).as_dict(),
            sales_by_employee(conn, start, end).as_dict(),
            refund_trend(conn, start, end, bucket).as_dict(),
            discount_trend(conn, start, end, bucket).as_dict(),
        ],
        "formulas": dict(FORMULAS),
    }
    if comparison:
        result["comparison"] = compare_periods(conn, (start, end), comparison)
    return result
