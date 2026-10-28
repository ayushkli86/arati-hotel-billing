"""Database models for guests, rooms, stays, invoices and payments."""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship, synonym

from .database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    full_name: Mapped[str] = mapped_column(String(160), default="")
    role: Mapped[str] = mapped_column(String(20), default="staff")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=False)
    session_version: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class Guest(Base):
    __tablename__ = "guests"
    __table_args__ = (
        UniqueConstraint("phone", name="uq_guests_phone"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    full_name: Mapped[str] = mapped_column(String(160), default="", index=True)
    name: Mapped[str] = mapped_column(String(160), index=True)
    phone: Mapped[str] = mapped_column(String(40), nullable=True, index=True)
    email: Mapped[str] = mapped_column(String(180), default="")
    id_type: Mapped[str] = mapped_column(String(40), default="")
    id_number: Mapped[str] = mapped_column(String(100), default="")
    address: Mapped[str] = mapped_column(String(240), default="")
    pan_vat_number: Mapped[str] = mapped_column(String(80), default="")
    customer_type: Mapped[str] = mapped_column(String(30), default="individual")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    pan_vat = synonym("pan_vat_number")
    stays: Mapped[list["Stay"]] = relationship(back_populates="guest", cascade="save-update")
    invoices: Mapped[list["Invoice"]] = relationship(back_populates="guest", cascade="save-update")


class Room(Base):
    __tablename__ = "rooms"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    number: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    type: Mapped[str] = mapped_column(String(50))
    bed_type: Mapped[str] = mapped_column(String(50), default="")
    status: Mapped[str] = mapped_column(String(30), default="available", index=True)
    housekeeping_status: Mapped[str] = mapped_column(String(30), default="clean")
    floor: Mapped[str] = mapped_column(String(30), default="1")
    nightly_rate: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    room_type_item_id: Mapped[int | None] = mapped_column(
        ForeignKey("catalog_items.id"), nullable=True, index=True,
    )
    nightly_rate_override: Mapped[bool] = mapped_column(Boolean, default=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    room_type = synonym("type")
    rate = synonym("nightly_rate")
    room_type_item: Mapped["CatalogItem | None"] = relationship(back_populates="rooms")
    stays: Mapped[list["Stay"]] = relationship(back_populates="room")
    reservations: Mapped[list["Reservation"]] = relationship(back_populates="room")


class Reservation(Base):
    __tablename__ = "reservations"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    room_id: Mapped[int | None] = mapped_column(ForeignKey("rooms.id"), index=True, nullable=True)
    guest_id: Mapped[int | None] = mapped_column(ForeignKey("guests.id"), index=True, nullable=True)
    check_in: Mapped[datetime] = mapped_column(DateTime)
    check_out: Mapped[datetime] = mapped_column(DateTime)
    status: Mapped[str] = mapped_column(String(30), default="confirmed")
    room_number: Mapped[str] = mapped_column(String(20), default="")
    guest_name: Mapped[str] = mapped_column(String(160), default="")
    guest_phone: Mapped[str] = mapped_column(String(40), default="")
    guest_email: Mapped[str] = mapped_column(String(180), default="")
    guest_address: Mapped[str] = mapped_column(String(240), default="")
    guest_pan: Mapped[str] = mapped_column(String(80), default="")
    nightly_rate: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    deposit: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    source: Mapped[str] = mapped_column(String(80), default="front desk")
    notes: Mapped[str] = mapped_column(Text, default="")
    cancel_reason: Mapped[str] = mapped_column(Text, default="")
    # Local (Asia/Kathmandu) business day the booking was made, stored day-wise.
    business_date: Mapped[str] = mapped_column(String(20), default="", index=True)
    created_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    room: Mapped[Room] = relationship(back_populates="reservations")
    guest: Mapped[Guest] = relationship()


class Stay(Base):
    __tablename__ = "stays"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    room_id: Mapped[int] = mapped_column(ForeignKey("rooms.id", ondelete="RESTRICT"), nullable=False, index=True)
    guest_id: Mapped[int] = mapped_column(ForeignKey("guests.id", ondelete="RESTRICT"), nullable=False, index=True)
    check_in: Mapped[datetime] = mapped_column(DateTime)
    check_out: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="checked_in", index=True)
    reservation_id: Mapped[int | None] = mapped_column(ForeignKey("reservations.id"), nullable=True)
    room_number: Mapped[str] = mapped_column(String(20), default="")
    invoice_number: Mapped[str] = mapped_column(String(40), default="")
    guest_name: Mapped[str] = mapped_column(String(160), default="")
    guest_phone: Mapped[str] = mapped_column(String(40), default="")
    guest_email: Mapped[str] = mapped_column(String(180), default="")
    guest_address: Mapped[str] = mapped_column(String(240), default="")
    guest_pan: Mapped[str] = mapped_column(String(80), default="")
    expected_checkout: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    nights: Mapped[int] = mapped_column(Integer, default=1)
    nightly_rate: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    rate_per_night: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    notes: Mapped[str] = mapped_column(Text, default="")
    business_date: Mapped[str] = mapped_column(String(20), default="", index=True)
    created_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    room: Mapped[Room] = relationship(back_populates="stays")
    guest: Mapped[Guest] = relationship(back_populates="stays")
    invoices: Mapped[list["Invoice"]] = relationship(back_populates="stay", cascade="save-update")


class Invoice(Base):
    __tablename__ = "invoices"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    invoice_number: Mapped[str] = mapped_column(String(40), unique=True, index=True, default="")
    stay_id: Mapped[int | None] = mapped_column(ForeignKey("stays.id", ondelete="SET NULL"), nullable=True, index=True)
    guest_id: Mapped[int] = mapped_column(ForeignKey("guests.id", ondelete="RESTRICT"), nullable=False, index=True)
    room_id: Mapped[int | None] = mapped_column(ForeignKey("rooms.id", ondelete="SET NULL"), nullable=True, index=True)
    issue_date: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    discount_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    total: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    paid_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    balance: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0, index=True)
    status: Mapped[str] = mapped_column(String(30), default="issued", index=True)
    invoice_type: Mapped[str] = mapped_column(String(30), default="Tax Invoice")
    language: Mapped[str] = mapped_column(String(20), default="English")
    copy_type: Mapped[str] = mapped_column(String(30), default="Customer Copy")
    payment_terms: Mapped[str] = mapped_column(String(60), default="Due on Check-out")
    notes: Mapped[str] = mapped_column(Text, default="")
    vat_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    invoice_date = synonym("issue_date")
    discount = synonym("discount_amount")
    grand_total = synonym("total")
    subtotal: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    check_in: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    check_out: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    nights: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    bill_date: Mapped[str] = mapped_column(String(20), default="")
    guest_name: Mapped[str] = mapped_column(String(160), default="")
    guest_phone: Mapped[str] = mapped_column(String(40), default="")
    guest_address: Mapped[str] = mapped_column(String(240), default="")
    guest_pan: Mapped[str] = mapped_column(String(80), default="")
    room_number: Mapped[str] = mapped_column(String(20), default="")
    item_discount: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    net_subtotal: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    taxable_net: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    service_charge_rate: Mapped[Decimal] = mapped_column(Numeric(7, 3), default=0)
    service_charge: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    vat_rate: Mapped[Decimal] = mapped_column(Numeric(7, 3), default=0)
    payment_method: Mapped[str] = mapped_column(String(40), default="Cash")
    prepared_by: Mapped[str] = mapped_column(String(80), default="")
    received_by: Mapped[str] = mapped_column(String(80), default="")
    customer_type: Mapped[str] = mapped_column(String(30), default="individual")
    is_draft: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    bill_type: Mapped[str] = mapped_column(String(30), default="tax")
    copy_label: Mapped[str] = mapped_column(String(80), default="")
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    guest: Mapped[Guest] = relationship(back_populates="invoices")
    stay: Mapped[Stay | None] = relationship(back_populates="invoices")
    room: Mapped[Room | None] = relationship()
    items: Mapped[list["InvoiceItem"]] = relationship(back_populates="invoice", cascade="all, delete-orphan")
    payments: Mapped[list["Payment"]] = relationship(back_populates="invoice", cascade="all, delete-orphan")
    kots: Mapped[list["Kot"]] = relationship(back_populates="invoice", cascade="all, delete-orphan")


class InvoiceItem(Base):
    __tablename__ = "invoice_items"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    invoice_id: Mapped[int] = mapped_column(ForeignKey("invoices.id", ondelete="CASCADE"), index=True, nullable=False)
    catalog_item_id: Mapped[int | None] = mapped_column(ForeignKey("catalog_items.id", ondelete="SET NULL"), nullable=True)
    description: Mapped[str] = mapped_column(String(240))
    quantity: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=1)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    rate: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    discount_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    vat_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    item_code: Mapped[str] = mapped_column(String(80), default="")
    category: Mapped[str] = mapped_column(String(30), default="food")
    unit: Mapped[str] = mapped_column(String(30), default="pcs")
    taxable: Mapped[bool] = mapped_column(Boolean, default=True)
    business_date = mapped_column(Date, nullable=True, index=True)
    added_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    added_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    qty = synonym("quantity")
    discount = synonym("discount_amount")
    vat = synonym("vat_amount")
    total = synonym("amount")
    invoice: Mapped[Invoice] = relationship(back_populates="items")
    catalog_item = relationship("CatalogItem")
    added_by = relationship("User")
    kot_id: Mapped[int | None] = mapped_column(
        ForeignKey("kots.id", ondelete="SET NULL"), nullable=True, index=True,
    )
    kot: Mapped["Kot | None"] = relationship(back_populates="items_rows")


