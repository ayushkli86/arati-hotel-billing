"""Room inventory, reservations and guest stays.

The module owns three separate pieces of state, exactly as the hotel works:

* **Inventory** — which room numbers exist (``rooms`` table).
* **Reservation state** — who has booked which room for which nights
  (``reservations`` table).
* **Occupancy state** — who is physically in the room right now
  (``stays`` table).
* **Housekeeping state** — whether the room is clean, needs cleaning or is
  out of service (``rooms.housekeeping``).

They are deliberately *not* merged into one status column: a room can be
occupied *and* awaiting cleaning, and a room awaiting cleaning must never be
handed to a new guest. The user-facing status is derived from all three by
:func:`room_state`.

Money for a stay is never tracked here. A stay settles through the ordinary
invoice and payment tables, so the room module and the billing module share
one ledger instead of two that disagree.
"""

from __future__ import annotations

import sqlite3
from datetime import date, datetime, timedelta

from . import business_time as bt
from . import db
from .money import compute_totals, from_paisa, to_paisa

# The hotel's default inventory: 25 rooms on three floors.
DEFAULT_ROOM_NUMBERS = tuple(str(number) for number in range(101, 126))

# Room type used when a room number is added without an explicit type.
DEFAULT_ROOM_TYPE = "Standard Room"

# Housekeeping states a room can be in.
HOUSEKEEPING_STATES = ("clean", "needs_cleaning", "maintenance")

# Display status, ordered by precedence.
STATUS_AVAILABLE = "Available"
STATUS_RESERVED = "Reserved"
STATUS_OCCUPIED = "Occupied"
STATUS_NEEDS_CLEANING = "Needs cleaning"
STATUS_UNDER_MAINTENANCE = "Under maintenance"

# Default plan for the 25 rooms: five rooms per type on three floors.
# (last room number of the block, room type, floor)
_DEFAULT_PLAN = (
    (110, "Standard Room", "1"),
    (120, "Deluxe Room", "2"),
    (125, "Super Deluxe Room", "3"),
)

# Billing policy.
DEFAULT_CHECKOUT_TIME = "11:00"


class RoomError(ValueError):
    """Raised when a room operation would break an invariant."""


# --------------------------------------------------------------------------- #
# inventory
# --------------------------------------------------------------------------- #
def parse_room_numbers(value: str) -> list[str]:
    """Parse a room list: ``"101, 102"`` or ``"101-125"`` -> room numbers."""
    numbers: list[str] = []
    for chunk in str(value or "").replace(";", ",").split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        if "-" in chunk:
            start_text, _, end_text = chunk.partition("-")
            try:
                start, end = int(start_text.strip()), int(end_text.strip())
            except ValueError:
                raise RoomError(f"'{chunk}' is not a valid room range.") from None
            if end < start:
                raise RoomError(f"Range '{chunk}' ends before it starts.")
            numbers.extend(str(number) for number in range(start, end + 1))
        else:
            numbers.append(chunk)
    seen: set[str] = set()
    ordered: list[str] = []
    for number in numbers:
        if number not in seen:
            seen.add(number)
            ordered.append(number)
    return ordered


def default_room_numbers() -> list[str]:
    """The 25 default room numbers, 101-125."""
    return list(DEFAULT_ROOM_NUMBERS)


