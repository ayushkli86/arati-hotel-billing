"""Business date, invoice numbering, and money-safe billing operations."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .models import Invoice, InvoiceItem, Payment, Room, Stay, utcnow

BUSINESS_TZ = ZoneInfo("Asia/Kathmandu")


def local_now() -> datetime:
    return datetime.now(BUSINESS_TZ)


def money(value: float | Decimal | None) -> str:
    return f"NPR {float(value or 0):,.2f}"


def amount_in_words(value: float | Decimal | None) -> str:
    """Format an NPR amount using Nepal's lakh/crore numbering convention."""
    amount = Decimal(str(value or 0)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    rupees = int(amount)
    paisa = int((amount - rupees) * 100)
    ones = ("Zero", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine",
            "Ten", "Eleven", "Twelve", "Thirteen", "Fourteen", "Fifteen", "Sixteen",
            "Seventeen", "Eighteen", "Nineteen")
    tens = ("", "", "Twenty", "Thirty", "Forty", "Fifty", "Sixty", "Seventy", "Eighty", "Ninety")

    def under_thousand(number: int) -> str:
        parts = []
        if number >= 100:
            parts.extend((ones[number // 100], "Hundred"))
            number %= 100
        if number >= 20:
            parts.append(tens[number // 10])
            number %= 10
        if number:
            parts.append(ones[number])
        return " ".join(parts)

    if rupees == 0:
        words = "Zero"
    else:
        chunks = ((10_000_000, "Crore"), (100_000, "Lakh"), (1_000, "Thousand"), (1, ""))
        parts = []
        for divisor, label in chunks:
            count, rupees = divmod(rupees, divisor)
            if count:
                parts.extend((under_thousand(count), label) if label else (under_thousand(count),))
        words = " ".join(parts)
    result = f"{words} Rupees"
    if paisa:
        result += f" and {under_thousand(paisa)} Paisa"
    return result + " Only"


def next_invoice_number(db: Session, instant: datetime | None = None) -> str:
    day = (instant or local_now()).strftime("%Y%m%d")
    prefix = f"ARH-{day}-"
    count = db.scalar(select(func.count(Invoice.id)).where(Invoice.invoice_number.like(f"{prefix}%"))) or 0
    return f"{prefix}{count + 1:04d}"


def add_invoice(
    db: Session, *, guest_id: int, description: str, quantity: float, rate: float,
    room_id: int | None = None, stay_id: int | None = None,
) -> Invoice:
    amount = float((Decimal(str(quantity)) * Decimal(str(rate))).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
    invoice = Invoice(
        invoice_number=next_invoice_number(db), guest_id=guest_id, room_id=room_id,
        stay_id=stay_id, issue_date=utcnow(), total=amount, paid_amount=0,
        balance=amount, status="issued",
    )
    invoice.items.append(InvoiceItem(
        description=description.strip(), quantity=quantity, rate=rate, amount=amount,
    ))
    db.add(invoice)
    db.flush()
    return invoice


def collect_payment(
    db: Session, invoice: Invoice, amount: Decimal | float | str, method: str,
    username: str, user_id: int | None = None,
) -> None:
    try:
        value = Decimal(str(amount)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except InvalidOperation as exc:
        raise ValueError("Enter a valid payment amount.") from exc
    outstanding = Decimal(str(invoice.balance)).quantize(Decimal("0.01"))
    if not value.is_finite() or value <= 0 or value > outstanding:
        raise ValueError("Payment must be greater than zero and no more than the outstanding balance.")
    invoice.paid_amount = Decimal(str(invoice.paid_amount)) + value
    invoice.balance = outstanding - value
    if invoice.balance <= 0:
        invoice.balance = Decimal("0.00")
        invoice.status = "paid"
    now = datetime.now(timezone.utc)
    db.add(Payment(
        invoice=invoice, amount=value, method=method, received_by=username,
        invoice_number=invoice.invoice_number,
        business_date=now.astimezone(BUSINESS_TZ).date().isoformat(),
        paid_at=now.replace(tzinfo=None), user_id=user_id,
    ))
    # Completed checkout releases a room once its invoice has been settled.
    if invoice.balance == 0 and invoice.stay is not None and invoice.stay.status == "checked_out":
        invoice.stay.room.status = "dirty"
        invoice.stay.room.housekeeping_status = "dirty"
