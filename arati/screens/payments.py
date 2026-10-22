"""Payments — the cash ledger at the front desk.

Cash is dated by the moment it changed hands, not by the invoice date, so
a guest paying yesterday's bill today shows up in today's collections and
not in today's sales. The screen keeps that distinction visible.
"""

from __future__ import annotations

import tkinter as tk
from datetime import timedelta
from tkinter import messagebox, ttk

from .. import business_time as bt
from .. import db, payments, permissions, ui

REFUND_REASONS = (
    "Service not delivered",
    "Guest overcharged",
    "Booking cancelled",
    "Courtesy / goodwill",
    "Other (see note)",
)


class PaymentsScreen(ttk.Frame):
    def __init__(self, master, app):
        super().__init__(master)
        self.app = app
        self.conn = app.conn
        self.search = tk.StringVar()
        self.method = tk.StringVar(value="All")

        header = ttk.Frame(self)
        header.pack(fill="x", pady=(0, 10))
        ttk.Label(header, text="Payments", style="H1.TLabel").pack(side="left")
        ttk.Label(header, text="Money received, refunds and outstanding balances",
                  style="Muted.TLabel").pack(side="left", padx=14, pady=(10, 0))

        bar = ttk.Frame(self)
        bar.pack(fill="x", pady=(0, 10))
        entry = ttk.Entry(bar, textvariable=self.search, width=22)
        entry.pack(side="left")
        entry.bind("<KeyRelease>", lambda _e: self.reload())
        ttk.Label(bar, text="Method", style="Muted.TLabel").pack(side="left", padx=(12, 4))
        self.method_box = ttk.Combobox(bar, textvariable=self.method, state="readonly",
                                       width=16, values=["All"])
        self.method_box.pack(side="left")
        self.method_box.bind("<<ComboboxSelected>>", lambda _e: self.reload())

        ttk.Button(bar, text="Record payment", style="Primary.TButton",
                   command=self.record_payment).pack(side="right")
        ttk.Button(bar, text="Refund", style="Danger.TButton",
                   command=self.record_refund).pack(side="right", padx=6)
        ttk.Button(bar, text="Adjustment", style="Danger.TButton",
                   command=self.record_adjustment).pack(side="right")

        cards = ttk.Frame(self)
        cards.pack(fill="x", pady=(0, 10))
        self.stat_labels: dict[str, ttk.Label] = {}
        for key, label in (
            ("collected", "Collected today"),
            ("cash", "Cash collected today"),
            ("outstanding", "Outstanding"),
            ("refunds", "Refunds today"),
        ):
            card = ui.Card(cards, padding=10)
            card.pack(side="left", fill="both", expand=True, padx=(0, 6))
            ttk.Label(card.inner, text=label.upper(), style="Section.TLabel").pack(anchor="w")
            value = ttk.Label(card.inner, text="—", style="Total.TLabel",
                              font=(ui.FONT, 14, "bold"))
            value.pack(anchor="w")
            self.stat_labels[key] = value

        body = ttk.Frame(self)
        body.pack(fill="both", expand=True)
        body.columnconfigure(0, weight=3)
        body.columnconfigure(1, weight=1)
        body.rowconfigure(0, weight=1)

        card = ui.Card(body)
        card.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        ttk.Label(card.inner, text="PAYMENTS RECEIVED", style="Section.TLabel").pack(anchor="w")
        wrap = ttk.Frame(card.inner, style="Card.TFrame")
        wrap.pack(fill="both", expand=True, pady=(6, 0))
        self.tree = ui.table(
            wrap,
            [("date", "Date", 95), ("bill_no", "Invoice", 105), ("guest", "Guest", 150),
             ("room", "Room", 55), ("method", "Method", 95), ("amount", "Amount", 105),
             ("note", "Note", 180)],
            height=14,
        )
        self.tree.pack(side="left", fill="both", expand=True)
        ui.scroll(self.tree, wrap).pack(side="right", fill="y")
        self.tree.bind("<Double-1>", lambda _e: self.record_payment())

        side = ttk.Frame(body)
        side.grid(row=0, column=1, sticky="nsew")

        method_card = ui.Card(side)
        method_card.pack(fill="both", expand=True)
        ttk.Label(method_card.inner, text="COLLECTIONS BY METHOD (30 DAYS)",
                  style="Section.TLabel").pack(anchor="w")
        wrap2 = ttk.Frame(method_card.inner, style="Card.TFrame")
        wrap2.pack(fill="both", expand=True, pady=(6, 0))
        self.method_tree = ui.table(
            wrap2, [("method", "Method", 150), ("entries", "Entries", 70),
                    ("total", "Collected", 120)],
            height=8,
        )
        self.method_tree.pack(side="left", fill="both", expand=True)
        ui.scroll(self.method_tree, wrap2).pack(side="right", fill="y")

        unpaid_card = ui.Card(side)
        unpaid_card.pack(fill="both", expand=True, pady=(10, 0))
        ttk.Label(unpaid_card.inner, text="INVOICES WITH A BALANCE",
                  style="Section.TLabel").pack(anchor="w")
        wrap3 = ttk.Frame(unpaid_card.inner, style="Card.TFrame")
        wrap3.pack(fill="both", expand=True, pady=(6, 0))
        self.unpaid_tree = ui.table(
            wrap3, [("bill_no", "Invoice", 105), ("guest", "Guest", 140),
                    ("balance", "Balance", 100)],
            height=8,
        )
        self.unpaid_tree.pack(side="left", fill="both", expand=True)
        ui.scroll(self.unpaid_tree, wrap3).pack(side="right", fill="y")
        self.unpaid_tree.bind("<Double-1>", lambda _e: self.record_payment())

        self.status = ui.status(self)
        self.status.pack(anchor="w", pady=(8, 0))

        self._load_methods()
        self.reload()

    def _load_methods(self) -> None:
        methods = [
            part.strip()
            for part in (self.app.settings.get("payment_methods") or "").split(",")
            if part.strip()
        ]
        self.method_box.configure(values=["All", *methods])

    def reload(self) -> None:
        day = bt.today().isoformat()
        start = (bt.today() - timedelta(days=29)).isoformat()

        self.tree.delete(*self.tree.get_children())
        rows = payments.list_payments(self.conn, limit=400)
        term = self.search.get().strip()
        for row in rows:
            if term and term.lower() not in (
                f"{row['bill_no']} {row.get('guest_name') or ''} {row.get('room_no') or ''}"
            ).lower():
                continue
            if self.method.get() != "All" and row["method"] != self.method.get():
                continue
            self.tree.insert("", "end", iid=f"p{row['payment_id']}", values=(
                row["business_date"], row["bill_no"], row.get("guest_name") or "Walk-in guest",
                row.get("room_no") or "—", row["method"], ui.money(row["amount"]),
                row["note"] or "",
            ))

        self.method_tree.delete(*self.method_tree.get_children())
        for row in payments.collections_by_method(self.conn, start, day):
            self.method_tree.insert("", "end", values=(
                row["method"], row["entries"], ui.money(row["total"]),
            ))

        self.unpaid_tree.delete(*self.unpaid_tree.get_children())
        for row in db.unpaid_bills(self.conn)[:50]:
            self.unpaid_tree.insert("", "end", iid=row["bill_no"], values=(
                row["bill_no"], row["guest_name"] or "Walk-in guest", ui.money(row["balance"]),
            ))

        today_rows = payments.list_payments(self.conn, day, day)
        cash = sum(float(r["amount"]) for r in today_rows if r["method"] == "Cash")
        refunds = payments.list_refunds(self.conn, day, day)
        refund_total = sum(
            float(r["amount"]) for r in refunds if r["kind"] == "refund"
        )
        self.stat_labels["collected"].configure(
            text=ui.money(sum(float(r["amount"]) for r in today_rows))
        )
        self.stat_labels["cash"].configure(text=ui.money(cash))
        self.stat_labels["outstanding"].configure(
            text=ui.money(payments.outstanding_total(self.conn))
        )
        self.stat_labels["refunds"].configure(text=ui.money(refund_total))
        ui.notify(self.status, f"{len(today_rows)} payment(s) today.", ui.MUTED)

    # ------------------------------------------------------------- actions
    def _guard(self, permission: str, action: str) -> bool:
        try:
            permissions.require(self.app.user, permission, action)
        except permissions.PermissionError_ as exc:
            ui.notify(self.status, str(exc), ui.DANGER)
            return False
        return True

    def record_payment(self) -> None:
        if not self._guard("payment.receive", "record a payment"):
            return
        PaymentDialog(self, self.conn, self.app, self.reload)

    def record_refund(self) -> None:
        if not self._guard("payment.refund", "record a refund"):
            return
        RefundDialog(self, self.conn, self.app, self.reload)

    def record_adjustment(self) -> None:
        if not self._guard("payment.adjust", "post an adjustment"):
            return
        RefundDialog(self, self.conn, self.app, self.reload, adjustment=True)


