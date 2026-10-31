"""Mobile KOT: room-linked kitchen tickets that also post to the room folio."""

from __future__ import annotations

import re
from datetime import datetime
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from webapp import auth
from webapp.database import Base, get_db
from webapp.main import app
from webapp.models import CatalogItem, Guest, HotelSetting, Kot, Room, RoomCharge, Stay, User


@pytest.fixture()
def app_db():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    session = session_factory()
    guest = Guest(name="Room Guest", full_name="Room Guest", phone="9800000001")
    room = Room(number="101", type="Deluxe Room", status="occupied", nightly_rate=4500)
    session.add_all([
        HotelSetting(key="hotel_name", value="Arati Hotel"),
        guest,
        room,
        User(username="admin", password_hash=auth.hash_password("admin123"),
             full_name="Hotel Administrator", role="admin"),
        CatalogItem(name="Chicken Momo", category="restaurant", menu_group="Momo",
                    rate=Decimal("250"), active=True),
        CatalogItem(name="Milk Tea", category="restaurant", menu_group="Tea & Coffee",
                    rate=Decimal("70"), active=True),
    ])
    session.flush()
    session.add(Stay(
        room_id=room.id, guest_id=guest.id, check_in=datetime(2026, 10, 29, 8, 0),
        status="checked_in", room_number="101", guest_name="Room Guest",
    ))
    session.commit()
    app.dependency_overrides[get_db] = lambda: session
    try:
        yield session
    finally:
        app.dependency_overrides.clear()
        session.close()
        engine.dispose()


def login(client: TestClient) -> None:
    page = client.get("/login")
    token = re.search(r'name="csrf_token" value="([^"]+)"', page.text).group(1)
    client.post("/login", data={"username": "admin", "password": "admin123", "csrf_token": token})


def csrf_from_page(page_text: str) -> str:
    match = (
        re.search(r'csrf: "([^"]+)"', page_text)
        or re.search(r"csrf: '([^']+)'", page_text)
        or re.search(r'name="csrf_token" value="([^"]+)"', page_text)
    )
    assert match is not None
    return match.group(1)


def test_mobile_kot_page_lists_occupied_rooms_and_menu(app_db):
    client = TestClient(app)
    login(client)
    response = client.get("/mobile/kot")
    assert response.status_code == 200
    assert "Room Guest" in response.text
    assert "Chicken Momo" in response.text


def test_saving_room_kot_posts_items_to_folio(app_db):
    client = TestClient(app)
    login(client)
    page = client.get("/mobile/kot")
    token = csrf_from_page(page.text)
    momo, tea = app_db.scalars(select(CatalogItem).order_by(CatalogItem.id)).all()

    response = client.post("/mobile/kot/save", json={
        "csrf_token": token,
        "room_id": app_db.scalar(select(Room)).id,
        "notes": "no chilli",
        "items": [
            {"catalog_id": momo.id, "particular": "x", "qty": 2, "rate": 1,
             "category": "restaurant", "menu_group": "Momo"},
            {"catalog_id": tea.id, "particular": "x", "qty": 3, "rate": 1,
             "category": "restaurant", "menu_group": "Tea & Coffee"},
        ],
    })
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["ok"] is True
    assert body["total"] == 710.0

    kot = app_db.scalar(select(Kot))
    assert kot is not None
    assert kot.status == "new"
    assert kot.room_number == "101"
    assert kot.notes == "no chilli"

    charges = app_db.scalars(select(RoomCharge).order_by(RoomCharge.id)).all()
    assert [(c.description, float(c.amount), c.category) for c in charges] == [
        ("Chicken Momo", 500.0, "food"),
        ("Milk Tea", 210.0, "beverage"),
    ]
    assert all(charge.kot_id == kot.id for charge in charges)


