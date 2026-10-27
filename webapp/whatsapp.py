"""WhatsApp ordering agent for the Arati Hotel front office.

One deterministic, numbered-menu conversation handles food orders, room
booking requests, and event/service requests. The same code path serves the
Meta WhatsApp Cloud API webhook and the in-app simulator, so the front desk can
train on the bot and see exactly what a guest would receive.

Configuration is read from the environment (never committed):

    ARATI_WHATSAPP_TOKEN             Meta permanent access token
    ARATI_WHATSAPP_PHONE_NUMBER_ID   WhatsApp Business phone number ID
    ARATI_WHATSAPP_VERIFY_TOKEN      webhook verification string you choose
    ARATI_WHATSAPP_APP_SECRET        Meta app secret for payload signatures
    ARATI_WHATSAPP_API_VERSION       Graph API version (default v21.0)
    ARATI_WHATSAPP_ENABLED           set 0/false to stop processing messages

Without a token the agent still runs in simulator mode and orders can be
created and worked from the Orders page.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import (
    CatalogItem, HotelSetting, Order, OrderItem, Room, WhatsAppConversation,
    WhatsAppMessage, utcnow,
)
from .orders import next_order_number
from .services import local_now, money

FOOD_CATEGORIES = ("restaurant", "food", "beverage")
MAX_MENU_ITEMS = 30
MAX_CART_LINES = 20
DEFAULT_PHONE = "9779800000000"


# --- configuration ---------------------------------------------------------


def config() -> dict[str, str | bool]:
    enabled = os.getenv("ARATI_WHATSAPP_ENABLED", "1").strip().lower() not in {
        "0", "false", "no", "off",
    }
    return {
        "enabled": enabled,
        "token": os.getenv("ARATI_WHATSAPP_TOKEN", "").strip(),
        "phone_number_id": os.getenv("ARATI_WHATSAPP_PHONE_NUMBER_ID", "").strip(),
        "verify_token": os.getenv("ARATI_WHATSAPP_VERIFY_TOKEN", "").strip(),
        "app_secret": os.getenv("ARATI_WHATSAPP_APP_SECRET", "").strip(),
        "api_version": os.getenv("ARATI_WHATSAPP_API_VERSION", "").strip() or "v21.0",
    }


def cloud_configured() -> bool:
    settings = config()
    return bool(settings["enabled"] and settings["token"] and settings["phone_number_id"])


def normalize_phone(value: str | None) -> str:
    digits = re.sub(r"\D", "", value or "")
    if digits.startswith("00"):
        digits = digits[2:]
    return digits if 7 <= len(digits) <= 15 else ""


def verify_signature(body: bytes, header: str | None) -> bool:
    """Check Meta's X-Hub-Signature-256 header when an app secret is set."""
    secret = str(config()["app_secret"])
    if not secret:
        # Without an app secret the payload cannot be authenticated. Refuse it
        # in production; allow it in development so the simulator and a local
        # tunnel keep working before Meta credentials are in place.
        return os.getenv("ARATI_ENV", "").strip().lower() != "production"
    if not header or not header.startswith("sha256="):
        return False
    expected = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header.split("=", 1)[1])


def parse_webhook(payload: dict) -> list[dict[str, str]]:
    """Flatten a Meta webhook payload into messages the agent can answer."""
    messages: list[dict[str, str]] = []
    for entry in payload.get("entry") or []:
        for change in entry.get("changes") or []:
            value = change.get("value") or {}
            names = {
                contact.get("wa_id", ""): ((contact.get("profile") or {}).get("name") or "")
                for contact in value.get("contacts") or []
            }
            for message in value.get("messages") or []:
                wa_id = str(message.get("from") or "")
                text = ""
                message_type = str(message.get("type") or "")
                if message_type == "text":
                    text = str((message.get("text") or {}).get("body") or "")
                elif message_type == "button":
                    text = str((message.get("button") or {}).get("text") or "")
                elif message_type == "interactive":
                    interactive = message.get("interactive") or {}
                    reply = interactive.get("button_reply") or interactive.get("list_reply") or {}
                    text = str(reply.get("id") or reply.get("title") or "")
                messages.append({
                    "wa_id": wa_id,
                    "name": names.get(wa_id, ""),
                    "text": text,
                    "message_id": str(message.get("id") or ""),
                    "type": message_type,
                })
    return messages


# --- outbound transport ----------------------------------------------------


