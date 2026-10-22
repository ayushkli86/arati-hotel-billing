"""Customers and Guests — the people the hotel bills.

Guest details are needed at the front desk, so staff can read and create
them. Deactivating a guest record is an administrator action, because it
affects historic reporting.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk

from .. import customers as customers_module
from .. import db, permissions, ui

CUSTOMER_TYPES = ("individual", "business")


class CustomersScreen(ttk.Frame):
    def __init__(self, master, app):
        super().__init__(master)
        self.app = app
        self.conn = app.conn
        self.search = tk.StringVar()

        header = ttk.Frame(self)
        header.pack(fill="x", pady=(0, 10))
        ttk.Label(header, text="Customers & Guests", style="H1.TLabel").pack(side="left")
        ttk.Label(header, text="Guest master records and their invoices",
                  style="Muted.TLabel").pack(side="left", padx=14, pady=(10, 0))

        bar = ttk.Frame(self)
        bar.pack(fill="x", pady=(0, 10))
        entry = ttk.Entry(bar, textvariable=self.search, width=34)
        entry.pack(side="left")
        entry.bind("<KeyRelease>", lambda _e: self.reload())
        ttk.Button(bar, text="Search", style="Ghost.TButton", command=self.reload).pack(
            side="left", padx=6
        )
        ttk.Button(bar, text="Add guest", style="Primary.TButton",
                   command=self.add_customer).pack(side="right")
        ttk.Button(bar, text="Edit", style="Ghost.TButton",
                   command=self.edit_customer).pack(side="right")
        ttk.Button(bar, text="Invoices", style="Ghost.TButton",
                   command=self.show_invoices).pack(side="right", padx=6)
        ttk.Button(bar, text="Deactivate", style="Danger.TButton",
                   command=self.deactivate).pack(side="right")

        card = ui.Card(self)
        card.pack(fill="both", expand=True)
        wrap = ttk.Frame(card.inner, style="Card.TFrame")
        wrap.pack(fill="both", expand=True)
        self.tree = ui.table(
            wrap,
            [("name", "Name", 190), ("phone", "Phone", 120), ("address", "Address", 220),
             ("pan", "PAN", 110), ("type", "Type", 90), ("invoices", "Invoices", 70),
             ("billed", "Billed", 110)],
            height=16,
        )
        self.tree.pack(side="left", fill="both", expand=True)
        ui.scroll(self.tree, wrap).pack(side="right", fill="y")
        self.tree.bind("<Double-1>", lambda _e: self.edit_customer())

        self.status = ui.status(self)
        self.status.pack(anchor="w", pady=(8, 0))

        self.reload()

    def reload(self) -> None:
        self.tree.delete(*self.tree.get_children())
        rows = customers_module.list_customers(self.conn, self.search.get().strip())
        for row in rows:
            stats = self.conn.execute(
                "SELECT COUNT(*) AS invoices, COALESCE(SUM(total), 0) AS billed "
                "FROM bills WHERE customer_id = ?",
                (row["customer_id"],),
            ).fetchone()
            self.tree.insert("", "end", iid=str(row["customer_id"]), values=(
                row["name"], row["phone"], row["address"], row["pan"],
                row["customer_type"].title(), stats["invoices"], ui.money(stats["billed"]),
            ))
        ui.notify(self.status, f"{len(rows)} guest(s).", ui.MUTED)

    def _selected(self) -> int | None:
        selection = self.tree.selection()
        if not selection:
            ui.notify(self.status, "Select a guest first.", ui.DANGER)
            return None
        return int(selection[0])

    def add_customer(self) -> None:
        try:
            permissions.require(self.app.user, "customer.edit", "add a guest")
        except permissions.PermissionError_ as exc:
            ui.notify(self.status, str(exc), ui.DANGER)
            return
        CustomerDialog(self, self.conn, self.reload)

    def edit_customer(self) -> None:
        customer_id = self._selected()
        if customer_id is None:
            return
        row = customers_module.get_customer(self.conn, customer_id)
        if row is None:
            return
        try:
            permissions.require(self.app.user, "customer.edit", "edit a guest")
        except permissions.PermissionError_ as exc:
            ui.notify(self.status, str(exc), ui.DANGER)
            return
        CustomerDialog(self, self.conn, self.reload, customer=dict(row))

    def deactivate(self) -> None:
        customer_id = self._selected()
        if customer_id is None:
            return
        try:
            permissions.require(self.app.user, "customer.deactivate", "deactivate a guest")
        except permissions.PermissionError_ as exc:
            ui.notify(self.status, str(exc), ui.DANGER)
            return
        if not ui.ask("Deactivate this guest? Their invoices are kept."):
            return
        customers_module.deactivate_customer(self.conn, customer_id)
        self.reload()
        ui.notify(self.status, "Guest deactivated.", ui.OK)

    def show_invoices(self) -> None:
        customer_id = self._selected()
        if customer_id is None:
            return
        row = customers_module.get_customer(self.conn, customer_id)
        if row is None:
            return
        CustomerInvoices(self, self.conn, dict(row))


class CustomerDialog(tk.Toplevel):
    def __init__(self, master, conn, on_done, customer: dict | None = None):
        super().__init__(master)
        self.title("Guest details")
        self.configure(bg=ui.BG)
        self.geometry("480x+140+140")
        self.transient(master.winfo_toplevel())
        self.grab_set()
        self.conn = conn
        self.on_done = on_done
        self.customer = customer or {}

        frame = ttk.Frame(self, padding=18)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="Guest details", style="H2.TLabel").pack(anchor="w")

        self.name = tk.StringVar(value=self.customer.get("name", ""))
        self.phone = tk.StringVar(value=self.customer.get("phone", ""))
        self.address = tk.StringVar(value=self.customer.get("address", ""))
        self.pan = tk.StringVar(value=self.customer.get("pan", ""))
        self.kind = tk.StringVar(value=self.customer.get("customer_type", "individual"))

        ui.field(frame, "Name", self.name, card=False).pack(fill="x", pady=(10, 0))
        row = ttk.Frame(frame)
        row.pack(fill="x", pady=(6, 0))
        ui.field(row, "Phone", self.phone, width=20, card=False).pack(side="left")
        ui.field(row, "PAN", self.pan, width=20, card=False).pack(side="left", padx=8)
        ui.field(frame, "Address", self.address, card=False).pack(fill="x", pady=(6, 0))
        ttk.Label(frame, text="Type", style="Muted.TLabel").pack(anchor="w")
        ttk.Combobox(frame, textvariable=self.kind, state="readonly", width=18,
                     values=list(CUSTOMER_TYPES)).pack(anchor="w", pady=(2, 0))

        buttons = ttk.Frame(frame)
        buttons.pack(fill="x", pady=(16, 0))
        ttk.Button(buttons, text="Save", style="Primary.TButton",
                   command=self.save).pack(side="right")
        ttk.Button(buttons, text="Cancel", style="Ghost.TButton",
                   command=self.destroy).pack(side="right", padx=8)

    def save(self) -> None:
        name = self.name.get().strip()
        if not name:
            messagebox.showerror("Name required", "A guest needs a name.", parent=self)
            return
        if self.customer:
            customers_module.save_customer(
                self.conn,
                int(self.customer["customer_id"]),
                name=name,
                phone=self.phone.get().strip(),
                address=self.address.get().strip(),
                pan=self.pan.get().strip(),
                customer_type=self.kind.get(),
            )
        else:
            customers_module.upsert_customer(
                self.conn,
                name,
                phone=self.phone.get().strip(),
                address=self.address.get().strip(),
                pan=self.pan.get().strip(),
                customer_type=self.kind.get(),
            )
        self.on_done()
        self.destroy()


class CustomerInvoices(tk.Toplevel):
    def __init__(self, master, conn, customer: dict):
        super().__init__(master)
        self.title(f"Invoices — {customer['name']}")
        self.configure(bg=ui.BG)
        self.geometry("720x460")
        self.transient(master.winfo_toplevel())

        frame = ttk.Frame(self, padding=18)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text=customer["name"], style="H2.TLabel").pack(anchor="w")
        ttk.Label(
            frame,
            text=f"{customer['phone'] or '—'} · {customer['address'] or '—'}",
            style="Muted.TLabel",
        ).pack(anchor="w", pady=(2, 10))

        wrap = ttk.Frame(frame)
        wrap.pack(fill="both", expand=True)
        tree = ui.table(
            wrap,
            [("bill_no", "Invoice", 110), ("date", "Date", 95), ("room", "Room", 60),
             ("total", "Total", 105), ("paid", "Paid", 100), ("balance", "Balance", 100),
             ("status", "Status", 85)],
            height=14,
        )
        tree.pack(side="left", fill="both", expand=True)
        ui.scroll(tree, wrap).pack(side="right", fill="y")
        rows = conn.execute(
            "SELECT * FROM bills WHERE customer_id = ? ORDER BY bill_date DESC, bill_id DESC",
            (customer["customer_id"],),
        ).fetchall()
        for row in rows:
            tree.insert("", "end", values=(
                row["bill_no"], row["bill_date"], row["room_no"] or "—",
                ui.money(row["total"]), ui.money(row["paid"]), ui.money(row["balance"]),
                row["status"].title(),
            ))
        if not rows:
            ttk.Label(frame, text="This guest has no invoices yet.",
                      style="Muted.TLabel").pack(anchor="w", pady=(10, 0))
        ttk.Button(frame, text="Close", style="Ghost.TButton",
                   command=self.destroy).pack(anchor="e", pady=(10, 0))
