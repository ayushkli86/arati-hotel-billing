"""The dashboard the front desk sees when the till opens.

Everything on it is a live figure from the database for the current
business day. Sales and collections are shown as separate cards, because
they are different measurements and mixing them is how a till starts
believing it is richer than it is.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from .. import business_time as bt
from .. import db, payments, reports, rooms, ui


class DashboardScreen(ttk.Frame):
    def __init__(self, master, app):
        super().__init__(master)
        self.app = app
        self.conn = app.conn

        header = ttk.Frame(self)
        header.pack(fill="x", pady=(0, 12))
        ttk.Label(header, text="Dashboard", style="H1.TLabel").pack(side="left")
        self.today_label = ttk.Label(header, text="", style="Muted.TLabel")
        self.today_label.pack(side="left", padx=14, pady=(10, 0))

        self.cards = ttk.Frame(self)
        self.cards.pack(fill="x", pady=(0, 12))

        body = ttk.Frame(self)
        body.pack(fill="both", expand=True)
        body.columnconfigure(0, weight=3)
        body.columnconfigure(1, weight=2)
        body.rowconfigure(0, weight=1)

        left = ttk.Frame(body)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 10))

        rooms_card = ui.Card(left)
        rooms_card.pack(fill="both", expand=True)
        ttk.Label(rooms_card.inner, text="ROOMS RIGHT NOW", style="Section.TLabel").pack(anchor="w")
        wrap = ttk.Frame(rooms_card.inner, style="Card.TFrame")
        wrap.pack(fill="both", expand=True, pady=(6, 0))
        self.rooms_tree = ui.table(
            wrap,
            [("room", "Room", 60), ("status", "Status", 120), ("guest", "Guest", 160),
             ("checkout", "Check-out", 120), ("balance", "Balance", 100)],
            height=10,
        )
        self.rooms_tree.pack(side="left", fill="both", expand=True)
        ui.scroll(self.rooms_tree, wrap).pack(side="right", fill="y")

        recent_card = ui.Card(left)
        recent_card.pack(fill="both", expand=True, pady=(10, 0))
        ttk.Label(recent_card.inner, text="RECENT INVOICES", style="Section.TLabel").pack(anchor="w")
        wrap2 = ttk.Frame(recent_card.inner, style="Card.TFrame")
        wrap2.pack(fill="both", expand=True, pady=(6, 0))
        self.bills_tree = ui.table(
            wrap2,
            [("bill_no", "Invoice", 110), ("time", "Time", 70), ("guest", "Guest", 150),
             ("room", "Room", 55), ("method", "Payment", 95), ("total", "Total", 100)],
            height=8,
        )
        self.bills_tree.pack(side="left", fill="both", expand=True)
        ui.scroll(self.bills_tree, wrap2).pack(side="right", fill="y")

        right = ttk.Frame(body)
        right.grid(row=0, column=1, sticky="nsew")

        outstanding_card = ui.Card(right)
        outstanding_card.pack(fill="both", expand=True)
        ttk.Label(outstanding_card.inner, text="OUTSTANDING BALANCES",
                  style="Section.TLabel").pack(anchor="w")
        wrap3 = ttk.Frame(outstanding_card.inner, style="Card.TFrame")
        wrap3.pack(fill="both", expand=True, pady=(6, 0))
        self.outstanding_tree = ui.table(
            wrap3,
            [("bill_no", "Invoice", 110), ("guest", "Guest", 150),
             ("room", "Room", 55), ("balance", "Balance", 100)],
            height=8,
        )
        self.outstanding_tree.pack(side="left", fill="both", expand=True)
        ui.scroll(self.outstanding_tree, wrap3).pack(side="right", fill="y")

        actions = ui.Card(right)
        actions.pack(fill="x", pady=(10, 0))
        ttk.Label(actions.inner, text="QUICK ACTIONS", style="Section.TLabel").pack(anchor="w")
        row = ttk.Frame(actions.inner, style="Card.TFrame")
        row.pack(fill="x", pady=(6, 0))
        ttk.Button(row, text="New invoice", style="Primary.TButton",
                   command=lambda: self.app.open_screen("billing")).pack(side="left")
        ttk.Button(row, text="Room board", style="Ghost.TButton",
                   command=lambda: self.app.open_screen("rooms")).pack(side="left", padx=6)
        ttk.Button(row, text="Take a payment", style="Ghost.TButton",
                   command=lambda: self.app.open_screen("payments")).pack(side="left")

        self.status = ui.status(self)
        self.status.pack(anchor="w", pady=(8, 0))

        self.reload()

    def reload(self) -> None:
        day = bt.today().isoformat()
        self.today_label.configure(
            text=f"Business date {day} · {self.app.settings.get('business_timezone', '')}"
        )
        cards = reports.dashboard_cards(self.conn, day)

        for child in self.cards.winfo_children():
            child.destroy()
        fields = (
            ("gross_sales", "Gross sales", ui.money(cards["gross_sales"])),
            ("net_sales", "Net sales", ui.money(cards["net_sales"])),
            ("collected", "Payments collected", ui.money(cards["collected"])),
            ("cash_collected", "Cash collections", ui.money(cards["cash_collected"])),
            ("outstanding", "Outstanding", ui.money(cards["outstanding"])),
            ("room_revenue", "Room revenue", ui.money(cards["room_revenue"])),
            ("invoices", "Invoices issued", str(cards["invoices"])),
            ("occupied", "Occupied rooms", f"{cards['occupied_rooms']} of {cards['sellable_rooms']}"),
        )
        for _key, label, value in fields:
            card = ui.Card(self.cards, padding=10)
            card.pack(side="left", fill="both", expand=True, padx=(0, 6))
            ttk.Label(card.inner, text=label.upper(), style="Section.TLabel").pack(anchor="w")
            ttk.Label(card.inner, text=value, style="Total.TLabel",
                      font=(ui.FONT, 14, "bold")).pack(anchor="w")

        self.rooms_tree.delete(*self.rooms_tree.get_children())
        for room in rooms.list_rooms(self.conn):
            self.rooms_tree.insert("", "end", values=(
                room["room_no"], room["status"], room["guest_name"] or "—",
                room["expected_checkout"] or "—", ui.money(room["balance"]),
            ))

        self.bills_tree.delete(*self.bills_tree.get_children())
        for row in db.list_bills(self.conn, "", limit=12):
            self.bills_tree.insert("", "end", values=(
                row["bill_no"], str(row["created_at"] or "")[11:16],
                row["guest_name"] or "Walk-in guest", row["room_no"] or "—",
                row["payment_method"], ui.money(row["total"]),
            ))

        self.outstanding_tree.delete(*self.outstanding_tree.get_children())
        total = 0.0
        for row in db.unpaid_bills(self.conn)[:40]:
            total += float(row["balance"] or 0)
            self.outstanding_tree.insert("", "end", values=(
                row["bill_no"], row["guest_name"] or "Walk-in guest",
                row["room_no"] or "—", ui.money(row["balance"]),
            ))
        ui.notify(
            self.status,
            f"{ui.money(total)} outstanding across "
            f"{len(db.unpaid_bills(self.conn))} invoice(s).",
            ui.MUTED,
        )