def ensure_inventory(
    conn: sqlite3.Connection, numbers: list[str] | None = None
) -> dict:
    """Create any missing rooms from ``numbers``.

    Existing rooms are never renamed, retyped or removed — a hotel that
    already has room 2001 keeps it. Calling this twice creates nothing the
    second time, so it is safe on every start-up.
    """
    wanted = [n for n in (numbers or default_room_numbers()) if n]
    if not wanted:
        return {"created": [], "existing": [], "total": 0}

    type_ids = _room_type_ids(conn)
    default_type = type_ids.get(DEFAULT_ROOM_TYPE) or next(iter(type_ids.values()), None)
    if default_type is None:
        raise RoomError("No room type is configured, so rooms cannot be created.")

    present = {
        row["room_no"]: row
        for row in conn.execute("SELECT * FROM rooms")
    }
    created: list[str] = []
    for index, room_no in enumerate(wanted):
        if room_no in present:
            continue
        type_name, floor = _default_type_for(wanted, index)
        item_id = type_ids.get(type_name, default_type)
        rate = _type_price(conn, item_id)
        db.save_room(conn, room_no, item_id, floor)
        conn.execute(
            "UPDATE rooms SET nightly_rate = ?, housekeeping = 'clean' WHERE room_no = ?",
            (rate, room_no),
        )
        created.append(room_no)

    if created:
        conn.commit()

    # Rooms created before rates were stored keep the type price, so the
    # front desk never sees a room that costs nothing.
    for room_no in wanted:
        row = conn.execute(
            "SELECT room_id, item_id, nightly_rate FROM rooms WHERE room_no = ?",
            (room_no,),
        ).fetchone()
        if row is not None and not float(row["nightly_rate"] or 0):
            conn.execute(
                "UPDATE rooms SET nightly_rate = ? WHERE room_id = ?",
                (_type_price(conn, row["item_id"]), row["room_id"]),
            )
    conn.commit()

    return {
        "created": created,
        "existing": [n for n in wanted if n not in created],
        "total": len(wanted),
    }


def set_inventory(
    conn: sqlite3.Connection, numbers: list[str], deactivate_extra: bool = False
) -> dict:
    """Apply a room list.

    Missing rooms are created. Rooms that are no longer listed are only
    deactivated when ``deactivate_extra`` is true, and even then they are
    deactivated, never deleted, so historic bills keep their room number.
    """
    result = ensure_inventory(conn, numbers)
    if deactivate_extra:
        wanted = set(numbers)
        extra = [
            row["room_no"]
            for row in conn.execute("SELECT room_no FROM rooms WHERE active = 1")
            if row["room_no"] not in wanted
        ]
        for room_no in extra:
            conn.execute("UPDATE rooms SET active = 0 WHERE room_no = ?", (room_no,))
        if extra:
            conn.commit()
        result["deactivated"] = extra
    return result