def send_text(to: str, body: str, *, transport: str = "auto") -> tuple[bool, str, str]:
    """Send one WhatsApp text. Returns (ok, error detail, message status)."""
    mode = transport if transport in {"cloud", "simulator"} else (
        "cloud" if cloud_configured() else "simulator"
    )
    if mode == "simulator":
        return True, "", "simulated"
    settings = config()
    if not settings["enabled"]:
        return False, "WhatsApp processing is disabled.", "failed"
    if not settings["token"] or not settings["phone_number_id"]:
        return False, "WhatsApp Cloud API is not configured.", "failed"
    url = (
        f"https://graph.facebook.com/{settings['api_version']}/"
        f"{settings['phone_number_id']}/messages"
    )
    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": re.sub(r"\D", "", to or ""),
        "type": "text",
        "text": {"preview_url": False, "body": (body or "")[:4096]},
    }
    try:
        response = httpx.post(
            url,
            json=payload,
            headers={"Authorization": f"Bearer {settings['token']}"},
            timeout=10,
        )
    except httpx.HTTPError as exc:
        return False, f"{type(exc).__name__}: {exc}"[:500], "failed"
    if response.status_code >= 400:
        return False, f"HTTP {response.status_code}: {response.text}"[:500], "failed"
    return True, "", "sent"


def _deliver(
    db: Session, conversation: WhatsAppConversation, to: str, body: str,
    transport: str, order_id: int | None = None,
) -> tuple[bool, str]:
    ok, detail, label = send_text(to, body, transport=transport)
    db.add(WhatsAppMessage(
        conversation_id=conversation.id, order_id=order_id, wa_id=to,
        direction="out", body=(body or "")[:4000], status=label, detail=detail,
        created_at=utcnow(),
    ))
    conversation.updated_at = utcnow()
    return ok, detail


# --- conversation state ----------------------------------------------------

_STATE_KEYS = (
    "step", "kind", "cart", "item_id", "fulfilment", "room_number",
    "delivery_address", "name", "check_in", "nights", "guests",
    "room_type_id", "room_type", "service_id", "when", "notes",
)


def _new_state() -> dict:
    return {
        "step": "main", "kind": "", "cart": [], "item_id": None,
        "fulfilment": "", "room_number": "", "delivery_address": "",
        "name": "", "check_in": "", "nights": 0, "guests": 0,
        "room_type_id": None, "room_type": "", "service_id": None,
        "when": "", "notes": "",
    }


def _load_state(conversation: WhatsAppConversation) -> dict:
    state = _new_state()
    try:
        stored = json.loads(conversation.state or "{}")
    except (TypeError, ValueError):
        stored = {}
    if isinstance(stored, dict):
        for key in _STATE_KEYS:
            if key in stored:
                state[key] = stored[key]
    if not isinstance(state["cart"], list):
        state["cart"] = []
    if not state["step"]:
        state["step"] = "main"
    return state


def _save_state(conversation: WhatsAppConversation, state: dict) -> None:
    conversation.state = json.dumps({key: state.get(key) for key in _STATE_KEYS})
    conversation.updated_at = utcnow()


def _conversation(db: Session, wa_id: str, name: str = "") -> WhatsAppConversation:
    conversation = db.scalar(
        select(WhatsAppConversation).where(WhatsAppConversation.wa_id == wa_id)
    )
    if conversation is None:
        conversation = WhatsAppConversation(
            wa_id=wa_id, display_name=(name or "")[:160],
            state=json.dumps(_new_state()), created_at=utcnow(), updated_at=utcnow(),
        )
        db.add(conversation)
        db.flush()
    elif name and not conversation.display_name:
        conversation.display_name = name[:160]
    return conversation


# --- catalog helpers -------------------------------------------------------


def _hotel_name(db: Session) -> str:
    row = db.get(HotelSetting, "hotel_name")
    return (row.value if row and row.value.strip() else "Arati Hotel").strip()


def _food_items(db: Session) -> list[CatalogItem]:
    return list(db.scalars(
        select(CatalogItem).where(
            CatalogItem.active.is_(True),
            CatalogItem.category.in_(FOOD_CATEGORIES),
        ).order_by(CatalogItem.category, CatalogItem.name)
    ).all())


def _service_items(db: Session) -> list[CatalogItem]:
    return list(db.scalars(
        select(CatalogItem).where(
            CatalogItem.active.is_(True), CatalogItem.category == "service",
        ).order_by(CatalogItem.name)
    ).all())


