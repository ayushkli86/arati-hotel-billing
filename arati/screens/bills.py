"""Invoice history: search bills, inspect, reprint or void them."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from .. import db, ui
from ..money import BILL_TYPE_LABELS


class BillsScreen(ttk.Frame):
    def __init__(self, master, app):
        super().__init__(master)
        self.app = app
        self.conn = app.conn
        self.search = tk.StringVar()

        header = ttk.Frame(self)
        header.pack(fill="x", pady=(0, 10))
        ttk.Label(header, text="Invoices", style="H1.TLabel").pack(side="left")
        ttk.Label(header, text="Search by bill no, guest, phone or room",
                  style="Muted.TLabel").pack(side="left", padx=14, pady=(10, 0))

        bar = ttk.Frame(self)
        bar.pack(fill="x", pady=(0, 10))
        entry = ttk.Entry(bar, textvariable=self.search, width=40)
        entry.pack(side="left")
        entry.bind("<KeyRelease>", lambda _e: self.reload())
        ttk.Button(bar, text="Search", style="Ghost.TButton", command=self.reload).pack(
            side="left", padx=6
        )
        ttk.Button(bar, text="Open invoice PDF", style="Primary.TButton",
                   command=self.open_pdf).pack(side="right")
        ttk.Button(bar, text="Reprint receipt", style="Ghost.TButton",
                   command=self.reprint).pack(side="right", padx=6)
        ttk.Button(bar, text="Void", style="Danger.TButton",
                   command=self.void).pack(side="right")
        ttk.Button(bar, text="Delete draft", style="Danger.TButton",
                   command=self.delete_draft).pack(side="right", padx=6)
        ttk.Button(bar, text="Edit draft", style="Ghost.TButton",
                   command=self.edit_draft).pack(side="right")

        card = ui.Card(self)
        card.pack(fill="both", expand=True)
        wrap = ttk.Frame(card.inner, style="Card.TFrame")
        wrap.pack(fill="both", expand=True)
        self.tree = ui.table(
            wrap,
            [("bill_no", "Bill no", 115), ("date", "Date", 95), ("guest", "Customer", 160),
             ("type", "Type", 105), ("method", "Payment", 105), ("total", "Total", 105),
             ("balance", "Balance", 95), ("status", "Status", 70)],
            height=18,
        )
        self.tree.pack(side="left", fill="both", expand=True)
        ui.scroll(self.tree, wrap).pack(side="right", fill="y")
        self.tree.bind("<Double-1>", lambda _e: self.show_detail())

        self.status = ui.status(self)
        self.status.pack(anchor="w", pady=(8, 0))

        self.reload()

    def reload(self) -> None:
        rows = db.list_bills(self.conn, self.search.get().strip())
        self.tree.delete(*self.tree.get_children())
        drafts = 0
        for row in rows:
            bill_type = BILL_TYPE_LABELS.get(row["bill_type"] or "tax", "Tax Invoice")
            if row["is_draft"]:
                drafts += 1
                state = "DRAFT"
            else:
                state = row["status"].upper()
            self.tree.insert(
                "", "end", iid=row["bill_no"],
                values=(
                    row["bill_no"], row["bill_date"], row["guest_name"] or "Walk-in",
                    bill_type, row["payment_method"],
                    ui.money(row["total"]), ui.money(row["balance"]),
                    state,
                ),
            )
        issued = [r for r in rows if r["status"] == "issued" and not r["is_draft"]]
        total = sum(r["total"] for r in issued)
        note = f"{len(issued)} bill(s) · {ui.money(total)} billed"
        if drafts:
            note += f" · {drafts} draft(s) excluded"
        ui.notify(self.status, note, ui.MUTED)

    def _selected(self) -> str | None:
        selection = self.tree.selection()
        if not selection:
            ui.notify(self.status, "Select a bill first.", ui.DANGER)
            return None
        return selection[0]

    def open_pdf(self) -> None:
        bill_no = self._selected()
        if not bill_no:
            return
        bill, lines = db.get_bill(self.conn, bill_no)
        path = self.app.render_invoice(bill, [dict(r) for r in lines])
        if path:
            self.app.open_pdf(path)

    def reprint(self) -> None:
        bill_no = self._selected()
        if not bill_no:
            return
        bill, lines = db.get_bill(self.conn, bill_no)
        path = self.app.render_receipt(bill, [dict(r) for r in lines])
        if path:
            self.app.open_pdf(path)

    def void(self) -> None:
        bill_no = self._selected()
        if not bill_no:
            return
        if self.app.user["role"] != "admin":
            ui.notify(self.status, "Only an admin can void a bill.", ui.DANGER)
            return
        if not ui.ask(f"Void bill {bill_no}? It will be excluded from sales reports."):
            return
        db.void_bill(self.conn, bill_no)
        self.reload()
        ui.notify(self.status, f"Bill {bill_no} voided.", ui.DANGER)

    def edit_draft(self) -> None:
        bill_no = self._selected()
        if not bill_no:
            return
        found = db.get_bill(self.conn, bill_no)
        if not found:
            return
        bill, lines = found
        if not bill["is_draft"]:
            ui.notify(self.status, "Only a draft can be edited — issued bills are permanent.",
                      ui.DANGER)
            return
        self.app.open_draft(bill, [dict(r) for r in lines])

    def delete_draft(self) -> None:
        bill_no = self._selected()
        if not bill_no:
            return
        if self.app.user["role"] != "admin":
            ui.notify(self.status, "Only an admin can delete a draft.", ui.DANGER)
            return
        if not ui.ask(f"Delete draft {bill_no}? This cannot be undone."):
            return
        if db.delete_draft(self.conn, bill_no):
            self.reload()
            ui.notify(self.status, f"Draft {bill_no} deleted.", ui.DANGER)
        else:
            ui.notify(self.status, "Only a draft can be deleted.", ui.DANGER)

    def show_detail(self) -> None:
        bill_no = self._selected()
        if not bill_no:
            return
        bill, lines = db.get_bill(self.conn, bill_no)
        InvoiceDetail(self, bill, lines)


class InvoiceDetail(tk.Toplevel):
    def __init__(self, master, bill: dict, lines):
        super().__init__(master)
        self.title(f"Invoice {bill['bill_no']}")
        self.configure(bg=ui.BG)
        self.geometry("640x560")
        self.transient(master.winfo_toplevel())

        frame = ttk.Frame(self, padding=18)
        frame.pack(fill="both", expand=True)

        top = ttk.Frame(frame)
        top.pack(fill="x")
        ttk.Label(top, text=bill["bill_no"], style="H1.TLabel").pack(anchor="w")
        ttk.Label(
            top,
            text=f"{BILL_TYPE_LABELS.get(bill.get('bill_type') or 'tax', 'Tax Invoice')} · "
                 f"{bill['bill_date']} · {bill['guest_name'] or 'Walk-in guest'}"
                 + (f" · Room {bill['room_no']}" if bill["room_no"] else ""),
            style="Muted.TLabel",
        ).pack(anchor="w")

        wrap = ttk.Frame(frame)
        wrap.pack(fill="both", expand=True, pady=12)
        tree = ui.table(
            wrap,
            [("description", "Description", 320), ("qty", "Qty", 70),
             ("rate", "Rate", 100), ("amount", "Amount", 110)],
            height=10,
        )
        tree.pack(side="left", fill="both", expand=True)
        ui.scroll(tree, wrap).pack(side="right", fill="y")
        for line in lines:
            tree.insert("", "end", values=(
                line["description"], f"{line['qty']:g} {line['unit']}",
                ui.money(line["unit_price"]), ui.money(line["line_total"]),
            ))

        totals = ttk.Frame(frame)
        totals.pack(fill="x")
        vat_applicable = (bill.get("bill_type") or "tax") == "tax" and (bill["vat_rate"] or 0) > 0
        rows = [
            ("Subtotal", bill["subtotal"]), ("Discount", -bill["discount"]),
        ]
        if vat_applicable:
            rows.append((f"VAT ({bill['vat_rate']:g}%)", bill["vat"]))
        else:
            rows.append(("VAT", "Not applicable"))
        rows += [
            (f"Service charge ({bill['service_charge_rate']:g}%)", bill["service_charge"]),
            ("Total", bill["total"]), ("Paid", bill["paid"]), ("Balance", bill["balance"]),
        ]
        for label, value in rows:
            row = ttk.Frame(totals)
            row.pack(fill="x")
            ttk.Label(row, text=label, style="Muted.TLabel").pack(side="left")
            shown = ui.money(value) if isinstance(value, (int, float)) else str(value)
            ttk.Label(row, text=shown,
                      style="Total.TLabel" if label == "Total" else "TLabel").pack(side="right")

        state = "DRAFT — not yet issued" if bill.get("is_draft") else bill["status"].upper()
        ttk.Label(
            frame, text=f"Payment: {bill['payment_method']} · Status: {state}",
            style="Muted.TLabel",
        ).pack(anchor="w", pady=(10, 0))
