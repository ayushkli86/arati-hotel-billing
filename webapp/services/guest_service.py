from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import Guest, utcnow


def _normalize_phone(phone: str | None) -> str:
    if not phone:
        return ""
    p = phone.strip().replace(" ", "").replace("-", "").replace("+", "")
    return p


def _normalize_name(name: str | None) -> str:
    return (name or "").strip()


def get_guest_by_id(db: Session, guest_id: int) -> Guest | None:
    return db.get(Guest, guest_id)


def get_or_create_guest(
    db: Session,
    *,
    name: str = "",
    full_name: str = "",
    phone: str = "",
    email: str = "",
    address: str = "",
    pan_vat: str = "",
    id_type: str = "",
    id_number: str = "",
    customer_type: str = "individual",
    user_id: int | None = None,
) -> Guest:
    display_name = _normalize_name(full_name or name)
    norm_phone = _normalize_phone(phone)

    if not display_name:
        raise ValueError("Guest name is required to create/find a guest.")

    if norm_phone:
        existing = db.execute(
            select(Guest)
            .where(func.replace(func.replace(Guest.phone, " ", ""), "-", "") == norm_phone)
            .where(Guest.active == True)
            .order_by(Guest.id.asc())
        ).scalars().first()
        if existing:
            changed = False
            if not (existing.full_name or "").strip() and display_name:
                existing.full_name = display_name
                existing.name = display_name
                changed = True
            elif display_name and (existing.full_name or "").strip() != display_name and not (existing.full_name or "").strip():
                existing.full_name = display_name
                existing.name = display_name
                changed = True
            if not (existing.email or "").strip() and (email or "").strip():
                existing.email = (email or "").strip()
                changed = True
            if not (existing.address or "").strip() and (address or "").strip():
                existing.address = (address or "").strip()
                changed = True
            if not (existing.pan_vat_number or "").strip() and (pan_vat or "").strip():
                existing.pan_vat_number = (pan_vat or "").strip()
                changed = True
            if not (existing.id_type or "").strip() and (id_type or "").strip():
                existing.id_type = (id_type or "").strip()
                changed = True
            if not (existing.id_number or "").strip() and (id_number or "").strip():
                existing.id_number = (id_number or "").strip()
                changed = True
            if customer_type and existing.customer_type != customer_type.strip():
                existing.customer_type = customer_type.strip()
                changed = True
            if changed:
                existing.updated_at = utcnow()
                db.flush()
            return existing

    q = select(Guest).where(Guest.active == True)
    q = q.where((Guest.full_name == display_name) | (Guest.name == display_name))
    if norm_phone:
        q = q.where((Guest.phone == phone.strip()) | (Guest.phone == norm_phone))
    existing = db.execute(q.order_by(Guest.id.asc())).scalars().first()
    if existing:
        existing.updated_at = utcnow()
        db.flush()
        return existing

    g = Guest(
        full_name=display_name,
        name=display_name,
        phone=(phone.strip() or None),
        email=(email or "").strip() or "",
        address=(address or "").strip() or "",
        id_type=(id_type or "").strip() or "",
        id_number=(id_number or "").strip() or "",
        pan_vat_number=(pan_vat or "").strip() or "",
        customer_type=(customer_type or "").strip() or "individual",
        active=True,
        created_at=utcnow(),
        updated_at=utcnow(),
    )
    db.add(g)
    db.flush()
    db.refresh(g)
    return g