def _default_type_for(numbers: list[str], index: int) -> tuple[str, str]:
    """Room type and floor for a new room.

    With the default 101-125 list the rooms are spread over three floors:
    101-110 Standard, 111-120 Deluxe, 121-125 Super Deluxe. Any other list
    falls back to cycling through the types.
    """
    if numbers == list(DEFAULT_ROOM_NUMBERS):
        room_no = int(numbers[index])
        for upper, type_name, floor in _DEFAULT_PLAN:
            if room_no <= upper:
                return type_name, floor
    type_names = [plan[1] for plan in _DEFAULT_PLAN]
    return type_names[index % len(type_names)], str((index // 10) + 1)


def _room_type_ids(conn: sqlite3.Connection) -> dict[str, int]:
    return {
        row["name"]: row["item_id"]
        for row in conn.execute(
            "SELECT item_id, name FROM items WHERE category = 'room' ORDER BY sort_order"
        )
    }


def _type_price(conn: sqlite3.Connection, item_id: int) -> float:
    row = conn.execute("SELECT price FROM items WHERE item_id = ?", (item_id,)).fetchone()
    return round(float(row["price"]) if row else 0.0, 2)


def list_rooms(conn: sqlite3.Connection) -> list[dict]:
    """Every active room with its derived status and current guest."""
    rooms = list(
        conn.execute(
            "SELECT r.*, i.name AS room_type, i.price AS type_price "
            "FROM rooms r LEFT JOIN items i ON i.item_id = r.item_id "
            "WHERE r.active = 1 ORDER BY CAST(r.room_no AS INTEGER), r.room_no"
        )
    )
    states = {room["room_no"]: room_state(conn, room["room_no"]) for room in rooms}
    result = []
    for room in rooms:
        state = states[room["room_no"]]
        result.append(
            {
                "room_no": room["room_no"],
                "room_type": room["room_type"] or "",
                "floor": room["floor"] or "",
                "rate": round(
                    float(room["nightly_rate"] or 0) or float(room["type_price"] or 0), 2
                ),
                "housekeeping": room["housekeeping"] or "clean",
                "status": state["status"],
                "guest_name": state["guest_name"],
                "guest_phone": state["guest_phone"],
                "check_in": state["check_in"],
                "expected_checkout": state["expected_checkout"],
                "balance": state["balance"],
                "stay_id": state["stay_id"],
                "reservation_id": state["reservation_id"],
            }
        )
    return result


def room_state(conn: sqlite3.Connection, room_no: str) -> dict:
    """The derived status of one room.

    Precedence: out of service beats occupied, which beats reserved, which
    beats needs cleaning. A dirty room is never reported as available.
    """
    room = conn.execute(
        "SELECT * FROM rooms WHERE room_no = ? AND active = 1", (room_no,)
    ).fetchone()
    housekeeping = (room["housekeeping"] if room else "clean") or "clean"
    stay = conn.execute(
        "SELECT * FROM stays WHERE room_no = ? AND status = 'active' "
        "ORDER BY stay_id DESC LIMIT 1",
        (room_no,),
    ).fetchone()
    reservation = conn.execute(
        "SELECT * FROM reservations WHERE room_no = ? AND status = 'confirmed' "
        "AND check_out >= ? ORDER BY check_in LIMIT 1",
        (room_no, bt.today().isoformat()),
    ).fetchone()

    balance = 0.0
    if stay and stay["bill_no"]:
        row = conn.execute(
            "SELECT balance FROM bills WHERE bill_no = ?", (stay["bill_no"],)
        ).fetchone()
        balance = round(float(row["balance"]) if row else 0.0, 2)

    if housekeeping == "maintenance":
        status = STATUS_UNDER_MAINTENANCE
    elif stay is not None:
        status = STATUS_OCCUPIED
    elif reservation is not None:
        status = STATUS_RESERVED
    elif housekeeping == "needs_cleaning":
        status = STATUS_NEEDS_CLEANING
    else:
        status = STATUS_AVAILABLE

    return {
        "room_no": room_no,
        "status": status,
        "housekeeping": housekeeping,
        "stay_id": stay["stay_id"] if stay else None,
        "reservation_id": reservation["reservation_id"] if reservation else None,
        "guest_name": stay["guest_name"] if stay else "",
        "guest_phone": stay["guest_phone"] if stay else "",
        "check_in": stay["check_in"] if stay else "",
        "expected_checkout": stay["expected_checkout"] if stay else "",
        "balance": balance,
    }


def set_housekeeping(
    conn: sqlite3.Connection, room_no: str, state: str, user_id: int | None = None
) -> None:
    """Mark a room clean, needing cleaning or under maintenance."""
    if state not in HOUSEKEEPING_STATES:
        raise RoomError(f"Unknown housekeeping state: {state}")
    room = conn.execute(
        "SELECT room_id FROM rooms WHERE room_no = ? AND active = 1", (room_no,)
    ).fetchone()
    if room is None:
        raise RoomError(f"Room {room_no} does not exist.")
    conn.execute(
        "UPDATE rooms SET housekeeping = ? WHERE room_no = ?", (state, room_no)
    )
    conn.commit()
    db.log_audit(
        conn,
        "room.housekeeping",
        "room",
        room_no,
        f"housekeeping set to {state}",
        user_id,
    )


def set_rate(conn: sqlite3.Connection, room_no: str, rate: float, user_id: int | None = None) -> None:
    """Change the nightly rate of a room."""
    rate_paisa = to_paisa(rate)
    if rate_paisa < 0:
        raise RoomError("A room rate cannot be negative.")
    conn.execute(
        "UPDATE rooms SET nightly_rate = ? WHERE room_no = ?",
        (from_paisa(rate_paisa), room_no),
    )
    conn.commit()
    db.log_audit(
        conn, "room.rate", "room", room_no, f"nightly rate set to {from_paisa(rate_paisa):,.2f}", user_id
    )


# --------------------------------------------------------------------------- #
# reservations
# --------------------------------------------------------------------------- #
def create_reservation(
    conn: sqlite3.Connection,
    room_no: str,
    guest_name: str,
    check_in: str,
    check_out: str,
    nightly_rate: float = 0.0,
    guest_phone: str = "",
    guest_address: str = "",
    guest_pan: str = "",
    deposit: float = 0.0,
    source: str = "front desk",
    notes: str = "",
    user_id: int | None = None,
) -> int:
    """Book a room.

    Refuses an overlapping confirmed reservation for the same room and refuses
    a room that is out of service.
    """
    if not guest_name.strip():
        raise RoomError("A reservation needs a guest name.")
    _validate_dates(check_in, check_out)
    room = conn.execute(
        "SELECT * FROM rooms WHERE room_no = ? AND active = 1", (room_no,)
    ).fetchone()
    if room is None:
        raise RoomError(f"Room {room_no} does not exist.")
    if (room["housekeeping"] or "clean") == "maintenance":
        raise RoomError(f"Room {room_no} is under maintenance and cannot be booked.")

    overlap = conn.execute(
        "SELECT reservation_id, guest_name, check_in, check_out FROM reservations "
        "WHERE room_no = ? AND status IN ('confirmed','checked_in') "
        "AND NOT (check_out <= ? OR check_in >= ?) LIMIT 1",
        (room_no, check_in, check_out),
    ).fetchone()
    if overlap is not None:
        raise RoomError(
            f"Room {room_no} is already booked from {overlap['check_in']} to "
            f"{overlap['check_out']}."
        )

    rate = nightly_rate or float(room["nightly_rate"] or 0) or _type_price(
        conn, room["item_id"]
    )
    with conn:
        cursor = conn.execute(
            "INSERT INTO reservations (room_no, guest_name, guest_phone, guest_address, "
            "guest_pan, check_in, check_out, status, nightly_rate, deposit, source, "
            "notes, created_at, user_id) VALUES (?,?,?,?,?,?,?,'confirmed',?,?,?,?,?,?)",
            (
                room_no,
                guest_name.strip(),
                guest_phone.strip(),
                guest_address.strip(),
                guest_pan.strip(),
                check_in,
                check_out,
                round(rate, 2),
                round(float(deposit or 0), 2),
                source.strip(),
                notes.strip(),
                bt.now().strftime("%Y-%m-%d %H:%M:%S"),
                user_id,
            ),
        )
    db.log_audit(
        conn,
        "reservation.create",
        "reservation",
        cursor.lastrowid,
        f"room {room_no} {check_in} to {check_out}",
        user_id,
    )
    return int(cursor.lastrowid)


def cancel_reservation(
    conn: sqlite3.Connection,
    reservation_id: int,
    reason: str = "",
    user_id: int | None = None,
) -> dict:
    """Cancel a reservation and report the deposit that must be refunded."""
    row = conn.execute(
        "SELECT * FROM reservations WHERE reservation_id = ?", (reservation_id,)
    ).fetchone()
    if row is None:
        raise RoomError("That reservation does not exist.")
    if row["status"] in ("cancelled", "checked_out"):
        raise RoomError(f"Reservation {reservation_id} is already {row['status']}.")
    if row["status"] == "checked_in":
        raise RoomError(
            "The guest has already checked in — check the guest out instead of "
            "cancelling the reservation."
        )
    conn.execute(
        "UPDATE reservations SET status = 'cancelled', cancel_reason = ? "
        "WHERE reservation_id = ?",
        (reason.strip(), reservation_id),
    )
    conn.commit()
    db.log_audit(
        conn,
        "reservation.cancel",
        "reservation",
        reservation_id,
        reason.strip() or "no reason given",
        user_id,
    )
    return {
        "reservation_id": reservation_id,
        "room_no": row["room_no"],
        "deposit": round(float(row["deposit"] or 0), 2),
        "guest_name": row["guest_name"],
    }


def list_reservations(
    conn: sqlite3.Connection,
    start: str | None = None,
    end: str | None = None,
    status: str | None = None,
    room_no: str = "",
) -> list[sqlite3.Row]:
    sql = "SELECT * FROM reservations WHERE 1=1"
    params: list = []
    if start:
        sql += " AND check_out >= ?"
        params.append(start)
    if end:
        sql += " AND check_in <= ?"
        params.append(end)
    if status and status != "All":
        sql += " AND status = ?"
        params.append(status)
    if room_no:
        sql += " AND room_no LIKE ?"
        params.append(f"%{room_no}%")
    sql += " ORDER BY check_in DESC, reservation_id DESC"
    return list(conn.execute(sql, params))


# --------------------------------------------------------------------------- #
# stays
# --------------------------------------------------------------------------- #
def check_in(
    conn: sqlite3.Connection,
    room_no: str,
    guest_name: str,
    check_in_at: str | None = None,
    expected_checkout: str | None = None,
    nightly_rate: float = 0.0,
    guest_phone: str = "",
    guest_address: str = "",
    guest_pan: str = "",
    reservation_id: int | None = None,
    user_id: int | None = None,
) -> int:
    """Check a guest into a room.

    Refuses a second check-in for a room that already has an active guest and
    refuses a room that is out of service.
    """
    if not guest_name.strip():
        raise RoomError("A check-in needs a guest name.")
    room = conn.execute(
        "SELECT * FROM rooms WHERE room_no = ? AND active = 1", (room_no,)
    ).fetchone()
    if room is None:
        raise RoomError(f"Room {room_no} does not exist.")
    if (room["housekeeping"] or "clean") == "maintenance":
        raise RoomError(f"Room {room_no} is under maintenance and cannot be used.")

    active = conn.execute(
        "SELECT stay_id, guest_name FROM stays WHERE room_no = ? AND status = 'active'",
        (room_no,),
    ).fetchone()
    if active is not None:
        raise RoomError(
            f"Room {room_no} is already occupied by {active['guest_name']}."
        )

    now = bt.now()
    arrival = check_in_at or now.strftime("%Y-%m-%d %H:%M")
    if expected_checkout:
        departure_date = expected_checkout.split(" ")[0]
        _validate_dates(arrival.split(" ")[0], departure_date)
        checkout = expected_checkout
    else:
        checkout = f"{(now + timedelta(days=1)).date().isoformat()} {DEFAULT_CHECKOUT_TIME}"

    rate = nightly_rate or float(room["nightly_rate"] or 0) or _type_price(
        conn, room["item_id"]
    )
    with conn:
        cursor = conn.execute(
            "INSERT INTO stays (reservation_id, room_no, guest_name, guest_phone, "
            "guest_address, guest_pan, check_in, expected_checkout, nights, "
            "nightly_rate, status, created_at, user_id) "
            "VALUES (?,?,?,?,?,?,?,?,1,?,'active',?,?)",
            (
                reservation_id,
                room_no,
                guest_name.strip(),
                guest_phone.strip(),
                guest_address.strip(),
                guest_pan.strip(),
                arrival,
                checkout,
                round(rate, 2),
                bt.now().strftime("%Y-%m-%d %H:%M:%S"),
                user_id,
            ),
        )
        if reservation_id:
            conn.execute(
                "UPDATE reservations SET status = 'checked_in' WHERE reservation_id = ?",
                (reservation_id,),
            )
    db.log_audit(
        conn,
        "stay.check_in",
        "stay",
        cursor.lastrowid,
        f"{guest_name.strip()} checked into room {room_no}",
        user_id,
    )
    return int(cursor.lastrowid)


def extend_stay(
    conn: sqlite3.Connection,
    stay_id: int,
    new_checkout: str,
    user_id: int | None = None,
) -> str:
    """Change or extend the expected check-out date."""
    row = conn.execute("SELECT * FROM stays WHERE stay_id = ?", (stay_id,)).fetchone()
    if row is None:
        raise RoomError("That stay does not exist.")
    if row["status"] != "active":
        raise RoomError("Only an active stay can be extended.")
    _validate_dates(row["check_in"].split(" ")[0], new_checkout.split(" ")[0])
    conn.execute(
        "UPDATE stays SET expected_checkout = ? WHERE stay_id = ?",
        (new_checkout, stay_id),
    )
    conn.commit()
    db.log_audit(
        conn,
        "stay.extend",
        "stay",
        stay_id,
        f"check-out moved to {new_checkout}",
        user_id,
    )
    return new_checkout


def add_charge(
    conn: sqlite3.Connection,
    stay_id: int,
    description: str,
    amount: float,
    category: str = "service",
    qty: float = 1.0,
    unit_price: float | None = None,
    charge_date: str | None = None,
    user_id: int | None = None,
) -> int:
    """Add a charge to a stay's folio (food, beverage, laundry, extra bed…).

    The folio is billed through the ordinary invoice tables, so the money is
    visible in the same reports as every other sale.
    """
    stay = conn.execute("SELECT * FROM stays WHERE stay_id = ?", (stay_id,)).fetchone()
    if stay is None:
        raise RoomError("That stay does not exist.")
    if stay["status"] != "active":
        raise RoomError("Only an active stay can take charges.")
    if not description.strip():
        raise RoomError("A charge needs a description.")
    amount_paisa = to_paisa(amount)
    if amount_paisa <= 0:
        raise RoomError("A charge must be greater than zero.")
    day = charge_date or bt.today().isoformat()
    with conn:
        cursor = conn.execute(
            "INSERT INTO room_charges (stay_id, room_no, description, category, qty, "
            "unit_price, amount, charge_date, created_at, user_id) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                stay_id,
                stay["room_no"],
                description.strip(),
                category,
                float(qty or 1),
                from_paisa(amount_paisa) if unit_price is None else round(float(unit_price), 2),
                from_paisa(amount_paisa),
                day,
                bt.now().strftime("%Y-%m-%d %H:%M:%S"),
                user_id,
            ),
        )
    db.log_audit(
        conn,
        "room_charge.create",
        "stay",
        stay_id,
        f"{description.strip()} {from_paisa(amount_paisa):,.2f}",
        user_id,
    )
    return int(cursor.lastrowid)


def list_charges(conn: sqlite3.Connection, stay_id: int) -> list[sqlite3.Row]:
    return list(
        conn.execute(
            "SELECT * FROM room_charges WHERE stay_id = ? ORDER BY charge_date, charge_id",
            (stay_id,),
        )
    )


def stay_nights(stay: sqlite3.Row, charges: list[sqlite3.Row]) -> int:
    """Nights to charge.

    The number of nights is measured from the arrival date to the departure
    date — the actual check-out when the guest has left, otherwise the
    expected check-out — plus any extra night already posted to the folio.
    """
    nights = int(stay["nights"] or 0)
    departure = stay["check_out"] or stay["expected_checkout"]
    if stay["check_in"] and departure:
        try:
            arrival = date.fromisoformat(str(stay["check_in"])[:10])
            leaving = date.fromisoformat(str(departure)[:10])
            nights = max(1, (leaving - arrival).days)
        except ValueError:
            pass
    extra = conn_extra_nights(stay, charges)
    return max(1, nights + extra)


def conn_extra_nights(stay: sqlite3.Row, charges: list[sqlite3.Row]) -> int:
    """Extra nights charged through the folio (one line per extra night)."""
    extra = 0
    for charge in charges:
        if charge["category"] == "room" and charge["description"].startswith("Extra night"):
            extra += 1
    return extra


def folio_preview(
    conn: sqlite3.Connection, stay_id: int, bill_type: str = "tax"
) -> dict:
    """The folio of a stay: the lines that would be billed and their totals.

    The check-out screen shows this so the guest sees the same numbers that
    end up on the invoice. The calculation lives here — once — so the
    preview and the invoice cannot drift apart.
    """
    stay = conn.execute("SELECT * FROM stays WHERE stay_id = ?", (stay_id,)).fetchone()
    if stay is None:
        raise RoomError("That stay does not exist.")
    charges = list_charges(conn, stay_id)
    nights = stay_nights(stay, charges)
    rate = float(stay["nightly_rate"] or 0)

    lines = [
        {
            "description": f"Room {stay['room_no']} — {nights} night(s)",
            "category": "room",
            "qty": nights,
            "unit_price": rate,
            "taxable": True,
            "unit": "night",
            "item_id": None,
        }
    ]
    for charge in charges:
        lines.append(
            {
                "description": charge["description"],
                "category": charge["category"],
                "qty": float(charge["qty"] or 1),
                "unit_price": float(charge["unit_price"] or 0),
                "taxable": True,
                "unit": "pcs",
                "item_id": None,
            }
        )

    settings = db.get_settings(conn)
    totals = compute_totals(
        [_line(line) for line in lines],
        discount=0.0,
        service_charge_rate=float(settings.get("service_charge_rate", 10)),
        vat_rate=float(settings.get("vat_rate", 13)),
        paid=0.0,
        bill_type=bill_type,
    )
    return {
        "stay": dict(stay),
        "lines": lines,
        "charges": [dict(charge) for charge in charges],
        "nights": nights,
        "rate": rate,
        "totals": totals.as_dict(),
        "settings": settings,
    }


def check_out(
    conn: sqlite3.Connection,
    stay_id: int,
    payment_method: str = "Cash",
    paid: float = 0.0,
    bill_type: str = "tax",
    user_id: int | None = None,
    username: str = "",
) -> str:
    """Close a stay: raise the folio invoice and settle it.

    Returns the invoice number. The invoice is created once — calling
    check-out twice for the same stay is refused, so a stay can never be
    billed twice.
    """
    stay = conn.execute("SELECT * FROM stays WHERE stay_id = ?", (stay_id,)).fetchone()
    if stay is None:
        raise RoomError("That stay does not exist.")
    if stay["status"] != "active":
        raise RoomError("This stay has already been checked out.")
    if stay["bill_no"]:
        raise RoomError(
            f"This stay was already invoiced as {stay['bill_no']}; it cannot be billed again."
        )

    preview = folio_preview(conn, stay_id, bill_type)
    lines = preview["lines"]
    nights = preview["nights"]

    settings = preview["settings"]
    totals = compute_totals(
        [_line(line) for line in lines],
        discount=0.0,
        service_charge_rate=float(settings.get("service_charge_rate", 10)),
        vat_rate=float(settings.get("vat_rate", 13)),
        paid=paid,
        bill_type=bill_type,
    )

    check_in_date = stay["check_in"].split(" ")[0]
    check_out_date = (stay["check_out"] or bt.today().isoformat()).split(" ")[0]
    bill_no = db.create_bill(
        conn,
        prefix=settings.get("bill_prefix", "ARH"),
        guest={
            "name": stay["guest_name"],
            "phone": stay["guest_phone"],
            "address": stay["guest_address"],
            "pan": stay["guest_pan"],
            "room_no": stay["room_no"],
            "check_in": check_in_date,
            "check_out": check_out_date,
            "nights": nights,
        },
        lines=lines,
        totals=totals.as_dict(),
        payment_method=payment_method,
        user_id=user_id,
        bill_type=bill_type,
        notes=f"Room {stay['room_no']} folio",
        prepared_by=username,
    )

    with conn:
        conn.execute(
            "UPDATE stays SET status = 'checked_out', check_out = ?, nights = ?, "
            "bill_no = ? WHERE stay_id = ?",
            (bt.now().strftime("%Y-%m-%d %H:%M"), nights, bill_no, stay_id),
        )
        conn.execute(
            "UPDATE room_charges SET bill_no = ? WHERE stay_id = ?", (bill_no, stay_id)
        )
        conn.execute(
            "UPDATE reservations SET status = 'checked_out' WHERE reservation_id = ? "
            "AND status = 'checked_in'",
            (stay["reservation_id"],),
        )

    if float(paid or 0) > 0:
        # The payment taken at checkout is already in the ledger: creating the
        # bill records it. Recording it again would double the cash.
        conn.execute(
            "UPDATE payments SET note = ? WHERE bill_no = ?",
            (f"Room {stay['room_no']} checkout", bill_no),
        )

    conn.execute(
        "UPDATE rooms SET housekeeping = 'needs_cleaning' WHERE room_no = ?",
        (stay["room_no"],),
    )
    conn.commit()
    db.log_audit(
        conn,
        "stay.check_out",
        "stay",
        stay_id,
        f"room {stay['room_no']} checked out as {bill_no}",
        user_id,
        username,
    )
    return bill_no


def _line(line: dict):
    from .money import Line

    return Line(
        description=line["description"],
        qty=line["qty"],
        unit_price=line["unit_price"],
        taxable=line.get("taxable", True),
        category=line.get("category", "service"),
        item_id=line.get("item_id"),
        unit=line.get("unit", "pcs"),
    )


def list_stays(
    conn: sqlite3.Connection, status: str | None = "active", room_no: str = ""
) -> list[sqlite3.Row]:
    sql = "SELECT * FROM stays WHERE 1=1"
    params: list = []
    if status and status != "All":
        sql += " AND status = ?"
        params.append(status)
    if room_no:
        sql += " AND room_no LIKE ?"
        params.append(f"%{room_no}%")
    sql += " ORDER BY stay_id DESC"
    return list(conn.execute(sql, params))


def room_history(conn: sqlite3.Connection, room_no: str) -> list[sqlite3.Row]:
    """Past stays in a room, newest first."""
    return list(
        conn.execute(
            "SELECT * FROM stays WHERE room_no = ? AND status = 'checked_out' "
            "ORDER BY check_out DESC, stay_id DESC",
            (room_no,),
        )
    )


# --------------------------------------------------------------------------- #
# occupancy
# --------------------------------------------------------------------------- #
def occupancy(conn: sqlite3.Connection, day: str | None = None) -> dict:
    """Occupancy for a business day.

    Two different measurements, both reported because they answer different
    questions:

    * ``end_of_day`` — how many rooms were occupied at the end of the day.
    * ``across_day`` — how many rooms were occupied at any point during it.
    """
    day = day or bt.today().isoformat()
    rooms = list(
        conn.execute("SELECT room_no FROM rooms WHERE active = 1")
    )
    sellable = len(rooms)

    # Guests who were still in-house at the end of the reporting day.
    end_of_day = conn.execute(
        "SELECT COUNT(*) FROM stays WHERE "
        "substr(COALESCE(check_out, ''), 1, 10) >= ? AND substr(check_in, 1, 10) <= ? "
        "AND status IN ('active','checked_out')",
        (day, day),
    ).fetchone()[0]
    across_day = conn.execute(
        "SELECT COUNT(*) FROM stays WHERE substr(check_in, 1, 10) <= ? AND "
        "(status = 'active' OR substr(COALESCE(check_out, ''), 1, 10) >= ?)",
        (day, day),
    ).fetchone()[0]

    occupied_nights = conn.execute(
        "SELECT COALESCE(SUM(nights), 0) FROM stays WHERE substr(check_in, 1, 10) <= ? "
        "AND (status = 'active' OR substr(COALESCE(check_out, ''), 1, 10) >= ?)",
        (day, day),
    ).fetchone()[0]

    available = sum(
        1
        for room in rooms
        if room_state(conn, room["room_no"])["status"] == STATUS_AVAILABLE
    )
    sellable_rate = round(across_day / sellable * 100, 2) if sellable else 0.0
    return {
        "business_date": day,
        "sellable_rooms": sellable,
        "occupied_end_of_day": int(end_of_day),
        "occupied_across_day": int(across_day),
        "available_now": int(available),
        "occupied_nights": int(occupied_nights),
        "occupancy_rate": sellable_rate,
    }


def room_revenue(conn: sqlite3.Connection, start: str, end: str) -> dict:
    """Room revenue over a business date range."""
    row = conn.execute(
        "SELECT COALESCE(SUM(bi.line_total), 0) FROM bill_items bi "
        "JOIN bills b ON b.bill_id = bi.bill_id "
        "WHERE bi.category = 'room' AND b.status = 'issued' AND b.is_draft = 0 "
        "AND b.bill_date BETWEEN ? AND ?",
        (start, end),
    ).fetchone()
    by_room = list(
        conn.execute(
            "SELECT b.room_no, COUNT(DISTINCT b.bill_id) AS invoices, "
            "COALESCE(SUM(bi.line_total), 0) AS total "
            "FROM bill_items bi JOIN bills b ON b.bill_id = bi.bill_id "
            "WHERE bi.category = 'room' AND b.status = 'issued' AND b.is_draft = 0 "
            "AND b.bill_date BETWEEN ? AND ? AND b.room_no <> '' "
            "GROUP BY b.room_no ORDER BY total DESC",
            (start, end),
        )
    )
    return {"total": round(float(row[0] or 0), 2), "by_room": by_room}


def _validate_dates(check_in: str, check_out: str) -> None:
    try:
        start = date.fromisoformat(str(check_in)[:10])
        end = date.fromisoformat(str(check_out)[:10])
    except ValueError:
        raise RoomError("Dates must be in YYYY-MM-DD format.") from None
    if end < start:
        raise RoomError("The check-out date cannot be before the check-in date.")


def datetime_now() -> str:
    """Current business time, for default fields."""
    return bt.now().strftime("%Y-%m-%d %H:%M")
