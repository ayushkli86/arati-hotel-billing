from __future__ import annotations

from sqlalchemy.orm import Session

from ..models import Room


def mark_occupied(db: Session, room_id: int) -> Room:
    room = db.get(Room, room_id)
    if not room:
        raise ValueError("Room not found")
    room.status = "occupied"
    return room


def mark_available(db: Session, room_id: int) -> Room:
    room = db.get(Room, room_id)
    if not room:
        raise ValueError("Room not found")
    room.status = "available"
    if not room.housekeeping_status:
        room.housekeeping_status = "clean"
    return room


def set_status(db: Session, room_id: int, status: str) -> Room:
    room = db.get(Room, room_id)
    if not room:
        raise ValueError("Room not found")
    allowed = {"available", "occupied", "reserved", "maintenance", "cleaning"}
    if status not in allowed:
        raise ValueError(f"Invalid room status: {status}")
    room.status = status
    return room
