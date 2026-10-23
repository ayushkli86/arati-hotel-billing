"""Order vocabulary, numbering and status rules shared by the web app and bot."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .models import Order
from .services import local_now

ORDER_STATUSES = ("new", "confirmed", "preparing", "ready", "completed", "cancelled")
OPEN_STATUSES = ("new", "confirmed", "preparing", "ready")

STATUS_LABELS = {
    "new": "New request",
    "confirmed": "Confirmed",
    "preparing": "Preparing",
    "ready": "Ready",
    "completed": "Completed",
    "cancelled": "Cancelled",
}

STATUS_BADGES = {
    "new": "amber",
    "confirmed": "teal",
    "preparing": "amber",
    "ready": "teal",
    "completed": "slate",
    "cancelled": "rose",
}

KIND_LABELS = {
    "food": "Food & drinks",
    "room": "Room booking",
    "service": "Service / event",
}

FULFILMENT_LABELS = {
    "pickup": "Pickup",
    "delivery": "Delivery",
    "dine_in": "Dine in",
    "room": "To room",
}

# Orders move forward through one pipeline. Jumping forward is allowed because a
# small kitchen often skips the "preparing" tap; going back is not, so the record
# stays an honest history of what the front desk actually did.
_STATUS_RANK = {"new": 0, "confirmed": 1, "preparing": 2, "ready": 3, "completed": 4}


def can_transition(current: str, target: str) -> bool:
    if target not in ORDER_STATUSES or current not in ORDER_STATUSES:
        return False
    if current in {"completed", "cancelled"}:
        return False
    if target == "cancelled":
        return True
    return _STATUS_RANK.get(target, -1) > _STATUS_RANK.get(current, -1)


def next_status(current: str) -> str | None:
    """The single forward action offered as the primary button."""
    sequence = ("new", "confirmed", "preparing", "ready", "completed")
    try:
        return sequence[sequence.index(current) + 1]
    except (ValueError, IndexError):
        return None


def next_order_number(db: Session, instant: datetime | None = None) -> str:
    day = (instant or local_now()).strftime("%Y%m%d")
    prefix = f"ORD-{day}-"
    count = db.scalar(
        select(func.count(Order.id)).where(Order.order_number.like(f"{prefix}%"))
    ) or 0
    while True:
        count += 1
        candidate = f"{prefix}{count:04d}"
        if db.scalar(select(Order.id).where(Order.order_number == candidate)) is None:
            return candidate


def item_summary(order: Order, limit: int = 2) -> str:
    items = list(order.items)
    parts = [
        f"{int(item.quantity) if item.quantity == int(item.quantity) else item.quantity}"
        f"× {item.description}"
        for item in items[:limit]
    ]
    if len(items) > limit:
        parts.append(f"+{len(items) - limit} more")
    return ", ".join(parts) or "—"

