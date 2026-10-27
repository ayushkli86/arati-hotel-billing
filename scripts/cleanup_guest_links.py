#!/usr/bin/env python3
from __future__ import annotations

from sqlalchemy import select

from webapp.database import SessionLocal
from webapp.models import Guest, Invoice, Stay
from webapp.services import guest_service


def main():
    db = SessionLocal()
    try:
        stays = db.execute(select(Stay).where((Stay.guest_id == None) | (Stay.guest_id == 0))).scalars().all()
        for s in stays:
            g = guest_service.get_or_create_guest(
                db,
                name=s.guest_name or "Walk-in Guest",
                phone=s.guest_phone or "",
                email=s.guest_email or "",
                address=s.guest_address or "",
                pan_vat=s.guest_pan or "",
            )
            s.guest_id = g.id
            s.guest_name = g.full_name or g.name
            s.guest_phone = g.phone or ""
            s.guest_address = g.address or ""
            s.guest_pan = g.pan_vat_number or ""
            s.guest_email = g.email or ""
        db.flush()

        invs = db.execute(select(Invoice).where((Invoice.guest_id == None) | (Invoice.guest_id == 0))).scalars().all()
        for inv in invs:
            if inv.stay_id:
                st = db.get(Stay, inv.stay_id)
                if st and st.guest_id:
                    inv.guest_id = st.guest_id
                    inv.guest_name = inv.guest_name or (st.guest_name or "")
                    inv.guest_phone = inv.guest_phone or (st.guest_phone or "")
                    inv.guest_address = inv.guest_address or (st.guest_address or "")
                    inv.guest_pan = inv.guest_pan or (st.guest_pan or "")
                    continue
            g = guest_service.get_or_create_guest(
                db,
                name=inv.guest_name or "Walk-in Guest",
                phone=inv.guest_phone or "",
                address=inv.guest_address or "",
                pan_vat=inv.guest_pan or "",
            )
            inv.guest_id = g.id
        db.flush()
        db.commit()
        print("Done: linked stays/invoices to guests")
    except Exception as e:
        db.rollback()
        print("Error:", e)
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
