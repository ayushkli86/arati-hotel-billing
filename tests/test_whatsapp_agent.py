"""Tests for the guided WhatsApp ordering agent and Meta webhook helpers."""

from __future__ import annotations

import hashlib
import hmac
import json
from datetime import timedelta

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from webapp import whatsapp
from webapp.database import Base
from webapp.models import CatalogItem, HotelSetting, Order, Room, WhatsAppMessage
from webapp.services import local_now

PHONE = "9779800000111"


@pytest.fixture()
def db(monkeypatch):
    for key in (
        "ARATI_WHATSAPP_TOKEN", "ARATI_WHATSAPP_PHONE_NUMBER_ID",
        "ARATI_WHATSAPP_VERIFY_TOKEN", "ARATI_WHATSAPP_APP_SECRET",
        "ARATI_WHATSAPP_ENABLED",
    ):
        monkeypatch.delenv(key, raising=False)
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    session = session_factory()
    session.add_all([
        HotelSetting(key="hotel_name", value="Arati Hotel"),
        CatalogItem(name="Chicken Thali", category="restaurant", rate=850, sort_order=1),
        CatalogItem(name="Tea / Coffee", category="restaurant", rate=120, sort_order=2),
        CatalogItem(name="Deluxe Room", category="room", rate=4500, unit="night"),
        CatalogItem(name="Airport Transfer", category="service", rate=1800),
        Room(number="101", type="Deluxe Room", status="available", nightly_rate=4500),
    ])
    session.commit()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def send(db, text: str, phone: str = PHONE) -> dict:
    return whatsapp.process_inbound(db, phone, "Sita Sharma", text, transport="simulator")


def test_food_order_end_to_end(db):
    assert "Order food" in send(db, "Hi")["replies"][0]
    menu = send(db, "1")["replies"][0]
    assert "Chicken Thali" in menu and "Tea / Coffee" in menu

    assert "Chicken Thali" in send(db, "1")["replies"][0]
    assert "Added 2" in send(db, "2")["replies"][0]

    checkout = send(db, "2")["replies"][0]
    assert "How would you like to receive it" in checkout
    assert "What name" in send(db, "1")["replies"][0]

    confirmation = send(db, "Sita Sharma")["replies"][0]
    assert "Please confirm your order" in confirmation
    assert "NPR 1,700.00" in confirmation

    result = send(db, "YES")
    order = result["order"]
    assert order is not None
    assert order.order_number.startswith("ORD-")
    assert order.kind == "food"
    assert order.status == "new"
    assert order.customer_name == "Sita Sharma"
    assert order.fulfilment == "pickup"
    assert float(order.total) == 1700.0
    assert len(order.items) == 1
    assert float(order.items[0].quantity) == 2
    assert "ORD-" in result["replies"][0]

    # The conversation is ready for a new request.
    assert json.loads(result["conversation"].state)["step"] == "main"
    outbound = db.scalars(
        select(WhatsAppMessage).where(WhatsAppMessage.direction == "out")
    ).all()
    assert outbound and outbound[-1].status == "simulated"


def test_room_booking_request(db):
    check_in = (local_now().date() + timedelta(days=3)).isoformat()
    send(db, "2")
    assert "nights" in send(db, check_in)["replies"][0]
    assert "guests" in send(db, "2")["replies"][0]

    room_menu = send(db, "3")["replies"][0]
    assert "Deluxe Room" in room_menu
    assert "What name" in send(db, "1")["replies"][0]
    assert "Estimated room charge" in send(db, "Ramesh Rai")["replies"][0]
    assert "saved as" in send(db, "YES")["replies"][0]

    order = db.scalars(select(Order)).one()
    assert order.kind == "room"
    assert order.check_in_date.isoformat() == check_in
    assert (order.check_out_date - order.check_in_date).days == 2
    assert order.party_size == 3
    assert float(order.total) == 9000.0
    assert order.requested_for == check_in


def test_service_request(db):
    when = (local_now() + timedelta(days=10)).strftime("%Y-%m-%d 18:30")
    menu = send(db, "3")["replies"][0]
    assert "Airport Transfer" in menu
    assert "When do you need it" in send(db, "1")["replies"][0]
    assert "Any details" in send(db, when)["replies"][0]
    assert "What name" in send(db, "SKIP")["replies"][0]
    confirmation = send(db, "Maya Gurung")["replies"][0]
    assert "Airport Transfer" in confirmation and "18:30" in confirmation
    order = send(db, "YES")["order"]
    assert order.kind == "service"
    assert order.requested_for == when
    assert order.notes == ""
    assert float(order.total) == 1800.0


def test_invalid_inputs_keep_the_flow(db):
    send(db, "2")
    assert "couldn't read that date" in send(db, "31-02-2030")["replies"][0]
    check_in = (local_now().date() + timedelta(days=1)).isoformat()
    assert "nights" in send(db, check_in)["replies"][0]
    assert "1 to 30" in send(db, "99")["replies"][0]
    assert "1 to 30" in send(db, "31")["replies"][0]
    # The flow stayed on nights and moves on with a valid answer.
    assert "guests" in send(db, "2")["replies"][0]


