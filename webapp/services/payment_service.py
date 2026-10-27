from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy.orm import Session

from ..models import Invoice, Payment, utcnow


def money(val):
    try:
        if isinstance(val, Decimal):
            return val.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        return Decimal(str(val)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except Exception:
        return Decimal("0.00")


def collect_payment(
    db: Session,
    *,
    invoice_id: int,
    amount: Decimal | float,
    method: str = "Cash",
    reference: str = "",
    received_by_id: int | None = None,
    notes: str = "",
) -> Payment:
    invoice = db.get(Invoice, invoice_id)
    if not invoice:
        raise ValueError("Invoice not found")
    if not invoice.guest_id:
        raise ValueError("Invoice has no linked guest")

    amt = Decimal(str(amount or 0))
    if amt <= 0:
        raise ValueError("Payment amount must be greater than 0")

    pay = Payment(
        invoice_id=invoice.id,
        amount=amt,
        method=(method or "Cash").strip(),
        note=(notes or "").strip(),
        paid_at=utcnow(),
        received_by=(str(received_by_id) if received_by_id else ""),
        invoice_number=invoice.invoice_number or "",
        business_date=invoice.bill_date or "",
        user_id=received_by_id,
    )
    db.add(pay)
    db.flush()

    invoice.paid_amount = (invoice.paid_amount or Decimal("0")) + amt
    invoice.balance = money((invoice.total or Decimal("0")) - invoice.paid_amount)
    invoice.updated_at = utcnow()

    if invoice.balance <= 0 and (invoice.total or Decimal("0")) > 0:
        invoice.status = "paid"
    elif (invoice.paid_amount or Decimal("0")) > 0 and invoice.balance > 0:
        invoice.status = "partial"
    else:
        if not invoice.is_draft:
            invoice.status = invoice.status or "issued"
        else:
            invoice.status = invoice.status or "issued"

    db.flush()
    return pay