def _room_type_items(db: Session) -> list[CatalogItem]:
    return list(db.scalars(
        select(CatalogItem).where(
            CatalogItem.active.is_(True), CatalogItem.category == "room",
        ).order_by(CatalogItem.rate, CatalogItem.name)
    ).all())


def _line_amount(rate: object, quantity: int) -> Decimal:
    value = Decimal(str(rate or 0)) * Decimal(max(1, int(quantity)))
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _cart_entries(db: Session, state: dict) -> list[dict]:
    entries = []
    for row in state.get("cart") or []:
        try:
            item_id = int(row.get("item_id"))
            quantity = int(row.get("qty"))
        except (TypeError, ValueError):
            continue
        item = db.get(CatalogItem, item_id)
        if item is None or not item.active or quantity < 1:
            continue
        entries.append({
            "item": item, "qty": quantity,
            "amount": _line_amount(item.rate, quantity),
        })
    return entries


def _cart_total(entries: list[dict]) -> Decimal:
    return sum((entry["amount"] for entry in entries), Decimal("0.00"))


def _cart_text(entries: list[dict]) -> str:
    lines = [f"{entry['qty']} × {entry['item'].name} — {money(entry['amount'])}"
             for entry in entries]
    return "\n".join(lines)


def _greeting(db: Session) -> str:
    return "\n".join([
        f"*{_hotel_name(db).upper()} · KHANDBARI*",
        "Namaste! I can take food orders and booking requests right now.",
        "",
        "1. Order food & drinks",
        "2. Book a room",
        "3. Event or service",
        "4. Talk to the front desk",
        "",
        "Reply with a number. Type *menu* anytime to restart.",
    ])


def _food_menu_text(db: Session) -> tuple[str, list[CatalogItem]]:
    items = _food_items(db)
    if not items:
        return "Our menu is being updated. Reply 4 to talk to the front desk.", []
    lines = ["*Food & drinks*", "Reply with an item number.", ""]
    for index, item in enumerate(items[:MAX_MENU_ITEMS], start=1):
        lines.append(f"{index}. {item.name} — {money(item.rate)}")
    if len(items) > MAX_MENU_ITEMS:
        lines.append(
            f"\nShowing {MAX_MENU_ITEMS} of {len(items)} items. "
            "Ask the front desk for the rest of the menu."
        )
    lines.extend(["", "0. Back to the main menu"])
    return "\n".join(lines), items


def _service_menu_text(db: Session) -> tuple[str, list[CatalogItem]]:
    items = _service_items(db)
    if not items:
        return "No services are listed right now. Reply 4 to talk to the front desk.", []
    lines = ["*Event & services*", "Reply with the service number.", ""]
    for index, item in enumerate(items[:MAX_MENU_ITEMS], start=1):
        lines.append(f"{index}. {item.name} — {money(item.rate)}")
    lines.extend(["", "0. Back to the main menu"])
    return "\n".join(lines), items


def _room_type_menu_text(db: Session) -> tuple[str, list[CatalogItem]]:
    items = _room_type_items(db)
    lines = ["Which room type would you like?", ""]
    for index, item in enumerate(items, start=1):
        lines.append(f"{index}. {item.name} — {money(item.rate)} / night")
    lines.extend(["0. No preference"])
    return "\n".join(lines), items


# --- order creation --------------------------------------------------------


