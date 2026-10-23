"""Dashboard analytics adapted to the Web App's SQLAlchemy data model."""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from . import reporting
from .models import (
    Invoice, InvoiceItem, Payment, Refund, Room, Stay,
)
from .services import local_now

PERIODS = {
    "today": ("Today", 1),
    "7": ("Last 7 days", 7),
    "30": ("Last 30 days", 30),
    "90": ("Last 90 days", 90),
}


def sales_details(db: Session, period: str = "30") -> dict:
    """Build the dashboard's chart, room-performance, and review data."""
    if period not in PERIODS:
        raise ValueError("Choose Today, Last 7 days, Last 30 days, or Last 90 days.")

    label, days = PERIODS[period]
    end = local_now().date()
    start = end - timedelta(days=days - 1)
    previous_end = start - timedelta(days=1)
    previous_start = previous_end - timedelta(days=days - 1)
    bucket = "day" if days <= 7 else "week"
    start_text, end_text = start.isoformat(), end.isoformat()
    result = reporting.analysis_data(
        db, start_text, end_text, bucket,
        previous_start.isoformat(), previous_end.isoformat(),
    )

    metrics = {item["key"]: item["value"] for item in result["metrics"]}
    chart_by_label = {item["label"]: item for item in result["charts"]}
    sales_chart = chart_by_label[f"Sales by {bucket}"]["points"]
    collections_chart = chart_by_label[f"Collections by {bucket}"]["points"]
    sales_by_label = {point["label"]: point for point in sales_chart}
    collection_by_label = {point["label"]: point for point in collections_chart}
    trend_points = []
    for point_label in sorted(set(sales_by_label) | set(collection_by_label)):
        point = sales_by_label.get(point_label, {"value": 0})
        collection = collection_by_label.get(point_label, {"value": 0})
        trend_points.append({
            "label": point_label,
            "sales": point["value"],
            "collections": collection["value"],
        })
    trend_max = max(
        (max(point["sales"], point["collections"]) for point in trend_points),
        default=0,
    )
    for point in trend_points:
        point["sales_width"] = max(2, round(point["sales"] / trend_max * 100)) if trend_max else 2
        point["collections_width"] = (
            max(2, round(point["collections"] / trend_max * 100)) if trend_max else 2
        )

    room_performance = _room_performance(db, start, end, metrics["room_revenue"])
    data_quality = _data_quality(db, start_text, end_text)
    if room_performance["overlapping_stays"]:
        count = len(room_performance["overlapping_stays"])
        action = "Review overlapping room stays and resolve conflicts through the authorized stay workflow."
        data_quality["findings"].append({
            "issue": "overlapping_room_stays",
            "severity": "high",
            "record_ids": [{
                "table": "stays",
                "id": ", ".join(str(stay_id) for stay_id in entry["stay_ids"]),
                "invoice_no": f"Room {entry['room']} · {entry['date']}",
            } for entry in room_performance["overlapping_stays"]],
            "count": count,
            "recommended_action": action,
        })
        data_quality["findings"].sort(key=lambda item: (
            {"high": 0, "medium": 1, "review": 2}.get(item["severity"], 3),
            item["issue"],
        ))
        data_quality["finding_count"] += count
    forecast = _forecast_availability(db, end_text)
    insights = _insights(result, data_quality)
    priority = {"high": 0, "medium": 1, "review": 2, "info": 3}
    insights.sort(key=lambda item: (priority.get(item["severity"], 4), item["title"]))

    return {
        "period": period,
        "period_label": label,
        "period_start": start_text,
        "period_end": end_text,
        "period_options": PERIODS,
        "metrics": metrics,
        "trend": trend_points,
        "categories": _top_points(chart_by_label["Revenue by category"]["points"]),
        "rooms": _top_points(chart_by_label["Room revenue by room"]["points"], 8),
        "methods": _top_points(chart_by_label["Collections by payment method"]["points"]),
        "room_performance": room_performance,
        "data_quality": data_quality,
        "forecast": forecast,
        "insights": insights[:6],
        "timezone": "Asia/Kathmandu",
    }


def _top_points(points: list[dict], limit: int = 8) -> list[dict]:
    return sorted(points, key=lambda item: (-item["value"], item["label"]))[:limit]