class PaymentDialog(tk.Toplevel):
    def __init__(self, master, conn, app, on_done):
        super().__init__(master)
        self.title("Record a payment")
        self.configure(bg=ui.BG)
        self.geometry("520x+120+120")
        self.transient(master.winfo_toplevel())
        self.grab_set()
        self.conn = conn
        self.app = app
        self.on_done = on_done

        frame = ttk.Frame(self, padding=18)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="Record a payment", style="H2.TLabel").pack(anchor="w")
        ttk.Label(
            frame,
            text="The payment is dated today, whatever date the invoice carries.",
            style="Muted.TLabel",
        ).pack(anchor="w", pady=(4, 10))

        self.invoice = tk.StringVar()
        self.amount = tk.StringVar()
        self.method = tk.StringVar(value="Cash")
        self.note = tk.StringVar()

        row1 = ttk.Frame(frame)
        row1.pack(fill="x", pady=(6, 0))
        ui.field(row1, "Invoice number", self.invoice, card=False).pack(side="left", fill="x", expand=True)
        ui.field(row1, "Amount", self.amount, width=14, card=False).pack(side="left", padx=(8, 0))

        row2 = ttk.Frame(frame)
        row2.pack(fill="x", pady=(6, 0))
        ttk.Label(row2, text="Method", style="Muted.TLabel").pack(side="left")
        methods = [
            part.strip()
            for part in (app.settings.get("payment_methods") or "").split(",")
            if part.strip()
        ] or ["Cash"]
        ttk.Combobox(row2, textvariable=self.method, state="readonly", width=18,
                     values=methods).pack(side="left", padx=6)
        ui.field(row2, "Note", self.note, card=False).pack(side="left", fill="x", expand=True, padx=8)

        self.balance_label = ttk.Label(frame, text="", style="Muted.TLabel")
        self.balance_label.pack(anchor="w", pady=(8, 0))

        self.invoice.trace_add("write", lambda *_: self._show_balance())

        buttons = ttk.Frame(frame)
        buttons.pack(fill="x", pady=(16, 0))
        ttk.Button(buttons, text="Record payment", style="Primary.TButton",
                   command=self.save).pack(side="right")
        ttk.Button(buttons, text="Cancel", style="Ghost.TButton",
                   command=self.destroy).pack(side="right", padx=8)

    def _show_balance(self) -> None:
        bill_no = self.invoice.get().strip()
        if not bill_no:
            self.balance_label.configure(text="")
            return
        row = self.conn.execute(
            "SELECT total, paid, balance FROM bills WHERE bill_no = ?", (bill_no,)
        ).fetchone()
        if row is None:
            self.balance_label.configure(text="No invoice with that number.")
            return
        self.balance_label.configure(
            text=f"Total {ui.money(row['total'])} · paid {ui.money(row['paid'])} · "
                 f"balance {ui.money(row['balance'])}"
        )

    def save(self) -> None:
        try:
            payments.record_payment(
                self.conn,
                self.invoice.get().strip(),
                float(self.amount.get() or 0),
                method=self.method.get(),
                user_id=self.app.user["user_id"],
                note=self.note.get().strip(),
            )
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Payment not recorded", str(exc), parent=self)
            return
        self.on_done()
        self.destroy()


