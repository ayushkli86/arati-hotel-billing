"""Seed catalog for Arati Hotel, taken from the hotel's public website.

Room *types* and their published rates are seeded here. Room *numbers* are
not: they belong to the hotel's room inventory, which is owned by
:mod:`arati.rooms` and configurable in the Room Management screen. The
published room numbers (``2001``, ``2222``, ``2224``) are listed in
``PUBLISHED_ROOM_NUMBERS`` for the admin to apply when the hotel confirms its
numbering.
"""

ROOM_TYPES = [
    ("Standard Room", 3000.0),
    ("Deluxe Room", 4500.0),
    ("Super Deluxe Room", 5000.0),
    ("Family Room", 4000.0),
    ("Suite Deluxe Room", 6500.0),
]

# Room numbers published on the hotel's website. The inventory defaults to
# 101-125; these are offered as the alternative list.
PUBLISHED_ROOM_NUMBERS = ("2001", "2222", "2224")

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
    from .db import upsert_item

    for order, (name, price) in enumerate(ROOM_TYPES):
        upsert_item(conn, name, "room", price, unit="night", sort_order=order)

    for order, (name, price) in enumerate(MENU):
        upsert_item(conn, name, "food", price, unit="plate", sort_order=order)

    for order, (name, price) in enumerate(SERVICES):
        upsert_item(conn, name, "service", price, unit="event", sort_order=order)