class Kot(Base):
    """Kitchen Order Ticket: a kitchen-bound snapshot of restaurant items."""

    __tablename__ = "kots"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kot_number: Mapped[str] = mapped_column(String(40), unique=True, index=True, default="")
    invoice_id: Mapped[int | None] = mapped_column(
        ForeignKey("invoices.id", ondelete="CASCADE"), nullable=True, index=True,
    )
    table_number: Mapped[str] = mapped_column(String(40), default="", index=True)
    guest_id: Mapped[int | None] = mapped_column(
        ForeignKey("guests.id", ondelete="SET NULL"), nullable=True, index=True,
    )
    guest_name: Mapped[str] = mapped_column(String(160), default="")
    items: Mapped[str] = mapped_column(Text, default="[]")
    total: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    status: Mapped[str] = mapped_column(String(30), default="open", index=True)
    business_date: Mapped[str] = mapped_column(String(20), default="", index=True)
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime | None] = mapped_column(DateTime, default=utcnow, index=True)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True,
    )
    invoice: Mapped[Invoice | None] = relationship(back_populates="kots")
    guest: Mapped[Guest | None] = relationship()
    items_rows: Mapped[list["InvoiceItem"]] = relationship(back_populates="kot")

    @property
    def date(self) -> str:
        return self.created_at.strftime("%Y-%m-%d %H:%M") if self.created_at else ""