def _create_order(db: Session, conversation: WhatsAppConversation, state: dict) -> Order:
    kind = state.get("kind") or "food"
    customer_name = (state.get("name") or conversation.display_name or "WhatsApp guest")[:160]
    now = utcnow()
    order = Order(
        order_number=next_order_number(db),
        channel="whatsapp",
        kind=kind,
        status="new",
        contact_wa_id=conversation.wa_id,
        customer_name=customer_name,
        customer_phone=conversation.wa_id,
        fulfilment=(state.get("fulfilment") or "")[:30],
        room_number=(state.get("room_number") or "")[:20],
        delivery_address=(state.get("delivery_address") or "")[:240],
        party_size=0,
        requested_for="",
        notes=(state.get("notes") or "")[:2000],
        total=Decimal("0.00"),
        conversation_id=conversation.id,
        # Day-wise ledger: the local business day the order came in.
        business_date=local_now().date().isoformat(),
        created_at=now,
        updated_at=now,
    )
    total = Decimal("0.00")

    if kind == "food":
        for entry in _cart_entries(db, state):
            item = entry["item"]
            order.items.append(OrderItem(
                catalog_item_id=item.id,
                description=item.name[:240],
                category=item.category,
                quantity=Decimal(entry["qty"]),
                unit_price=Decimal(str(item.rate or 0)),
                amount=entry["amount"],
            ))
            total += entry["amount"]
        order.requested_for = "As soon as possible"
    elif kind == "room":
        try:
            check_in = date.fromisoformat(str(state.get("check_in") or ""))
        except ValueError:
            check_in = local_now().date()
        nights = max(1, int(state.get("nights") or 1))
        order.check_in_date = check_in
        order.check_out_date = check_in + timedelta(days=nights)
        order.party_size = max(1, int(state.get("guests") or 1))
        order.requested_for = check_in.isoformat()
        order.notes = (
            f"Room request via WhatsApp · {nights} night(s) · "
            f"{order.party_size} guest(s)."
        )[:2000]
        if state.get("room_type_id"):
            item = db.get(CatalogItem, int(state["room_type_id"]))
            if item is not None:
                amount = _line_amount(item.rate, nights)
                order.items.append(OrderItem(
                    catalog_item_id=item.id,
                    description=f"{item.name} — {nights} night(s)"[:240],
                    category="room",
                    quantity=Decimal(nights),
                    unit_price=Decimal(str(item.rate or 0)),
                    amount=amount,
                ))
                total += amount
    elif kind == "service":
        order.requested_for = str(state.get("when") or "")[:80]
        if state.get("service_id"):
            item = db.get(CatalogItem, int(state["service_id"]))
            if item is not None:
                amount = _line_amount(item.rate, 1)
                order.items.append(OrderItem(
                    catalog_item_id=item.id,
                    description=item.name[:240],
                    category=item.category,
                    quantity=Decimal(1),
                    unit_price=Decimal(str(item.rate or 0)),
                    amount=amount,
                ))
                total += amount

    order.total = total.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    db.add(order)
    db.flush()
    return order


def _confirmation_text(db: Session, state: dict) -> str:
    kind = state.get("kind")
    name = state.get("name") or "Guest"
    lines = []
    if kind == "food":
        entries = _cart_entries(db, state)
        lines = ["*Please confirm your order*", f"Name: {name}", "", "Items:"]
        lines.extend(
            f"{entry['qty']} × {entry['item'].name} — {money(entry['amount'])}"
            for entry in entries
        )
        lines.extend([
            "",
            f"Fulfilment: {_fulfilment_text(state)}",
            f"Items total: {money(_cart_total(entries))}",
            "_Service charge and VAT are added on the bill._",
        ])
    elif kind == "room":
        try:
            check_in = date.fromisoformat(str(state.get("check_in") or ""))
        except ValueError:
            check_in = local_now().date()
        nights = max(1, int(state.get("nights") or 1))
        check_out = check_in + timedelta(days=nights)
        room_type = state.get("room_type") or "No preference"
        item = (db.get(CatalogItem, int(state["room_type_id"]))
                if state.get("room_type_id") else None)
        lines = ["*Please confirm your room request*", f"Room: {room_type}"]
        if item is not None:
            lines.append(f"Rate: {money(item.rate)} / night")
            lines.append(f"Estimated room charge: {money(_line_amount(item.rate, nights))}")
        lines.extend([
            f"Check-in: {check_in.strftime('%d %b %Y')}",
            f"Check-out: {check_out.strftime('%d %b %Y')} ({nights} night(s))",
            f"Guests: {int(state.get('guests') or 1)}",
            f"Name: {name}",
            "",
            "The front desk will confirm availability.",
        ])
    else:
        item = (db.get(CatalogItem, int(state["service_id"]))
                if state.get("service_id") else None)
        lines = ["*Please confirm your request*"]
        if item is not None:
            lines.append(f"Service: {item.name} — {money(item.rate)}")
        lines.append(f"When: {state.get('when') or 'To be arranged'}")
        lines.append(f"Name: {name}")
        if state.get("notes"):
            lines.append(f"Notes: {state['notes']}")
    lines.extend(["", "Reply *YES* to confirm, or *NO* to cancel."])
    return "\n".join(lines)


def _fulfilment_text(state: dict) -> str:
    fulfilment = state.get("fulfilment")
    if fulfilment == "room":
        return f"To room {state.get('room_number') or '—'}"
    if fulfilment == "delivery":
        return f"Delivery to {state.get('delivery_address') or '—'}"
    if fulfilment == "dine_in":
        return "Dine in"
    return "Pickup"


