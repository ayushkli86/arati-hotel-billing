"""Seed the complete Arati Hotel, Khandbari, Sankhuwasabha restaurant menu."""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import select, text

from .database import Base, SessionLocal, engine
from .models import CatalogItem

UNIT_KG = "kg"

MENU: list[tuple[str, str, int, str]] = [
    # 1. Soup
    ("Soup", "Veg clear soup", 180, "pcs"),
    ("Soup", "Chicken corn soup", 210, "pcs"),
    ("Soup", "Sweet corn soup", 190, "pcs"),
    ("Soup", "Cream of Chicken Soup", 240, "pcs"),
    ("Soup", "Cream of mushroom soup", 230, "pcs"),
    ("Soup", "Hot & sour soup Veg", 180, "pcs"),
    ("Soup", "Hot & sour soup Non veg", 210, "pcs"),
    ("Soup", "Manchow soup", 225, "pcs"),
    # 2. Sandwich
    ("Sandwich", "Veg. sandwich", 350, "pcs"),
    ("Sandwich", "Non-veg sandwich", 470, "pcs"),
    # 3. Breakfast Set
    ("Breakfast Set", "Simple Breakfast", 300, "pcs"),
    ("Breakfast Set", "Organic Breakfast", 450, "pcs"),
    ("Breakfast Set", "Indian Breakfast", 350, "pcs"),
    # 4. Tea & Coffee
    ("Tea & Coffee", "Mint tea", 100, "pcs"),
    ("Tea & Coffee", "Black tea", 40, "pcs"),
    ("Tea & Coffee", "Milk tea", 70, "pcs"),
    ("Tea & Coffee", "Milk masala tea", 80, "pcs"),
    ("Tea & Coffee", "Green tea", 100, "pcs"),
    ("Tea & Coffee", "Lemon tea", 50, "pcs"),
    ("Tea & Coffee", "Hot lemon with Ginger Honey", 150, "pcs"),
    ("Tea & Coffee", "Hot Milk", 150, "pcs"),
    ("Tea & Coffee", "Expresso", 165, "pcs"),
    ("Tea & Coffee", "Americano", 185, "pcs"),
    ("Tea & Coffee", "Cappuccino", 250, "pcs"),
    # 5. Cold Beverage
    ("Cold Beverage", "Plain Lassi", 150, "pcs"),
    ("Cold Beverage", "Banana Lassi", 220, "pcs"),
    ("Cold Beverage", "Sweet Lassi", 200, "pcs"),
    ("Cold Beverage", "Sweet Curd", 150, "pcs"),
    ("Cold Beverage", "Cold Coffee", 200, "pcs"),
    ("Cold Beverage", "Blue Lagoon", 300, "pcs"),
    ("Cold Beverage", "Virgin Majito", 250, "pcs"),
    # 6. Salad
    ("Salad", "Green Salad", 210, "pcs"),
    ("Salad", "Fruit salad", 420, "pcs"),
    ("Salad", "Nepali Salad", 210, "pcs"),
    # 7. Veg Snacks
    ("Veg Snacks", "French fried", 250, "pcs"),
    ("Veg Snacks", "Chips chilly", 340, "pcs"),
    ("Veg Snacks", "Paneer chilly", 430, "pcs"),
    ("Veg Snacks", "Paneer pakauda", 370, "pcs"),
    ("Veg Snacks", "Onion pakauda", 275, "pcs"),
    ("Veg Snacks", "Mushroom Chilly", 380, "pcs"),
    ("Veg Snacks", "Crispy Sweet Corn", 300, "pcs"),
    ("Veg Snacks", "Veg. pakauda", 275, "pcs"),
    ("Veg Snacks", "Onion Ring", 240, "pcs"),
    ("Veg Snacks", "Aalu Jeera", 230, "pcs"),
    ("Veg Snacks", "Peanut Sadheko", 250, "pcs"),
    ("Veg Snacks", "Mushroom Choila", 380, "pcs"),
    ("Veg Snacks", "Cashew nut fry", 495, "pcs"),
    ("Veg Snacks", "Papad Fry/Dry (2pcs)", 150, "pcs"),
    ("Veg Snacks", "Masala Papad", 200, "pcs"),
    ("Veg Snacks", "Mustang Potato Wedges", 375, "pcs"),
    ("Veg Snacks", "Sweet Corn Sadheko", 280, "pcs"),
    ("Veg Snacks", "Bhatmas sadeko", 250, "pcs"),
    ("Veg Snacks", "Aalu sadheko", 250, "pcs"),
    # 8. Non-Veg Snacks
    ("Non-Veg Snacks", "Boiled chicken", 400, "pcs"),
    ("Non-Veg Snacks", "Chicken Chilly", 410, "pcs"),
    ("Non-Veg Snacks", "Chicken Drumstick Leg", 410, "pcs"),
    ("Non-Veg Snacks", "Chicken Sadheko (fry/boiled)", 350, "pcs"),
    ("Non-Veg Snacks", "Chicken fried", 440, "pcs"),
    ("Non-Veg Snacks", "Chicken Sekuwa", 400, "pcs"),
    ("Non-Veg Snacks", "Crispy Chicken", 460, "pcs"),
    ("Non-Veg Snacks", "Grilled Chicken", 520, "pcs"),
    ("Non-Veg Snacks", "Chicken 65", 395, "pcs"),
    ("Non-Veg Snacks", "Chicken Taas", 475, "pcs"),
    ("Non-Veg Snacks", "Chicken sausage (3 pc)", 250, "pcs"),
    ("Non-Veg Snacks", "Chicken Lollipop", 410, "pcs"),
    ("Non-Veg Snacks", "Timur Chicken", 395, "pcs"),
    ("Non-Veg Snacks", "Crispy Chicken wings", 410, "pcs"),
    ("Non-Veg Snacks", "Dragon Chicken", 400, "pcs"),
    ("Non-Veg Snacks", "Singapore Chicken", 400, "pcs"),
    ("Non-Veg Snacks", "Chicken Chaila", 410, "pcs"),
    ("Non-Veg Snacks", "Boiled Egg", 50, "pcs"),
    ("Non-Veg Snacks", "Plain Omelet", 150, "pcs"),
    ("Non-Veg Snacks", "Masala Omelet", 200, "pcs"),
    # 9. Local Chicken
    ("Local Chicken", "Local Chicken Bhutuwa", 550, "pcs"),
    ("Local Chicken", "Local Chicken Curry", 550, "pcs"),
    ("Local Chicken", "Local chicken per kg (Bhutwa & Grevey)", 2500, UNIT_KG),
    # 10. Local Fish
    ("Local Fish", "Local Fish Fry", 450, "pcs"),
    ("Local Fish", "Local Fish Curry", 500, "pcs"),
    # 11. Mutton
    ("Mutton", "Mutton Boiled", 495, "pcs"),
    ("Mutton", "Mutton Bhutan", 350, "pcs"),
    ("Mutton", "Mutton Sadheko", 480, "pcs"),
    ("Mutton", "Mutton Sekuwa", 550, "pcs"),
    ("Mutton", "Mutton Taas", 650, "pcs"),
    ("Mutton", "Mutton Choila", 495, "pcs"),
    # 12. Chopsey
    ("Chopsey", "American Copsey Veg", 400, "pcs"),
    ("Chopsey", "American Copsey Non veg", 450, "pcs"),
    ("Chopsey", "Chinese Copsey Veg", 400, "pcs"),
    ("Chopsey", "Chinese Copsey Non veg", 450, "pcs"),
    # 13. Chowmein / Noodles
    ("Chowmein / Noodles", "Mix Chowmein/Noodles", 280, "pcs"),
    ("Chowmein / Noodles", "Chicken Chowmein/Noodles", 220, "pcs"),
    ("Chowmein / Noodles", "Egg Chowmein/Noodles", 200, "pcs"),
    ("Chowmein / Noodles", "Veg Chowmein/Noodles", 180, "pcs"),
    # 14. Nepali Thukpa
    ("Nepali Thukpa", "Mix Thukpa", 250, "pcs"),
    ("Nepali Thukpa", "Chicken Thukpa", 220, "pcs"),
    ("Nepali Thukpa", "Egg Thukpa", 200, "pcs"),
    ("Nepali Thukpa", "Veg Thukpa", 180, "pcs"),
    # 15. Chicken Momo
    ("Chicken Momo", "Chicken Steam Momo", 200, "pcs"),
    ("Chicken Momo", "Chicken Kothey Momo", 210, "pcs"),
    ("Chicken Momo", "Chicken Jhol Momo", 240, "pcs"),
    ("Chicken Momo", "Chicken Sizzler Momo", 350, "pcs"),
    ("Chicken Momo", "Chicken Fried Momo", 240, "pcs"),
    ("Chicken Momo", "Chicken Chilly Momo", 300, "pcs"),
    ("Chicken Momo", "Kodo ko Chicken Momo", 250, "pcs"),
    ("Chicken Momo", "Chicken Momo Plater", 500, "pcs"),
    # 16. Veg Momo
    ("Veg Momo", "Veg Steam Momo", 180, "pcs"),
    ("Veg Momo", "Veg Kothey Momo", 190, "pcs"),
    ("Veg Momo", "Veg Jhol Momo", 200, "pcs"),
    ("Veg Momo", "Veg Sizzler Momo", 300, "pcs"),
    ("Veg Momo", "Veg Fried Momo", 190, "pcs"),
    ("Veg Momo", "Veg Chilly Momo", 275, "pcs"),
    ("Veg Momo", "Kodo ko Veg. Momo", 200, "pcs"),
    ("Veg Momo", "Veg Momo Plater", 400, "pcs"),
    # 17. Khaja Set
    ("Khaja Set", "Veg Khaja set", 450, "pcs"),
    ("Khaja Set", "Mutton Khaja set", 650, "pcs"),
    ("Khaja Set", "Chicken Khaja set", 550, "pcs"),
    ("Khaja Set", "Fish Khaja set", 750, "pcs"),
    ("Khaja Set", "Sukuti Khaja set", 600, "pcs"),
    # 18. Fried Rice
    ("Fried Rice", "Mix Fried Rice", 370, "pcs"),
    ("Fried Rice", "Chicken Fried Rice", 320, "pcs"),
    ("Fried Rice", "Egg Fried Rice", 300, "pcs"),
    ("Fried Rice", "Veg Fried Rice", 275, "pcs"),
    ("Fried Rice", "Jira Rice", 300, "pcs"),
    ("Fried Rice", "Chicken Biryani", 600, "pcs"),
    ("Fried Rice", "Mutton Biryani", 650, "pcs"),
    ("Fried Rice", "Veg Biryani", 450, "pcs"),
    ("Fried Rice", "Egg Biryani", 400, "pcs"),
    # 19. Traditional Nepali Thali
    ("Traditional Nepali Thali", "Local Fish Thali", 650, "pcs"),
    ("Traditional Nepali Thali", "Mutton Thali", 600, "pcs"),
    ("Traditional Nepali Thali", "Local Chicken Thali", 650, "pcs"),
    ("Traditional Nepali Thali", "Boiler Chicken Thali", 500, "pcs"),
    ("Traditional Nepali Thali", "Veg. Thali", 400, "pcs"),
    # 20. Veg Curry
    ("Veg Curry", "Paneer butter masala", 480, "pcs"),
    ("Veg Curry", "Mattar paneer", 450, "pcs"),
    ("Veg Curry", "Kadai paneer", 480, "pcs"),
    ("Veg Curry", "Mushroom Masala", 450, "pcs"),
    ("Veg Curry", "Mix veg curry", 400, "pcs"),
    # 21. Non veg curry / Gravy
    ("Non veg curry / Gravy", "Chicken curry", 400, "pcs"),
    ("Non veg curry / Gravy", "Local chicken curry", 600, "pcs"),
    ("Non veg curry / Gravy", "Chicken butter masala", 480, "pcs"),
    ("Non veg curry / Gravy", "Mutton curry", 550, "pcs"),
    ("Non veg curry / Gravy", "Local Fish Curry", 600, "pcs"),
    ("Non veg curry / Gravy", "Pork curry", 500, "pcs"),
    # 22. Roti / Paratha
    ("Roti / Paratha", "Tawa roti Per pic", 40, "pcs"),
    ("Roti / Paratha", "Butter roti per pic", 60, "pcs"),
    ("Roti / Paratha", "Aaloo Paratha", 150, "pcs"),
    ("Roti / Paratha", "Laccha Paratha", 120, "pcs"),
    # 23. Daal
    ("Daal", "Plain daal", 120, "pcs"),
    ("Daal", "Daal makhani", 220, "pcs"),
    ("Daal", "Daal tadka", 240, "pcs"),
    ("Daal", "Daal fried", 240, "pcs"),
    # 24. Continental
    ("Continental", "Chicken sizzler", 500, "pcs"),
    ("Continental", "Veg. Sizzler", 380, "pcs"),
    # 25. Italian (Pizza / Pasta)
    ("Italian (Pizza / Pasta)", "Mix Veg pizza", 550, "pcs"),
    ("Italian (Pizza / Pasta)", "Chicken pizza", 500, "pcs"),
    ("Italian (Pizza / Pasta)", "Mushroom pizza", 500, "pcs"),
    ("Italian (Pizza / Pasta)", "Cheese Pizza", 600, "pcs"),
    ("Italian (Pizza / Pasta)", "Chicken Alfredo", 480, "pcs"),
    ("Italian (Pizza / Pasta)", "Chicken Arabiata", 450, "pcs"),
    ("Italian (Pizza / Pasta)", "Chicken Bolognese", 500, "pcs"),
]