class RefundDialog(tk.Toplevel):
    def __init__(self, master, conn, app, on_done, adjustment: bool = False):
        super().__init__(master)
        self.title("Post an adjustment" if adjustment else "Record a refund")
        self.configure(bg=ui.BG)
        self.geometry("520x+120+120")
        self.transient(master.winfo_toplevel())
        self.grab_set()
        self.conn = conn
        self.app = app
        self.on_done = on_done
        self.adjustment = adjustment

        frame = ttk.Frame(self, padding=18)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="Post an adjustment" if adjustment else "Record a refund",
                  style="H2.TLabel").pack(anchor="w")
        ttk.Label(
            frame,
            text=(
                "An adjustment corrects a balance without changing the invoice "
                "total. A positive amount credits the guest."
                if adjustment
                else "The money returned is recorded separately; the original "
                "invoice is never edited or deleted."
            ),
            style="Muted.TLabel",
            wraplength=460,
            justify="left",
        ).pack(anchor="w", pady=(4, 10))

        self.invoice = tk.StringVar()
        self.amount = tk.StringVar()
        self.reason = tk.StringVar()
        self.method = tk.StringVar(value="Cash")

        row1 = ttk.Frame(frame)
        row1.pack(fill="x", pady=(6, 0))
        ui.field(row1, "Invoice number", self.invoice, card=False).pack(side="left", fill="x", expand=True)
        ui.field(row1, "Amount", self.amount, width=14, card=False).pack(side="left", padx=(8, 0))

        row2 = ttk.Frame(frame)
        row2.pack(fill="x", pady=(6, 0))
        ttk.Label(row2, text="Reason", style="Muted.TLabel").pack(side="left")
        ttk.Combobox(row2, textvariable=self.reason, state="readonly", width=28,
                     values=list(REFUND_REASONS)).pack(side="left", padx=6)
        if not adjustment:
            ttk.Label(row2, text="Method", style="Muted.TLabel").pack(side="left", padx=(8, 0))
            ttk.Combobox(row2, textvariable=self.method, state="readonly", width=14,
                         values=["Cash", "Card", "Bank Transfer", "Digital Wallet"]).pack(
                             side="left", padx=6)

        buttons = ttk.Frame(frame)
        buttons.pack(fill="x", pady=(16, 0))
        ttk.Button(buttons, text="Post", style="Primary.TButton",
                   command=self.save).pack(side="right")
        ttk.Button(buttons, text="Cancel", style="Ghost.TButton",
                   command=self.destroy).pack(side="right", padx=8)

    def save(self) -> None:
        try:
            if self.adjustment:
                payments.record_adjustment(
                    self.conn,
                    self.invoice.get().strip(),
                    float(self.amount.get() or 0),
                    reason=self.reason.get(),
                    user_id=self.app.user["user_id"],
                )
            else:
                payments.record_refund(
                    self.conn,
                    self.invoice.get().strip(),
                    float(self.amount.get() or 0),
                    method=self.method.get(),
                    reason=self.reason.get(),
                    user_id=self.app.user["user_id"],
                )
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Not recorded", str(exc), parent=self)
            return
        self.on_done()
        self.destroy()