def test_kot_status_flow_moves_forward_only(app_db):
    client = TestClient(app)
    login(client)
    page = client.get("/mobile/kot")
    token = csrf_from_page(page.text)
    momo = app_db.scalar(select(CatalogItem).order_by(CatalogItem.id))
    client.post("/mobile/kot/save", json={
        "csrf_token": token,
        "room_id": app_db.scalar(select(Room)).id,
        "items": [{"catalog_id": momo.id, "particular": "x", "qty": 1, "rate": 1}],
    })
    kot = app_db.scalar(select(Kot))

    for target in ("preparing", "ready", "served"):
        response = client.post(
            f"/kots/{kot.id}/status",
            data={"csrf_token": token, "status": target, "next": "/mobile/kot"},
            follow_redirects=False,
        )
        assert response.status_code == 303
        app_db.expire_all()
        assert app_db.get(Kot, kot.id).status == target

    response = client.post(
        f"/kots/{kot.id}/status",
        data={"csrf_token": token, "status": "preparing", "next": "/mobile/kot"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert "toast_type=warning" in response.headers["location"]
    app_db.expire_all()
    assert app_db.get(Kot, kot.id).status == "served"


def test_kitchen_cut_requires_second_confirmation_and_records_cook(app_db):
    client = TestClient(app)
    login(client)
    page = client.get("/mobile/kot")
    token = csrf_from_page(page.text)
    momo = app_db.scalar(select(CatalogItem).order_by(CatalogItem.id))
    client.post("/mobile/kot/save", json={
        "csrf_token": token,
        "room_id": app_db.scalar(select(Room)).id,
        "items": [{"catalog_id": momo.id, "particular": "x", "qty": 1, "rate": 1}],
    })
    kot = app_db.scalar(select(Kot))
    assert kot.issued_by_name == "Hotel Administrator"

    kitchen = client.get("/kitchen")
    assert kitchen.status_code == 200
    assert "Kitchen Display" in kitchen.text
    assert "Issued by" in kitchen.text
    assert "Hotel Administrator" in kitchen.text

    response = client.post(
        f"/kots/{kot.id}/cut",
        data={"csrf_token": token, "next": "/kitchen"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert "toast_type=warning" in response.headers["location"]
    app_db.expire_all()
    assert app_db.get(Kot, kot.id).status == "new"

    response = client.post(
        f"/kots/{kot.id}/cut",
        data={"csrf_token": token, "cut_confirmed": "1", "next": "/kitchen"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    app_db.expire_all()
    cut = app_db.get(Kot, kot.id)
    assert cut.status == "ready"
    assert cut.cut_by_id is not None
    assert cut.cut_at is not None


def test_kitchen_settings_and_price_edit(app_db):
    client = TestClient(app)
    login(client)
    page = client.get("/kitchen")
    token = csrf_from_page(page.text)
    momo = app_db.scalar(select(CatalogItem).order_by(CatalogItem.id))

    response = client.post(
        "/kitchen/items/%d/price" % momo.id,
        data={"csrf_token": token, "price": "275.50"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    app_db.expire_all()
    assert app_db.get(CatalogItem, momo.id).rate == Decimal("275.50")

    response = client.post(
        "/kitchen/settings",
        data={"csrf_token": token},
        follow_redirects=False,
    )
    assert response.status_code == 303
    app_db.expire_all()
    assert app_db.get(HotelSetting, "kot_double_confirm").value == "0"


def test_json_api_reports_401_to_a_signed_out_client(app_db):
    """The phone app cannot follow a 303 to /login, so it gets a 401 instead."""
    client = TestClient(app)
    for path in ("/api/rooms", "/api/menu", "/api/kots"):
        response = client.get(path, follow_redirects=False)
        assert response.status_code == 401, path
        assert response.json()["detail"]


def test_json_api_serves_rooms_menu_and_the_csrf_token(app_db):
    client = TestClient(app)
    login(client)

    rooms = client.get("/api/rooms").json()
    assert [(row["number"], row["guest_name"]) for row in rooms["rooms"]] == [("101", "Room Guest")]
    assert rooms["csrf"]

    menu = client.get("/api/menu").json()
    assert [row["name"] for row in menu["menu"]] == ["Chicken Momo", "Milk Tea"]
    assert menu["csrf"] == rooms["csrf"]

    # The token handed to the phone is the one the save endpoint accepts.
    momo = app_db.scalar(
        select(CatalogItem).where(CatalogItem.name == "Chicken Momo")
    )
    response = client.post("/mobile/kot/save", json={
        "csrf_token": rooms["csrf"],
        "room_id": app_db.scalar(select(Room)).id,
        "items": [{"catalog_id": momo.id, "particular": "x", "qty": 2, "rate": 1}],
    })
    assert response.status_code == 200, response.text
    assert response.json()["ok"] is True


def test_json_api_lists_and_cuts_an_open_kot_from_any_device(app_db):
    client = TestClient(app)
    login(client)
    page = client.get("/mobile/kot")
    token = csrf_from_page(page.text)
    momo = app_db.scalar(select(CatalogItem).order_by(CatalogItem.id))
    client.post("/mobile/kot/save", json={
        "csrf_token": token,
        "room_id": app_db.scalar(select(Room)).id,
        "items": [{"catalog_id": momo.id, "particular": "x", "qty": 1, "rate": 1}],
    })
    kot = app_db.scalar(select(Kot))

    listing = client.get("/api/kots")
    assert listing.status_code == 200
    assert [row["id"] for row in listing.json()["kots"]] == [kot.id]
    assert listing.json()["csrf"]

    # Double confirmation is on by default: the first call only asks again.
    response = client.post(
        f"/api/kots/{kot.id}/cut", json={"csrf_token": token, "confirm": False},
    )
    assert response.status_code == 428
    app_db.expire_all()
    assert app_db.get(Kot, kot.id).status == "new"

    response = client.post(
        f"/api/kots/{kot.id}/cut", json={"csrf_token": token, "confirm": True},
    )
    assert response.status_code == 200, response.text
    assert response.json()["kot"]["status"] == "ready"
    app_db.expire_all()
    cut = app_db.get(Kot, kot.id)
    assert cut.status == "ready"
    assert cut.cut_by_id is not None
    assert cut.cut_at is not None

    # A second device cutting the same ticket gets a clear conflict.
    response = client.post(
        f"/api/kots/{kot.id}/cut", json={"csrf_token": token, "confirm": True},
    )
    assert response.status_code == 409


def test_json_api_cut_rejects_a_bad_csrf_token(app_db):
    client = TestClient(app)
    login(client)
    page = client.get("/mobile/kot")
    token = csrf_from_page(page.text)
    momo = app_db.scalar(select(CatalogItem).order_by(CatalogItem.id))
    client.post("/mobile/kot/save", json={
        "csrf_token": token,
        "room_id": app_db.scalar(select(Room)).id,
        "items": [{"catalog_id": momo.id, "particular": "x", "qty": 1, "rate": 1}],
    })
    kot = app_db.scalar(select(Kot))

    response = client.post(
        f"/api/kots/{kot.id}/cut", json={"csrf_token": "wrong", "confirm": True},
    )
    assert response.status_code == 403
    app_db.expire_all()
    assert app_db.get(Kot, kot.id).status == "new"


def _save_one_kot(client: TestClient, app_db, token: str) -> Kot:
    momo = app_db.scalar(select(CatalogItem).order_by(CatalogItem.id))
    response = client.post("/mobile/kot/save", json={
        "csrf_token": token,
        "room_id": app_db.scalar(select(Room)).id,
        "items": [{"catalog_id": momo.id, "particular": "x", "qty": 1, "rate": 1}],
    })
    assert response.status_code == 200, response.text
    app_db.expire_all()
    return app_db.scalar(select(Kot).order_by(Kot.id.desc()))


def test_json_api_delete_requires_confirmation_and_reverses_room_charges(app_db):
    client = TestClient(app)
    login(client)
    token = csrf_from_page(client.get("/mobile/kot").text)
    kot = _save_one_kot(client, app_db, token)

    response = client.post(
        f"/api/kots/{kot.id}/delete", json={"csrf_token": token},
    )
    assert response.status_code == 428
    app_db.expire_all()
    assert app_db.get(Kot, kot.id) is not None

    response = client.post(
        f"/api/kots/{kot.id}/delete",
        json={"csrf_token": token, "confirm": True},
    )
    assert response.status_code == 200, response.text
    assert response.json()["reversed_charges"] == 1
    app_db.expire_all()
    assert app_db.get(Kot, kot.id) is None
    assert app_db.scalars(select(RoomCharge)).all() == []
    assert client.get("/api/kots").json()["kots"] == []


def test_delete_refuses_a_ticket_already_on_an_invoice(app_db):
    client = TestClient(app)
    login(client)
    token = csrf_from_page(client.get("/mobile/kot").text)
    kot = _save_one_kot(client, app_db, token)
    charge = app_db.scalar(select(RoomCharge))
    charge.invoice_number = "INV-TEST"
    app_db.commit()

    response = client.post(
        f"/api/kots/{kot.id}/delete",
        json={"csrf_token": token, "confirm": True},
    )
    assert response.status_code == 409
    assert "invoice" in response.json()["detail"].lower()

    response = client.post(
        f"/kots/{kot.id}/delete",
        data={"csrf_token": token, "next": "/kitchen"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert "toast_type=warning" in response.headers["location"]
    app_db.expire_all()
    assert app_db.get(Kot, kot.id) is not None
    assert app_db.scalars(select(RoomCharge)).all()


def test_printed_kot_hides_the_number_title_and_footer(app_db):
    client = TestClient(app)
    login(client)
    token = csrf_from_page(client.get("/mobile/kot").text)
    kot = _save_one_kot(client, app_db, token)

    page = client.get(f"/kots/{kot.id}/print")
    assert page.status_code == 200
    assert kot.kot_number not in page.text
    assert "K.O.T No." not in page.text
    assert "kot-title" not in page.text
    assert "End of K.O.T" not in page.text
    assert "Room No." in page.text


def test_kitchen_board_offers_delete_for_open_tickets(app_db):
    client = TestClient(app)
    login(client)
    token = csrf_from_page(client.get("/mobile/kot").text)
    kot = _save_one_kot(client, app_db, token)

    page = client.get("/kitchen")
    assert page.status_code == 200
    assert f"/kots/{kot.id}/delete" in page.text
    assert "Delete KOT" in page.text


def test_mobile_save_walkin_creates_ticket_without_folio_charge(app_db):
    client = TestClient(app)
    login(client)
    token = csrf_from_page(client.get("/mobile/kot").text)
    momo = app_db.scalar(select(CatalogItem).order_by(CatalogItem.id))

    response = client.post("/mobile/kot/save", json={
        "csrf_token": token,
        "mode": "walkin",
        "guest_name": "Sita Sharma",
        "table_number": "Table 3",
        "items": [{"catalog_id": momo.id, "particular": "Momos", "qty": 2, "rate": 0}],
    })
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["mode"] == "walkin"
    assert body["table_number"] == "Table 3"
    assert body["guest_name"] == "Sita Sharma"

    app_db.expire_all()
    kot = app_db.get(Kot, body["id"])
    assert kot.room_id is None
    assert kot.room_number == ""
    assert kot.guest_name == "Sita Sharma"
    assert app_db.scalars(select(RoomCharge)).all() == []
    rows = client.get("/api/kots").json()["kots"]
    assert rows[0]["table_number"] == "Table 3"
    assert rows[0]["room_number"] == ""


def test_mobile_save_walkin_defaults_to_walk_in_guest(app_db):
    client = TestClient(app)
    login(client)
    token = csrf_from_page(client.get("/mobile/kot").text)
    momo = app_db.scalar(select(CatalogItem).order_by(CatalogItem.id))

    response = client.post("/mobile/kot/save", json={
        "csrf_token": token,
        "mode": "walkin",
        "items": [{"catalog_id": momo.id, "particular": "Momos", "qty": 1, "rate": 0}],
    })
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["guest_name"] == "Walk-in guest"
    assert body["table_number"] == "Walk-in"


def test_mobile_save_room_mode_still_requires_a_room(app_db):
    client = TestClient(app)
    login(client)
    token = csrf_from_page(client.get("/mobile/kot").text)
    momo = app_db.scalar(select(CatalogItem).order_by(CatalogItem.id))

    response = client.post("/mobile/kot/save", json={
        "csrf_token": token,
        "mode": "room",
        "items": [{"catalog_id": momo.id, "particular": "Momos", "qty": 1, "rate": 0}],
    })
    assert response.status_code == 422
    assert "room" in response.json()["detail"].lower()