def _room_performance(
    db: Session, start: date, end: date, room_revenue: float,
) -> dict:
    days = (end - start).days + 1
    rooms = list(db.scalars(select(Room).where(Room.active.is_(True))))
    exact_current_day = start == end == local_now().date()
    excluded_rooms = sum(
        room.status in {"dirty", "needs_cleaning", "maintenance", "under_maintenance"}
        for room in rooms
    ) if exact_current_day else 0
    capacity = max(0, len(rooms) - excluded_rooms) * days

    stays = db.scalars(select(Stay).where(
        Stay.status.in_(("checked_in", "checked_out")),
        Stay.check_in < datetime.combine(end + timedelta(days=1), datetime.min.time()),
        or_(Stay.check_out.is_(None), Stay.check_out >= datetime.combine(start, datetime.min.time())),
    )).all()
    occupied_nights: set[tuple[int, date]] = set()
    nights_by_room: dict[tuple[int, date], list[int]] = defaultdict(list)
    for stay in stays:
        arrival = stay.check_in.date()
        departure_value = stay.check_out or stay.expected_checkout
        departure = departure_value.date() if departure_value else end
        if departure < arrival:
            continue
        if departure == arrival:
            occupied_dates = [arrival] if start <= arrival <= end else []
        else:
            first_night = max(arrival, start)
            last_night = min(departure, end + timedelta(days=1))
            occupied_dates = [
                first_night + timedelta(days=offset)
                for offset in range(max(0, (last_night - first_night).days))
            ]
        for night in occupied_dates:
            key = (stay.room_id, night)
            occupied_nights.add(key)
            nights_by_room[key].append(stay.id)

    occupied = len(occupied_nights)
    occupancy = round(occupied / capacity * 100, 2) if capacity else None
    adr = round(room_revenue / occupied, 2) if occupied else None
    revpar = round(room_revenue / capacity, 2) if capacity else None
    overlaps = [
        {"room": room_id, "date": night.isoformat(), "stay_ids": sorted(stay_ids)}
        for (room_id, night), stay_ids in nights_by_room.items()
        if len(stay_ids) > 1
    ]
    return {
        "occupied_room_nights": occupied,
        "capacity": capacity,
        "occupancy_rate": occupancy,
        "adr": adr,
        "revpar": revpar,
        "capacity_status": (
            "Exact current-day capacity"
            if exact_current_day else "Approximate: current room inventory held constant"
        ),
        "overlapping_stays": overlaps,
    }