class CatalogItem(Base):
    """Room-adjacent restaurant and service items available for billing."""
    __tablename__ = "catalog_items"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(160), index=True)
    category: Mapped[str] = mapped_column(String(30), index=True)
    menu_group: Mapped[str] = mapped_column(String(80), default="", index=True)
    rate: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    item_code: Mapped[str] = mapped_column(String(80), default="")
    unit: Mapped[str] = mapped_column(String(30), default="pcs")
    taxable: Mapped[bool] = mapped_column(Boolean, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    rooms: Mapped[list[Room]] = relationship(back_populates="room_type_item")


class Payment(Base):
    __tablename__ = "payments"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    invoice_id: Mapped[int | None] = mapped_column(ForeignKey("invoices.id"), index=True, nullable=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    method: Mapped[str] = mapped_column(String(40), default="Cash")
    paid_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    received_by: Mapped[str] = mapped_column(String(80), default="")
    note: Mapped[str] = mapped_column(Text, default="")
    invoice_number: Mapped[str] = mapped_column(String(40), default="")
    business_date: Mapped[str] = mapped_column(String(20), default="")
    created_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    invoice: Mapped[Invoice] = relationship(back_populates="payments")


class Refund(Base):
    __tablename__ = "refunds"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    invoice_id: Mapped[int | None] = mapped_column(ForeignKey("invoices.id"), nullable=True, index=True)
    invoice_number: Mapped[str] = mapped_column(String(40), default="")
    kind: Mapped[str] = mapped_column(String(30), default="refund")
    method: Mapped[str] = mapped_column(String(40), default="Cash")
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    reason: Mapped[str] = mapped_column(Text, default="")
    refunded_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    business_date: Mapped[str] = mapped_column(String(20), default="")
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class RoomCharge(Base):
    __tablename__ = "room_charges"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    stay_id: Mapped[int] = mapped_column(ForeignKey("stays.id"), index=True)
    room_number: Mapped[str] = mapped_column(String(20), default="")
    invoice_number: Mapped[str] = mapped_column(String(40), default="")
    description: Mapped[str] = mapped_column(String(240))
    category: Mapped[str] = mapped_column(String(30), default="service")
    quantity: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=1)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    charge_date: Mapped[str] = mapped_column(String(20), default="")
    created_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)