def _order_received_text(db: Session, order: Order) -> str:
    name = (order.customer_name or "there").split()[0]
    if order.kind == "room":
        follow_up = "Our front desk will confirm availability shortly."
    elif order.kind == "service":
        follow_up = "Our team will confirm the details shortly."
    else:
        follow_up = "Our team will confirm your order shortly."
    return (
        f"Thank you, {name}!\nYour request is saved as *{order.order_number}*.\n"
        f"{follow_up}\n\nReply *menu* to start another order."
    )


# --- step handlers ---------------------------------------------------------


def _handle_main(db: Session, conversation: WhatsAppConversation, state: dict,
                 text: str) -> tuple[list[str], Order | None]:
    lowered = text.strip()
    if lowered == "1":
        menu, items = _food_menu_text(db)
        if not items:
            return [menu], None
        state["kind"] = "food"
        state["step"] = "food_menu"
        return [menu], None
    if lowered == "2":
        state["kind"] = "room"
        state["step"] = "room_checkin"
        return [
            "Which date will you check in?\n"
            f"Reply in YYYY-MM-DD format (today is {local_now().date().isoformat()})."
        ], None
    if lowered == "3":
        menu, items = _service_menu_text(db)
        if not items:
            return [menu], None
        state["kind"] = "service"
        state["step"] = "service_menu"
        return [menu], None
    if lowered == "4":
        state["step"] = "human"
        conversation.bot_paused = True
        return [
            "Connecting you to the front desk. A team member will reply here shortly.\n"
            "Reply *menu* if you would rather use the assistant again."
        ], None
    return ["Please reply with a number from 1 to 4, or type *menu*."], None


def _handle_food_menu(db: Session, state: dict,
                      text: str) -> tuple[list[str], Order | None]:
    menu, items = _food_menu_text(db)
    if not items:
        return [menu], None
    if not text.strip().isdigit():
        return ["Reply with the item number, or 0 for the main menu."], None
    choice = int(text.strip())
    if choice == 0:
        state["step"] = "main"
        return [_greeting(db)], None
    if not 1 <= choice <= len(items):
        return ["That item number is not on the list. Reply with a number from the menu."], None
    item = items[choice - 1]
    state["item_id"] = item.id
    state["step"] = "food_qty"
    return [f"{item.name} — {money(item.rate)}\nHow many would you like? Reply 1–50."], None


def _handle_food_qty(db: Session, state: dict,
                     text: str) -> tuple[list[str], Order | None]:
    value = text.strip()
    if not value.isdigit() or not 1 <= int(value) <= 50:
        return ["Please reply with a quantity from 1 to 50."], None
    quantity = int(value)
    item = db.get(CatalogItem, int(state.get("item_id") or 0))
    if item is None or not item.active:
        state["step"] = "food_menu"
        menu, _ = _food_menu_text(db)
        return ["That item is no longer available.\n\n" + menu], None
    cart = state.get("cart") or []
    for row in cart:
        if int(row.get("item_id", 0)) == item.id:
            row["qty"] = min(50, int(row.get("qty", 0)) + quantity)
            break
    else:
        if len(cart) >= MAX_CART_LINES:
            state["step"] = "food_more"
            return ["That is the maximum number of items per order. Reply 2 to checkout."], None
        cart.append({"item_id": item.id, "qty": quantity})
    state["cart"] = cart
    state["step"] = "food_more"
    entries = _cart_entries(db, state)
    return [
        f"Added {quantity} × {item.name}.\n\n*Your order*\n{_cart_text(entries)}\n"
        f"Total: {money(_cart_total(entries))}\n\n"
        "1. Add another item\n2. Checkout\n3. Clear the order"
    ], None


def _handle_food_more(db: Session, state: dict,
                      text: str) -> tuple[list[str], Order | None]:
    choice = text.strip()
    if choice == "1":
        state["step"] = "food_menu"
        menu, _ = _food_menu_text(db)
        return [menu], None
    if choice == "2":
        if not _cart_entries(db, state):
            state["step"] = "main"
            return ["Your order is empty. Reply 1 to choose an item."], None
        state["step"] = "food_fulfilment"
        return [
            "How would you like to receive it?\n"
            "1. Pickup\n2. Delivery\n3. Dine in\n4. To my room"
        ], None
    if choice == "3":
        state["cart"] = []
        state["step"] = "main"
        return ["Your order has been cleared.\n\n" + _greeting(db)], None
    return ["Reply 1 to add another item, 2 to checkout, or 3 to clear the order."], None