def _data_quality(db: Session, start: str, end: str) -> dict:
    invoices = list(db.scalars(select(Invoice).where(
        Invoice.bill_date.between(start, end),
    ).order_by(Invoice.id)))
    invoice_ids = [invoice.id for invoice in invoices]
    invoice_numbers = [invoice.invoice_number for invoice in invoices]
    if not invoice_ids:
        return {"findings": [], "finding_count": 0, "records_checked": 0}

    item_totals = {
        invoice_id: (int(count), Decimal(str(line_total or 0)), Decimal(str(discount or 0)))
        for invoice_id, count, line_total, discount in db.execute(
            select(
                InvoiceItem.invoice_id,
                func.count(InvoiceItem.id),
                func.sum(InvoiceItem.quantity * InvoiceItem.rate),
                func.sum(InvoiceItem.discount_amount),
            ).where(InvoiceItem.invoice_id.in_(invoice_ids))
            .group_by(InvoiceItem.invoice_id)
        )
    }
    payments = db.scalars(select(Payment).where(or_(
        Payment.invoice_id.in_(invoice_ids),
        (Payment.invoice_id.is_(None) & Payment.invoice_number.in_(invoice_numbers)),
    ))).all()
    ledger_rows = db.scalars(select(Refund).where(or_(
        Refund.invoice_id.in_(invoice_ids),
        (Refund.invoice_id.is_(None) & Refund.invoice_number.in_(invoice_numbers)),
    ))).all()
    payment_by_number: dict[str, Decimal] = defaultdict(Decimal)
    refunds_by_number: dict[str, Decimal] = defaultdict(Decimal)
    adjustments_by_number: dict[str, Decimal] = defaultdict(Decimal)
    for payment in payments:
        number = payment.invoice_number
        if number:
            payment_by_number[number] += Decimal(str(payment.amount or 0))
    for entry in ledger_rows:
        number = entry.invoice_number
        if entry.kind == "refund":
            refunds_by_number[number] += Decimal(str(entry.amount or 0))
        elif entry.kind == "adjustment":
            adjustments_by_number[number] += Decimal(str(entry.amount or 0))

    groups: dict[str, list[dict]] = defaultdict(list)

    def add(issue: str, severity: str, records: list[dict], action: str) -> None:
        if records:
            unique = {
                (record.get("table"), record.get("id"), record.get("invoice_no")): record
                for record in records
            }
            groups[issue].append({
                "issue": issue,
                "severity": severity,
                "record_ids": list(unique.values()),
                "count": len(unique),
                "recommended_action": action,
            })

    missing_lines = []
    bad_math = []
    bad_ledger = []
    large_discounts = []
    for invoice in invoices:
        record = {
            "table": "invoices",
            "id": invoice.id,
            "invoice_no": invoice.invoice_number,
        }
        count, line_subtotal, line_discount = item_totals.get(
            invoice.id, (0, Decimal("0"), Decimal("0"))
        )
        if invoice.status in {"issued", "paid"} and not count:
            missing_lines.append(record)
        calculated_total = (
            Decimal(str(invoice.net_subtotal or 0))
            + Decimal(str(invoice.service_charge or 0))
            + Decimal(str(invoice.vat_amount or 0))
        )
        if (
            (count and abs(line_subtotal - Decimal(str(invoice.subtotal or 0))) > Decimal("0.01"))
            or abs(calculated_total - Decimal(str(invoice.total or 0))) > Decimal("0.01")
            or min(
                Decimal(str(invoice.total or 0)),
                Decimal(str(invoice.paid_amount or 0)),
                Decimal(str(invoice.balance or 0)),
            ) < 0
        ):
            bad_math.append(record)
        expected_paid = payment_by_number[invoice.invoice_number] - refunds_by_number[invoice.invoice_number]
        expected_balance = (
            Decimal(str(invoice.total or 0)) - expected_paid
            - adjustments_by_number[invoice.invoice_number]
        )
        if invoice.status != "draft" and (
            abs(expected_paid - Decimal(str(invoice.paid_amount or 0))) > Decimal("0.01")
            or abs(expected_balance - Decimal(str(invoice.balance or 0))) > Decimal("0.01")
            or Decimal(str(invoice.paid_amount or 0)) > Decimal(str(invoice.total or 0))
        ):
            bad_ledger.append(record)
        subtotal = Decimal(str(invoice.subtotal or 0))
        discounts = (
            Decimal(str(invoice.discount_amount or 0))
            + Decimal(str(invoice.item_discount or 0))
        )
        if subtotal and discounts / subtotal >= Decimal("0.5"):
            large_discounts.append(record)

    add(
        "invoice_without_lines", "high", missing_lines,
        "Review the invoice and its original line items; restore only through an authorized correction.",
    )
    add(
        "invoice_total_or_amount_invalid", "high", bad_math,
        "Reconcile the invoice totals against its line items and tax snapshot.",
    )
    add(
        "payment_ledger_does_not_reconcile", "high", bad_ledger,
        "Compare invoice paid/balance fields with payment, refund, and adjustment ledger rows.",
    )
    add(
        "large_discount_review", "review", large_discounts,
        "Review discounts at or above 50%; this is a review threshold, not an allegation.",
    )

    payment_invoice_match = or_(
        Payment.invoice_id == Invoice.id,
        Payment.invoice_id.is_(None) & (Payment.invoice_number == Invoice.invoice_number),
    )
    refund_invoice_match = or_(
        Refund.invoice_id == Invoice.id,
        Refund.invoice_id.is_(None) & (Refund.invoice_number == Invoice.invoice_number),
    )
    orphan_payments = [{
        "table": "payments", "id": payment.id, "invoice_no": payment.invoice_number,
    } for payment in db.scalars(select(Payment).outerjoin(
        Invoice, payment_invoice_match,
    ).where(or_(
        Invoice.id.is_(None),
        (Payment.invoice_id.is_not(None) & (Invoice.invoice_number != Payment.invoice_number)),
    )))]
    orphan_refunds = [{
        "table": "refunds", "id": entry.id, "invoice_no": entry.invoice_number,
    } for entry in db.scalars(select(Refund).outerjoin(
        Invoice, refund_invoice_match,
    ).where(or_(
        Invoice.id.is_(None),
        (Refund.invoice_id.is_not(None) & (Invoice.invoice_number != Refund.invoice_number)),
    )))]
    nonpositive = [{
        "table": "payments", "id": payment.id, "invoice_no": payment.invoice_number,
    } for payment in db.scalars(select(Payment).where(Payment.amount <= 0))]
    nonpositive.extend({
        "table": "refunds", "id": entry.id, "invoice_no": entry.invoice_number,
    } for entry in db.scalars(select(Refund).where(
        Refund.kind == "refund", Refund.amount <= 0,
    )))
    add(
        "orphan_or_mismatched_payments", "high", orphan_payments,
        "Link the payment to the correct invoice using an audited repair.",
    )
    add(
        "orphan_or_mismatched_refunds", "high", orphan_refunds,
        "Link the refund to the correct invoice using an audited repair.",
    )
    add(
        "nonpositive_payment_or_refund", "high", nonpositive,
        "Review the ledger row and correct it through an authorized reversal workflow.",
    )

    findings = [finding for entries in groups.values() for finding in entries]
    findings.sort(key=lambda item: (
        {"high": 0, "medium": 1, "review": 2}.get(item["severity"], 3),
        item["issue"],
    ))
    return {
        "findings": findings,
        "finding_count": sum(item["count"] for item in findings),
        "records_checked": len(invoices),
    }