class Order(Base):
    """A food, room, or event/service request received from a guest.

    WhatsApp orders are created by the assistant in ``webapp/whatsapp.py``.
    The front desk maintains the status; nothing here touches accounting until
    the order is billed as an invoice.
    """

    __tablename__ = "orders"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_number: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    channel: Mapped[str] = mapped_column(String(30), default="whatsapp", index=True)
    kind: Mapped[str] = mapped_column(String(20), default="food", index=True)
    status: Mapped[str] = mapped_column(String(30), default="new", index=True)
    contact_wa_id: Mapped[str] = mapped_column(String(40), default="", index=True)
    customer_name: Mapped[str] = mapped_column(String(160), default="")
    customer_phone: Mapped[str] = mapped_column(String(40), default="")
    fulfilment: Mapped[str] = mapped_column(String(30), default="")
    room_number: Mapped[str] = mapped_column(String(20), default="")
    delivery_address: Mapped[str] = mapped_column(String(240), default="")
    check_in_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    check_out_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    party_size: Mapped[int] = mapped_column(Integer, default=0)
    requested_for: Mapped[str] = mapped_column(String(80), default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    total: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    invoice_number: Mapped[str] = mapped_column(String(40), default="")
    conversation_id: Mapped[int | None] = mapped_column(
        ForeignKey("whatsapp_conversations.id"), nullable=True
    )
    created_at: Mapped[datetime | None] = mapped_column(DateTime, default=utcnow, index=True)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # Local (Asia/Kathmandu) business day the order came in, stored day-wise.
    business_date: Mapped[str] = mapped_column(String(20), default="", index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    items: Mapped[list["OrderItem"]] = relationship(
        back_populates="order", cascade="all, delete-orphan"
    )
    conversation: Mapped["WhatsAppConversation | None"] = relationship(back_populates="orders")


class OrderItem(Base):
    __tablename__ = "order_items"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), index=True)
    catalog_item_id: Mapped[int | None] = mapped_column(ForeignKey("catalog_items.id"), nullable=True)
    description: Mapped[str] = mapped_column(String(240))
    category: Mapped[str] = mapped_column(String(30), default="restaurant")
    quantity: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=1)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    order: Mapped[Order] = relationship(back_populates="items")


class WhatsAppConversation(Base):
    __tablename__ = "whatsapp_conversations"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    wa_id: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(160), default="")
    state: Mapped[str] = mapped_column(Text, default="{}")
    bot_paused: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime | None] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    orders: Mapped[list[Order]] = relationship(back_populates="conversation")
    messages: Mapped[list["WhatsAppMessage"]] = relationship(
        back_populates="conversation", cascade="all, delete-orphan"
    )