def _handle_food_fulfilment(db: Session, state: dict,
                            text: str) -> tuple[list[str], Order | None]:
    options = {"1": "pickup", "2": "delivery", "3": "dine_in", "4": "room"}
    if text.strip() not in options:
        return ["Reply 1 for pickup, 2 for delivery, 3 for dine in, or 4 for your room."], None
    state["fulfilment"] = options[text.strip()]
    if state["fulfilment"] == "room":
        state["step"] = "food_room"
        return ["Which room number should we bring it to?"], None
    if state["fulfilment"] == "delivery":
        state["step"] = "food_address"
        return ["Please send the delivery address."], None
    state["step"] = "food_name"
    return ["What name should the order be under?"], None


def _handle_food_room(db: Session, state: dict,
                      text: str) -> tuple[list[str], Order | None]:
    value = text.strip()
    if not value or len(value) > 20:
        return ["Please reply with your room number."], None
    room = db.scalar(select(Room).where(Room.number == value, Room.active.is_(True)))
    if room is None:
        return ["I can't find that room. Please check the room number and reply again."], None
    state["room_number"] = room.number
    state["step"] = "food_name"
    return ["What name should the order be under?"], None


def _handle_food_address(db: Session, state: dict,
                         text: str) -> tuple[list[str], Order | None]:
    value = text.strip()
    if len(value) < 5:
        return ["Please send a fuller delivery address (at least 5 characters)."], None
    state["delivery_address"] = value[:240]
    state["step"] = "food_name"
    return ["What name should the order be under?"], None


def _handle_room_checkin(db: Session, state: dict,
                         text: str) -> tuple[list[str], Order | None]:
    value = text.strip()
    try:
        check_in = date.fromisoformat(value)
    except ValueError:
        return [
            "I couldn't read that date. Please reply in YYYY-MM-DD, "
            f"for example {local_now().date().isoformat()}."
        ], None
    today = local_now().date()
    if check_in < today:
        return ["That date has already passed. Please choose a future check-in date."], None
    if check_in > today + timedelta(days=365):
        return ["Please choose a check-in date within the next 12 months."], None
    state["check_in"] = check_in.isoformat()
    state["step"] = "room_nights"
    return ["How many nights will you stay? Reply with a number (1–30)."], None


def _handle_room_nights(db: Session, state: dict,
                        text: str) -> tuple[list[str], Order | None]:
    value = text.strip()
    if not value.isdigit() or not 1 <= int(value) <= 30:
        return ["Please reply with the number of nights, from 1 to 30."], None
    state["nights"] = int(value)
    state["step"] = "room_guests"
    return ["How many guests? Reply with a number (1–10)."], None


def _handle_room_guests(db: Session, state: dict,
                        text: str) -> tuple[list[str], Order | None]:
    value = text.strip()
    if not value.isdigit() or not 1 <= int(value) <= 10:
        return ["Please reply with the number of guests, from 1 to 10."], None
    state["guests"] = int(value)
    menu, items = _room_type_menu_text(db)
    if not items:
        state["room_type"] = "No preference"
        state["room_type_id"] = None
        state["step"] = "room_name"
        return [menu + "\n\nWhat name should the booking be under?"], None
    state["step"] = "room_type"
    return [menu], None


def _handle_room_type(db: Session, state: dict,
                      text: str) -> tuple[list[str], Order | None]:
    menu, items = _room_type_menu_text(db)
    value = text.strip()
    if not value.isdigit():
        return ["Reply with a room type number, or 0 for no preference."], None
    choice = int(value)
    if choice == 0:
        state["room_type"] = "No preference"
        state["room_type_id"] = None
    elif 1 <= choice <= len(items):
        item = items[choice - 1]
        state["room_type"] = item.name
        state["room_type_id"] = item.id
    else:
        return ["That room type is not on the list. Please reply with a number from the list."], None
    state["step"] = "room_name"
    return ["What name should the booking be under?"], None


