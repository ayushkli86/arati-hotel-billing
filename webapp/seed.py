"""Idempotently create a local demo hotel dataset and login accounts.

Default credentials are a development convenience only. In production
(``ARATI_ENV=production``) the demo accounts are refused, seed data is not
created unless explicitly asked for, and the first admin comes from
``ARATI_INITIAL_ADMIN_USER`` / ``ARATI_INITIAL_ADMIN_PASSWORD`` with a forced
password change on first login.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from .auth import hash_password
from .database import Base, SessionLocal, engine
from .models import CatalogItem, Guest, Invoice, InvoiceItem, Payment, Reservation, Room, Stay, User
from .services import local_now


def _is_production() -> bool:
    return os.getenv("ARATI_ENV", "development").strip().lower() == "production"


def seed_users() -> None:
    """Create the first accounts without shipping known passwords."""
    with SessionLocal.begin() as db:
        if db.scalar(select(User.id).limit(1)):
            return
        if _is_production():
            username = (os.getenv("ARATI_INITIAL_ADMIN_USER") or "admin").strip().lower()
            password = os.getenv("ARATI_INITIAL_ADMIN_PASSWORD", "")
            if len(password) < 12:
                raise RuntimeError(
                    "Set ARATI_INITIAL_ADMIN_PASSWORD (at least 12 characters) before "
                    "starting the web app for the first time in production."
                )
            db.add(User(
                username=username, password_hash=hash_password(password),
                full_name="Hotel Administrator", role="admin", must_change_password=True,
            ))
            return
        db.add_all([
            User(username="admin", password_hash=hash_password("admin123"),
                 full_name="Hotel Administrator", role="admin"),
            User(username="frontdesk", password_hash=hash_password("staff123"),
                 full_name="Front Desk", role="staff"),
        ])


def seed_demo_data() -> None:
    Base.metadata.create_all(bind=engine)
    seed_users()
    if _is_production() and os.getenv("ARATI_SEED_DEMO", "0") != "1":
        return
    with SessionLocal.begin() as db:
        if not db.scalar(select(CatalogItem.id).limit(1)):
            db.add_all([
                CatalogItem(name="Chicken Thali", category="restaurant", rate=850),
                CatalogItem(name="Veg Thali", category="restaurant", rate=550),
                CatalogItem(name="Breakfast Set", category="restaurant", rate=450),
                CatalogItem(name="Tea / Coffee", category="restaurant", rate=120),
                CatalogItem(name="Laundry Service", category="service", rate=350),
                CatalogItem(name="Airport Transfer", category="service", rate=1800),
                CatalogItem(name="Extra Bed", category="service", rate=1000),
                CatalogItem(name="Meeting Room (hour)", category="service", rate=1500),
            ])
        room_type_rates = {
            "Standard Room": 3000.0,
            "Deluxe Room": 4500.0,
            "Super Deluxe Room": 5000.0,
        }
        room_type_items = {}
        for name, rate in room_type_rates.items():
            item = db.scalar(select(CatalogItem).where(
                CatalogItem.category == "room", CatalogItem.name == name,
            ))
            if item is None:
                item = CatalogItem(name=name, category="room", rate=rate, unit="night")
                db.add(item)
            room_type_items[name] = item
        db.flush()
        if db.scalar(select(Room.id).limit(1)):
            return

        room_types = ["Standard"] * 12 + ["Deluxe"] * 9 + ["Super Deluxe"] * 4
        rates = {"Standard": 3000.0, "Deluxe": 4500.0, "Super Deluxe": 5000.0}
        rooms = []
        for index, kind in enumerate(room_types):
            floor = str(index // 8 + 1)
            type_name = f"{kind} Room"
            room = Room(
                number=str(101 + index), type=type_name, status="available",
                housekeeping_status="clean", floor=floor, nightly_rate=rates[kind],
                room_type_item=room_type_items[type_name],
            )
            rooms.append(room)
        db.add_all(rooms)
        guests = [
            Guest(name=name, phone=f"98{50000000 + i:08d}",
                  email=f"guest{i + 1}@example.com", id_type="Citizenship")
            for i, name in enumerate(("Sita Rai", "Ramesh Karki", "Maya Gurung",
                                      "Prakash Shrestha", "Nima Sherpa", "Asha Tamang",
                                      "Walk-in Guest", "Bikash Limbu"))
        ]
        db.add_all(guests)
        db.flush()

        local = local_now()
        for index, room_index in enumerate((0, 10)):
            room = rooms[room_index]
            guest = guests[index]
            room.status = "occupied"
            db.add(Stay(
                room=room, guest_id=guest.id,
                check_in=(local - timedelta(days=index + 1)).astimezone(timezone.utc).replace(tzinfo=None),
                check_out=(local + timedelta(days=index % 2 + 1)).astimezone(timezone.utc).replace(tzinfo=None),
                status="checked_in",
            ))
        for room_index in (2, 4):
            rooms[room_index].status = "dirty"
            rooms[room_index].housekeeping_status = "dirty"
        reserved_room = rooms[7]
        reserved_room.status = "reserved"
        db.add(Reservation(
            room=reserved_room, guest=guests[5],
            check_in=(local + timedelta(days=1)).astimezone(timezone.utc).replace(tzinfo=None),
            check_out=(local + timedelta(days=3)).astimezone(timezone.utc).replace(tzinfo=None),
            status="confirmed",
        ))

        now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
        invoice_specs = [
            (0, 0, "Room 101 · 2 nights", 7000, 1800, "Cash"),
            (1, 3, "Room 104 · 1 night", 5500, 2000, "Card"),
            (2, 8, "Room 109 · 2 nights", 11000, 4000, "Cash"),
            (3, 12, "Room 113 · 1 night", 8500, 3500, "eSewa"),
            (4, 18, "Room 119 · 3 nights", 10500, 0, ""),
            (5, None, "Restaurant · dinner", 2450, 0, ""),
            (6, None, "Restaurant · lunch", 1850, 1850, "Bank Transfer"),
            (7, None, "Airport transfer", 2200, 0, ""),
            (0, None, "Breakfast", 950, 950, "Cash"),
            (2, None, "Laundry", 1250, 0, ""),
        ]
        for index, (guest_index, room_index, description, total, paid, method) in enumerate(invoice_specs, 1):
            issued = now_utc - timedelta(minutes=index * 23)
            invoice = Invoice(
                invoice_number=f"ARH-{local.strftime('%Y%m%d')}-{index:04d}",
                guest_id=guests[guest_index].id,
                room_id=rooms[room_index].id if room_index is not None else None,
                issue_date=issued, discount_amount=100 if index == 1 else 0,
                total=total, paid_amount=paid,
                balance=total - paid, status="paid" if paid >= total else "issued",
            )
            invoice.items.append(InvoiceItem(
                description=description, quantity=1, rate=total + (100 if index == 1 else 0),
                amount=total + (100 if index == 1 else 0),
            ))
            db.add(invoice)
            db.flush()
            if paid:
                db.add(Payment(invoice=invoice, amount=paid, method=method,
                               paid_at=issued + timedelta(minutes=3), received_by="frontdesk"))


if __name__ == "__main__":
    seed_demo_data()
    if _is_production():
        print("Production setup ready. The initial administrator must change the password on first login.")
    else:
        print("Demo data ready. Sign in with admin / admin123 or frontdesk / staff123.")