LEGACY_PLACEHOLDERS = {"Breakfast Set", "Chicken Thali", "Veg Thali", "Tea / Coffee"}


def _ensure_menu_group_column() -> None:
    with engine.begin() as conn:
        columns = {row[1] for row in conn.execute(text("PRAGMA table_info(catalog_items)"))}
        if "menu_group" not in columns:
            conn.execute(text("ALTER TABLE catalog_items ADD COLUMN menu_group VARCHAR(80) NOT NULL DEFAULT ''"))


def seed_complete_menu() -> int:
    Base.metadata.create_all(bind=engine)
    _ensure_menu_group_column()

    menu_names = {name for _, name, _, _ in MENU}
    created = updated = 0
    with SessionLocal.begin() as db:
        for order, (group, name, rate, unit) in enumerate(MENU, start=1):
            item = db.scalar(
                select(CatalogItem).where(
                    CatalogItem.name == name,
                    CatalogItem.menu_group == group,
                )
            )
            if item is None:
                item = db.scalar(
                    select(CatalogItem).where(
                        CatalogItem.name == name,
                        CatalogItem.menu_group == "",
                    )
                )
            if item is None:
                item = CatalogItem(name=name, item_code="", taxable=True)
                db.add(item)
                created += 1
            else:
                updated += 1
            item.category = "restaurant"
            item.menu_group = group
            item.rate = Decimal(str(rate))
            item.unit = unit
            item.sort_order = order
            item.active = True

        for item in db.scalars(
            select(CatalogItem).where(
                CatalogItem.name.in_(LEGACY_PLACEHOLDERS),
                CatalogItem.menu_group == "",
            )
        ).all():
            if item.name not in menu_names:
                item.active = False

    return created


if __name__ == "__main__":
    added = seed_complete_menu()
    print(f"Menu ready: {len(MENU)} items seeded ({added} new).")
