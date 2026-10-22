"""Seed catalog for Arati Hotel, taken from the hotel's public website.

Room numbers marked as placeholders in the README; rates and menu prices are
the published ones as of the scrape (Oct 2026). Admins can edit everything in
the Catalog screen.
"""

ROOM_TYPES = [
    ("Standard Room", 3000.0),
    ("Deluxe Room", 4500.0),
    ("Super Deluxe Room", 5000.0),
    ("Family Room", 4000.0),
    ("Suite Deluxe Room", 6500.0),
]

# (room number, room type, floor)
ROOMS = [
    ("101", "Standard Room", "1"),
    ("2001", "Deluxe Room", "2"),
    ("2222", "Deluxe Room", "2"),
    ("2224", "Deluxe Room", "2"),
    ("301", "Super Deluxe Room", "3"),
    ("302", "Super Deluxe Room", "3"),
    ("303", "Super Deluxe Room", "3"),
    ("401", "Family Room", "4"),
    ("501", "Suite Deluxe Room", "5"),
    ("502", "Suite Deluxe Room", "5"),
]

MENU = [
    ("Arati House Kebab Set Veg", 800.0),
    ("Arati House Kebab Set Non-Veg", 1400.0),
    ("Chicken Biryani", 490.0),
    ("Chicken Pizza", 600.0),
    ("Chicken Steam Momo", 180.0),
    ("Chicken Chilly", 350.0),
    ("Chinese Combo Veg", 800.0),
    ("Chinese Combo Non-Veg", 990.0),
    ("Momo Set Veg", 700.0),
    ("Momo Set Non-Veg", 950.0),
    ("Mutton Biryani", 550.0),
    ("French Fries", 250.0),
    ("Chicken Burger Set", 370.0),
    ("Chicken Thukpa", 220.0),
    ("Simple Breakfast", 250.0),
    ("Mutton Bhutan", 350.0),
    ("Mutton Sadeko", 420.0),
    ("Local Chicken Bhutwa", 440.0),
    ("Egg Thukpa", 200.0),
    ("Veg Thukpa", 180.0),
    ("Chicken Kothey Momo", 210.0),
    ("Chicken Khaja Set", 450.0),
    ("Mutton Khaja Set", 550.0),
]

SERVICES = [
    ("Birthday Party", 0.0),
    ("Anniversary Party", 0.0),
    ("Engagement Party", 0.0),
    ("Meeting Hall", 0.0),
    ("Teej Celebration", 0.0),
    ("Valentine's Romantic Dinner", 0.0),
]


def seed_catalog(conn) -> None:
    from .db import save_room, upsert_item

    type_ids = {}
    for order, (name, price) in enumerate(ROOM_TYPES):
        type_ids[name] = upsert_item(
            conn, name, "room", price, unit="night", sort_order=order
        )

    for room_no, room_type, floor in ROOMS:
        save_room(conn, room_no, type_ids[room_type], floor)

    for order, (name, price) in enumerate(MENU):
        upsert_item(conn, name, "food", price, unit="plate", sort_order=order)

    for order, (name, price) in enumerate(SERVICES):
        upsert_item(conn, name, "service", price, unit="event", sort_order=order)
