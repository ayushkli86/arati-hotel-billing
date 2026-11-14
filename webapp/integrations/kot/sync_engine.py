# Copyright 2026 AI Memory System. All rights reserved.
"""The bidirectional half of the KOT integration.

Responsibilities are deliberately split by ownership:

* **Cloud → local (pull).** Kitchen and payment status of a cloud ticket is
  authoritative, so cloud rows are upserted into ``kot_orders`` every cycle.
  A persisted cursor (last cloud ticket id) plus a bounded refresh of the
  tickets that are still open keeps the local mirror current without ever
  re-reading the whole history.
* **Local → cloud (push).** The hotel's own ``Kot`` rows (cut in the webapp)
  and the admin menu are authoritative locally. They are queued in
  ``kot_sync_queue`` and pushed over HTTPS; nothing is ever deleted on the
  other side.

Nothing in here writes to ``invoices``/``payments`` unless a linked cloud
ticket already points at a local KOT — billing stays local-only.
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ...database import SessionLocal
from ...models import AuditLog, CatalogItem, Guest, Invoice, Kot, Room, RoomCharge, Stay
from .client import KotApiError, KotClient
from .config import KotSyncSettings
from .models import KotOrder, KotOrderItem, KotSyncQueue, KotSyncState, utcnow

_log = logging.getLogger("webapp.kot_sync")

BUSINESS_TZ = ZoneInfo("Asia/Kathmandu")
UUID_NAMESPACE = uuid.uuid5(uuid.NAMESPACE_URL, "https://arati-hotel.example/kot")

CURSOR_KEY = "kots.cursor"
MENU_MAP_KEY = "menu.map"
ROOMS_MAP_KEY = "rooms.map"
LAST_RUN_KEY = "sync.last_run_at"
LAST_ERROR_KEY = "sync.last_error"
LAST_CURSOR_OK_KEY = "sync.last_cursor_ok_at"

CLOUD_TO_LOCAL_STATUS = {
    "pending": "new",
    "preparing": "preparing",
    "ready": "ready",
    "served": "served",
    "cancelled": "cancelled",
}
OPEN_STATUSES = ("new", "preparing", "ready")
# Counts on the dashboard are keyed by the cloud status names.
OPEN_CLOUD_STATUSES = ("pending", "preparing", "ready")
MAX_ATTEMPTS = 5
FOOD_CATEGORIES = {"restaurant", "food", "kitchen", "bar", "beverage", "beverages"}
_ROOM_TABLE = re.compile(r"^(?:room|suite)\s*[#-]?\s*(\d+[a-z]?)", re.IGNORECASE)


@dataclass
class CycleResult:
    """What one sync cycle did — shown on the dashboard and in the log."""

    pulled: int = 0
    refreshed: int = 0
    queued: int = 0
    pushed_orders: int = 0
    pushed_dishes: int = 0
    pushed_rooms: int = 0
    billed: int = 0
    failed: int = 0
    cursor: int = 0
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


# --------------------------------------------------------------------- helpers
def order_uuid_for(cloud_kot_id: int) -> str:
    """Deterministic UUID for a cloud ticket (cloud ids are integers)."""
    return str(uuid.uuid5(UUID_NAMESPACE, f"kot:{int(cloud_kot_id)}"))


def get_state(db: Session, key: str, default: str = "") -> str:
    row = db.get(KotSyncState, key)
    return row.value if row is not None and row.value is not None else default


def set_state(db: Session, key: str, value: str) -> None:
    row = db.get(KotSyncState, key)
    if row is None:
        db.add(KotSyncState(key=key, value=str(value)))
    else:
        row.value = str(value)
        row.updated_at = utcnow()


def _parse_cloud_time(value: object) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


def _money(value: object) -> Decimal:
    try:
        return Decimal(str(value)).quantize(Decimal("0.01"))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal("0.00")


def business_date_for(moment: datetime | None) -> str:
    if moment is None:
        return ""
    return moment.replace(tzinfo=timezone.utc).astimezone(BUSINESS_TZ).date().isoformat()


def _order_shape(table_name: str) -> tuple[str, str]:
    """Derive (order_type, room_number) from a cloud table name."""
    name = (table_name or "").strip()
    if not name:
        return "walk-in", ""
    match = _ROOM_TABLE.match(name)
    if match:
        return "room", match.group(1)
    return "table", ""


def resolve_room(db: Session, room_number: str) -> tuple[Room | None, Stay | None, Guest | None, str, str]:
    """Resolve a cloud room reference to a local room/stay/guest.

    Returns ``(room, stay, guest, status, reason)``. Status is one of
    ``resolved``, ``unknown_room``, ``vacant``, ``checked_out``.
    """
    room = db.scalar(select(Room).where(Room.number == str(room_number).strip()))
    if room is None:
        return None, None, None, "unknown_room", f"Room {room_number} does not exist locally."
    stay = db.scalar(
        select(Stay).where(
            Stay.room_id == room.id,
            Stay.status == "checked_in",
            Stay.check_out.is_(None),
        ).order_by(Stay.check_in.desc())
    )
    if stay is None:
        last = db.scalar(
            select(Stay).where(Stay.room_id == room.id).order_by(Stay.check_in.desc())
        )
        if last is not None and (last.check_out is not None or last.status != "checked_in"):
            return room, last, None, "checked_out", f"Room {room_number} has no active check-in (last guest checked out)."
        return room, None, None, "vacant", f"Room {room_number} is vacant."
    guest = db.get(Guest, stay.guest_id) if stay.guest_id else None
    if guest is not None and not guest.active:
        return room, stay, guest, "checked_out", f"Guest for room {room_number} is inactive."
    return room, stay, guest, "resolved", ""


def _reverse_menu_map(db: Session) -> dict[str, int]:
    """Cloud dish id -> local catalog item id."""
    mapping = {}
    raw = get_state(db, MENU_MAP_KEY, "{}")
    try:
        parsed = json.loads(raw or "{}")
    except (TypeError, ValueError):
        return mapping
    if not isinstance(parsed, dict):
        return mapping
    for local_id, cloud_id in parsed.items():
        try:
            mapping[str(cloud_id)] = int(local_id)
        except (TypeError, ValueError):
            continue
    return mapping


def _validate_menu_line(db: Session, line: dict, price: Decimal) -> tuple[int | None, bool, bool, str]:
    dish_id = line.get("dish_id")
    reverse = _reverse_menu_map(db)
    local_id: int | None = None
    if dish_id is not None:
        local_id = reverse.get(str(dish_id))
    if local_id is None:
        return None, True, True, "Unmapped cloud dish; cannot validate against local menu."
    item = db.get(CatalogItem, local_id)
    if item is None:
        return local_id, False, True, "Local menu item missing."
    available = bool(item.active)
    price_matches = abs(float(item.rate or 0) - float(price or 0)) <= 0.009
    note = ""
    if not available:
        note = "Menu item disabled locally."
    if not price_matches:
        note = (note + " " if note else "") + (
            f"Price mismatch: cloud {price}, local {item.rate}."
        )
    return local_id, available, price_matches, note


def queue_event(
    db: Session,
    event_type: str,
    payload: dict,
    *,
    dedupe_key: str | None = None,
) -> KotSyncQueue | None:
    """Idempotent enqueue. Returns None when the same job is already waiting."""
    if dedupe_key:
        existing = db.scalar(
            select(KotSyncQueue).where(KotSyncQueue.dedupe_key == dedupe_key)
        )
        if existing is not None:
            return None
    row = KotSyncQueue(
        direction="out",
        event_type=event_type,
        dedupe_key=dedupe_key,
        payload=json.dumps(payload, default=str),
        status="pending",
    )
    db.add(row)
    return row


# ------------------------------------------------------------------- mirroring
def upsert_cloud_kot(db: Session, payload: dict) -> tuple[KotOrder, bool]:
    """Insert or update one mirrored cloud ticket. Returns (row, created)."""
    cloud_id = int(payload["id"])
    order = db.scalar(select(KotOrder).where(KotOrder.cloud_kot_id == cloud_id))
    created = order is None
    if order is None:
        order = KotOrder(cloud_kot_id=cloud_id, order_uuid=order_uuid_for(cloud_id))
        db.add(order)

    table_name = str(payload.get("table_name") or "")
    order_type, room_number = _order_shape(table_name)
    status = str(payload.get("status") or "pending").lower()
    paid = bool(payload.get("paid"))

    # Room/customer resolution happens here, on every upsert, so a room that
    # checks in later gets resolved on the next refresh.
    room_obj = stay_obj = guest_obj = None
    if order_type == "room" and room_number:
        room_obj, stay_obj, guest_obj, resolution_status, resolution_reason = resolve_room(
            db, room_number
        )
    else:
        resolution_status = "not_room"
        resolution_reason = ""

    order.cloud_number = int(payload["number"]) if payload.get("number") is not None else None
    order.kot_number = f"KOT-{order.cloud_number}" if order.cloud_number else ""
    order.order_type = order_type
    order.room_number = room_number
    order.table_name = table_name
    order.customer_ref = order.kot_number
    order.local_room_id = room_obj.id if room_obj is not None else None
    order.local_stay_id = stay_obj.id if stay_obj is not None else None
    order.local_guest_id = guest_obj.id if guest_obj is not None else None
    order.resolution_status = resolution_status
    order.resolution_reason = resolution_reason
    order.waiter = str(payload.get("waiter") or "")
    order.notes = str(payload.get("note") or "")
    order.kitchen_status = status
    order.payment_status = "paid" if paid else "unpaid"
    order.cloud_created_at = _parse_cloud_time(payload.get("created_at"))
    order.business_date = business_date_for(order.cloud_created_at)

    lines = payload.get("lines") or []
    if not isinstance(lines, list):
        lines = []
    computed = Decimal("0.00")
    existing_items = {item.position: item for item in order.items}
    keep: set[int] = set()
    menu_issues: list[dict] = []
    for position, line in enumerate(lines):
        if not isinstance(line, dict):
            continue
        qty = int(line.get("qty") or 1)
        price = _money(line.get("price"))
        computed += price * qty
        item = existing_items.get(position)
        if item is None:
            item = KotOrderItem(position=position)
            order.items.append(item)
        local_id, available, price_ok, note = _validate_menu_line(db, line, price)
        item.local_catalog_item_id = local_id
        item.local_available = available
        item.price_matches = price_ok
        if note:
            menu_issues.append({"position": position, "dish": str(line.get("name") or ""), "issue": note})
        item.cloud_line_id = (
            int(line["id"]) if isinstance(line.get("id"), int) else None
        )
        item.dish_id = int(line["dish_id"]) if isinstance(line.get("dish_id"), int) else None
        item.dish_name = str(line.get("name") or "")
        item.category = str(line.get("category") or "")
        item.station = str(line.get("station") or "kitchen")
        item.qty = qty
        item.unit_price = price
        item.line_total = price * qty
        keep.add(position)
    for position, item in existing_items.items():
        if position not in keep:
            order.items.remove(item)

    order.menu_issues = json.dumps(menu_issues)
    # Preserve billing decision once made; otherwise derive from resolution.
    if order.billing_status not in ("billed", "review"):
        if order_type == "room":
            order.billing_status = "pending" if resolution_status == "resolved" else "review"
        else:
            order.billing_status = "not_applicable"
    order.total = _money(payload.get("total") if payload.get("total") is not None else computed)
    order.cloud_updated_at = utcnow()
    order.synced_at = utcnow()
    return order, created


def link_billing(db: Session) -> int:
    """Attach local receipt references to mirrored tickets that now have one.

    A cloud ticket is never the source of an invoice; this only records the
    mapping the hotel created locally, and writes an audit line when it does.
    """
    linked = 0
    rows = db.scalars(
        select(KotOrder).where(
            KotOrder.local_kot_id.is_not(None),
            KotOrder.local_invoice_id.is_(None),
        )
    ).all()
    for order in rows:
        kot = db.get(Kot, order.local_kot_id)
        if kot is None or kot.invoice_id is None:
            continue
        invoice = db.get(Invoice, kot.invoice_id)
        if invoice is None:
            continue
        order.local_invoice_id = invoice.id
        order.local_invoice_number = invoice.invoice_number
        db.add(AuditLog(
            user_id=None,
            username="kot-sync",
            action="kot.billing_link",
            entity="kot_order",
            entity_id=order.order_uuid,
            detail=f"{order.kot_number or order.cloud_kot_id} → {invoice.invoice_number}",
        ))
        linked += 1
    return linked


def _room_charge_category(item: KotOrderItem) -> str:
    category = str(item.category or "").lower()
    name = str(item.dish_name or "").lower()
    if category in {"beverage", "beverages", "drink", "drinks", "bar", "tea", "coffee"}:
        return "beverage"
    if any(word in name for word in ("tea", "coffee", "juice", "drink", "soda")):
        return "beverage"
    return "food"


def post_room_charges(db: Session) -> int:
    """Post resolved room-service tickets to the stay folio exactly once.

    Idempotent: only tickets whose ``billing_status`` is still ``pending`` are
    touched, and the status flips to ``billed`` in the same transaction.
    Vacant/checked-out/unknown rooms are moved to ``review`` instead.
    """
    billed = 0
    rows = db.scalars(
        select(KotOrder).where(
            KotOrder.order_type == "room",
            KotOrder.billing_status.in_(("pending", "review")),
        )
    ).all()
    for order in rows:
        if order.resolution_status != "resolved" or order.local_stay_id is None:
            # Re-resolve in case the room checked in since last cycle.
            room_obj, stay_obj, guest_obj, status, reason = resolve_room(
                db, order.room_number
            )
            order.local_room_id = room_obj.id if room_obj is not None else None
            order.local_stay_id = stay_obj.id if stay_obj is not None else None
            order.local_guest_id = guest_obj.id if guest_obj is not None else None
            order.resolution_status = status
            order.resolution_reason = reason
            if status != "resolved":
                order.billing_status = "review"
                continue
        stay = db.get(Stay, order.local_stay_id)
        room = db.get(Room, order.local_room_id) if order.local_room_id else None
        if stay is None or stay.status != "checked_in" or stay.check_out is not None:
            order.resolution_status = "checked_out"
            order.resolution_reason = (
                f"Room {order.room_number} has no active check-in."
            )
            order.billing_status = "review"
            continue
        if order.billing_status == "billed":
            continue
        charge_date = order.business_date or ""
        if not charge_date:
            charge_date = order.cloud_created_at.date().isoformat() if order.cloud_created_at else ""
        for item in order.items:
            amount = item.line_total
            if amount is None or amount <= 0:
                amount = (item.unit_price or Decimal("0")) * (item.qty or 0)
            if amount <= 0:
                continue
            db.add(RoomCharge(
                stay_id=stay.id,
                room_number=room.number if room is not None else order.room_number,
                description=f"{item.dish_name} (KOT {order.display_number})"[:240],
                category=_room_charge_category(item),
                quantity=Decimal(str(item.qty or 1)),
                unit_price=item.unit_price or Decimal("0.00"),
                amount=amount,
                charge_date=charge_date,
                created_at=utcnow(),
                kot_id=None,
            ))
        order.billing_status = "billed"
        order.billed_at = utcnow()
        db.add(AuditLog(
            user_id=None,
            username="kot-sync",
            action="kot.room_charge_post",
            entity="kot_order",
            entity_id=order.order_uuid,
            detail=f"{order.kot_number or order.cloud_kot_id} → Room {order.room_number} folio",
        ))
        billed += 1
    return billed


# ---------------------------------------------------------------------- engine
class SyncEngine:
    """One engine per process; the poller owns the only instance."""

    def __init__(
        self,
        client: KotClient,
        settings: KotSyncSettings,
        *,
        session_factory=SessionLocal,
    ) -> None:
        self.client = client
        self.settings = settings
        self.session_factory = session_factory

    # ---------------------------------------------------------------- cycles
    async def run_cycle(self) -> CycleResult:
        result = CycleResult(cursor=self._cursor())
        try:
            await self.pull(result)
            if self.settings.open_refresh_limit:
                await self.refresh_open(result)
            with self.session_factory() as db:
                result.billed += post_room_charges(db)
                link_billing(db)
                db.commit()
            if self.settings.push_menu:
                await self.push_menu(result)
            if self.settings.push_rooms:
                await self.push_rooms(result)
            if self.settings.push_orders:
                self.enqueue_local_orders(result)
                await self.flush_queue(result)
            self._record_run(result)
        except KotApiError as exc:
            result.errors.append(str(exc))
            self._record_error(str(exc))
        except Exception as exc:  # noqa: BLE001 - a sync failure must never crash the app
            _log.exception("kot sync: cycle failed")
            result.errors.append(f"{type(exc).__name__}: {exc}")
            self._record_error(str(exc))
        return result

    def _cursor(self) -> int:
        with self.session_factory() as db:
            try:
                return int(get_state(db, CURSOR_KEY, "0") or 0)
            except ValueError:
                return 0

    def _record_run(self, result: CycleResult) -> None:
        with self.session_factory() as db:
            set_state(db, LAST_RUN_KEY, utcnow().isoformat(timespec="seconds"))
            set_state(db, LAST_ERROR_KEY, "; ".join(result.errors)[:500])
            if result.pulled:
                set_state(db, LAST_CURSOR_OK_KEY, utcnow().isoformat(timespec="seconds"))
            db.commit()

    def _record_error(self, message: str) -> None:
        try:
            with self.session_factory() as db:
                set_state(db, LAST_ERROR_KEY, message[:500])
                set_state(db, LAST_RUN_KEY, utcnow().isoformat(timespec="seconds"))
                db.commit()
        except Exception:  # noqa: BLE001
            _log.debug("kot sync: could not persist error state", exc_info=True)

    # ------------------------------------------------------------------ pull
    async def pull(self, result: CycleResult) -> None:
        cursor = self._cursor()
        while True:
            page = await self.client.list_kots(since_id=cursor, limit=self.settings.page_size)
            if not page:
                break
            highest = cursor
            for payload in page:
                try:
                    highest = max(highest, int(payload["id"]))
                except (KeyError, TypeError, ValueError):
                    continue
            stored, skipped = self._store_page(page)
            result.pulled += stored
            result.failed += skipped
            cursor = highest
            result.cursor = cursor
            if len(page) < self.settings.page_size:
                break
        # Cursor and rows commit together, so a restart resumes exactly once.
        with self.session_factory() as db:
            set_state(db, CURSOR_KEY, str(cursor))
            db.commit()

    def _store_page(self, page: list[dict]) -> tuple[int, int]:
        stored = failed = 0
        with self.session_factory() as db:
            try:
                for payload in page:
                    try:
                        upsert_cloud_kot(db, payload)
                        stored += 1
                    except Exception:  # noqa: BLE001 - one bad row must not stop the page
                        failed += 1
                        _log.warning("kot sync: skipped malformed ticket", exc_info=True)
                link_billing(db)
                db.commit()
            except Exception:
                db.rollback()
                raise
        return stored, failed

    async def refresh_open(self, result: CycleResult) -> None:
        """Re-read tickets that are still open so status changes land promptly.

        A cursor cannot see a status change on an older ticket, so the open
        ones are refreshed explicitly (bounded by ``open_refresh_limit``).
        """
        with self.session_factory() as db:
            ids = db.scalars(
                select(KotOrder.cloud_kot_id)
                .where(
                    KotOrder.payment_status != "paid",
                    ~KotOrder.kitchen_status.in_(["served", "cancelled"]),
                )
                .order_by(KotOrder.cloud_kot_id.desc())
                .limit(self.settings.open_refresh_limit)
            ).all()
        for cloud_id in ids:
            try:
                payload = await self.client.get_kot(cloud_id)
            except KotApiError as exc:
                result.errors.append(f"refresh {cloud_id}: {exc}")
                continue
            with self.session_factory() as db:
                upsert_cloud_kot(db, payload)
                link_billing(db)
                db.commit()
            result.refreshed += 1

    # ------------------------------------------------------- local → cloud
    def enqueue_local_orders(self, result: CycleResult) -> None:
        """Queue webapp KOTs that the cloud does not know about yet."""
        with self.session_factory() as db:
            mapped = set(
                db.scalars(
                    select(KotOrder.local_kot_id).where(KotOrder.local_kot_id.is_not(None))
                ).all()
            )
            rows = db.scalars(
                select(Kot)
                .where(Kot.status.in_(self.settings.push_order_statuses))
                .order_by(Kot.id.asc())
                .limit(50)
            ).all()
            queued = 0
            for kot in rows:
                if kot.id in mapped:
                    continue
                payload = {
                    "local_kot_id": kot.id,
                    "kot_number": kot.kot_number,
                    "table_number": kot.table_number,
                    "room_number": kot.room_number,
                    "guest_name": kot.guest_name,
                    "issued_by": kot.issued_by_name,
                    "notes": kot.notes,
                    "items": self._local_kot_items(kot),
                }
                if queue_event(
                    db, "order.create", payload, dedupe_key=f"kot:{kot.id}"
                ) is not None:
                    queued += 1
            db.commit()
            result.queued += queued

    @staticmethod
    def _local_kot_items(kot: Kot) -> list[dict]:
        try:
            rows = json.loads(kot.items or "[]")
        except (TypeError, ValueError):
            return []
        items = []
        for row in rows if isinstance(rows, list) else []:
            if not isinstance(row, dict):
                continue
            name = str(row.get("particular") or row.get("name") or "").strip()
            if not name:
                continue
            try:
                qty = int(Decimal(str(row.get("qty") or row.get("quantity") or 1)))
            except (InvalidOperation, TypeError, ValueError):
                qty = 1
            try:
                price = float(row.get("rate") or row.get("price") or 0)
            except (TypeError, ValueError):
                price = 0.0
            items.append({"name": name, "qty": max(1, qty), "price": price})
        return items

    async def push_menu(self, result: CycleResult) -> None:
        """Reconcile the cloud menu with the local admin catalog.

        Local wins for name/price/availability. Nothing is deleted: a dish that
        disappears locally is simply left available=false on the cloud so past
        tickets stay readable.
        """
        with self.session_factory() as db:
            local = db.scalars(
                select(CatalogItem).where(
                    CatalogItem.active.is_(True),
                    func.lower(CatalogItem.category).in_(sorted(FOOD_CATEGORIES)),
                ).order_by(CatalogItem.name)
            ).all()
            mapping = self._menu_map(db)
        if not local:
            return
        try:
            cloud_dishes = await self.client.list_dishes()
        except KotApiError as exc:
            result.errors.append(f"menu: {exc}")
            return
        by_name = {
            str(dish.get("name") or "").strip().lower(): dish for dish in cloud_dishes
        }
        changed = 0
        with self.session_factory() as db:
            for item in local:
                key = item.name.strip().lower()
                payload = {
                    "name": item.name.strip()[:120],
                    "category": (item.menu_group or item.category or "Mains")[:60],
                    "price": float(item.rate or 0),
                    "available": bool(item.active),
                    "station": _station_for(item),
                }
                dish = by_name.get(key)
                try:
                    if dish is None:
                        created = await self.client.create_dish(payload)
                        by_name[key] = created
                        mapping[str(item.id)] = int(created["id"])
                        changed += 1
                    else:
                        mapping[str(item.id)] = int(dish["id"])
                        if _dish_changed(dish, payload):
                            updated = await self.client.update_dish(int(dish["id"]), payload)
                            by_name[key] = updated
                            changed += 1
                except KotApiError as exc:
                    result.errors.append(f"menu {item.name}: {exc}")
            set_state(db, MENU_MAP_KEY, json.dumps(mapping))
            db.commit()
        result.pushed_dishes += changed

    async def push_rooms(self, result: CycleResult) -> None:
        """Mirror the local room list into the cloud as dining tables.

        A hotel room is a place a waiter can cut a KOT against (room service),
        so each active room becomes a table named ``Room <number>`` in the
        cloud app. Existing tables are updated in place; nothing is deleted,
        so manually created dining tables and past tickets stay intact.
        """
        with self.session_factory() as db:
            local = db.scalars(
                select(Room).where(Room.active.is_(True)).order_by(Room.number)
            ).all()
            mapping = self._rooms_map(db)
        if not local:
            return
        try:
            cloud_tables = await self.client.list_tables()
        except KotApiError as exc:
            result.errors.append(f"rooms: {exc}")
            return
        by_name = {
            str(table.get("name") or "").strip().lower(): table
            for table in cloud_tables
        }
        changed = 0
        with self.session_factory() as db:
            for room in local:
                name = f"Room {room.number.strip()}"[:40]
                key = name.strip().lower()
                payload = {
                    "name": name,
                    "zone": "Room",
                    "seats": 2,
                    "is_active": True,
                }
                table = by_name.get(key)
                try:
                    if table is None:
                        created = await self.client.create_table(payload)
                        by_name[key] = created
                        mapping[str(room.id)] = int(created["id"])
                        changed += 1
                    else:
                        mapping[str(room.id)] = int(table["id"])
                        if _table_changed(table, payload):
                            updated = await self.client.update_table(
                                int(table["id"]), payload
                            )
                            by_name[key] = updated
                            changed += 1
                except KotApiError as exc:
                    result.errors.append(f"room {room.number}: {exc}")
            set_state(db, ROOMS_MAP_KEY, json.dumps(mapping))
            db.commit()
        result.pushed_rooms += changed

    @staticmethod
    def _rooms_map(db: Session) -> dict[str, int]:
        raw = get_state(db, ROOMS_MAP_KEY, "{}")
        try:
            parsed = json.loads(raw or "{}")
            return {str(k): int(v) for k, v in parsed.items()}
        except (TypeError, ValueError, AttributeError):
            return {}

    @staticmethod
    def _menu_map(db: Session) -> dict[str, int]:
        raw = get_state(db, MENU_MAP_KEY, "{}")
        try:
            parsed = json.loads(raw or "{}")
        except (TypeError, ValueError):
            return {}
        if not isinstance(parsed, dict):
            return {}
        out: dict[str, int] = {}
        for key, value in parsed.items():
            try:
                out[str(key)] = int(value)
            except (TypeError, ValueError):
                continue
        return out

    async def flush_queue(self, result: CycleResult) -> None:
        """Send queued outbound jobs, oldest first, with retry bookkeeping."""
        with self.session_factory() as db:
            jobs = db.scalars(
                select(KotSyncQueue)
                .where(KotSyncQueue.status == "pending")
                .order_by(KotSyncQueue.id.asc())
                .limit(25)
            ).all()
            job_data = [(job.id, job.event_type, job.payload, job.dedupe_key) for job in jobs]

        for job_id, event_type, payload, dedupe_key in job_data:
            try:
                if event_type == "order.create":
                    await self._push_order(json.loads(payload or "{}"), dedupe_key or "")
                    result.pushed_orders += 1
                    self._finish_job(job_id, ok=True)
                else:
                    raise KotApiError(f"unknown event {event_type}")
            except Exception as exc:  # noqa: BLE001 - recorded, then retried later
                message = str(exc)[:300]
                result.errors.append(message)
                result.failed += 1
                self._finish_job(job_id, ok=False, error=message)

    def _finish_job(self, job_id: int, *, ok: bool, error: str = "") -> None:
        with self.session_factory() as db:
            job = db.get(KotSyncQueue, job_id)
            if job is None:
                return
            job.updated_at = utcnow()
            if ok:
                job.status = "sent"
                job.sent_at = utcnow()
                job.last_error = ""
            else:
                job.attempts += 1
                job.last_error = error
                if job.attempts >= MAX_ATTEMPTS:
                    job.status = "failed"
            db.commit()

    async def _push_order(self, payload: dict, dedupe_key: str) -> None:
        local_id = int(payload["local_kot_id"])
        items = payload.get("items") or []
        if not items:
            raise KotApiError("order has no kitchen items")

        dishes = await self.client.list_dishes()
        by_name = {
            str(dish.get("name") or "").strip().lower(): dish for dish in dishes
        }
        lines: list[dict] = []
        with self.session_factory() as db:
            catalog = {
                str(row.name).strip().lower(): row
                for row in db.scalars(select(CatalogItem)).all()
            }
        for item in items:
            name = str(item.get("name") or "").strip()
            key = name.lower()
            dish = by_name.get(key)
            if dish is None:
                row = catalog.get(key)
                dish = await self.client.create_dish({
                    "name": name[:120],
                    "category": ((row.menu_group or row.category) if row else "Mains")[:60],
                    "price": float(item.get("price") or (row.rate if row else 0) or 0),
                    "available": True,
                    "station": _station_for(row) if row else "kitchen",
                })
                by_name[key] = dish
            lines.append({"dish_id": int(dish["id"]), "qty": int(item.get("qty") or 1)})

        table_id = await self._cloud_table_id(payload)
        note_parts = [str(payload.get("notes") or "").strip()]
        if payload.get("room_number"):
            note_parts.append(f"Room {payload['room_number']}")
        elif payload.get("table_number"):
            note_parts.append(f"Table {payload['table_number']}")
        if payload.get("guest_name"):
            note_parts.append(str(payload["guest_name"]))
        note = " · ".join(part for part in note_parts if part)

        created = await self.client.create_kot(
            {
                "table_id": table_id,
                "waiter": (str(payload.get("issued_by") or "Front desk"))[:120],
                "note": note[:500],
                "lines": lines,
            },
            idempotency_key=dedupe_key or f"arati-kot-{local_id}",
        )
        with self.session_factory() as db:
            order, _ = upsert_cloud_kot(db, created)
            order.local_kot_id = local_id
            link_billing(db)
            db.commit()

    async def _cloud_table_id(self, payload: dict) -> int | None:
        wanted = str(payload.get("table_number") or "").strip()
        if not wanted:
            return None
        try:
            tables = await self.client.list_tables()
        except KotApiError:
            return None
        for table in tables:
            if str(table.get("name") or "").strip().lower() == wanted.lower():
                return int(table["id"])
        return None


def _station_for(item: CatalogItem | None) -> str:
    group = f"{getattr(item, 'menu_group', '') or ''} {getattr(item, 'category', '') or ''}".lower()
    if "bar" in group or "beverage" in group or "drink" in group or "coffee" in group or "tea" in group:
        return "bar"
    return "kitchen"


def _dish_changed(dish: dict, payload: dict) -> bool:
    try:
        if str(dish.get("name") or "").strip() != payload["name"]:
            return True
        if str(dish.get("category") or "").strip() != payload["category"]:
            return True
        if abs(float(dish.get("price") or 0) - float(payload["price"])) > 0.009:
            return True
        if bool(dish.get("available")) != bool(payload["available"]):
            return True
        if str(dish.get("station") or "").strip() != payload["station"]:
            return True
    except (TypeError, ValueError):
        return True
    return False


def _table_changed(table: dict, payload: dict) -> bool:
    try:
        if str(table.get("name") or "").strip() != payload["name"]:
            return True
        if str(table.get("zone") or "").strip() != payload["zone"]:
            return True
        if int(table.get("seats") or 0) != int(payload["seats"]):
            return True
        if bool(table.get("is_active")) != bool(payload["is_active"]):
            return True
    except (TypeError, ValueError):
        return True
    return False


# ------------------------------------------------------------------ dashboard
@contextmanager
def _session_scope(source):
    """Accept a session factory or a live session; close only what we opened."""
    if isinstance(source, Session):
        yield source
    else:
        with source() as db:
            yield db


def snapshot(session_factory=SessionLocal) -> dict:
    """Everything the /kot-integration page needs, computed in one session."""
    with _session_scope(session_factory) as db:
        counts = {
            status: db.scalar(
                select(func.count(KotOrder.id)).where(KotOrder.kitchen_status == status)
            ) or 0
            for status in ("pending", "preparing", "ready", "served", "cancelled")
        }
        pending_out = db.scalar(
            select(func.count(KotSyncQueue.id)).where(KotSyncQueue.status == "pending")
        ) or 0
        failed_events = db.scalars(
            select(KotSyncQueue)
            .where(KotSyncQueue.status == "failed")
            .order_by(KotSyncQueue.id.desc())
            .limit(10)
        ).all()
        recent = db.scalars(
            select(KotOrder).order_by(KotOrder.cloud_kot_id.desc()).limit(20)
        ).all()
        exceptions = db.scalars(
            select(KotOrder).where(
                (KotOrder.resolution_status.notin_(["resolved", "not_room"]))
                | (KotOrder.billing_status == "review")
                | (KotOrder.menu_issues.notin_(["", "[]"]))
            ).order_by(KotOrder.cloud_kot_id.desc()).limit(20)
        ).all()
        cursor = get_state(db, CURSOR_KEY, "0")
        last_run = get_state(db, LAST_RUN_KEY, "")
        last_error = get_state(db, LAST_ERROR_KEY, "")
        unmapped = db.scalar(
            select(func.count(KotOrder.id)).where(KotOrder.local_invoice_id.is_(None))
        ) or 0
        return {
            "counts": counts,
            "open_count": sum(counts[s] for s in OPEN_CLOUD_STATUSES),
            "pending_out": pending_out,
            "failed_events": failed_events,
            "failed_count": db.scalar(
                select(func.count(KotSyncQueue.id)).where(KotSyncQueue.status == "failed")
            ) or 0,
            "recent": recent,
            "exceptions": exceptions,
            "exception_count": len(exceptions),
            "billed_count": db.scalar(
                select(func.count(KotOrder.id)).where(KotOrder.billing_status == "billed")
            ) or 0,
            "review_count": db.scalar(
                select(func.count(KotOrder.id)).where(KotOrder.billing_status == "review")
            ) or 0,
            "cursor": cursor,
            "last_run": last_run,
            "last_error": last_error,
            "unmapped": unmapped,
            "today": date.today().isoformat(),
            "today_count": db.scalar(
                select(func.count(KotOrder.id)).where(
                    KotOrder.business_date == business_date_for(utcnow())
                )
            ) or 0,
        }
