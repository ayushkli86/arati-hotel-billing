# Copyright 2026 AI Memory System. All rights reserved.
"""Additive local mirror tables for the cloud KOT integration.

These tables are prefixed ``kot_`` on purpose: the webapp already has a legacy
``kots`` table with a different shape, and nothing here may touch it. They are
created by the normal ``Base.metadata.create_all`` path and only ever hold
referenced copies of cloud tickets plus the sync bookkeeping.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from sqlalchemy import (
    Boolean, DateTime, ForeignKey, Index, Integer, Numeric, String, Text, UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ...database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def new_uuid() -> str:
    return str(uuid.uuid4())


class KotOrder(Base):
    """A cloud kitchen ticket, mirrored locally and linked to billing.

    ``order_uuid`` is the stable identity used across both systems. Cloud
    tickets expose integer ids, so the UUID is derived deterministically from
    that id when the cloud does not provide one — re-syncing the same ticket
    therefore always lands on the same row.
    """

    __tablename__ = "kot_orders"
    __table_args__ = (
        UniqueConstraint("cloud_kot_id", name="uq_kot_orders_cloud_kot_id"),
        UniqueConstraint("order_uuid", name="uq_kot_orders_order_uuid"),
        Index("ix_kot_orders_status_created", "kitchen_status", "cloud_created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    cloud_kot_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    cloud_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    order_uuid: Mapped[str] = mapped_column(String(36), default=new_uuid, nullable=False)
    kot_number: Mapped[str] = mapped_column(String(60), default="", index=True)
    order_type: Mapped[str] = mapped_column(String(30), default="")
    room_number: Mapped[str] = mapped_column(String(20), default="", index=True)
    table_name: Mapped[str] = mapped_column(String(60), default="")
    customer_ref: Mapped[str] = mapped_column(String(120), default="")
    guest_name: Mapped[str] = mapped_column(String(160), default="")
    guest_phone: Mapped[str] = mapped_column(String(40), default="")
    waiter: Mapped[str] = mapped_column(String(120), default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    kitchen_status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    payment_status: Mapped[str] = mapped_column(String(20), default="unpaid", index=True)
    total: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0.00"))
    business_date: Mapped[str] = mapped_column(String(20), default="", index=True)
    cloud_created_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    cloud_updated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    synced_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    # Billing links. Both are nullable: a cloud ticket exists before the hotel
    # raises a receipt for it, and this app never invents an invoice.
    local_kot_id: Mapped[int | None] = mapped_column(
        ForeignKey("kots.id", ondelete="SET NULL"), nullable=True, index=True,
    )
    local_room_id: Mapped[int | None] = mapped_column(
        ForeignKey("rooms.id", ondelete="SET NULL"), nullable=True, index=True,
    )
    local_stay_id: Mapped[int | None] = mapped_column(
        ForeignKey("stays.id", ondelete="SET NULL"), nullable=True, index=True,
    )
    local_guest_id: Mapped[int | None] = mapped_column(
        ForeignKey("guests.id", ondelete="SET NULL"), nullable=True, index=True,
    )
    local_invoice_id: Mapped[int | None] = mapped_column(
        ForeignKey("invoices.id", ondelete="SET NULL"), nullable=True, index=True,
    )
    local_invoice_number: Mapped[str] = mapped_column(String(40), default="")
    resolution_status: Mapped[str] = mapped_column(String(20), default="unresolved", index=True)
    resolution_reason: Mapped[str] = mapped_column(Text, default="")
    billing_status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    billed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    menu_issues: Mapped[str] = mapped_column(Text, default="[]")

    items: Mapped[list["KotOrderItem"]] = relationship(
        back_populates="order", cascade="all, delete-orphan",
        order_by="KotOrderItem.position",
    )

    @property
    def display_number(self) -> str:
        return self.kot_number or (f"#{self.cloud_number}" if self.cloud_number else f"#{self.cloud_kot_id}")

    @property
    def is_open(self) -> bool:
        return self.kitchen_status not in {"served", "cancelled"} and self.payment_status != "paid"


class KotOrderItem(Base):
    """One line of a mirrored cloud ticket (name/price snapshot, never a FK)."""

    __tablename__ = "kot_order_items"
    __table_args__ = (
        UniqueConstraint("order_id", "position", name="uq_kot_order_items_position"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_id: Mapped[int] = mapped_column(
        ForeignKey("kot_orders.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    position: Mapped[int] = mapped_column(Integer, default=0)
    cloud_line_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    dish_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    local_catalog_item_id: Mapped[int | None] = mapped_column(
        ForeignKey("catalog_items.id", ondelete="SET NULL"), nullable=True, index=True,
    )
    dish_name: Mapped[str] = mapped_column(String(160), default="")
    category: Mapped[str] = mapped_column(String(60), default="")
    station: Mapped[str] = mapped_column(String(40), default="")
    kitchen_status: Mapped[str] = mapped_column(String(20), default="")
    local_available: Mapped[bool] = mapped_column(Boolean, default=True)
    price_matches: Mapped[bool] = mapped_column(Boolean, default=True)
    qty: Mapped[int] = mapped_column(Integer, default=1)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0.00"))
    line_total: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0.00"))

    order: Mapped[KotOrder] = relationship(back_populates="items")


class KotSyncState(Base):
    """Tiny key/value store: cursors, last run info, menu id mapping.

    A single row per key means the cursor commit is one atomic statement, which
    is what makes resume-after-restart exact even if the process is killed
    mid-cycle.
    """

    __tablename__ = "kot_sync_state"

    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class KotSyncQueue(Base):
    """Outbound work queue (local orders and menu changes heading to cloud).

    ``dedupe_key`` makes enqueueing idempotent: pushing the same dish twice
    while it is still pending does not create a second job.
    """

    __tablename__ = "kot_sync_queue"
    __table_args__ = (
        UniqueConstraint("dedupe_key", name="uq_kot_sync_queue_dedupe"),
        Index("ix_kot_sync_queue_status_id", "status", "id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    direction: Mapped[str] = mapped_column(String(10), default="out")
    event_type: Mapped[str] = mapped_column(String(40), default="")
    dedupe_key: Mapped[str | None] = mapped_column(String(120), nullable=True)
    payload: Mapped[str] = mapped_column(Text, default="{}")
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
    sent_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
