"""Catalog: menu items, room types and room numbers."""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk

from .. import db, ui


class CatalogScreen(ttk.Frame):
    def __init__(self, master, app):
        super().__init__(master)
        self.app = app
        self.conn = app.conn
        self.is_admin = app.user["role"] == "admin"
        self.item_id = None
        self.room_id = None

        header = ttk.Frame(self)
        header.pack(fill="x", pady=(0, 10))
        ttk.Label(header, text="Catalog", style="H1.TLabel").pack(side="left")
        ttk.Label(header, text="Rates and items used on bills", style="Muted.TLabel").pack(
            side="left", padx=14, pady=(10, 0)
        )

        self.nb = ttk.Notebook(self)
        self.nb.pack(fill="both", expand=True)
        self._build_items_tab()
        self._build_rooms_tab()
        self._build_room_types_tab()

        self.status = ui.status(self)
        self.status.pack(anchor="w", pady=(8, 0))
        self.reload()

    # ------------------------------------------------------------- items tab
    def _build_items_tab(self) -> None:
        tab = ttk.Frame(self.nb, padding=10)
        self.nb.add(tab, text="Menu & services")
        tab.columnconfigure(0, weight=1)
        tab.rowconfigure(1, weight=1)

        bar = ttk.Frame(tab)
        bar.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        self.search = tk.StringVar()
        self.filter_category = tk.StringVar(value="All")
        entry = ttk.Entry(bar, textvariable=self.search, width=30)
        entry.pack(side="left")
        entry.bind("<KeyRelease>", lambda _e: self.reload())
        ttk.Combobox(bar, textvariable=self.filter_category, state="readonly", width=12,
                     values=["All", "food", "service", "room", "other"]).pack(side="left", padx=8)
        self.filter_category.trace_add("write", lambda *_: self.reload())

        card = ui.Card(tab)
        card.grid(row=1, column=0, sticky="nsew")
        wrap = ttk.Frame(card.inner, style="Card.TFrame")
        wrap.pack(fill="both", expand=True)
        self.item_tree = ui.table(
            wrap,
            [("name", "Name", 250), ("category", "Category", 90), ("price", "Price", 100),
             ("unit", "Unit", 70), ("tax", "VAT", 50)],
            height=14,
        )
        self.item_tree.pack(side="left", fill="both", expand=True)
        ui.scroll(self.item_tree, wrap).pack(side="right", fill="y")
        self.item_tree.bind("<<TreeviewSelect>>", lambda _e: self.load_item())

        form = ttk.Frame(tab)
        form.grid(row=2, column=0, sticky="ew", pady=(10, 0))
        self.item_name = tk.StringVar()
        self.item_price = tk.StringVar()
        self.item_unit = tk.StringVar(value="plate")
        self.item_category = tk.StringVar(value="food")
        self.item_taxable = tk.BooleanVar(value=True)
        self.item_id = None

        ui.field(form, "Name", self.item_name, width=28, card=False).pack(side="left", padx=(0, 8))
        ui.field(form, "Category", self.item_category, width=11, card=False).pack(side="left", padx=(0, 8))
        ui.field(form, "Price (NPR)", self.item_price, width=12, card=False).pack(side="left", padx=(0, 8))
        ui.field(form, "Unit", self.item_unit, width=8, card=False).pack(side="left", padx=(0, 8))
        ttk.Checkbutton(form, text="VAT", variable=self.item_taxable).pack(side="left", pady=(14, 0))

        buttons = ttk.Frame(tab)
        buttons.grid(row=3, column=0, sticky="e", pady=(8, 0))
        ttk.Button(buttons, text="New item", style="Ghost.TButton",
                   command=self.clear_item).pack(side="left", padx=(0, 6))
        ttk.Button(buttons, text="Save item", style="Primary.TButton",
                   command=self.save_item).pack(side="left", padx=(0, 6))
        ttk.Button(buttons, text="Delete", style="Danger.TButton",
                   command=self.delete_item).pack(side="left")

    # ------------------------------------------------------------- rooms tab
    def _build_rooms_tab(self) -> None:
        tab = ttk.Frame(self.nb, padding=10)
        self.nb.add(tab, text="Rooms")
        tab.columnconfigure(0, weight=1)
        tab.rowconfigure(0, weight=1)

        card = ui.Card(tab)
        card.grid(row=0, column=0, sticky="nsew")
        wrap = ttk.Frame(card.inner, style="Card.TFrame")
        wrap.pack(fill="both", expand=True)
        self.room_tree = ui.table(
            wrap,
            [("no", "Room no", 90), ("type", "Room type", 200), ("rate", "Rate / night", 120),
             ("floor", "Floor", 70)],
            height=14,
        )
        self.room_tree.pack(side="left", fill="both", expand=True)
        ui.scroll(self.room_tree, wrap).pack(side="right", fill="y")
        self.room_tree.bind("<<TreeviewSelect>>", lambda _e: self.load_room())

        form = ttk.Frame(tab)
        form.grid(row=1, column=0, sticky="ew", pady=(10, 0))
        self.room_no = tk.StringVar()
        self.room_floor = tk.StringVar()
        self.room_type = tk.StringVar()

        ui.field(form, "Room no", self.room_no, width=12, card=False).pack(side="left", padx=(0, 8))
        ui.field(form, "Floor", self.room_floor, width=8, card=False).pack(side="left", padx=(0, 8))
        ttk.Label(form, text="ROOM TYPE", style="Muted.TLabel").pack(side="left", padx=(0, 4))
        self.type_box = ttk.Combobox(form, textvariable=self.room_type, width=22,
                                     state="readonly")
        self.type_box.pack(side="left", pady=(16, 0))

        buttons = ttk.Frame(tab)
        buttons.grid(row=2, column=0, sticky="e", pady=(8, 0))
        ttk.Button(buttons, text="New room", style="Ghost.TButton",
                   command=self.clear_room).pack(side="left", padx=(0, 6))
        ttk.Button(buttons, text="Save room", style="Primary.TButton",
                   command=self.save_room).pack(side="left", padx=(0, 6))
        ttk.Button(buttons, text="Deactivate", style="Danger.TButton",
                   command=self.delete_room).pack(side="left")

    # -------------------------------------------------------- room types tab
    def _build_room_types_tab(self) -> None:
        tab = ttk.Frame(self.nb, padding=10)
        self.nb.add(tab, text="Room types & rates")
        tab.columnconfigure(0, weight=1)
        tab.rowconfigure(0, weight=1)

        card = ui.Card(tab)
        card.grid(row=0, column=0, sticky="nsew")
        ttk.Label(
            card.inner,
            text="Room types are catalog items in the “room” category. "
                 "Add a new type from the Menu & services tab, then assign rooms to it.",
            style="CardMuted.TLabel",
        ).pack(anchor="w")
        wrap = ttk.Frame(card.inner, style="Card.TFrame")
        wrap.pack(fill="both", expand=True, pady=(10, 0))
        self.type_tree = ui.table(
            wrap,
            [("name", "Room type", 260), ("price", "Rate / night", 140),
             ("unit", "Billed per", 110)],
            height=14,
        )
        self.type_tree.pack(side="left", fill="both", expand=True)
        ui.scroll(self.type_tree, wrap).pack(side="right", fill="y")

    # ------------------------------------------------------------- reloading
    def reload(self) -> None:
        category = self.filter_category.get()
        items = db.list_items(
            self.conn, None if category == "All" else category, self.search.get().strip()
        )
        self.item_tree.delete(*self.item_tree.get_children())
        for item in items:
            self.item_tree.insert(
                "", "end", iid=str(item["item_id"]),
                values=(item["name"], item["category"], ui.money(item["price"]),
                        item["unit"], "Yes" if item["taxable"] else "No"),
            )

        self.room_tree.delete(*self.room_tree.get_children())
        for room in db.list_rooms(self.conn):
            self.room_tree.insert(
                "", "end", iid=str(room["room_id"]),
                values=(room["room_no"], room["room_type"], ui.money(room["rate"]),
                        room["floor"] or "—"),
            )

        types = db.list_items(self.conn, "room")
        self.type_tree.delete(*self.type_tree.get_children())
        for item in types:
            self.type_tree.insert("", "end", iid=str(item["item_id"]),
                                  values=(item["name"], ui.money(item["price"]), item["unit"]))
        self.type_box.configure(values=[t["name"] for t in types])
        self._type_ids = {t["name"]: t["item_id"] for t in types}

    # ----------------------------------------------------------------- items
    def load_item(self) -> None:
        selection = self.item_tree.selection()
        if not selection:
            return
        item = db.get_item(self.conn, int(selection[0]))
        self.item_id = item["item_id"]
        self.item_name.set(item["name"])
        self.item_category.set(item["category"])
        self.item_price.set(f"{item['price']:.2f}")
        self.item_unit.set(item["unit"])
        self.item_taxable.set(bool(item["taxable"]))

    def clear_item(self) -> None:
        self.item_id = None
        for var in (self.item_name, self.item_price):
            var.set("")
        self.item_unit.set("plate")
        self.item_category.set("food")
        self.item_taxable.set(True)

    def _require_admin(self) -> bool:
        if not self.is_admin:
            messagebox.showwarning("Admin only", "Only an admin can edit the catalog.")
            return False
        return True

    def save_item(self) -> None:
        if not self._require_admin():
            return
        try:
            price = float(self.item_price.get() or 0)
        except ValueError:
            ui.notify(self.status, "Price must be a number.", ui.DANGER)
            return
        try:
            item_id = db.upsert_item(
                self.conn,
                name=self.item_name.get(),
                category=self.item_category.get(),
                price=price,
                unit=self.item_unit.get(),
                taxable=self.item_taxable.get(),
                item_id=self.item_id,
            )
        except Exception as exc:  # sqlite unique violation etc.
            ui.notify(self.status, f"Could not save: {exc}", ui.DANGER)
            return
        self.item_id = item_id
        self.reload()
        ui.notify(self.status, "Item saved.", ui.OK)

    def delete_item(self) -> None:
        if not self._require_admin() or not self.item_id:
            ui.notify(self.status, "Select an item first.", ui.DANGER)
            return
        if not ui.ask("Remove this item from the catalog? Existing bills keep their lines."):
            return
        db.deactivate_item(self.conn, self.item_id)
        self.clear_item()
        self.reload()
        ui.notify(self.status, "Item removed.", ui.MUTED)

    # ----------------------------------------------------------------- rooms
    def load_room(self) -> None:
        selection = self.room_tree.selection()
        if not selection:
            return
        room = next((r for r in db.list_rooms(self.conn) if str(r["room_id"]) == selection[0]), None)
        if not room:
            return
        self.room_id = room["room_id"]
        self.room_no.set(room["room_no"])
        self.room_floor.set(room["floor"] or "")
        self.room_type.set(room["room_type"])

    def clear_room(self) -> None:
        self.room_id = None
        self.room_no.set("")
        self.room_floor.set("")
        self.room_type.set("")

    def save_room(self) -> None:
        if not self._require_admin():
            return
        if not self.room_no.get().strip() or self.room_type.get() not in self._type_ids:
            ui.notify(self.status, "Room number and room type are required.", ui.DANGER)
            return
        db.save_room(
            self.conn, self.room_no.get().strip(),
            self._type_ids[self.room_type.get()], self.room_floor.get().strip(),
        )
        self.reload()
        ui.notify(self.status, f"Room {self.room_no.get()} saved.", ui.OK)

    def delete_room(self) -> None:
        if not self._require_admin() or not getattr(self, "room_id", None):
            ui.notify(self.status, "Select a room first.", ui.DANGER)
            return
        if not ui.ask("Deactivate this room?"):
            return
        db.delete_room(self.conn, self.room_id)
        self.clear_room()
        self.reload()
        ui.notify(self.status, "Room deactivated.", ui.MUTED)
