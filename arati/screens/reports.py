"""Sales reports for a date range, with CSV export."""

from __future__ import annotations

import csv
import tkinter as tk
from datetime import date
from pathlib import Path
from tkinter import filedialog, ttk

from .. import db, ui


class ReportsScreen(ttk.Frame):
    def __init__(self, master, app):
        super().__init__(master)
        self.app = app
        self.conn = app.conn
        self.start = tk.StringVar(value=date.today().replace(day=1).isoformat())
        self.end = tk.StringVar(value=ui.today_iso())

        header = ttk.Frame(self)
        header.pack(fill="x", pady=(0, 10))
        ttk.Label(header, text="Reports", style="H1.TLabel").pack(side="left")
        ttk.Label(header, text="Sales, VAT and payment mix", style="Muted.TLabel").pack(
            side="left", padx=14, pady=(10, 0)
        )

        bar = ttk.Frame(self)
        bar.pack(fill="x", pady=(0, 10))
        ui.field(bar, "From (YYYY-MM-DD)", self.start, width=14, card=False).pack(side="left")
        ui.field(bar, "To (YYYY-MM-DD)", self.end, width=14, card=False).pack(
            side="left", padx=8
        )
        ttk.Button(bar, text="Run report", style="Primary.TButton",
                   command=self.run).pack(side="left", padx=(10, 0))
        ttk.Button(bar, text="Export CSV", style="Ghost.TButton",
                   command=self.export_csv).pack(side="left", padx=6)

        cards = ttk.Frame(self)
        cards.pack(fill="x", pady=(0, 10))
        self.stat_labels = {}
        for key, label in (
            ("bills", "Bills"), ("subtotal", "Net sales"), ("service_charge", "Service charge"),
            ("vat", "VAT collected"), ("total", "Gross total"), ("balance", "Outstanding"),
        ):
            card = ui.Card(cards, padding=12)
            card.pack(side="left", fill="both", expand=True, padx=(0, 8))
            ttk.Label(card.inner, text=label.upper(), style="Section.TLabel").pack(anchor="w")
            value = ttk.Label(card.inner, text="—", style="Total.TLabel")
            value.pack(anchor="w")
            self.stat_labels[key] = value

        body = ttk.Frame(self)
        body.pack(fill="both", expand=True)
        body.columnconfigure(0, weight=1)
        body.columnconfigure(1, weight=1)
        body.rowconfigure(0, weight=1)

        method_card = ui.Card(body)
        method_card.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        ttk.Label(method_card.inner, text="PAYMENT METHODS", style="Section.TLabel").pack(anchor="w")
        wrap = ttk.Frame(method_card.inner, style="Card.TFrame")
        wrap.pack(fill="both", expand=True, pady=(6, 0))
        self.method_tree = ui.table(
            wrap, [("method", "Method", 160), ("bills", "Bills", 70), ("total", "Total", 130)],
            height=8,
        )
        self.method_tree.pack(side="left", fill="both", expand=True)
        ui.scroll(self.method_tree, wrap).pack(side="right", fill="y")

        category_card = ui.Card(body)
        category_card.grid(row=0, column=1, sticky="nsew")
        ttk.Label(category_card.inner, text="REVENUE BY CATEGORY", style="Section.TLabel").pack(anchor="w")
        wrap2 = ttk.Frame(category_card.inner, style="Card.TFrame")
        wrap2.pack(fill="both", expand=True, pady=(6, 0))
        self.category_tree = ui.table(
            wrap2, [("category", "Category", 160), ("total", "Revenue", 140)], height=8
        )
        self.category_tree.pack(side="left", fill="both", expand=True)
        ui.scroll(self.category_tree, wrap2).pack(side="right", fill="y")

        daily_card = ui.Card(self)
        daily_card.pack(fill="both", expand=True, pady=(10, 0))
        ttk.Label(daily_card.inner, text="DAILY TOTALS", style="Section.TLabel").pack(anchor="w")
        wrap3 = ttk.Frame(daily_card.inner, style="Card.TFrame")
        wrap3.pack(fill="both", expand=True, pady=(6, 0))
        self.daily_tree = ui.table(
            wrap3, [("date", "Date", 140), ("bills", "Bills", 80), ("total", "Total", 140)],
            height=7,
        )
        self.daily_tree.pack(side="left", fill="both", expand=True)
        ui.scroll(self.daily_tree, wrap3).pack(side="right", fill="y")

        self.status = ui.status(self)
        self.status.pack(anchor="w", pady=(8, 0))
        self.summary = None
        self.run()

    def run(self) -> None:
        if not ui.is_iso_date(self.start.get()) or not ui.is_iso_date(self.end.get()):
            ui.notify(self.status, "Dates must be YYYY-MM-DD.", ui.DANGER)
            return
        summary = db.sales_summary(self.conn, self.start.get(), self.end.get())
        self.summary = summary
        totals = summary["totals"]
        self.stat_labels["bills"].configure(text=str(totals["bills"]))
        for key in ("subtotal", "service_charge", "vat", "total", "balance"):
            self.stat_labels[key].configure(text=ui.money(totals[key]))

        self.method_tree.delete(*self.method_tree.get_children())
        for row in summary["by_method"]:
            self.method_tree.insert("", "end", values=(
                row["payment_method"], row["bills"], ui.money(row["total"])
            ))

        self.category_tree.delete(*self.category_tree.get_children())
        for row in summary["by_category"]:
            self.category_tree.insert("", "end", values=(
                row["category"].title(), ui.money(row["total"])
            ))

        self.daily_tree.delete(*self.daily_tree.get_children())
        for row in summary["daily"]:
            self.daily_tree.insert("", "end", values=(
                row["bill_date"], row["bills"], ui.money(row["total"])
            ))

        ui.notify(self.status,
                  f"{totals['bills']} bill(s) · {ui.money(totals['total'])} gross · "
                  f"VAT {ui.money(totals['vat'])}", ui.MUTED)

    def export_csv(self) -> None:
        if not self.summary:
            ui.notify(self.status, "Run a report first.", ui.DANGER)
            return
        path = filedialog.asksaveasfilename(
            defaultextension=".csv", filetypes=[("CSV", "*.csv")],
            initialfile=f"arati-sales-{self.start.get()}_{self.end.get()}.csv",
        )
        if not path:
            return
        bills = db.list_bills(self.conn, "", limit=100000)
        with open(path, "w", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(["Bill no", "Date", "Guest", "Room", "Payment", "Subtotal",
                             "Service charge", "VAT", "Total", "Paid", "Balance", "Status"])
            for bill in bills:
                if not (self.start.get() <= bill["bill_date"] <= self.end.get()):
                    continue
                if bill["is_draft"]:
                    continue  # a draft has no accounting value yet
                writer.writerow([bill["bill_no"], bill["bill_date"], bill["guest_name"],
                                 bill["room_no"], bill["payment_method"], bill["subtotal"],
                                 bill["service_charge"], bill["vat"], bill["total"],
                                 bill["paid"], bill["balance"], bill["status"]])
        ui.notify(self.status, f"Exported to {Path(path).name}", ui.OK)
