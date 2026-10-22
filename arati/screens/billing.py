"""Billing screen — entry form on the left, live invoice preview on the right."""

from __future__ import annotations

import shutil
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk

from .. import customers as customer_db
from .. import db, ui
from ..money import (
    BILL_TYPE_LABELS,
    Line,
    amount_in_words,
    compute_totals,
    discount_from_input,
    payment_status,
    stay_duration,
)
from ..nepali import LANGUAGE_CODES, LANGUAGE_LABELS
from ..preview import InvoicePreview

PAYMENT_METHODS = ["Cash", "Card", "eSewa", "Khalti", "Fonepay", "Bank Transfer", "Room Credit"]
BILL_TYPE_DISPLAY = {label: code for code, label in BILL_TYPE_LABELS.items()}
CUSTOMER_DISPLAY = {"Individual": "individual", "Business": "business"}
COPY_CUSTOMER = "customer"
COPY_OFFICE = "office"


class BillingScreen(ttk.Frame):
    def __init__(self, master, app):
        super().__init__(master)
        self.app = app
        self.conn = app.conn
        self.cart: list[dict] = []
        self.room_rows: list = []
        self.food_rows: list = []
        self.service_rows: list = []

        settings = app.settings
        self.bill_type = tk.StringVar(value=BILL_TYPE_LABELS["tax"])
        self.customer_type = tk.StringVar(value="Individual")
        self.bill_date = tk.StringVar(value=ui.today_iso())
        self.guest_name = tk.StringVar()
        self.guest_phone = tk.StringVar()
        self.guest_address = tk.StringVar()
        self.guest_pan = tk.StringVar()
        self.room_no = tk.StringVar()
        self.check_in = tk.StringVar()
        self.check_out = tk.StringVar()
        self.nights = tk.StringVar(value="0")
        self.discount = tk.StringVar(value="0")
        self.discount_kind = tk.StringVar(value="Rs.")
        self.paid = tk.StringVar(value="0")
        self.payment_method = tk.StringVar(value="Cash")
        self.notes = tk.StringVar()
        self.payment_terms = tk.StringVar(value=settings.get("payment_terms", ""))
        self.prepared_by = tk.StringVar(value=app.user["full_name"] or app.user["username"])
        self.received_by = tk.StringVar()
        self.customer_pick = tk.StringVar()
        self.language = tk.StringVar(value=LANGUAGE_LABELS[
            settings.get("invoice_language", "en") if settings.get("invoice_language") in LANGUAGE_LABELS else "en"
        ])
        self.copy = tk.StringVar(value=self._copy_label(COPY_CUSTOMER))
        self._customer_map: dict[str, int] = {}
        self.editing_draft: str | None = None
        self._saving = False
        self._preview_visible = True

        self._build()
        self.bill_type.trace_add("write", lambda *_: self._refresh_totals())
        self.reload_catalog()
        self.reload_customers()
        self._refresh_cart()

    def _copy_label(self, key: str) -> str:
        setting = "invoice_copy_office" if key == COPY_OFFICE else "invoice_copy"
        return self.app.settings.get(setting) or (
            "Office Copy" if key == COPY_OFFICE else "Customer Copy"
        )

    # ------------------------------------------------------------------ UI
    def _build(self) -> None:
        self.columnconfigure(0, minsize=268, weight=0)
        self.columnconfigure(1, weight=3, minsize=380)
        self.columnconfigure(2, minsize=520, weight=0)
        self.rowconfigure(0, weight=1)

        self._build_catalog_column()
        self._build_entry_column()
        self._build_preview_column()

    # ----------------------------------------------------------- catalog
    def _build_catalog_column(self) -> None:
        left = ui.Card(self)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        ttk.Label(left.inner, text="ADD ITEMS", style="Section.TLabel").pack(anchor="w")
        ttk.Label(left.inner, text="Rooms, kitchen & services", style="H2.TLabel").pack(
            anchor="w", pady=(2, 8)
        )

        self.nb = ttk.Notebook(left.inner)
        self.nb.pack(fill="both", expand=True)

        self.room_search = tk.StringVar()
        self.food_search = tk.StringVar()
        self.service_search = tk.StringVar()

        self.room_tree = self._tab("Rooms", self.room_search,
                                   [("no", "Room", 70), ("type", "Type", 110), ("rate", "Rate", 70)])
        self.food_tree = self._tab("Restaurant", self.food_search,
                                   [("name", "Item", 160), ("rate", "Rate", 70)])
        self.service_tree = self._tab("Services", self.service_search,
                                      [("name", "Service", 160), ("rate", "Rate", 70)])

        for tree in (self.room_tree, self.food_tree, self.service_tree):
            tree.bind("<Double-1>", lambda _e: self.add_selected())

        ttk.Button(left.inner, text="Add selected  ↵", style="Primary.TButton",
                   command=self.add_selected).pack(fill="x", pady=(10, 0))

    def _tab(self, title: str, search_var: tk.StringVar, columns) -> ttk.Treeview:
        frame = ttk.Frame(self.nb, style="Card.TFrame")
        self.nb.add(frame, text=title)
        entry = ttk.Entry(frame, textvariable=search_var)
        entry.pack(fill="x", padx=8, pady=(8, 6))
        entry.bind("<KeyRelease>", lambda _e: self.reload_catalog())
        wrap = ttk.Frame(frame, style="Card.TFrame")
        wrap.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        tree = ui.table(wrap, columns, height=14)
        tree.pack(side="left", fill="both", expand=True)
        ui.scroll(tree, wrap).pack(side="right", fill="y")
        return tree

    # ------------------------------------------------------------- entry
    def _build_entry_column(self) -> None:
        entry = ttk.Frame(self)
        entry.grid(row=0, column=1, sticky="nsew", padx=(0, 10))
        entry.columnconfigure(0, weight=1)
        entry.rowconfigure(2, weight=1)

        # Customer card
        customer = ui.Card(entry)
        customer.grid(row=0, column=0, sticky="ew")
        ttk.Label(customer.inner, text="CUSTOMER", style="Section.TLabel").grid(
            row=0, column=0, columnspan=3, sticky="w"
        )
        ttk.Button(customer.inner, text="Clear", style="Ghost.TButton",
                   command=self._clear_customer).grid(row=0, column=3, sticky="e")

        picker = ttk.Frame(customer.inner, style="Card.TFrame")
        picker.grid(row=1, column=0, columnspan=4, sticky="ew", pady=(4, 6))
        ttk.Label(picker, text="SAVED CUSTOMER", style="CardMuted.TLabel").pack(anchor="w")
        self.customer_box = ttk.Combobox(picker, textvariable=self.customer_pick,
                                         state="readonly")
        self.customer_box.pack(fill="x", pady=(2, 0))
        self.customer_box.bind("<<ComboboxSelected>>", self._on_customer_pick)

        self._combo_field(customer.inner, "Customer type", self.customer_type,
                          list(CUSTOMER_DISPLAY), width=12).grid(
            row=2, column=0, columnspan=2, sticky="ew", padx=(0, 10), pady=(4, 6)
        )
        ui.field(customer.inner, "Name", self.guest_name, width=18).grid(
            row=2, column=2, columnspan=2, sticky="ew", pady=(4, 6)
        )
        ui.field(customer.inner, "Phone", self.guest_phone, width=13).grid(
            row=3, column=0, columnspan=2, sticky="ew", padx=(0, 10)
        )
        ui.field(customer.inner, "PAN / VAT no. (9 digits)", self.guest_pan, width=13).grid(
            row=3, column=2, columnspan=2, sticky="ew"
        )
        ui.field(customer.inner, "Address", self.guest_address, width=26).grid(
            row=4, column=0, columnspan=4, sticky="ew", pady=(8, 0)
        )
        for col in range(4):
            customer.inner.columnconfigure(col, weight=1)

        # Invoice & stay card
        meta = ui.Card(entry)
        meta.grid(row=1, column=0, sticky="ew", pady=10)
        ttk.Label(meta.inner, text="INVOICE & STAY", style="Section.TLabel").grid(
            row=0, column=0, columnspan=8, sticky="w"
        )
        self._combo_field(meta.inner, "Invoice type", self.bill_type,
                          list(BILL_TYPE_DISPLAY), width=14).grid(
            row=1, column=0, columnspan=2, sticky="ew", padx=(0, 10), pady=(4, 6)
        )
        ui.field(meta.inner, "Invoice date", self.bill_date, width=12).grid(
            row=1, column=2, sticky="ew", padx=(0, 10), pady=(4, 6)
        )
        self._combo_field(meta.inner, "Language", self.language,
                          list(LANGUAGE_CODES), width=10).grid(
            row=1, column=3, sticky="ew", pady=(4, 6)
        )
        self._combo_field(meta.inner, "Copy", self.copy,
                          [self._copy_label(COPY_CUSTOMER), self._copy_label(COPY_OFFICE)],
                          width=14).grid(
            row=2, column=0, columnspan=2, sticky="ew", padx=(0, 10)
        )
        ui.field(meta.inner, "Room no.", self.room_no, width=9).grid(
            row=2, column=2, sticky="ew", padx=(0, 10)
        )
        ui.field(meta.inner, "Nights", self.nights, width=6).grid(
            row=2, column=3, sticky="ew"
        )
        ui.field(meta.inner, "Check-in", self.check_in, width=16).grid(
            row=3, column=0, sticky="ew", padx=(0, 10), pady=(4, 6)
        )
        ui.field(meta.inner, "Check-out", self.check_out, width=16).grid(
            row=3, column=1, sticky="ew", padx=(0, 10), pady=(4, 6)
        )
        ui.field(meta.inner, "Payment terms", self.payment_terms, width=24).grid(
            row=3, column=2, columnspan=2, sticky="ew", pady=(4, 6)
        )
        for col in range(4):
            meta.inner.columnconfigure(col, weight=1)

        # Items card
        items = ui.Card(entry)
        items.grid(row=2, column=0, sticky="nsew")
        header = ttk.Frame(items.inner, style="Card.TFrame")
        header.pack(fill="x")
        ttk.Label(header, text="ITEMS", style="Section.TLabel").pack(side="left")
        self.line_count = ttk.Label(header, text="0 lines", style="CardMuted.TLabel")
        self.line_count.pack(side="right")

        wrap = ttk.Frame(items.inner, style="Card.TFrame")
        wrap.pack(fill="both", expand=True, pady=(6, 6))
        self.cart_tree = ui.table(
            wrap,
            [("no", "S.N.", 34), ("description", "Description", 150), ("unit", "Unit", 44),
             ("qty", "Qty", 42), ("rate", "Rate", 66), ("discount", "Disc.", 56),
             ("taxable", "VAT", 38), ("amount", "Total", 76)],
            height=7,
        )
        self.cart_tree.pack(side="left", fill="both", expand=True)
        ui.scroll(self.cart_tree, wrap).pack(side="right", fill="y")
        self.cart_tree.bind("<Double-1>", lambda _e: self.edit_line())

        actions = ttk.Frame(items.inner, style="Card.TFrame")
        actions.pack(fill="x")
        for text, command in (
            ("+ Qty", lambda: self.bump_qty(1)),
            ("− Qty", lambda: self.bump_qty(-1)),
            ("Edit line", self.edit_line),
            ("Remove", self.remove_line),
        ):
            ttk.Button(
                actions, text=text,
                style="Danger.TButton" if text == "Remove" else "Ghost.TButton",
                command=command,
            ).pack(side="left", padx=(0, 6))

        ui.field(items.inner, "Notes on this invoice", self.notes, width=40).pack(
            fill="x", pady=(6, 0)
        )

        # Totals & payment card
        totals = ui.Card(entry)
        totals.grid(row=3, column=0, sticky="ew", pady=(10, 0))
        ttk.Label(totals.inner, text="TOTALS & PAYMENT", style="Section.TLabel").pack(
            anchor="w"
        )
        self.vat_label = ttk.Label(totals.inner, text="", style="CardMuted.TLabel")
        self.vat_label.pack(anchor="w")

        self.totals_labels = {}
        for key, label in (
            ("subtotal", "Subtotal"), ("item_discount", "Item discount"),
            ("discount", "Overall discount"), ("taxable", "Taxable amount"),
            ("service_charge", "Service charge"), ("vat", "VAT"),
        ):
            row = ttk.Frame(totals.inner, style="Card.TFrame")
            row.pack(fill="x", pady=1)
            text = ttk.Label(row, text=label, style="CardMuted.TLabel")
            text.pack(side="left")
            value = ttk.Label(row, text="NPR 0.00", style="Card.TLabel")
            value.pack(side="right")
            self.totals_labels[key] = (text, value)

        ttk.Separator(totals.inner).pack(fill="x", pady=6)
        total_row = ttk.Frame(totals.inner, style="Card.TFrame")
        total_row.pack(fill="x")
        ttk.Label(total_row, text="GRAND TOTAL", style="Section.TLabel").pack(side="left")
        self.total_label = ttk.Label(total_row, text="NPR 0.00", style="Total.TLabel")
        self.total_label.pack(side="right")

        discount_row = ttk.Frame(totals.inner, style="Card.TFrame")
        discount_row.pack(fill="x", pady=(6, 0))
        ttk.Label(discount_row, text="Overall discount", style="CardMuted.TLabel").pack(
            side="left"
        )
        ttk.Combobox(discount_row, textvariable=self.discount_kind, width=4,
                     values=["Rs.", "%"], state="readonly").pack(side="right")
        entry_widget = ttk.Entry(discount_row, textvariable=self.discount, width=9)
        entry_widget.pack(side="right", padx=6)
        entry_widget.bind("<KeyRelease>", lambda _e: self._refresh_totals())
        self.discount_kind.trace_add("write", lambda *_: self._refresh_totals())

        self.words_label = ttk.Label(totals.inner, text="", style="CardMuted.TLabel",
                                     wraplength=320, justify="left")
        self.words_label.pack(anchor="w", pady=(8, 0))

        ttk.Separator(totals.inner).pack(fill="x", pady=8)
        ttk.Combobox(totals.inner, textvariable=self.payment_method, values=PAYMENT_METHODS,
                     state="readonly", width=24).pack(fill="x", pady=(0, 6))

        paid_row = ttk.Frame(totals.inner, style="Card.TFrame")
        paid_row.pack(fill="x")
        ttk.Label(paid_row, text="AMOUNT PAID", style="CardMuted.TLabel").pack(side="left")
        inner_paid = ttk.Frame(paid_row, style="Card.TFrame")
        inner_paid.pack(fill="x")
        ttk.Entry(inner_paid, textvariable=self.paid, width=14).pack(side="left")
        ttk.Button(inner_paid, text="Full", style="Ghost.TButton",
                   command=self.pay_full).pack(side="left", padx=6)

        balance_row = ttk.Frame(totals.inner, style="Card.TFrame")
        balance_row.pack(fill="x", pady=(8, 0))
        ttk.Label(balance_row, text="Balance", style="CardMuted.TLabel").pack(side="left")
        self.balance_label = ttk.Label(balance_row, text="NPR 0.00", style="Card.TLabel")
        self.balance_label.pack(side="right")

        status_row = ttk.Frame(totals.inner, style="Card.TFrame")
        status_row.pack(fill="x", pady=(2, 0))
        ttk.Label(status_row, text="Payment status", style="CardMuted.TLabel").pack(side="left")
        self.status_label = ttk.Label(status_row, text="Unpaid", style="Card.TLabel")
        self.status_label.pack(side="right")

        self.paid.trace_add("write", lambda *_: self._refresh_totals())

    def _combo_field(self, master, label, variable, values, width=16):
        """A labelled read-only combobox, matching ui.field's look."""
        row = ttk.Frame(master, style="Card.TFrame")
        ttk.Label(row, text=label.upper(), style="CardMuted.TLabel").pack(anchor="w")
        ttk.Combobox(row, textvariable=variable, values=values, state="readonly",
                     width=width).pack(fill="x", pady=(2, 0))
        return row

    # ----------------------------------------------------------- preview
    def _build_preview_column(self) -> None:
        right = ttk.Frame(self)
        right.grid(row=0, column=2, sticky="nsew")
        right.columnconfigure(0, weight=1)
        right.rowconfigure(0, weight=1)

        card = ui.Card(right)
        card.grid(row=0, column=0, sticky="nsew")
        head = ttk.Frame(card.inner, style="Card.TFrame")
        head.pack(fill="x")
        ttk.Label(head, text="LIVE INVOICE PREVIEW", style="Section.TLabel").pack(side="left")
        self.toggle_preview = ttk.Button(
            head, text="Hide", style="Ghost.TButton", command=self._toggle_preview
        )
        self.toggle_preview.pack(side="right")

        body = ttk.Frame(card.inner, style="Card.TFrame")
        body.pack(fill="both", expand=True, pady=(6, 0))
        self.preview = InvoicePreview(body, self.app.settings)
        self.preview.pack(fill="both", expand=True)

        buttons = ttk.Frame(right)
        buttons.grid(row=1, column=0, sticky="ew", pady=(10, 0))
        buttons.columnconfigure(0, weight=1)
        buttons.columnconfigure(1, weight=1)
        self.action_buttons: list[ttk.Button] = []
        for text, command, style in (
            ("Preview PDF", self.preview, "Ghost.TButton"),
            ("Download PDF", self.download_pdf, "Ghost.TButton"),
            ("Save draft", self.save_draft, "Ghost.TButton"),
            ("Reset", self.reset, "Danger.TButton"),
            ("Save invoice", lambda: self.save(open_pdf=False), "Gold.TButton"),
            ("Print invoice", lambda: self.save(open_pdf=True), "Primary.TButton"),
        ):
            button = ttk.Button(buttons, text=text, style=style, command=command)
            button.grid(row=len(self.action_buttons) // 2,
                        column=len(self.action_buttons) % 2, sticky="ew", padx=4, pady=4)
            self.action_buttons.append(button)

        handled = ttk.Frame(right)
        handled.grid(row=2, column=0, sticky="ew", pady=(8, 0))
        handled.columnconfigure(0, weight=1)
        handled.columnconfigure(1, weight=1)
        ui.field(handled, "Prepared by", self.prepared_by, width=16, card=False).grid(
            row=0, column=0, sticky="ew", padx=(0, 8)
        )
        ui.field(handled, "Received by", self.received_by, width=16, card=False).grid(
            row=0, column=1, sticky="ew"
        )

        self.status = ui.status(self)
        self.status.grid(row=1, column=0, sticky="w", pady=(6, 0))

    def _toggle_preview(self) -> None:
        self._preview_visible = not self._preview_visible
        if self._preview_visible:
            self.preview.pack(fill="both", expand=True)
            self.toggle_preview.configure(text="Hide")
        else:
            self.preview.pack_forget()
            self.toggle_preview.configure(text="Show")
        self._refresh_totals()

    # ------------------------------------------------------------- catalog
    def reload_catalog(self) -> None:
        self.room_rows = db.list_rooms(self.conn)
        self.room_tree.delete(*self.room_tree.get_children())
        needle = self.room_search.get().strip().lower()
        for room in self.room_rows:
            label = f"{room['room_no']} · {room['floor']}F" if room["floor"] else room["room_no"]
            if needle and needle not in f"{room['room_no']} {room['room_type']}".lower():
                continue
            self.room_tree.insert("", "end", iid=str(room["room_id"]),
                                  values=(label, room["room_type"], ui.money(room["rate"])))

        self.food_rows = db.list_items(self.conn, "food", self.food_search.get().strip())
        self.food_tree.delete(*self.food_tree.get_children())
        for item in self.food_rows:
            self.food_tree.insert("", "end", iid=str(item["item_id"]),
                                  values=(item["name"], ui.money(item["price"])))

        self.service_rows = db.list_items(self.conn, "service", self.service_search.get().strip())
        self.service_tree.delete(*self.service_tree.get_children())
        for item in self.service_rows:
            self.service_tree.insert("", "end", iid=str(item["item_id"]),
                                     values=(item["name"], ui.money(item["price"])))

    def add_selected(self) -> None:
        tab = self.nb.index(self.nb.select())
        if tab == 0:
            selected = self.room_tree.selection()
            if not selected:
                ui.notify(self.status, "Pick a room first.", ui.DANGER)
                return
            room = next(r for r in self.room_rows if str(r["room_id"]) == selected[0])
            self._add_room(room)
            return
        tree, pool = (self.food_tree, self.food_rows) if tab == 1 else (
            self.service_tree, self.service_rows)
        selected = tree.selection()
        if not selected:
            ui.notify(self.status, "Pick an item first.", ui.DANGER)
            return
        item = next(i for i in pool if str(i["item_id"]) == selected[0])
        self._add_item(item)

    def _add_item(self, item) -> None:
        for line in self.cart:
            if line["item_id"] == item["item_id"] and line["category"] == item["category"]:
                line["qty"] += 1
                self._refresh_cart()
                return
        self.cart.append(
            {
                "item_id": item["item_id"],
                "category": item["category"],
                "description": item["name"],
                "code": item["code"] or "",
                "unit": item["unit"],
                "qty": 1,
                "unit_price": float(item["price"]),
                "taxable": bool(item["taxable"]),
                "discount": 0.0,
            }
        )
        self._refresh_cart()
        ui.notify(self.status, f"Added {item['name']}.", ui.MUTED)

    def _add_room(self, room) -> None:
        dialog = StayDialog(self, room)
        self.wait_window(dialog)
        if not dialog.result:
            return
        nights, rate, check_in, check_out, duration = dialog.result
        self.room_no.set(room["room_no"])
        self.check_in.set(check_in)
        self.check_out.set(check_out)
        self.nights.set(str(nights))
        self.cart.append(
            {
                "item_id": room["item_id"],
                "category": "room",
                "description": f"{room['room_type']} — Room {room['room_no']}",
                "code": f"ROOM-{room['room_no']}",
                "unit": "night",
                "qty": nights,
                "unit_price": rate,
                "taxable": True,
                "discount": 0.0,
            }
        )
        self._refresh_cart()
        ui.notify(self.status,
                  f"Room {room['room_no']} added · {nights} night(s) · stay {duration}.", ui.OK)

    # ---------------------------------------------------------------- cart
    def _selected_line(self) -> dict | None:
        selection = self.cart_tree.selection()
        if not selection:
            return None
        return self.cart[int(selection[0])]

    def bump_qty(self, delta: int) -> None:
        line = self._selected_line()
        if not line:
            ui.notify(self.status, "Select a bill line first.", ui.DANGER)
            return
        line["qty"] = max(1, line["qty"] + delta)
        self._refresh_cart()

    def edit_qty(self) -> None:
        line = self._selected_line()
        if not line:
            ui.notify(self.status, "Select a bill line first.", ui.DANGER)
            return
        answer = simpledialog.askfloat(
            "Quantity", f"Quantity for {line['description']}:",
            initialvalue=line["qty"], minvalue=0.01, parent=self,
        )
        if answer:
            line["qty"] = answer
            self._refresh_cart()

    def edit_line(self) -> None:
        """Open the line editor: qty, rate, unit, discount and VAT flag."""
        line = self._selected_line()
        if not line:
            ui.notify(self.status, "Select a bill line first.", ui.DANGER)
            return
        dialog = LineEditor(self, line)
        self.wait_window(dialog)
        if dialog.result:
            line.update(dialog.result)
            self._refresh_cart()

    def remove_line(self) -> None:
        line = self._selected_line()
        if not line:
            return
        self.cart.remove(line)
        self._refresh_cart()

    def clear_bill(self, force: bool = False) -> None:
        if self.cart and not force and not ui.ask("Clear this bill?"):
            return
        self.cart = []
        self.editing_draft = None
        self.customer_pick.set("")
        for var in (self.guest_name, self.guest_phone, self.guest_address, self.guest_pan,
                    self.room_no, self.check_in, self.check_out, self.discount, self.paid,
                    self.notes, self.received_by):
            var.set("")
        self.nights.set("0")
        self.paid.set("0")
        self.discount.set("0")
        self.bill_date.set(ui.today_iso())
        self.bill_type.set(BILL_TYPE_LABELS["tax"])
        self.customer_type.set("Individual")
        self.payment_terms.set(self.app.settings.get("payment_terms", ""))
        default_lang = self.app.settings.get("invoice_language", "en")
        self.language.set(LANGUAGE_LABELS.get(default_lang, "English"))
        self.copy.set(self._copy_label(COPY_CUSTOMER))
        self._refresh_cart()

    def reset(self) -> None:
        """Cancel the current entry, asking first when something would be lost."""
        if not ui.ask("Reset this invoice? Unsaved entries are lost."):
            return
        self.clear_bill(force=True)
        ui.notify(self.status, "Invoice reset.", ui.MUTED)

    def _refresh_cart(self) -> None:
        self.cart_tree.delete(*self.cart_tree.get_children())
        for index, line in enumerate(self.cart):
            gross = line["qty"] * line["unit_price"]
            net = max(0.0, gross - float(line.get("discount") or 0))
            self.cart_tree.insert(
                "", "end", iid=str(index),
                values=(
                    index + 1,
                    line["description"],
                    line["unit"] or "",
                    f"{line['qty']:g}",
                    ui.money(line["unit_price"]),
                    ui.money(line.get("discount") or 0),
                    "Yes" if line["taxable"] else "No",
                    ui.money(net),
                ),
            )
        self.line_count.configure(text=f"{len(self.cart)} line(s)")
        self._refresh_totals()

    # -------------------------------------------------------------- totals
    def _bill_type_code(self) -> str:
        return BILL_TYPE_DISPLAY.get(self.bill_type.get(), "tax")

    def _language_code(self) -> str:
        return LANGUAGE_CODES.get(self.language.get(), "en")

    def _copy_code(self) -> str:
        return COPY_OFFICE if self.copy.get() == self._copy_label(COPY_OFFICE) else COPY_CUSTOMER

    def _totals(self):
        lines = [
            Line(description=l["description"], qty=l["qty"], unit_price=l["unit_price"],
                 taxable=l["taxable"], category=l["category"], code=l.get("code", ""),
                 unit=l.get("unit", "pcs"), discount=float(l.get("discount") or 0))
            for l in self.cart
        ]
        subtotal = sum(line.total for line in lines)
        try:
            disc_value = float(self.discount.get() or 0)
        except ValueError:
            disc_value = 0.0
        discount = discount_from_input(
            subtotal, "percent" if self.discount_kind.get() == "%" else "amount", disc_value
        )
        try:
            paid = float(self.paid.get() or 0)
        except ValueError:
            paid = 0.0
        return compute_totals(
            lines,
            discount=discount,
            service_charge_rate=float(self.app.settings.get("service_charge_rate", 10)),
            vat_rate=float(self.app.settings.get("vat_rate", 13)),
            paid=paid,
            bill_type=self._bill_type_code(),
        )

    def _refresh_totals(self) -> None:
        totals = self._totals()
        self.totals_labels["subtotal"][1].configure(text=ui.money(totals.subtotal))
        self.totals_labels["item_discount"][1].configure(
            text=f"- {ui.money(totals.item_discount)}"
        )
        self.totals_labels["discount"][1].configure(text=f"- {ui.money(totals.discount)}")
        self.totals_labels["taxable"][1].configure(
            text=ui.money(totals.taxable_net) if totals.vat_applicable else "—"
        )
        self.totals_labels["vat"][0].configure(
            text=f"VAT ({totals.vat_rate:g}%)" if totals.vat_applicable else "VAT"
        )
        self.totals_labels["vat"][1].configure(
            text=ui.money(totals.vat) if totals.vat_applicable else "Not applicable"
        )
        self.totals_labels["service_charge"][1].configure(
            text=ui.money(totals.service_charge)
        )
        self.vat_label.configure(
            text="" if totals.vat_applicable else "Bill of Supply — VAT is not charged."
        )
        self.total_label.configure(text=ui.money(totals.total))
        self.words_label.configure(text=amount_in_words(totals.total))
        self.balance_label.configure(
            text=ui.money(totals.balance),
            foreground=ui.OK if totals.balance <= 0 else ui.DANGER,
        )
        self.status_label.configure(
            text=payment_status(totals.total, totals.paid),
            foreground=ui.OK if totals.balance <= 0 else ui.DANGER,
        )
        if self._preview_visible:
            self.preview.show(self._bill_payload(totals), self._lines_payload())

    def pay_full(self) -> None:
        self.paid.set(f"{self._totals().total:.2f}")

    # --------------------------------------------------------------- save
    def _validate(self) -> str | None:
        if not self.cart:
            return "Add at least one item before saving."
        if not ui.is_iso_date(self.bill_date.get()):
            return "Invoice date must be YYYY-MM-DD."
        pan = self.guest_pan.get().strip()
        if pan and not (len(pan) == 9 and pan.isdigit()):
            return "PAN / VAT number must be exactly 9 digits."
        if self.customer_type.get() == "Business" and not self.guest_name.get().strip():
            return "A business invoice needs a customer name."
        for line in self.cart:
            if line["qty"] <= 0 or line["unit_price"] < 0:
                return "Quantities must be positive and prices cannot be negative."
            if float(line.get("discount") or 0) < 0:
                return "A line discount cannot be negative."
            if float(line.get("discount") or 0) > line["qty"] * line["unit_price"]:
                return "A line discount cannot be more than the line amount."
        try:
            float(self.paid.get() or 0)
        except ValueError:
            return "Amount paid must be a number."
        return None

    def _lines_payload(self) -> list[dict]:
        return [
            {
                "item_id": line["item_id"],
                "category": line["category"],
                "description": line["description"],
                "code": line.get("code", ""),
                "unit": line["unit"],
                "qty": line["qty"],
                "unit_price": line["unit_price"],
                "line_total": round(line["qty"] * line["unit_price"], 2),
                "taxable": line["taxable"],
                "discount": round(float(line.get("discount") or 0), 2),
            }
            for line in self.cart
        ]

    def _guest_payload(self) -> dict:
        return {
            "name": self.guest_name.get().strip(),
            "phone": self.guest_phone.get().strip(),
            "address": self.guest_address.get().strip(),
            "pan": self.guest_pan.get().strip(),
            "room_no": self.room_no.get().strip(),
            "check_in": self.check_in.get().strip(),
            "check_out": self.check_out.get().strip(),
            "nights": int(self.nights.get() or 0),
        }

    def _bill_payload(self, totals) -> dict:
        """The bill as the document sees it — preview, PDF and saved row."""
        return {
            "bill_no": self.editing_draft
            or db.next_bill_no(self.conn, self.app.settings.get("bill_prefix", "ARH")),
            "bill_date": self.bill_date.get(),
            "created_at": db.now(),
            "bill_type": self._bill_type_code(),
            "customer_type": CUSTOMER_DISPLAY.get(self.customer_type.get(), "individual"),
            "payment_method": self.payment_method.get(),
            "payment_terms": self.payment_terms.get(),
            "notes": self.notes.get(),
            "prepared_by": self.prepared_by.get(),
            "received_by": self.received_by.get(),
            "language": self._language_code(),
            "copy": self._copy_code(),
            **self._guest_payload(),
            **totals.as_dict(),
        }

    # ------------------------------------------------------------ customers
    def reload_customers(self) -> None:
        self._customer_map = {}
        labels = []
        for customer in customer_db.list_customers(self.conn):
            label = customer["name"] + (f" · {customer['phone']}" if customer["phone"] else "")
            self._customer_map[label] = customer["customer_id"]
            labels.append(label)
        self.customer_box.configure(values=labels)

    def _on_customer_pick(self, _event=None) -> None:
        customer_id = self._customer_map.get(self.customer_pick.get())
        if not customer_id:
            return
        customer = customer_db.get_customer(self.conn, customer_id)
        if not customer:
            return
        self.guest_name.set(customer["name"])
        self.guest_phone.set(customer["phone"])
        self.guest_address.set(customer["address"])
        self.guest_pan.set(customer["pan"])
        self.customer_type.set(
            "Business" if customer["customer_type"] == "business" else "Individual"
        )

    def _clear_customer(self) -> None:
        self.customer_pick.set("")
        for var in (self.guest_name, self.guest_phone, self.guest_address, self.guest_pan):
            var.set("")
        self.customer_type.set("Individual")

    def _customer_id(self) -> int | None:
        return customer_db.upsert_customer(
            self.conn,
            self.guest_name.get().strip(),
            self.guest_phone.get().strip(),
            self.guest_address.get().strip(),
            self.guest_pan.get().strip(),
            CUSTOMER_DISPLAY.get(self.customer_type.get(), "individual"),
        )

    # --------------------------------------------------------------- drafts
    def load_draft(self, bill: dict, lines: list) -> None:
        """Populate the form from a saved draft so it can be edited and finalised."""
        self.clear_bill(force=True)
        self.editing_draft = bill["bill_no"]
        self.guest_name.set(bill.get("guest_name") or "")
        self.guest_phone.set(bill.get("guest_phone") or "")
        self.guest_address.set(bill.get("guest_address") or "")
        self.guest_pan.set(bill.get("guest_pan") or "")
        self.room_no.set(bill.get("room_no") or "")
        self.check_in.set(bill.get("check_in") or "")
        self.check_out.set(bill.get("check_out") or "")
        self.nights.set(str(bill.get("nights") or 0))
        self.bill_date.set(bill.get("bill_date") or ui.today_iso())
        self.customer_type.set(
            "Business" if (bill.get("customer_type") or "individual") == "business" else "Individual"
        )
        self.bill_type.set(BILL_TYPE_LABELS.get(bill.get("bill_type") or "tax", "Tax Invoice"))
        self.payment_terms.set(bill.get("payment_terms") or "")
        self.prepared_by.set(bill.get("prepared_by") or "")
        self.received_by.set(bill.get("received_by") or "")
        self.notes.set(bill.get("notes") or "")
        self.payment_method.set(bill.get("payment_method") or "Cash")
        self.language.set(LANGUAGE_LABELS.get(bill.get("language") or "en", "English"))
        self.discount_kind.set("Rs.")
        self.discount.set(f"{float(bill.get('discount') or 0):.2f}")
        self.paid.set(f"{float(bill.get('paid') or 0):.2f}")
        copy_code = bill.get("copy") or COPY_CUSTOMER
        self.copy.set(self._copy_label(copy_code))

        self.cart = [
            {
                "item_id": line.get("item_id"),
                "category": line.get("category") or "food",
                "description": line["description"],
                "code": line.get("code") or "",
                "unit": line.get("unit") or "pcs",
                "qty": line["qty"],
                "unit_price": line["unit_price"],
                "taxable": bool(line.get("taxable", 1)),
                "discount": float(line.get("discount") or 0),
            }
            for line in lines
        ]
        self._refresh_cart()
        ui.notify(self.status, f"Editing draft {bill['bill_no']}.", ui.OK)

    # ------------------------------------------------------------- preview
    def preview(self) -> None:
        problem = self._validate()
        if problem:
            ui.notify(self.status, problem, ui.DANGER)
            return
        totals = self._totals()
        bill = self._bill_payload(totals)
        path = self.app.render_preview(bill, self._lines_payload())
        if path:
            ui.notify(self.status, "Preview generated (not saved).", ui.OK)
        else:
            ui.notify(self.status, "Could not build the preview.", ui.DANGER)

    def download_pdf(self) -> None:
        """Save a copy of the invoice PDF wherever the user asks."""
        problem = self._validate()
        if problem:
            ui.notify(self.status, problem, ui.DANGER)
            return
        totals = self._totals()
        bill = self._bill_payload(totals)
        path = self.app.render_preview(bill, self._lines_payload())
        if not path:
            ui.notify(self.status, "Could not build the PDF.", ui.DANGER)
            return
        target = filedialog.asksaveasfilename(
            parent=self,
            title="Save invoice PDF",
            defaultextension=".pdf",
            initialfile=f"{bill['bill_no']}.pdf",
            filetypes=[("PDF document", "*.pdf"), ("All files", "*.*")],
        )
        if not target:
            ui.notify(self.status, "Download cancelled.", ui.MUTED)
            return
        try:
            shutil.copyfile(path, target)
        except OSError as exc:
            ui.notify(self.status, f"Could not save the PDF: {exc}", ui.DANGER)
            return
        ui.notify(self.status, f"Saved {Path(target).name}.", ui.OK)

    def save(self, open_pdf: bool = False) -> None:
        self._guarded_save(draft=False, open_pdf=open_pdf)

    def save_draft(self) -> None:
        self._guarded_save(draft=True)

    def _guarded_save(self, draft: bool, open_pdf: bool = False) -> None:
        """Guard against a double click issuing two invoices."""
        if self._saving:
            return
        self._saving = True
        self._set_busy(True)
        try:
            self._persist(draft=draft, open_pdf=open_pdf)
        finally:
            self._saving = False
            self._set_busy(False)

    def _set_busy(self, busy: bool) -> None:
        for button in self.action_buttons:
            button.configure(state="disabled" if busy else "normal")
        if busy:
            ui.notify(self.status, "Saving…", ui.MUTED, ms=60000)

    def _persist(self, draft: bool = False, open_pdf: bool = False) -> None:
        problem = self._validate()
        if problem:
            ui.notify(self.status, problem, ui.DANGER)
            return

        totals = self._totals()
        common = dict(
            guest=self._guest_payload(),
            lines=self._lines_payload(),
            totals=totals.as_dict(),
            payment_method=self.payment_method.get(),
            bill_type=self._bill_type_code(),
            customer_type=CUSTOMER_DISPLAY.get(self.customer_type.get(), "individual"),
            payment_terms=self.payment_terms.get(),
            prepared_by=self.prepared_by.get(),
            received_by=self.received_by.get(),
            customer_id=self._customer_id(),
            notes=self.notes.get(),
            language=self._language_code(),
            copy=self._copy_code(),
        )
        try:
            if self.editing_draft:
                if not db.update_draft(self.conn, self.editing_draft, **common):
                    messagebox.showerror(
                        "Draft missing",
                        f"Draft {self.editing_draft} no longer exists.",
                        parent=self,
                    )
                    self.editing_draft = None
                    return
                bill_no = self.editing_draft
                if not draft and not db.finalize_draft(self.conn, bill_no):
                    messagebox.showerror("Could not finalise",
                                         f"Draft {bill_no} was already issued.", parent=self)
                    return
            else:
                bill_no = db.create_bill(
                    self.conn,
                    prefix=self.app.settings.get("bill_prefix", "ARH"),
                    user_id=self.app.user["user_id"],
                    bill_date=self.bill_date.get(),
                    is_draft=1 if draft else 0,
                    **common,
                )
        except Exception as exc:  # noqa: BLE001 - surface DB errors instead of losing the bill
            messagebox.showerror("Could not save bill", str(exc), parent=self)
            return

        self.reload_customers()
        if draft:
            self.editing_draft = bill_no
            ui.notify(self.status, f"Draft {bill_no} saved — {ui.money(totals.total)}", ui.OK)
            return

        saved = db.get_bill(self.conn, bill_no)
        bill, bill_lines = saved
        path = self.app.render_invoice(bill, [dict(r) for r in bill_lines])
        ui.notify(self.status, f"Bill {bill_no} saved — {ui.money(totals.total)}", ui.OK)
        if open_pdf and path:
            self.app.open_pdf(path)
        self.clear_bill(force=True)


