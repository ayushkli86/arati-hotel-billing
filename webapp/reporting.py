"""Reporting and trend calculations for the Web App's SQLAlchemy data."""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from .models import (
    HotelSetting,
    Invoice,
    InvoiceItem,
    Payment,
    Refund,
    Room,
    Stay,
)
from .services import local_now


REPORTS = {
    "daily_sales": "Daily Sales Report",
    "daily_full": "Complete Daily Sales Report",
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

REPORT_COLUMNS = {
    "daily_sales": [
        ("date", "Business date"), ("invoices", "Invoices"),
        ("gross_sales", "Gross sales"), ("discount", "Discounts"),
        ("tax", "VAT"), ("service_charge", "Service charge"),
        ("net_sales", "Net sales"), ("collected", "Paid"),
        ("outstanding", "Outstanding"),
    ],
    "daily_full": [
        ("invoice_number", "Invoice no."), ("date", "Date"), ("time", "Time"),
        ("guest", "Guest"), ("phone", "Phone"), ("room", "Room"),
        ("cashier", "Cashier"), ("subtotal", "Subtotal"),
        ("discount", "Discount"), ("tax", "VAT"), ("total", "Total"),
        ("method", "Method"), ("paid", "Paid"), ("balance", "Balance"),
    ],
    "monthly_sales": [
        ("month", "Month"), ("invoices", "Invoices"),
        ("gross_sales", "Gross sales"), ("discount", "Discounts"),
        ("tax", "VAT"), ("net_sales", "Net sales"),
        ("collected", "Paid"), ("outstanding", "Outstanding"),
    ],
    "custom_range": [
        ("invoice_number", "Invoice no."), ("date", "Date"), ("time", "Time"),
        ("guest", "Guest"), ("room", "Room"), ("cashier", "Cashier"),
        ("subtotal", "Subtotal"), ("discount", "Discount"), ("tax", "VAT"),
        ("total", "Total"), ("method", "Method"), ("paid", "Paid"),
        ("balance", "Balance"),
    ],
    "payment_collection": [
        ("date", "Business date"), ("time", "Time"), ("invoice_number", "Invoice no."),
        ("guest", "Guest"), ("room", "Room"), ("method", "Method"),
        ("amount", "Amount"), ("note", "Note"),
    ],
    "outstanding_invoices": [
        ("invoice_number", "Invoice no."), ("date", "Issued"), ("guest", "Guest"),
        ("phone", "Phone"), ("room", "Room"), ("total", "Total"),
        ("paid", "Paid"), ("balance", "Balance"), ("age_days", "Age (days)"),
    ],
    "refunds_adjustments": [
        ("date", "Business date"), ("invoice_number", "Invoice no."),
        ("guest", "Guest"), ("room", "Room"), ("kind", "Type"),
        ("method", "Method"), ("amount", "Amount"), ("reason", "Reason"),
    ],
    "employee_sales": [
        ("cashier", "Cashier"), ("invoices", "Invoices"),
        ("gross_sales", "Gross sales"), ("collected", "Collected"),
        ("outstanding", "Outstanding"),
    ],
    "room_occupancy": [
        ("date", "Business date"), ("sellable", "Sellable rooms"),
        ("occupied_end", "Occupied at day end"), ("occupied_across", "Occupied during day"),
        ("available", "Available now"), ("nights", "Occupied nights"),
        ("rate", "Occupancy %"),
    ],
    "room_revenue": [
        ("invoice_number", "Invoice no."), ("date", "Date"), ("guest", "Guest"),
        ("room", "Room"), ("nights", "Nights"), ("cashier", "Cashier"),
        ("revenue", "Room revenue"),
    ],
    "operations_summary": [
        ("metric", "Measure"), ("value", "Value"), ("note", "How it is measured"),
    ],
}

FORMULAS = {
    "gross_sales": "Gross sales = invoice totals for issued, non-void invoices dated in the period.",
    "net_sales": "Net sales = gross sales − refunds and reversals posted in the period.",
    "collections": "Payments received = payment ledger rows dated when cash changed hands.",
    "outstanding": "Outstanding = current balance of issued invoices dated on or before period end.",
    "occupancy": "Occupancy rate = occupied rooms ÷ active room inventory × 100.",
    "room_revenue": "Room revenue = room-category line value after line and allocated invoice discounts.",
    "collection_ratio": "Collection ratio = payments received ÷ gross sales × 100.",
    "discount_ratio": "Discount ratio = discounts ÷ invoice subtotals × 100.",
    "growth": "Period change = (current value − prior value) ÷ prior value × 100.",
}

_ISSUED = ("issued", "paid")
_MONEY_FIELDS = (
    "gross_sales", "net_sales", "discount", "tax", "service_charge",
    "collected", "outstanding", "room_revenue",
)


def validate_period(start: str, end: str, *, max_days: int = 366) -> tuple[date, date]:
    try:
        first, last = date.fromisoformat(start), date.fromisoformat(end)
    except (TypeError, ValueError) as exc:
        raise ValueError("Dates must use YYYY-MM-DD format.") from exc
    if last < first:
        raise ValueError("The end date cannot be before the start date.")
    if (last - first).days + 1 > max_days:
        raise ValueError(f"Choose a period of {max_days} days or fewer.")
    return first, last


def _money(value: object) -> float:
    try:
        return round(float(value or 0), 2)
    except (TypeError, ValueError):
        return 0.0


def _sum(rows: list, key: str) -> float:
    return _money(sum((Decimal(str(row.get(key) or 0)) for row in rows), Decimal("0")))


def _invoice_date(invoice: Invoice) -> str:
    return invoice.bill_date or invoice.issue_date.date().isoformat()


def _invoice_rows(db: Session, start: str, end: str, filters: dict) -> list[Invoice]:
    query = select(Invoice).where(
        Invoice.status.in_(_ISSUED),
        Invoice.bill_date.between(start, end),
        # Running folios (draft invoices) are not issued sales until finalized.
        Invoice.is_draft.is_(False),
        Invoice.invoice_number.notlike("DRAFT-%"),
    )
    employee = (filters.get("employee") or "").strip()
    method = (filters.get("payment_method") or "").strip()
    room_number = (filters.get("room_no") or "").strip()
    invoice_number = (filters.get("invoice_no") or "").strip()
    kind = (filters.get("transaction_type") or "").strip()
    if employee and employee != "All":
        query = query.where(Invoice.prepared_by == employee)
    if method and method != "All":
        query = query.where(Invoice.payment_method == method)
    if room_number:
        query = query.where(Invoice.room_number == room_number)
    if invoice_number:
        query = query.where(Invoice.invoice_number.ilike(f"%{invoice_number}%"))
    if kind == "Room":
        query = query.where(Invoice.room_number != "")
    elif kind == "Non-room":
        query = query.where(or_(Invoice.room_number == "", Invoice.room_number.is_(None)))
    return list(db.scalars(query.order_by(Invoice.bill_date, Invoice.issue_date, Invoice.id)))


def _invoice_dict(invoice: Invoice) -> dict:
    return {
        "invoice_number": invoice.invoice_number,
        "date": _invoice_date(invoice),
        "time": invoice.issue_date.strftime("%H:%M:%S"),
        "guest": invoice.guest_name or "Walk-in guest",
        "phone": invoice.guest_phone,
        "room": invoice.room_number or "",
        "cashier": invoice.prepared_by or "",
        "method": invoice.payment_method,
        "subtotal": _money(invoice.subtotal),
        "discount": round(_money(invoice.discount_amount) + _money(invoice.item_discount), 2),
        "tax": _money(invoice.vat_amount),
        "service_charge": _money(invoice.service_charge),
        "net_sales": _money(invoice.net_subtotal),
        "total": _money(invoice.total),
        "paid": _money(invoice.paid_amount),
        "balance": _money(invoice.balance),
    }


def _payments(
    db: Session, start: str, end: str, filters: dict | None = None
) -> list[dict]:
    filters = filters or {}
    query = select(Payment, Invoice).outerjoin(Invoice, Payment.invoice_id == Invoice.id).where(
        Payment.business_date.between(start, end)
    )
    method = (filters.get("payment_method") or "").strip()
    employee = (filters.get("employee") or "").strip()
    invoice_number = (filters.get("invoice_no") or "").strip()
    if method and method != "All":
        query = query.where(Payment.method == method)
    if employee and employee != "All":
        query = query.where(Invoice.prepared_by == employee)
    if invoice_number:
        query = query.where(Payment.invoice_number.ilike(f"%{invoice_number}%"))
    result = []
    for payment, invoice in db.execute(query.order_by(Payment.business_date, Payment.paid_at, Payment.id)):
        result.append({
            "date": payment.business_date,
            "time": payment.paid_at.strftime("%H:%M:%S") if payment.paid_at else "",
            "invoice_number": payment.invoice_number or (invoice.invoice_number if invoice else ""),
            "guest": (invoice.guest_name if invoice else "") or "Walk-in guest",
            "room": (invoice.room_number if invoice else "") or "",
            "method": payment.method,
            "amount": _money(payment.amount),
            "note": payment.note or "",
            "cashier": (invoice.prepared_by if invoice else "") or payment.received_by,
        })
    return result


def _refund_rows(
    db: Session, start: str, end: str, filters: dict | None = None
) -> list[dict]:
    filters = filters or {}
    query = select(Refund, Invoice).outerjoin(Invoice, Refund.invoice_id == Invoice.id).where(
        Refund.business_date.between(start, end)
    )
    invoice_number = (filters.get("invoice_no") or "").strip()
    method = (filters.get("payment_method") or "").strip()
    kind = (filters.get("transaction_type") or "").strip()
    employee = (filters.get("employee") or "").strip()
    if invoice_number:
        query = query.where(Refund.invoice_number.ilike(f"%{invoice_number}%"))
    if method and method != "All":
        query = query.where(Refund.method == method)
    if kind in {"Refund", "Adjustment"}:
        query = query.where(Refund.kind == kind.lower())
    if employee and employee != "All":
        query = query.where(Invoice.prepared_by == employee)
    return [{
        "date": entry.business_date,
        "invoice_number": entry.invoice_number,
        "guest": (invoice.guest_name if invoice else "") or "Walk-in guest",
        "room": (invoice.room_number if invoice else "") or "",
        "kind": "Refund" if entry.kind == "refund" else "Adjustment",
        "method": entry.method,
        "amount": _money(entry.amount),
        "reason": entry.reason,
        "cashier": (invoice.prepared_by if invoice else "") or "",
    } for entry, invoice in db.execute(
        query.order_by(Refund.business_date, Refund.refunded_at, Refund.id)
    )]


def _occupancy_for_day(db: Session, day: date) -> dict:
    rooms = list(db.scalars(select(Room).where(Room.active.is_(True))))
    stays = list(db.scalars(select(Stay).where(
        Stay.check_in < datetime.combine(day + timedelta(days=1), datetime.min.time()),
        or_(Stay.check_out.is_(None), Stay.check_out >= datetime.combine(day, datetime.min.time())),
        Stay.status.in_(("checked_in", "checked_out")),
    )))
    end_of_day = sum(
        1 for stay in stays
        if stay.check_in.date() <= day and (stay.check_out is None or stay.check_out.date() > day)
    )
    across = sum(
        1 for stay in stays
        if stay.check_in.date() <= day and (stay.check_out is None or stay.check_out.date() >= day)
    )
    active_rooms = len(rooms)
    status_counts = defaultdict(int)
    for room in rooms:
        status_counts[room.status] += 1
    available = status_counts["available"]
    return {
        "sellable": active_rooms,
        "occupied_end": end_of_day,
        "occupied_across": across,
        "available": available,
        "nights": sum(max(0, int(stay.nights or 0)) for stay in stays),
        "rate": round(across / active_rooms * 100, 2) if active_rooms else 0.0,
        "status_counts": dict(status_counts),
    }


def _room_revenue_by_invoice(
    db: Session, start: str, end: str, filters: dict | None = None
) -> tuple[list[dict], dict[str, float]]:
    invoices = _invoice_rows(db, start, end, filters or {})
    invoice_ids = [invoice.id for invoice in invoices]
    if not invoice_ids:
        return [], {}
    line_rows = list(db.scalars(select(InvoiceItem).where(
        InvoiceItem.invoice_id.in_(invoice_ids)
    ).order_by(InvoiceItem.invoice_id, InvoiceItem.id)))
    grouped: dict[int, list[InvoiceItem]] = defaultdict(list)
    for line in line_rows:
        grouped[line.invoice_id].append(line)
    rows = []
    by_room: dict[str, float] = defaultdict(float)
    for invoice in invoices:
        lines = grouped[invoice.id]
        bases = [
            max(Decimal("0"), Decimal(line.quantity or 0) * Decimal(line.rate or 0) - Decimal(line.discount_amount or 0))
            for line in lines
        ]
        total_base = sum(bases, Decimal("0"))
        bill_discount = min(Decimal(invoice.discount_amount or 0), total_base)
        room_base = sum(
            (base for line, base in zip(lines, bases) if line.category == "room"),
            Decimal("0"),
        )
        room_nights = sum(
            (Decimal(line.quantity or 0) for line in lines if line.category == "room"),
            Decimal("0"),
        )
        room_discount = bill_discount * room_base / total_base if total_base else Decimal("0")
        revenue = _money(room_base - room_discount)
        if revenue <= 0:
            continue
        room = invoice.room_number or "—"
        by_room[room] += revenue
        rows.append({
            "invoice_number": invoice.invoice_number,
            "date": _invoice_date(invoice),
            "guest": invoice.guest_name or "Walk-in guest",
            "room": room,
            "nights": int(room_nights),
            "cashier": invoice.prepared_by or "",
            "revenue": revenue,
        })
    return rows, {key: round(value, 2) for key, value in by_room.items()}


def _category_revenue(db: Session, invoices: list[Invoice]) -> dict[str, float]:
    if not invoices:
        return {}
    totals: dict[str, Decimal] = defaultdict(Decimal)
    lines = db.scalars(select(InvoiceItem).where(
        InvoiceItem.invoice_id.in_([invoice.id for invoice in invoices])
    ))
    for line in lines:
        base = max(
            Decimal("0"),
            Decimal(line.quantity or 0) * Decimal(line.rate or 0)
            - Decimal(line.discount_amount or 0),
        )
        totals[line.category] += base
    return {category: _money(amount) for category, amount in totals.items()}


def _totals(invoices: list[Invoice]) -> dict:
    mapped = [_invoice_dict(invoice) for invoice in invoices]
    return {
        "invoices": len(invoices),
        "gross_sales": _sum(mapped, "total"),
        "discount": _sum(mapped, "discount"),
        "tax": _sum(mapped, "tax"),
        "service_charge": _sum(mapped, "service_charge"),
        "net_sales": _sum(mapped, "net_sales"),
        "collected": _sum(mapped, "paid"),
        "outstanding": _sum(mapped, "balance"),
    }


def build_report(
    db: Session, key: str, start: str, end: str, filters: dict | None = None
) -> dict:
    validate_period(start, end)
    if key not in REPORTS:
        raise ValueError("Choose a valid report.")
    filters = filters or {}
    invoices = _invoice_rows(db, start, end, filters)
    invoice_rows = [_invoice_dict(invoice) for invoice in invoices]
    totals = _totals(invoices)
    rows: list[dict]
    formulas = [FORMULAS["gross_sales"], FORMULAS["net_sales"]]
    if key in {"daily_sales", "monthly_sales"}:
        grouped: dict[str, list[dict]] = defaultdict(list)
        for row in invoice_rows:
            grouped[row["date"] if key == "daily_sales" else row["date"][:7]].append(row)
        if key == "daily_sales":
            first, last = validate_period(start, end)
            labels = [(first + timedelta(days=n)).isoformat() for n in range((last - first).days + 1)]
        else:
            labels = sorted(grouped)
        rows = [{
            "date" if key == "daily_sales" else "month": label,
            "invoices": len(grouped[label]),
            "gross_sales": _sum(grouped[label], "total"),
            "discount": _sum(grouped[label], "discount"),
            "tax": _sum(grouped[label], "tax"),
            "service_charge": _sum(grouped[label], "service_charge"),
            "net_sales": _sum(grouped[label], "net_sales"),
            "collected": _sum(grouped[label], "paid"),
            "outstanding": _sum(grouped[label], "balance"),
        } for label in labels]
        if key == "daily_sales":
            totals["invoices"] = len(invoices)
        formulas.append("Voided and draft invoices are excluded.")
    elif key == "daily_full":
        rows = invoice_rows
        payments = _payments(db, start, end, filters)
        refunds = _refund_rows(db, start, end, filters)
        by_method: dict[str, float] = defaultdict(float)
        for payment in payments:
            by_method[payment["method"]] += payment["amount"]
        totals.update({
            "transactions": len(rows),
            "collected": _sum(payments, "amount"),
            "payments_entries": len(payments),
            "refunds": _sum([row for row in refunds if row["kind"] == "Refund"], "amount"),
            "cash": round(by_method.get("Cash", 0.0), 2),
            "card": round(sum(v for m, v in by_method.items() if m == "Card"), 2),
            "digital": round(sum(v for m, v in by_method.items() if m not in ("Cash", "Card")), 2),
            "by_method": {method: round(amount, 2) for method, amount in sorted(by_method.items())},
            "room_revenue": _sum(
                _room_revenue_by_invoice(db, start, end)[0], "revenue"
            ),
        })
        formulas = [
            FORMULAS["gross_sales"], FORMULAS["collections"],
            FORMULAS["outstanding"], "Voided and draft invoices are excluded.",
        ]
    elif key == "custom_range":
        refunds = _refund_rows(db, start, end, filters)
        rows = invoice_rows
        totals.update({
            "refunds": _sum(refunds, "amount"),
            "net_ledger_sales": round(totals["gross_sales"] - _sum(refunds, "amount"), 2),
        })
    elif key == "payment_collection":
        rows = _payments(db, start, end, filters)
        by_method: dict[str, float] = defaultdict(float)
        for row in rows:
            by_method[row["method"]] += row["amount"]
        totals = {
            "entries": len(rows),
            "collected": _sum(rows, "amount"),
            "by_method": {method: round(amount, 2) for method, amount in by_method.items()},
        }
        formulas = [FORMULAS["collections"]]
    elif key == "outstanding_invoices":
        query = select(Invoice).where(
            Invoice.status.in_(_ISSUED), Invoice.bill_date <= end, Invoice.balance > 0,
            Invoice.is_draft.is_(False), Invoice.invoice_number.notlike("DRAFT-%"),
        )
        employee = (filters.get("employee") or "").strip()
        method = (filters.get("payment_method") or "").strip()
        room_number = (filters.get("room_no") or "").strip()
        invoice_number = (filters.get("invoice_no") or "").strip()
        if employee and employee != "All":
            query = query.where(Invoice.prepared_by == employee)
        if method and method != "All":
            query = query.where(Invoice.payment_method == method)
        if room_number:
            query = query.where(Invoice.room_number == room_number)
        if invoice_number:
            query = query.where(Invoice.invoice_number.ilike(f"%{invoice_number}%"))
        rows = []
        for invoice in db.scalars(query.order_by(Invoice.bill_date, Invoice.invoice_number)):
            record = _invoice_dict(invoice)
            try:
                age = max(0, (date.fromisoformat(end) - date.fromisoformat(record["date"])).days)
            except ValueError:
                age = 0
            rows.append({**record, "age_days": age})
        totals = {
            "invoices": len(rows), "total": _sum(rows, "total"),
            "paid": _sum(rows, "paid"), "balance": _sum(rows, "balance"),
        }
        formulas = [FORMULAS["outstanding"]]
    elif key == "refunds_adjustments":
        rows = _refund_rows(db, start, end, filters)
        totals = {
            "entries": len(rows),
            "refunds": _sum([row for row in rows if row["kind"] == "Refund"], "amount"),
            "adjustments": _sum([row for row in rows if row["kind"] == "Adjustment"], "amount"),
            "total": _sum(rows, "amount"),
        }
    elif key == "employee_sales":
        groups: dict[str, list[dict]] = defaultdict(list)
        for row in invoice_rows:
            groups[row["cashier"] or "Unassigned"].append(row)
        payment_rows = _payments(db, start, end, filters)
        payment_totals: dict[str, float] = defaultdict(float)
        for payment in payment_rows:
            payment_totals[payment["cashier"] or "Unassigned"] += payment["amount"]
        rows = [{
            "cashier": cashier, "invoices": len(records),
            "gross_sales": _sum(records, "total"),
            "collected": round(payment_totals[cashier], 2),
            "outstanding": _sum(records, "balance"),
        } for cashier, records in sorted(groups.items())]
    elif key == "room_occupancy":
        first, last = validate_period(start, end)
        rows = []
        for offset in range((last - first).days + 1):
            day = first + timedelta(days=offset)
            occupancy = _occupancy_for_day(db, day)
            rows.append({"date": day.isoformat(), **occupancy})
        today = _occupancy_for_day(db, local_now().date())
        totals = {
            "sellable": today["sellable"], "occupied_end": today["occupied_end"],
            "occupied_across": today["occupied_across"], "available": today["available"],
            "occupancy_rate": today["rate"],
        }
        formulas = [FORMULAS["occupancy"], "Historical room maintenance and blocked inventory snapshots are not stored."]
    elif key == "room_revenue":
        rows, by_room = _room_revenue_by_invoice(db, start, end, filters)
        revenue = _sum(rows, "revenue")
        totals = {
            "total": revenue, "invoices": len(rows), "by_room": by_room,
            "average": round(revenue / len(rows), 2) if rows else 0.0,
        }
        formulas = [FORMULAS["room_revenue"]]
    else:
        payments = _payments(db, start, end)
        refunds = _refund_rows(db, start, end)
        occupancy = _occupancy_for_day(db, date.fromisoformat(end))
        room_rows, _ = _room_revenue_by_invoice(db, start, end)
        room_total = _sum(room_rows, "revenue")
        by_category = _category_revenue(db, invoices)
        cash_collected = _sum([row for row in payments if row["method"] == "Cash"], "amount")
        cash_refunds = _sum([
            row for row in refunds if row["kind"] == "Refund" and row["method"] == "Cash"
        ], "amount")
        setting = db.get(HotelSetting, "cash_opening_balance")
        opening = _money(setting.value if setting else 0)
        prior_cash = db.scalar(select(func.coalesce(func.sum(Payment.amount), 0)).where(
            Payment.business_date < start, Payment.method == "Cash"
        )) or 0
        prior_refunds = db.scalar(select(func.coalesce(func.sum(Refund.amount), 0)).where(
            Refund.business_date < start, Refund.method == "Cash", Refund.kind == "refund"
        )) or 0
        opening += _money(prior_cash) - _money(prior_refunds)
        gross = totals["gross_sales"]
        collected = _sum(payments, "amount")
        refunded = _sum([row for row in refunds if row["kind"] == "Refund"], "amount")
        adjustment = _sum([row for row in refunds if row["kind"] == "Adjustment"], "amount")
        totals = {
            "invoices": len(invoices), **totals, "collected": collected,
            "cash_collected": cash_collected, "refunds": refunded,
            "adjustments": adjustment, "opening_cash": opening,
            "closing_cash": round(opening + cash_collected - cash_refunds, 2),
            "room_revenue": room_total,
            "other_revenue": round(sum(by_category.get(c, 0) for c in ("food", "service", "other")), 2),
            "occupied_rooms": occupancy["occupied_across"],
            "available_rooms": occupancy["available"],
            "sellable_rooms": occupancy["sellable"],
            "occupancy_rate": occupancy["rate"],
            "average_invoice": round(gross / len(invoices), 2) if invoices else 0.0,
        }
        rows = [
            {"metric": label, "value": value, "note": note}
            for label, value, note in (
                ("Gross sales", gross, "Invoiced in the period"),
                ("Discounts", totals["discount"], "Invoice and line discounts"),
                ("VAT", totals["tax"], "VAT charged"),
                ("Service charge", totals["service_charge"], "Hotel service charge"),
                ("Payments received", collected, "Payments by business date"),
                ("Cash collections", cash_collected, "Cash method only"),
                ("Refunds", refunded, "Money returned"),
                ("Adjustments", adjustment, "Authorised balance corrections"),
                ("Outstanding receivables", totals["outstanding"], "Current invoice balances"),
                ("Opening cash", opening, "Configured opening balance plus prior net cash"),
                ("Closing cash", totals["closing_cash"], "Opening + cash collected − cash refunds"),
                ("Room revenue", room_total, "Room line revenue after discounts"),
                ("Other revenue", totals["other_revenue"], "Food, service, and other lines"),
                ("Occupied rooms", occupancy["occupied_across"], "Occupied during selected period end"),
                ("Available rooms", occupancy["available"], "Available currently"),
                ("Occupancy rate", occupancy["rate"], "Occupied rooms ÷ active inventory"),
            )
        ]
        formulas = [FORMULAS["gross_sales"], FORMULAS["collections"], FORMULAS["outstanding"], FORMULAS["occupancy"]]

    return {
        "key": key,
        "title": REPORTS[key],
        "subtitle": f"Business dates {start} to {end}",
        "period": f"{start} – {end}",
        "generated_at": local_now().strftime("%Y-%m-%d %H:%M:%S"),
        "columns": REPORT_COLUMNS[key],
        "rows": rows,
        "totals": totals,
        "formulas": formulas,
        "empty_message": "No transactions recorded for this period.",
    }


def daily_close_sections(db: Session, day: str) -> dict:
    """Every ledger slice available for one business date, for the daily-close PDF."""
    first, last = validate_period(day, day)
    invoices = _invoice_rows(db, day, day, {})
    invoice_rows = [_invoice_dict(invoice) for invoice in invoices]
    invoice_ids = [invoice.id for invoice in invoices]
    numbers = {invoice.id: invoice.invoice_number for invoice in invoices}
    guest_names = {invoice.id: invoice.guest_name for invoice in invoices}
    guests = sorted({row["guest"] for row in invoice_rows if row["guest"]})

    lines: list[InvoiceItem] = []
    if invoice_ids:
        lines = list(db.scalars(select(InvoiceItem).where(
            InvoiceItem.invoice_id.in_(invoice_ids)
        ).order_by(InvoiceItem.invoice_id, InvoiceItem.id)))

    line_rows = [{
        "invoice": numbers.get(line.invoice_id) or f"#{line.invoice_id}",
        "guest": guest_names.get(line.invoice_id, "") or "Walk-in guest",
        "description": line.description or "",
        "category": line.category or "other",
        "qty": _money(line.quantity),
        "price": _money(line.rate),
        "discount": _money(line.discount_amount),
        "vat": _money(line.vat_amount),
        "amount": _money(line.amount),
    } for line in lines]

    categories: dict[str, dict] = {}
    items: dict[tuple[str, str], dict] = {}
    for row in line_rows:
        base = max(0.0, row["qty"] * row["price"] - row["discount"])
        category = categories.setdefault(row["category"], {
            "label": row["category"], "qty": 0.0, "net_sales": 0.0, "vat": 0.0, "amount": 0.0,
        })
        category["qty"] += row["qty"]
        category["net_sales"] += base
        category["vat"] += row["vat"]
        category["amount"] += row["amount"]
        key = (row["description"], row["category"])
        entry = items.setdefault(key, {
            "label": row["description"], "category": row["category"],
            "qty": 0.0, "net_sales": 0.0, "amount": 0.0,
        })
        entry["qty"] += row["qty"]
        entry["net_sales"] += base
        entry["amount"] += row["amount"]
    category_rows = sorted(categories.values(), key=lambda row: -row["amount"])
    for row in category_rows:
        row["net_sales"] = round(row["net_sales"], 2)
        row["vat"] = round(row["vat"], 2)
        row["amount"] = round(row["amount"], 2)
    item_rows = sorted(items.values(), key=lambda row: -row["amount"])[:25]
    for row in item_rows:
        row["net_sales"] = round(row["net_sales"], 2)
        row["amount"] = round(row["amount"], 2)

    payments = _payments(db, day, day)
    payment_by_cashier: dict[str, float] = defaultdict(float)
    for row in payments:
        payment_by_cashier[row["cashier"] or "Unassigned"] += row["amount"]
    cashiers: dict[str, dict] = defaultdict(lambda: {"cashier": "", "invoices": 0, "gross_sales": 0.0, "collected": 0.0, "outstanding": 0.0})
    for row in invoice_rows:
        name = row["cashier"] or "Unassigned"
        cashiers[name]["cashier"] = name
        cashiers[name]["invoices"] += 1
        cashiers[name]["gross_sales"] += row["total"]
        cashiers[name]["outstanding"] += row["balance"]
    for name, group in cashiers.items():
        group["collected"] = round(payment_by_cashier[name], 2)
        group["gross_sales"] = round(group["gross_sales"], 2)
        group["outstanding"] = round(group["outstanding"], 2)
    cashier_rows = sorted(cashiers.values(), key=lambda row: -row["gross_sales"])

    _room_rows, room_by_room = _room_revenue_by_invoice(db, day, day)
    room_rows = [{"room": room, "revenue": round(amount, 2)} for room, amount in room_by_room.items()]
    room_rows = sorted(room_rows, key=lambda row: -row["revenue"])

    refunds = _refund_rows(db, day, day)

    folio_rows = [{
        "invoice": folio.invoice_number,
        "guest": folio.guest_name or "Walk-in guest",
        "room": folio.room_number or "",
        "opened": (folio.created_at or folio.issue_date).strftime("%Y-%m-%d %H:%M") if (folio.created_at or folio.issue_date) else "",
        "paid": _money(folio.paid_amount),
        "balance": _money(folio.balance),
    } for folio in db.scalars(select(Invoice).where(
        Invoice.status.in_(_ISSUED),
        or_(Invoice.is_draft.is_(True), Invoice.invoice_number.like("DRAFT-%")),
        Invoice.bill_date <= day,
    ).order_by(Invoice.bill_date, Invoice.id))]

    occupancy = _occupancy_for_day(db, last)

    return {
        "day": day,
        "guests": guests,
        "guest_count": len(guests),
        "categories": category_rows,
        "items_sold": item_rows,
        "lines": line_rows,
        "cashiers": cashier_rows,
        "rooms": room_rows,
        "payments": payments,
        "refunds": refunds,
        "folios": folio_rows,
        "occupancy": occupancy,
    }


def dashboard_cards(db: Session, day: str) -> dict:
    report = build_report(db, "operations_summary", day, day)
    totals = report["totals"]
    occupancy = _occupancy_for_day(db, date.fromisoformat(day))
    return {
        "business_date": day,
        "gross_sales": totals["gross_sales"],
        "net_sales": totals["net_sales"],
        "collected": totals["collected"],
        "cash_collected": totals["cash_collected"],
        "outstanding": totals["outstanding"],
        "room_revenue": totals["room_revenue"],
        "invoices": totals["invoices"],
        "occupied_rooms": occupancy["occupied_across"],
        "available_rooms": occupancy["available"],
        "sellable_rooms": occupancy["sellable"],
        "occupancy_rate": occupancy["rate"],
        "average_invoice": totals["average_invoice"],
    }


def analysis_data(
    db: Session,
    start: str,
    end: str,
    bucket: str = "day",
    compare_start: str = "",
    compare_end: str = "",
) -> dict:
    first, last = validate_period(start, end)
    if bucket not in {"day", "week", "month"}:
        raise ValueError("Choose day, week, or month buckets.")
    invoices = _invoice_rows(db, start, end, {})
    invoice_rows = [_invoice_dict(invoice) for invoice in invoices]
    payments = _payments(db, start, end)
    refunds = _refund_rows(db, start, end)
    gross = _sum(invoice_rows, "total")
    collected = _sum(payments, "amount")
    refunded = _sum([row for row in refunds if row["kind"] == "Refund"], "amount")
    subtotal = _sum(invoice_rows, "subtotal")
    discount = _sum(invoice_rows, "discount")
    outstanding = _sum([
        _invoice_dict(invoice)
        for invoice in db.scalars(select(Invoice).where(
            Invoice.status.in_(_ISSUED), Invoice.bill_date <= end, Invoice.balance > 0,
            Invoice.is_draft.is_(False), Invoice.invoice_number.notlike("DRAFT-%"),
        ))
    ], "balance")
    room_rows, by_room = _room_revenue_by_invoice(db, start, end)
    room_revenue = _sum(room_rows, "revenue")
    room_invoices = len(room_rows)
    occupancy = _occupancy_for_day(db, last)
    current_values = {
        "gross_sales": gross,
        "net_sales": round(gross - refunded, 2),
        "transactions": len(invoices),
        "average_invoice": round(gross / len(invoices), 2) if invoices else 0.0,
        "collected": collected,
        "collection_ratio": round(collected / gross * 100, 2) if gross else 0.0,
        "discount_ratio": round(discount / subtotal * 100, 2) if subtotal else 0.0,
        "refunds": refunded,
        "outstanding": outstanding,
        "occupancy_rate": occupancy["rate"],
        "occupied_end_of_day": occupancy["occupied_end"],
        "occupied_across_day": occupancy["occupied_across"],
        "room_revenue": room_revenue,
        "average_room_revenue": round(room_revenue / room_invoices, 2) if room_invoices else 0.0,
    }
    labels = {
        "gross_sales": ("Gross sales", "amount"),
        "net_sales": ("Net sales", "amount"),
        "transactions": ("Transactions", "count"),
        "average_invoice": ("Average invoice value", "amount"),
        "collected": ("Payments received", "amount"),
        "collection_ratio": ("Collection ratio", "percent"),
        "discount_ratio": ("Discount ratio", "percent"),
        "refunds": ("Refunds and reversals", "amount"),
        "outstanding": ("Outstanding receivables", "amount"),
        "occupancy_rate": ("Room occupancy rate", "percent"),
        "occupied_end_of_day": ("Occupied at end of day", "count"),
        "occupied_across_day": ("Occupied during the day", "count"),
        "room_revenue": ("Room revenue", "amount"),
        "average_room_revenue": ("Average room revenue", "amount"),
    }
    metrics = [{
        "key": key, "label": label, "unit": unit, "value": current_values[key],
        "formula": {
            "gross_sales": FORMULAS["gross_sales"],
            "net_sales": FORMULAS["net_sales"],
            "collected": FORMULAS["collections"],
            "outstanding": FORMULAS["outstanding"],
            "occupancy_rate": FORMULAS["occupancy"],
            "room_revenue": FORMULAS["room_revenue"],
        }.get(key, ""),
    } for key, (label, unit) in labels.items()]

    def bucket_key(raw_day: str) -> str:
        current = date.fromisoformat(raw_day[:10])
        if bucket == "month":
            return current.strftime("%Y-%m")
        if bucket == "week":
            year, week, _ = current.isocalendar()
            return f"{year}-W{week:02d}"
        return current.isoformat()

    sales: dict[str, float] = defaultdict(float)
    collections: dict[str, float] = defaultdict(float)
    refund_trend: dict[str, float] = defaultdict(float)
    discount_trend: dict[str, float] = defaultdict(float)
    for row in invoice_rows:
        key = bucket_key(row["date"])
        sales[key] += row["total"]
        discount_trend[key] += row["discount"]
    for row in payments:
        collections[bucket_key(row["date"])] += row["amount"]
    for row in refunds:
        refund_trend[bucket_key(row["date"])] += row["amount"]

    categories: dict[str, float] = defaultdict(float)
    room_groups: dict[str, float] = defaultdict(float)
    employee_groups: dict[str, float] = defaultdict(float)
    if invoices:
        categories.update(_category_revenue(db, invoices))
        for row in invoice_rows:
            employee_groups[row["cashier"] or "Unassigned"] += row["total"]
    for name, amount in by_room.items():
        room_groups[name] = amount
    methods: dict[str, float] = defaultdict(float)
    for row in payments:
        methods[row["method"]] += row["amount"]

    def chart(label: str, values: dict[str, float]) -> dict:
        maximum = max(values.values(), default=0)
        return {
            "label": label,
            "points": [{
                "label": name,
                "value": round(value, 2),
                "width": max(2, round(value / maximum * 100)) if maximum else 2,
            } for name, value in sorted(values.items(), key=lambda item: item[0])],
        }

    comparison = None
    if compare_start or compare_end:
        cfirst, clast = validate_period(compare_start, compare_end)
        previous = analysis_data(db, compare_start, compare_end, bucket)
        comparison = {
            "current_period": (start, end),
            "previous_period": (compare_start, compare_end),
            "same_length": (last - first).days == (clast - cfirst).days,
            "rows": [],
        }
        previous_metrics = {metric["key"]: metric["value"] for metric in previous["metrics"]}
        for metric in metrics:
            before = previous_metrics.get(metric["key"], 0)
            change = round((metric["value"] - before) / abs(before) * 100, 2) if before else None
            comparison["rows"].append({
                **metric, "current": metric["value"], "previous": before,
                "difference": round(metric["value"] - before, 2),
                "change": change,
                "change_status": "computed" if before else ("new_activity" if metric["value"] else "no_activity"),
            })

    return {
        "period": (start, end),
        "bucket": bucket,
        "metrics": metrics,
        "charts": [
            {"key": "sales", **chart(f"Sales by {bucket}", sales)},
            {"key": "collections", **chart(f"Collections by {bucket}", collections)},
            {"key": "categories", **chart("Revenue by category", categories)},
            {"key": "methods", **chart("Collections by payment method", methods)},
            {"key": "rooms", **chart("Room revenue by room", room_groups)},
            {"key": "cashiers", **chart("Sales by cashier", employee_groups)},
            {"key": "refunds", **chart(f"Refunds by {bucket}", refund_trend)},
            {"key": "discounts", **chart(f"Discounts by {bucket}", discount_trend)},
        ],
        "comparison": comparison,
        "generated_at": local_now().strftime("%Y-%m-%d %H:%M:%S"),
        "formula_growth": FORMULAS["growth"],
    }