def _handle_service_menu(db: Session, state: dict,
                         text: str) -> tuple[list[str], Order | None]:
    menu, items = _service_menu_text(db)
    value = text.strip()
    if not value.isdigit():
        return ["Reply with the service number, or 0 for the main menu."], None
    choice = int(value)
    if choice == 0:
        state["step"] = "main"
        return [_greeting(db)], None
    if not 1 <= choice <= len(items):
        return ["That number is not on the list. Please reply with a service number."], None
    item = items[choice - 1]
    state["service_id"] = item.id
    state["step"] = "service_when"
    return [
        f"{item.name} — {money(item.rate)}\n\n"
        "When do you need it? Reply with date and time, for example 2026-10-25 18:30."
    ], None


def _handle_service_when(db: Session, state: dict,
                         text: str) -> tuple[list[str], Order | None]:
    value = text.strip()
    try:
        if len(value) <= 10:
            requested = datetime.combine(date.fromisoformat(value), datetime.min.time()).replace(
                hour=12, minute=0
            )
        else:
            requested = datetime.fromisoformat(value)
    except ValueError:
        return [
            "I couldn't read that date and time. Reply like 2026-10-25 18:30."
        ], None
    now = local_now().replace(tzinfo=None)
    if requested < now - timedelta(hours=1):
        return ["That time has already passed. Please choose a future date and time."], None
    if requested > now + timedelta(days=365):
        return ["Please choose a date within the next 12 months."], None
    state["when"] = requested.strftime("%Y-%m-%d %H:%M")
    state["step"] = "service_notes"
    return ["Any details for the team? Reply with a note, or *SKIP*."], None


def _handle_service_notes(db: Session, state: dict,
                          text: str) -> tuple[list[str], Order | None]:
    value = text.strip()
    state["notes"] = "" if value.casefold() == "skip" else value[:900]
    state["step"] = "service_name"
    return ["What name should the booking be under?"], None


def _handle_name(db: Session, conversation: WhatsAppConversation, state: dict,
                 text: str) -> tuple[list[str], Order | None]:
    name = text.strip()
    if len(name) < 2 or len(name) > 80:
        return ["Please reply with the name for this order (2–80 characters)."], None
    state["name"] = name
    state["step"] = "confirm"
    return [_confirmation_text(db, state)], None


def _handle_confirm(db: Session, conversation: WhatsAppConversation, state: dict,
                    text: str) -> tuple[list[str], Order | None]:
    lowered = text.strip().casefold()
    if lowered in {"yes", "y", "confirm", "ok", "okay"}:
        order = _create_order(db, conversation, state)
        return [_order_received_text(db, order)], order
    if lowered in {"no", "n"}:
        state.clear()
        state.update(_new_state())
        return ["No problem — nothing has been ordered or booked. Reply *menu* to start again."], None
    return ["Please reply *YES* to confirm or *NO* to cancel."], None


_HANDLERS = {
    "main": _handle_main,
    "food_menu": lambda db, conv, state, text: _handle_food_menu(db, state, text),
    "food_qty": lambda db, conv, state, text: _handle_food_qty(db, state, text),
    "food_more": lambda db, conv, state, text: _handle_food_more(db, state, text),
    "food_fulfilment": lambda db, conv, state, text: _handle_food_fulfilment(db, state, text),
    "food_room": lambda db, conv, state, text: _handle_food_room(db, state, text),
    "food_address": lambda db, conv, state, text: _handle_food_address(db, state, text),
    "food_name": _handle_name,
    "room_checkin": lambda db, conv, state, text: _handle_room_checkin(db, state, text),
    "room_nights": lambda db, conv, state, text: _handle_room_nights(db, state, text),
    "room_guests": lambda db, conv, state, text: _handle_room_guests(db, state, text),
    "room_type": lambda db, conv, state, text: _handle_room_type(db, state, text),
    "room_name": _handle_name,
    "service_menu": lambda db, conv, state, text: _handle_service_menu(db, state, text),
    "service_when": lambda db, conv, state, text: _handle_service_when(db, state, text),
    "service_notes": lambda db, conv, state, text: _handle_service_notes(db, state, text),
    "service_name": _handle_name,
    "confirm": _handle_confirm,
}


# --- public entry point ----------------------------------------------------