class WhatsAppMessage(Base):
    __tablename__ = "whatsapp_messages"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    conversation_id: Mapped[int | None] = mapped_column(
        ForeignKey("whatsapp_conversations.id"), nullable=True, index=True
    )
    order_id: Mapped[int | None] = mapped_column(ForeignKey("orders.id"), nullable=True)
    wa_id: Mapped[str] = mapped_column(String(40), default="", index=True)
    direction: Mapped[str] = mapped_column(String(10), default="in", index=True)
    body: Mapped[str] = mapped_column(Text, default="")
    message_id: Mapped[str] = mapped_column(String(120), default="")
    status: Mapped[str] = mapped_column(String(30), default="received")
    detail: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    conversation: Mapped[WhatsAppConversation | None] = relationship(back_populates="messages")


class HotelSetting(Base):
    __tablename__ = "hotel_settings"
    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="")


class DailyReport(Base):
    __tablename__ = "daily_reports"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    business_date: Mapped[str] = mapped_column(String(20), index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(30), default="generated")
    file_path: Mapped[str] = mapped_column(Text, default="")
    generated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    generated_by: Mapped[str] = mapped_column(String(80), default="scheduler")
    error: Mapped[str] = mapped_column(Text, default="")
    totals_json: Mapped[str] = mapped_column(Text, default="{}")
    superseded_by: Mapped[int | None] = mapped_column(ForeignKey("daily_reports.id"), nullable=True)


class SchedulerRun(Base):
    __tablename__ = "scheduler_runs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_name: Mapped[str] = mapped_column(String(100))
    business_date: Mapped[str | None] = mapped_column(String(20), nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="running")
    message: Mapped[str] = mapped_column(Text, default="")


class AuditLog(Base):
    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    username: Mapped[str] = mapped_column(String(80), default="")
    action: Mapped[str] = mapped_column(String(100))
    entity: Mapped[str] = mapped_column(String(80), default="")
    entity_id: Mapped[str] = mapped_column(String(80), default="")
    detail: Mapped[str] = mapped_column(Text, default="")


class UserSession(Base):
    """Server-side record of an active signed-in session.

    The cookie itself remains the signed Starlette session; this table is the
    revocation ledger. It is what lets an administrator invalidate a specific
    browser session (by its server-side session id) without disturbing every
    other session for the same user, and what lets ``/logout`` mark a cookie
    dead server-side so a captured cookie cannot be replayed inside its max-age
    window.

    ``session_id`` is derived from the signed cookie value at auth time, so it
    is stable for the life of that cookie and unique per signed session.
    """

    __tablename__ = "user_sessions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[str] = mapped_column(String(128), unique=True, index=True, nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    ip_address: Mapped[str] = mapped_column(String(45), default="")
    user_agent: Mapped[str] = mapped_column(String(512), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    revoked_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    revoked_reason: Mapped[str] = mapped_column(Text, default="")

    user: Mapped[User] = relationship(
        back_populates="sessions", foreign_keys=[user_id]
    )
    revoked_by: Mapped[User | None] = relationship(
        "User", foreign_keys=[revoked_by_id], viewonly=True
    )


User.sessions: Mapped[list[UserSession]] = relationship(
    "UserSession", back_populates="user", cascade="all, delete-orphan",
    foreign_keys="UserSession.user_id",
)


class StaffAttendance(Base):
    """Daily staff attendance record for check-in/check-out tracking.

    Each record represents one day of attendance for a staff member.
    Staff check in when they arrive and check out when they leave.
    """

    __tablename__ = "staff_attendance"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    business_date: Mapped[str] = mapped_column(String(20), default="", index=True)
    check_in: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    check_out: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    check_in_ip: Mapped[str] = mapped_column(String(45), default="")
    check_out_ip: Mapped[str] = mapped_column(String(45), default="")
    check_in_user_agent: Mapped[str] = mapped_column(String(512), default="")
    check_out_user_agent: Mapped[str] = mapped_column(String(512), default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    user: Mapped[User] = relationship(foreign_keys=[user_id])

    __table_args__ = (
        UniqueConstraint("user_id", "business_date", name="uq_staff_attendance_user_date"),
    )


User.attendance_records: Mapped[list["StaffAttendance"]] = relationship(
    "StaffAttendance", back_populates="user", cascade="all, delete-orphan",
    foreign_keys="StaffAttendance.user_id",
)
