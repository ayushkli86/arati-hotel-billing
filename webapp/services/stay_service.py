from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Room, Stay, utcnow
from . import guest_service, invoice_service, room_service


def create_stay(
    db: Session,
    *,
    guest_id: int,
    room_id: int,
    check_in: datetime,
    expected_checkout: datetime | None = None,
    rate_per_night: Decimal | float = 0,
    user_id: int | None = None,
    business_date: str = "",
    notes: str = "",
) -> Stay:
    guest = guest_service.get_guest_by_id(db, guest_id)
    if not guest or not guest.active:
        raise ValueError("Valid active guest required to create stay")

    room = db.get(Room, room_id)
    if not room or not room.active:
        raise ValueError("Valid active room required")

    if room.status not in {"available"}:
        raise ValueError(f"Room {room.number} is not available for check-in")

    rate = Decimal(str(rate_per_night or room.nightly_rate or 0))

    stay = Stay(
        guest_id=guest.id,
        room_id=room.id,
        check_in=check_in,
        expected_checkout=expected_checkout,
        status="checked_in",
        room_number=room.number,
        guest_name=guest.full_name or guest.name,
        guest_phone=guest.phone or "",
        guest_email=guest.email or "",
        guest_address=guest.address or "",
        guest_pan=guest.pan_vat_number or "",
        rate_per_night=rate,
        nightly_rate=rate,
        business_date=business_date,
        notes=(notes or "").strip(),
        created_at=utcnow(),
        updated_at=utcnow(),
        user_id=user_id,
    )
    db.add(stay)
    db.flush()

    room_service.mark_occupied(db, room.id)
    invoice_service.get_or_create_draft_invoice(
        db,
        guest_id=guest.id,
        stay_id=stay.id,
        room_id=room.id,
        user_id=user_id,
    )
    return stay


def get_active_stay_by_room(db: Session, room_id: int) -> Stay | None:
    return db.execute(
        select(Stay).where(Stay.room_id == room_id, Stay.status == "checked_in").order_by(Stay.id.desc())
    ).scalars().first()


def checkout_stay(db: Session, *, stay_id: int, user_id: int | None = None) -> Stay:
    stay = db.get(Stay, stay_id)
    if not stay:
        raise ValueError("Stay not found")
    if stay.status != "checked_in":
        raise ValueError("Only checked-in stays can be checked out")

    stay.status = "checked_out"
    stay.check_out = utcnow()
    stay.updated_at = utcnow()
    room_service.set_status(db, stay.room_id, "cleaning")
    return stay
