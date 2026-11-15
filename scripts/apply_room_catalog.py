#!/usr/bin/env python3
# Copyright 2026 AI Memory System. All rights reserved.
"""Apply the hotel's room types, nightly rates and bed layouts to a webapp DB.

The room board reads ``rooms.type`` / ``rooms.nightly_rate`` and the room
inventory form reads the matching ``catalog_items`` room row, so both must be
updated together. The script is idempotent and safe to run against an existing
database after a fresh install or a price change.
"""
from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = ROOT / "webapp" / "data" / "arati_web.db"

ROOM_TYPES: dict[str, float] = {
    "Standard Room": 3000.0,
    "Deluxe Room": 5000.0,
    "Super Deluxe Room": 5500.0,
    "Suite Deluxe Room": 6500.0,
    "Family Room": 4000.0,
    "Arati Suite Room": 8000.0,
}

# number -> (type, bed layout, rate)
ROOM_SPECS: dict[str, tuple[str, str, float]] = {
    "A-1222": ("Super Deluxe Room", "Twin Bed", 5500.0),
    "A-2222": ("Super Deluxe Room", "Twin Bed", 5500.0),
    "A-2221": ("Super Deluxe Room", "King Size", 5500.0),
    "A-4441": ("Super Deluxe Room", "King Size", 5500.0),
    "A-4442": ("Super Deluxe Room", "Twin Bed", 5500.0),
    "A-2224": ("Deluxe Room", "Single Bed", 5000.0),
    "A-2225": ("Deluxe Room", "Single Bed", 5000.0),
    "A-2226": ("Deluxe Room", "Single Bed", 5000.0),
    "A-4444": ("Deluxe Room", "Twin Bed", 5000.0),
    "A-4445": ("Deluxe Room", "Twin Bed", 5000.0),
    "A-4446": ("Deluxe Room", "Twin Bed", 5000.0),
    "A-5551": ("Suite Deluxe Room", "Master Bed", 6500.0),
    "A-5552": ("Suite Deluxe Room", "Master Bed", 6500.0),
    "A-5554": ("Suite Deluxe Room", "Master Bed", 6500.0),
    "A-5555": ("Arati Suite Room", "Master Bed", 8000.0),
    "B-111": ("Family Room", "1 Master + 1 Single", 4000.0),
    "B-221": ("Family Room", "1 Master + 1 Single", 4000.0),
    "B-441": ("Family Room", "1 Master + 1 Single", 4000.0),
    "B-555": ("Family Room", "1 Master + 1 Single", 4000.0),
    "B-112": ("Standard Room", "Twin Bed", 3000.0),
    "B-114": ("Standard Room", "Twin Bed", 3000.0),
    "B-222": ("Standard Room", "Twin Bed", 3000.0),
    "B-224": ("Standard Room", "Twin Bed", 3000.0),
    "B-442": ("Standard Room", "Twin Bed", 3000.0),
    "B-444": ("Standard Room", "Twin Bed", 3000.0),
}


def _room_type_id(conn: sqlite3.Connection, name: str, rate: float) -> int:
    row = conn.execute(
        "SELECT id FROM catalog_items WHERE category = 'room' AND name = ?",
        (name,),
    ).fetchone()
    if row is not None:
        conn.execute(
            "UPDATE catalog_items SET rate = ?, active = 1, unit = 'night' WHERE id = ?",
            (rate, row[0]),
        )
        return int(row[0])
    cursor = conn.execute(
        "INSERT INTO catalog_items "
        "(name, category, rate, active, item_code, unit, taxable, sort_order, menu_group) "
        "VALUES (?, 'room', ?, 1, '', 'night', 1, 0, '')",
        (name, rate),
    )
    return int(cursor.lastrowid)


def apply_room_catalog(conn: sqlite3.Connection) -> list[str]:
    """Update room types/rates and return room numbers that were not found."""
    type_ids = {
        name: _room_type_id(conn, name, rate) for name, rate in ROOM_TYPES.items()
    }

    missing: list[str] = []
    for number, (type_name, bed_type, rate) in ROOM_SPECS.items():
        cursor = conn.execute(
            "UPDATE rooms SET type = ?, bed_type = ?, nightly_rate = ?, "
            "nightly_rate_override = 0, room_type_item_id = ?, floor = ? "
            "WHERE number = ?",
            (
                type_name,
                bed_type,
                rate,
                type_ids[type_name],
                "B" if number.startswith("B") else "A",
                number,
            ),
        )
        if cursor.rowcount == 0:
            missing.append(number)

    # ``King Room`` was a legacy bucket; retire it when nothing points at it.
    king = conn.execute(
        "SELECT id FROM catalog_items WHERE category = 'room' AND name = 'King Room'"
    ).fetchone()
    if king is not None:
        used = conn.execute(
            "SELECT COUNT(*) FROM rooms WHERE room_type_item_id = ?", (king[0],)
        ).fetchone()[0]
        if not used:
            conn.execute("UPDATE catalog_items SET active = 0 WHERE id = ?", (king[0],))
    return missing


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if not args.db.is_file():
        parser.error(f"database not found: {args.db}")

    conn = sqlite3.connect(args.db)
    try:
        missing = apply_room_catalog(conn)
        if args.dry_run:
            conn.rollback()
            print(f"Dry run: would update {len(ROOM_SPECS) - len(missing)} rooms")
        else:
            conn.commit()
            print(f"Updated {len(ROOM_SPECS) - len(missing)} rooms")
        if missing:
            print("Missing room numbers: " + ", ".join(missing))
        return 0
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