def _forecast_availability(db: Session, end: str) -> dict:
    count = int(db.scalar(select(func.count(func.distinct(Invoice.bill_date))).where(
        Invoice.status.in_(("issued", "paid")),
        Invoice.is_draft.is_(False),
        Invoice.bill_date <= end,
    )) or 0)
    if count < 90:
        reason = (
            f"Only {count} business date(s) contain invoice activity; at least 90 distinct "
            "sales dates are required before backtested forecasting is considered."
        )
        status = "insufficient_history"
    else:
        reason = "Forecasting is not enabled until a chronological baseline and backtest are implemented."
        status = "not_implemented"
    return {
        "status": status,
        "training_business_days": count,
        "minimum_business_days": 90,
        "reason": reason,
    }


def _insights(result: dict, data_quality: dict) -> list[dict]:
    insights = []
    comparison = result.get("comparison") or {}
    gross = next(
        (row for row in comparison.get("rows", []) if row["key"] == "gross_sales"),
        None,
    )
    if gross and gross["change_status"] != "no_activity":
        if gross["change_status"] == "new_activity":
            title = "Sales recorded after a zero-sales period"
            explanation = f"Gross sales were NPR {gross['current']:,.2f} in this period; the comparison period had no issued sales."
            severity = "info"
        elif gross["difference"] > 0:
            title = "Gross sales increased"
            explanation = f"Gross sales rose by NPR {gross['difference']:,.2f} ({gross['change']:.2f}%) compared with the previous period."
            severity = "info"
        elif gross["difference"] < 0:
            title = "Gross sales decreased"
            explanation = f"Gross sales fell by NPR {abs(gross['difference']):,.2f} ({abs(gross['change']):.2f}%) compared with the previous period."
            severity = "review"
        else:
            title = "Gross sales were unchanged"
            explanation = "Gross sales matched the previous period."
            severity = "info"
        insights.append({
            "title": title,
            "explanation": explanation,
            "severity": severity,
            "source_records": [],
            "recommended_action": "Review the sales trend and invoice detail if follow-up is needed.",
        })

    for finding in data_quality["findings"]:
        insights.append({
            "title": finding["issue"].replace("_", " ").title(),
            "explanation": (
                f"{finding['count']} record(s) need review. "
                f"{finding['recommended_action']}"
            ),
            "severity": finding["severity"],
            "source_records": finding["record_ids"],
            "recommended_action": finding["recommended_action"],
        })
    return insights