def process_inbound(
    db: Session, wa_id: str, name: str, text: str, *,
    transport: str = "auto", message_id: str = "",
) -> dict:
    """Run one inbound message through the agent and persist the conversation."""
    phone = normalize_phone(wa_id)
    if not phone:
        return {"replies": [], "order": None, "conversation": None}

    if message_id and db.scalar(select(WhatsAppMessage.id).where(
        WhatsAppMessage.message_id == message_id,
        WhatsAppMessage.direction == "in",
    )) is not None:
        # Meta retries a webhook when it does not see a timely 200. Never let a
        # retried "YES" create a second order.
        return {"replies": [], "order": None, "conversation": None}

    conversation = _conversation(db, phone, name)
    body = (text or "").strip()[:4000]
    lowered = body.casefold()
    db.add(WhatsAppMessage(
        conversation_id=conversation.id, wa_id=phone, direction="in",
        body=body or "[unsupported message]", message_id=(message_id or "")[:120],
        status="received", created_at=utcnow(),
    ))
    db.flush()

    if conversation.bot_paused and lowered not in {"menu", "start", "resume", "bot"}:
        db.commit()
        return {"replies": [], "order": None, "conversation": conversation}

    state = _load_state(conversation)
    order = None

    if conversation.bot_paused:
        conversation.bot_paused = False
        _save_state(conversation, _new_state())
        replies = [_greeting(db)]
    elif lowered in {"cancel", "stop", "quit"}:
        _save_state(conversation, _new_state())
        replies = ["Cancelled. Nothing has been ordered or booked.\nReply *menu* to start again."]
    elif lowered in {"menu", "start", "hi", "hello", "namaste", "help"}:
        _save_state(conversation, _new_state())
        replies = [_greeting(db)]
    elif lowered == "0" and state.get("step") != "main":
        _save_state(conversation, _new_state())
        replies = [_greeting(db)]
    else:
        handler = _HANDLERS.get(str(state.get("step") or "main"), _handle_main)
        replies, order = handler(db, conversation, state, body)
        _save_state(conversation, _new_state() if order is not None else state)

    db.flush()
    for reply in replies:
        _deliver(db, conversation, phone, reply, transport, order.id if order else None)
    conversation.updated_at = utcnow()
    db.commit()
    return {"replies": replies, "order": order, "conversation": conversation}


def conversation_for(db: Session, wa_id: str, name: str = "") -> WhatsAppConversation | None:
    phone = normalize_phone(wa_id)
    if not phone:
        return None
    conversation = _conversation(db, phone, name)
    db.commit()
    return conversation


def set_bot_paused(db: Session, conversation: WhatsAppConversation, paused: bool) -> None:
    conversation.bot_paused = paused
    if not paused:
        _save_state(conversation, _new_state())
    conversation.updated_at = utcnow()
    db.commit()


def status_message(order: Order, status: str) -> str:
    number = order.order_number
    if status == "confirmed":
        if order.kind == "room":
            return (
                f"Good news — your room request *{number}* is confirmed. "
                "Our front desk will have your room ready."
            )
        if order.kind == "service":
            return f"Your request *{number}* is confirmed. Our team will be ready for you."
        return f"Good news — your order *{number}* is confirmed."
    if status == "preparing":
        return f"We are preparing your order *{number}* now."
    if status == "ready":
        if order.kind == "room":
            return f"Your room for booking *{number}* is ready. Please come to the front desk."
        if order.kind == "food" and order.fulfilment == "room" and order.room_number:
            return f"Your order *{number}* is ready and will be brought to room {order.room_number}."
        if order.kind == "food" and order.fulfilment == "pickup":
            return f"Your order *{number}* is ready for pickup at the restaurant."
        return f"Your *{number}* request is ready."
    if status == "completed":
        return f"Thank you for choosing Arati Hotel. Your request *{number}* is now complete."
    if status == "cancelled":
        return (
            f"Your request *{number}* has been cancelled. "
            "Please reply here or call the front desk if you need help."
        )
    return ""


def notify_order_status(db: Session, order: Order, status: str,
                        *, transport: str = "auto") -> bool:
    """Send a status update to the guest on WhatsApp and log it."""
    phone = normalize_phone(order.contact_wa_id or order.customer_phone)
    if not phone:
        return False
    body = status_message(order, status)
    if not body:
        return False
    conversation = _conversation(db, phone, order.customer_name)
    ok, _ = _deliver(db, conversation, phone, body, transport, order.id)
    db.commit()
    return ok


def send_manual(db: Session, conversation: WhatsAppConversation, body: str,
                *, transport: str = "auto") -> tuple[bool, str]:
    text = (body or "").strip()
    if not text:
        return False, "Write a message first."
    ok, detail = _deliver(
        db, conversation, conversation.wa_id, text[:4000], transport,
    )
    db.commit()
    return ok, detail