def test_delivery_to_room_requires_a_known_room(db):
    send(db, "1")
    send(db, "2")          # Tea / Coffee
    send(db, "1")          # one cup
    send(db, "2")          # checkout
    send(db, "4")          # to my room
    assert "can't find that room" in send(db, "999")["replies"][0]
    assert "What name" in send(db, "101")["replies"][0]
    send(db, "Sita")
    order = send(db, "YES")["order"]
    assert order.fulfilment == "room"
    assert order.room_number == "101"
    assert float(order.total) == 120.0


def test_human_handoff_pauses_and_resumes(db):
    result = send(db, "4")
    conversation = result["conversation"]
    assert conversation.bot_paused is True
    assert "front desk" in result["replies"][0]

    quiet = send(db, "1")
    assert quiet["replies"] == []
    assert quiet["order"] is None

    resumed = send(db, "menu")
    assert "Order food" in resumed["replies"][0]
    assert resumed["conversation"].bot_paused is False

    # Staff can also resume the assistant from the order page.
    whatsapp.set_bot_paused(db, conversation, True)
    assert send(db, "Hi")["replies"] == []
    whatsapp.set_bot_paused(db, conversation, False)
    assert "Order food" in send(db, "Hi")["replies"][0]


def test_cancel_and_menu_commands_reset_the_conversation(db):
    send(db, "1")
    cancelled = send(db, "cancel")
    assert "Cancelled" in cancelled["replies"][0]
    assert json.loads(cancelled["conversation"].state)["step"] == "main"

    send(db, "2")
    started = send(db, "menu")
    assert "Order food" in started["replies"][0]
    assert json.loads(started["conversation"].state)["step"] == "main"


def test_duplicate_webhook_delivery_does_not_duplicate_an_order(db):
    send(db, "1")
    send(db, "1")
    send(db, "1")
    send(db, "2")
    send(db, "1")
    send(db, "Sita")
    first = whatsapp.process_inbound(
        db, PHONE, "Sita", "YES", transport="simulator", message_id="wamid.yes",
    )
    assert first["order"] is not None
    repeated = whatsapp.process_inbound(
        db, PHONE, "Sita", "YES", transport="simulator", message_id="wamid.yes",
    )
    assert repeated["replies"] == [] and repeated["order"] is None
    assert len(db.scalars(select(Order)).all()) == 1


def test_status_update_is_sent_and_logged(db):
    send(db, "1")
    send(db, "1")
    send(db, "1")
    send(db, "2")
    send(db, "1")
    send(db, "Sita")
    order = send(db, "YES")["order"]

    order.status = "confirmed"
    db.commit()
    assert whatsapp.notify_order_status(db, order, "confirmed") is True
    latest = db.scalars(
        select(WhatsAppMessage).order_by(WhatsAppMessage.id.desc()).limit(1)
    ).one()
    assert order.order_number in latest.body
    assert latest.direction == "out"
    assert "cancelled" in whatsapp.status_message(order, "cancelled")


def test_webhook_parsing_reads_text_and_button_replies():
    payload = {
        "entry": [{
            "changes": [{
                "value": {
                    "contacts": [{"wa_id": "9779800000111", "profile": {"name": "Sita"}}],
                    "messages": [
                        {"from": "9779800000111", "id": "wamid.1", "type": "text",
                         "text": {"body": "Hi"}},
                        {"from": "9779800000111", "id": "wamid.2", "type": "interactive",
                         "interactive": {"type": "button_reply",
                                         "button_reply": {"id": "1", "title": "Order food"}}},
                    ],
                },
            }],
        }],
    }
    messages = whatsapp.parse_webhook(payload)
    assert [message["text"] for message in messages] == ["Hi", "1"]
    assert messages[0]["name"] == "Sita"
    assert messages[0]["message_id"] == "wamid.1"


def test_signature_verification(monkeypatch):
    body = b'{"hello":"world"}'
    monkeypatch.setenv("ARATI_WHATSAPP_APP_SECRET", "top-secret")
    digest = hmac.new(b"top-secret", body, hashlib.sha256).hexdigest()
    assert whatsapp.verify_signature(body, f"sha256={digest}") is True
    assert whatsapp.verify_signature(body, "sha256=deadbeef") is False
    assert whatsapp.verify_signature(body, None) is False
    monkeypatch.delenv("ARATI_WHATSAPP_APP_SECRET")
    assert whatsapp.verify_signature(body, None) is True
    monkeypatch.setenv("ARATI_ENV", "production")
    assert whatsapp.verify_signature(body, None) is False


def test_phone_normalization():
    assert whatsapp.normalize_phone("+977 98000 00111") == "9779800000111"
    assert whatsapp.normalize_phone("009779800000111") == "9779800000111"
    assert whatsapp.normalize_phone("123") == ""
    assert whatsapp.normalize_phone(None) == ""