class LineEditor(tk.Toplevel):
    """Edit one invoice line: qty, rate, unit, discount and the VAT flag."""

    def __init__(self, master, line: dict):
        super().__init__(master)
        self.title(f"Edit line · {line['description']}")
        self.configure(bg=ui.BG)
        self.resizable(False, False)
        self.result: dict | None = None
        self.transient(master.winfo_toplevel())
        self.grab_set()

        self.description = tk.StringVar(value=line["description"])
        self.unit = tk.StringVar(value=line.get("unit") or "pcs")
        self.qty = tk.StringVar(value=f"{float(line['qty']):g}")
        self.rate = tk.StringVar(value=f"{float(line['unit_price']):.2f}")
        self.discount = tk.StringVar(value=f"{float(line.get('discount') or 0):.2f}")
        self.taxable = tk.BooleanVar(value=bool(line.get("taxable", True)))

        frame = ttk.Frame(self, padding=18)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="Edit invoice line", style="H2.TLabel").grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, 12)
        )

        rows = (
            ("Description", self.description, False),
            ("Unit", self.unit, False),
            ("Quantity", self.qty, False),
            ("Rate (रु.)", self.rate, False),
            ("Discount on this line (रु.)", self.discount, False),
        )
        for index, (label, variable, _numeric) in enumerate(rows):
            ttk.Label(frame, text=label.upper(), style="Muted.TLabel").grid(
                row=1 + index * 2, column=0, columnspan=2, sticky="w", pady=(0, 2)
            )
            ttk.Entry(frame, textvariable=variable, width=32).grid(
                row=2 + index * 2, column=0, columnspan=2, sticky="ew", pady=(0, 8)
            )
        ttk.Checkbutton(frame, text="VAT applies to this line", variable=self.taxable).grid(
            row=len(rows) * 2 + 1, column=0, columnspan=2, sticky="w", pady=(0, 10)
        )

        buttons = ttk.Frame(frame)
        buttons.grid(row=len(rows) * 2 + 2, column=0, columnspan=2, sticky="e")
        ttk.Button(buttons, text="Cancel", command=self.destroy).pack(side="left", padx=6)
        ttk.Button(buttons, text="Apply", style="Primary.TButton",
                   command=self._confirm).pack(side="left")

        self.bind("<Return>", lambda _e: self._confirm())
        self.bind("<Escape>", lambda _e: self.destroy())

    def _confirm(self) -> None:
        try:
            qty = float(self.qty.get())
            rate = float(self.rate.get())
            discount = float(self.discount.get() or 0)
        except (TypeError, ValueError):
            messagebox.showerror("Invalid line", "Quantity, rate and discount must be numbers.",
                                 parent=self)
            return
        if qty <= 0:
            messagebox.showerror("Invalid line", "Quantity must be greater than zero.",
                                 parent=self)
            return
        if rate < 0:
            messagebox.showerror("Invalid line", "Rate cannot be negative.", parent=self)
            return
        if discount < 0:
            messagebox.showerror("Invalid line", "Discount cannot be negative.", parent=self)
            return
        if discount > qty * rate:
            messagebox.showerror("Invalid line",
                                 "Discount cannot be more than the line amount.", parent=self)
            return
        self.result = {
            "description": self.description.get().strip() or self.description.get(),
            "unit": self.unit.get().strip(),
            "qty": qty,
            "unit_price": rate,
            "discount": round(discount, 2),
            "taxable": bool(self.taxable.get()),
        }
        self.destroy()


