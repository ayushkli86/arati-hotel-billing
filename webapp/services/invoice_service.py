from __future__ import annotations

import secrets
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import CatalogItem, Guest, Invoice, InvoiceItem, Room, Stay, utcnow
from ..money import Line, compute_totals
from .. import services as web_services


def money(val):
    try:
        if isinstance(val, Decimal):
            return val.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        return Decimal(str(val)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except Exception:
        return Decimal("0.00")


def local_now():
    return web_services.local_now()


BUSINESS_TZ = ZoneInfo("Asia/Kathmandu")


def get_business_date(dt: datetime | None = None) -> date:
    dt = dt or local_now()
    if getattr(dt, "tzinfo", None) is None:
        dt = dt.replace(tzinfo=BUSINESS_TZ)
    else:
        dt = dt.astimezone(BUSINESS_TZ)
    return dt.date()


def get_active_draft_for_stay(db: Session, stay_id: int) -> Invoice | None:
    return db.execute(
        select(Invoice)
        .where(Invoice.stay_id == stay_id, Invoice.is_draft == True)
        .order_by(Invoice.id.desc())
    ).scalars().first()


def get_or_create_draft_invoice(
    db: Session,
    *,
    guest_id: int,
    stay_id: int | None = None,
    room_id: int | None = None,
    user_id: int | None = None,
    settings: dict | None = None,
) -> Invoice:
    if stay_id is not None:
        existing = get_active_draft_for_stay(db, stay_id)
        if existing:
            return existing

    guest = db.get(Guest, guest_id)
    if not guest or not guest.active:
        raise ValueError("Active guest required for invoice")

    stay = db.get(Stay, stay_id) if stay_id else None
    room_obj = db.get(Room, room_id) if room_id else (db.get(Room, stay.room_id) if stay else None)

    settings = settings or {}
    vat_r = Decimal(str(settings.get("vat_rate", "13")))
    sc_r = Decimal(str(settings.get("service_charge_rate", "10")))

    temp_number = f"DRAFT-{secrets.token_hex(5).upper()}"
    inv = Invoice(
        invoice_number=temp_number,
        guest_id=guest.id,
        stay_id=stay.id if stay else None,
        room_id=(room_obj.id if room_obj else (stay.room_id if stay else None)),
        is_draft=True,
        status="issued",
        bill_type="tax",
        invoice_type="Tax Invoice",
        issue_date=local_now(),
        created_at=utcnow(),
        updated_at=utcnow(),
        user_id=user_id,
        guest_name=guest.full_name or guest.name or "",
        guest_phone=guest.phone or "",
        guest_address=guest.address or "",
        guest_pan=guest.pan_vat_number or "",
        customer_type=guest.customer_type or "individual",
        room_number=(stay.room_number if stay and stay.room_number else (room_obj.number if room_obj else "")),
        check_in=stay.check_in if stay else None,
        check_out=stay.check_out if stay else None,
        nights=stay.nights if stay else 1,
        vat_rate=vat_r,
        service_charge_rate=sc_r,
        subtotal=Decimal("0"),
        net_subtotal=Decimal("0"),
        taxable_net=Decimal("0"),
        discount_amount=Decimal("0"),
        item_discount=Decimal("0"),
        service_charge=Decimal("0"),
        vat_amount=Decimal("0"),
        total=Decimal("0"),
        paid_amount=Decimal("0"),
        balance=Decimal("0"),
        payment_method="Cash",
        payment_terms="Due on Check-out",
    )
    db.add(inv)
    db.flush()
    return inv


def add_item_to_draft(
    db: Session,
    *,
    invoice: Invoice,
    description: str,
    quantity: Decimal | float,
    rate: Decimal | float,
    catalog_item: CatalogItem | None = None,
    category: str = "food",
    unit: str = "pcs",
    taxable: bool = True,
    business_date: date | None = None,
    user_id: int | None = None,
) -> InvoiceItem:
    if not invoice.is_draft:
        raise ValueError("Cannot add items to a finalized invoice")

    qty = Decimal(str(quantity or 1))
    if qty <= 0:
        qty = Decimal("1")
    r = Decimal(str(rate or 0))
    bd = business_date or get_business_date()

    item = InvoiceItem(
        invoice_id=invoice.id,
        catalog_item_id=catalog_item.id if catalog_item else None,
        description=(description or "").strip(),
        quantity=qty,
        unit_price=r,
        rate=r,
        amount=qty * r,
        discount_amount=Decimal("0"),
        vat_amount=Decimal("0"),
        item_code=getattr(catalog_item, "code", "") or "",
        category=category or "food",
        unit=unit or "pcs",
        taxable=bool(taxable),
        business_date=bd,
        added_by_id=user_id,
        added_at=utcnow(),
    )
    db.add(item)
    db.flush()
    recalc_invoice_totals(db, invoice)
    return item


def recalc_invoice_totals(db: Session, invoice: Invoice, settings: dict | None = None):
    db.refresh(invoice, attribute_names=["items"])
    lines = []
    for it in invoice.items:
        lines.append(
            Line(
                description=it.description or "Item",
                qty=float(it.quantity or 0),
                unit_price=float(it.rate or it.unit_price or 0),
                discount=float(it.discount_amount or 0),
                taxable=bool(it.taxable),
                category=it.category or "food",
                unit=it.unit or "pcs",
            )
        )
    s = settings or {}
    vat_rate = float(invoice.vat_rate if invoice.vat_rate is not None else s.get("vat_rate", 13))
    sc_rate = float(invoice.service_charge_rate if invoice.service_charge_rate is not None else s.get("service_charge_rate", 10))
    disc = float(invoice.discount_amount or 0)
    paid = float(invoice.paid_amount or 0)

    totals = compute_totals(lines, discount=disc, vat_rate=vat_rate, service_charge_rate=sc_rate, paid=paid)

    invoice.subtotal = money(totals.subtotal)
    invoice.item_discount = money(totals.item_discount)
    invoice.net_subtotal = money(totals.net_subtotal)
    invoice.taxable_net = money(totals.taxable_net)
    invoice.service_charge = money(totals.service_charge)
    invoice.vat_amount = money(totals.vat)
    invoice.total = money(totals.total)
    invoice.balance = money((invoice.total or Decimal("0")) - (invoice.paid_amount or Decimal("0")))
    invoice.updated_at = utcnow()
    db.flush()


def finalize_invoice(db: Session, invoice_id: int, prefix: str, user_id: int | None = None) -> Invoice:
    invoice = db.get(Invoice, invoice_id)
    if not invoice:
        raise ValueError("Invoice not found")
    if not invoice.is_draft:
        raise ValueError("Invoice already finalized")
    if not invoice.guest_id:
        raise ValueError("Invoice must be linked to a guest before finalizing")
    if not invoice.items:
        raise ValueError("Cannot finalize an empty running folio")

    from ..models import Invoice as InvoiceModel

    count = db.query(InvoiceModel).filter(InvoiceModel.invoice_number != "").count() + 1
    candidate = f"{prefix}{count:06d}"
    existing_numbers = {
        row for row in db.scalars(select(InvoiceModel.invoice_number))
    }
    while candidate in existing_numbers:
        count += 1
        candidate = f"{prefix}{count:06d}"
    invoice.invoice_number = candidate
    invoice.is_draft = False
    invoice.issue_date = invoice.issue_date or local_now()
    invoice.copy_label = invoice.copy_label or "Customer Copy"

    bal = (invoice.total or Decimal("0")) - (invoice.paid_amount or Decimal("0"))
    if bal <= 0 and (invoice.total or Decimal("0")) > 0:
        invoice.status = "paid"
    elif (invoice.paid_amount or Decimal("0")) > 0 and bal > 0:
        invoice.status = "partial"
    else:
        invoice.status = "issued"

    invoice.balance = money(bal)
    invoice.updated_at = utcnow()
    if user_id and not invoice.user_id:
        invoice.user_id = user_id
    db.flush()
    return invoice