class StayDialog(tk.Toplevel):
    """Ask for stay dates and times, and the rate, for a room."""

    def __init__(self, master, room):
        super().__init__(master)
        self.title(f"Room {room['room_no']} · {room['room_type']}")
        self.configure(bg=ui.BG)
        self.resizable(False, False)
        self.result = None
        self.transient(master.winfo_toplevel())
        self.grab_set()

        frame = ttk.Frame(self, padding=18)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text=room["room_type"], style="H2.TLabel").grid(
            row=0, column=0, columnspan=2, sticky="w"
        )
        ttk.Label(frame, text=f"Room {room['room_no']} · {ui.money(room['rate'])} / night",
                  style="Muted.TLabel").grid(row=1, column=0, columnspan=2, sticky="w", pady=(0, 12))

        self.check_in_date = tk.StringVar(value=ui.today_iso())
        self.check_in_time = tk.StringVar(value="10:00")
        self.check_out_date = tk.StringVar(value=ui.tomorrow_iso())
        self.check_out_time = tk.StringVar(value="10:00")
        self.rate = tk.StringVar(value=f"{float(room['rate']):.2f}")
        self.nights_label = ttk.Label(frame, text="", style="Muted.TLabel")

        fields = (
            ("Check-in date (YYYY-MM-DD)", self.check_in_date),
            ("Check-in time (HH:MM)", self.check_in_time),
            ("Check-out date (YYYY-MM-DD)", self.check_out_date),
            ("Check-out time (HH:MM)", self.check_out_time),
            ("Rate per night", self.rate),
        )
        for index, (label, var) in enumerate(fields):
            label_row = 2 + index * 2
            entry_row = label_row + 1
            ttk.Label(frame, text=label.upper(), style="Muted.TLabel").grid(
                row=label_row, column=0, sticky="w", pady=(0, 2)
            )
            entry = ttk.Entry(frame, textvariable=var, width=22)
            entry.grid(row=entry_row, column=0, sticky="w", pady=(0, 8))
            entry.bind("<KeyRelease>", lambda _e: self._update_nights())
        bottom_row = 2 + len(fields) * 2
        self.nights_label.grid(row=bottom_row, column=0, sticky="w")
        self._update_nights()

        buttons = ttk.Frame(frame)
        buttons.grid(row=bottom_row + 1, column=0, sticky="e", pady=(14, 0))
        ttk.Button(buttons, text="Cancel", command=self.destroy).pack(side="left", padx=6)
        ttk.Button(buttons, text="Add stay", style="Primary.TButton",
                   command=self._confirm).pack(side="left")

        self.bind("<Return>", lambda _e: self._confirm())
        self.bind("<Escape>", lambda _e: self.destroy())

    def _stay_start(self) -> str:
        time = self.check_in_time.get().strip()
        return f"{self.check_in_date.get().strip()} {time}" if time else self.check_in_date.get()

    def _stay_end(self) -> str:
        time = self.check_out_time.get().strip()
        return f"{self.check_out_date.get().strip()} {time}" if time else self.check_out_date.get()

    def _update_nights(self) -> None:
        try:
            nights, duration = stay_duration(self._stay_start(), self._stay_end())
            rate = float(self.rate.get() or 0)
            self.nights_label.configure(
                text=f"{nights} night(s) · stay {duration} · {ui.money(nights * rate)}"
            )
        except (ValueError, TypeError):
            self.nights_label.configure(text="Enter valid dates and times")

    def _confirm(self) -> None:
        try:
            nights, duration = stay_duration(self._stay_start(), self._stay_end())
            rate = float(self.rate.get())
            if rate < 0:
                raise ValueError
        except (ValueError, TypeError):
            messagebox.showerror("Invalid stay", "Check the dates, times and rate.", parent=self)
            return
        self.result = (nights, rate, self._stay_start(), self._stay_end(), duration)
        self.destroy()
