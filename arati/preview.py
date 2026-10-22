"""Live invoice preview for the billing form.

A miniature of the printed A4 invoice, drawn on a canvas. The numbers come
from :func:`arati.invoice_html.line_amounts` and the stored bill totals, so
what the staff member sees while typing is what the PDF will contain — the
preview never re-computes money on its own.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from . import invoice_html, nepali, ui
from .money import BILL_TYPE_LABELS, amount_in_words, payment_status
from .nepali import format_date

PAGE_WIDTH = 560
MARGIN = 22
INK = "#1A1A1A"
MUTED = "#6A6A6A"
RULE = "#9A9A9A"
LIGHT = "#F2F2F2"


class InvoicePreview(ttk.Frame):
    """Draw the invoice being entered, scaled down to a scrollable canvas."""

    def __init__(self, master, settings: dict | None = None):
        super().__init__(master)
        self.settings = settings or {}

        self.canvas = tk.Canvas(
            self, background="#FFFFFF", highlightthickness=1,
            highlightbackground=ui.LINE, width=PAGE_WIDTH,
        )
        scroll = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.canvas.bind("<Configure>", lambda _e: self._redraw())

        self._bill: dict = {}
        self._lines: list = []
        self._height = 0

    # ------------------------------------------------------------------ api
    def show(self, bill: dict, lines: list) -> None:
        """Replace the preview content with this bill and its lines."""
        self._bill = bill or {}
        self._lines = lines or []
        self._redraw()

    def set_settings(self, settings: dict) -> None:
        self.settings = settings or {}
        self._redraw()

    # --------------------------------------------------------------- drawing
    def _redraw(self) -> None:
        canvas = self.canvas
        canvas.delete("all")
        if not self._bill:
            return

        y = MARGIN
        x0 = MARGIN
        x1 = PAGE_WIDTH - MARGIN
        right = x1
        bill = self._bill
        settings = self.settings
        language = (bill.get("language") or settings.get("invoice_language") or "en").lower()
        if language not in nepali.LANGUAGES:
            language = "en"
        symbol = settings.get("currency_symbol") or "रु."

        # ------------------------------------------------------------ header
        canvas.create_text(
            x0, y, anchor="nw", text=settings.get("hotel_name", "Arati Hotel"),
            fill=INK, font=(ui.FONT, 15, "bold"),
        )
        y += 20
        name_ne = settings.get("hotel_name_ne") or ""
        if name_ne:
            canvas.create_text(x0, y, anchor="nw", text=name_ne, fill=INK,
                               font=(ui.FONT, 11))
            y += 16
        for line in (
            settings.get("hotel_address1", ""),
            settings.get("hotel_address2", ""),
        ):
            if line:
                canvas.create_text(x0, y, anchor="nw", text=line, fill=MUTED,
                                   font=(ui.FONT, 8))
                y += 11
        contact = " · ".join(
            part for part in (
                settings.get("hotel_phone", ""),
                settings.get("hotel_email", ""),
            ) if part
        )
        if contact:
            canvas.create_text(x0, y, anchor="nw", text=contact, fill=MUTED,
                               font=(ui.FONT, 8))
            y += 11
        ids = " · ".join(
            part for part in (
                f"PAN: {settings['hotel_pan']}" if settings.get("hotel_pan") else "",
                f"VAT No.: {settings['hotel_vat']}" if settings.get("hotel_vat") else "",
            ) if part
        )
        if ids:
            canvas.create_text(x0, y, anchor="nw", text=ids, fill=MUTED,
                               font=(ui.FONT, 8))
            y += 11

        bill_type = bill.get("bill_type") or "tax"
        title = BILL_TYPE_LABELS.get(bill_type, "Tax Invoice").upper()
        canvas.create_rectangle(right - 168, MARGIN, right, MARGIN + 30,
                                outline=INK, width=1.2)
        canvas.create_text(right - 84, MARGIN + 9, text=title, fill=INK,
                           font=(ui.FONT, 11, "bold"))
        copy_key = "office" if (bill.get("copy") or "customer") == "office" else "customer"
        copy_text = settings.get(
            "invoice_copy_office" if copy_key == "office" else "invoice_copy"
        ) or invoice_html.COPIES[copy_key][0]
        canvas.create_text(right - 84, MARGIN + 33, text=copy_text, fill=MUTED,
                           font=(ui.FONT, 8))
        y = max(y, MARGIN + 46)

        canvas.create_line(x0, y, x1, y, fill=INK, width=1.2)
        y += 8

        # --------------------------------------------------------- meta row
        bs = nepali.to_bs(bill.get("bill_date"))
        bs_value = "—"
        if bs:
            bs_value = nepali.to_latin(bs[0]) if language == "en" else bs[1]
        meta = [
            ("Invoice No.", bill.get("bill_no", "")),
            ("Date", format_date(bill.get("bill_date"), settings.get("date_format", "DD/MM/YYYY"))),
            ("BS date", bs_value),
            ("Payment", bill.get("payment_method", "")),
        ]
        column = (x1 - x0) / 4
        for index, (label, value) in enumerate(meta):
            cx = x0 + column * index
            canvas.create_text(cx, y, anchor="nw", text=label.upper(), fill=MUTED,
                               font=(ui.FONT, 7))
            canvas.create_text(cx, y + 10, anchor="nw", text=str(value or "—"), fill=INK,
                               font=(ui.FONT, 9, "bold"))
        y += 28
        canvas.create_line(x0, y, x1, y, fill=RULE, width=0.6)
        y += 8

        # -------------------------------------------------------- customer
        canvas.create_text(x0, y, anchor="nw", text="CUSTOMER", fill=MUTED,
                           font=(ui.FONT, 7, "bold"))
        y += 11
        canvas.create_text(
            x0, y, anchor="nw",
            text=bill.get("guest_name") or ("Walk-in guest" if language == "en" else "आगन्तुक ग्राहक"),
            fill=INK, font=(ui.FONT, 10, "bold"),
        )
        y += 15
        details = [
            ("Address", bill.get("guest_address") or "—"),
            ("Phone", bill.get("guest_phone") or "—"),
            ("PAN / VAT No.", bill.get("guest_pan") or "—"),
            ("Type", (bill.get("customer_type") or "individual").title()),
        ]
        if bill.get("room_no"):
            details.append(("Stay", f"Room {bill['room_no']} · {bill.get('nights') or 0}N"))
        column = (x1 - x0) / 3
        for index, (label, value) in enumerate(details):
            row, col = divmod(index, 3)
            cx = x0 + column * col
            cy = y + row * 24
            canvas.create_text(cx, cy, anchor="nw", text=label.upper(), fill=MUTED,
                               font=(ui.FONT, 7))
            canvas.create_text(cx, cy + 10, anchor="nw", text=str(value), fill=INK,
                               font=(ui.FONT, 8))
        y += 24 * ((len(details) + 2) // 3) + 6

        # ------------------------------------------------------------ items
        rows = invoice_html.line_amounts(bill, self._lines)
        heads = [
            ("S.N.", 24, "w"), ("Item", 168, "w"), ("Unit", 38, "c"), ("Qty", 34, "r"),
            ("Rate", 62, "r"), ("Disc.", 50, "r"), ("Taxable", 62, "r"),
            ("VAT", 46, "r"), ("Total", 70, "r"),
        ]
        positions = []
        cursor = x0
        for label, width, align in heads:
            positions.append((cursor, width, align, label))
            cursor += width
        header_y = y
        for cx, width, align, label in positions:
            anchor = {"w": "w", "c": "center", "r": "e"}[align]
            offset = {"w": 0, "c": width / 2, "r": width}[align]
            canvas.create_text(cx + offset, y, anchor="nw", text=label, fill=MUTED,
                               font=(ui.FONT, 7, "bold"))
        y += 13
        canvas.create_line(x0, y, x1, y, fill=RULE, width=0.6)
        y += 4

        for index, row in enumerate(rows, start=1):
            line = row["line"]
            cells = [
                str(index),
                str(line.get("description", "")),
                str(line.get("unit") or ""),
                f"{float(line.get('qty') or 0):g}",
                f"{float(line.get('unit_price') or 0):,.2f}",
                f"{float(row['discount']):,.2f}",
                f"{float(row['taxable_net']):,.2f}" if row["taxable"] else "—",
                f"{float(row['vat']):,.2f}" if row["taxable"] else "—",
                f"{float(row['total']):,.2f}",
            ]
            row_y = y
            for (cx, width, align, _label), value in zip(positions, cells):
                anchor = {"w": "w", "c": "center", "r": "e"}[align]
                offset = {"w": 0, "c": width / 2, "r": width}[align]
                bold = (ui.FONT, 8, "bold") if align == "r" else (ui.FONT, 8)
                canvas.create_text(cx + offset, row_y, anchor="nw", text=value,
                                   fill=INK, font=bold)
            y += 14
            canvas.create_line(x0, y - 3, x1, y - 3, fill="#DDDDDD", width=0.5)

        if not rows:
            canvas.create_text(x0 + (x1 - x0) / 2, y, anchor="n",
                               text="No items yet", fill=MUTED, font=(ui.FONT, 8))
            y += 16

        # footer totals of the item table
        total_discount = sum(float(row["discount"]) for row in rows)
        total_taxable = sum(float(row["taxable_net"]) for row in rows)
        total_vat = sum(float(row["vat"]) for row in rows)
        total_all = sum(float(row["total"]) for row in rows)
        footer_cells = [
            ("", 24), ("Total", 168), ("", 38), ("", 34),
            (f"{total_discount:,.2f}", 50), (f"{total_taxable:,.2f}", 62),
            (f"{total_vat:,.2f}", 46), (f"{total_all:,.2f}", 70),
        ]
        cursor = x0
        for value, width in footer_cells:
            if value:
                canvas.create_text(cursor + width, y, anchor="ne", text=value, fill=INK,
                                   font=(ui.FONT, 8, "bold"))
            cursor += width
        y += 6
        canvas.create_line(x0, y, x1, y, fill=INK, width=1)
        y += 10

        # ---------------------------------------------------------- summary
        vat_applicable = (bill.get("bill_type") or "tax") == "tax" and float(
            bill.get("vat_rate") or 0
        ) > 0
        summary = [("Subtotal", f"{float(bill.get('subtotal') or 0):,.2f}")]
        if float(bill.get("item_discount") or 0) > 0:
            summary.append(("Item discount", f"− {float(bill['item_discount']):,.2f}"))
        if float(bill.get("discount") or 0) > 0:
            summary.append(("Discount", f"− {float(bill['discount']):,.2f}"))
        if vat_applicable:
            summary.append(
                ("Taxable amount", f"{float(bill.get('taxable_net') or 0):,.2f}")
            )
            summary.append(
                (
                    f"Service charge ({float(bill.get('service_charge_rate') or 0):g}%)",
                    f"{float(bill.get('service_charge') or 0):,.2f}",
                )
            )
            summary.append(
                (f"VAT ({float(bill.get('vat_rate') or 0):g}%)",
                 f"{float(bill.get('vat') or 0):,.2f}")
            )
        else:
            summary.append(("Service charge", f"{float(bill.get('service_charge') or 0):,.2f}"))
            summary.append(("VAT", "Not applicable"))

        box_x = x0 + (x1 - x0) * 0.42
        box_w = x1 - box_x
        row_h = 13
        box_h = row_h * (len(summary) + 4) + 10
        canvas.create_rectangle(box_x, y, x1, y + box_h, outline=RULE, width=0.8,
                                 fill=LIGHT)
        row_y = y + 5
        for label, value in summary:
            canvas.create_text(box_x + 8, row_y, anchor="nw", text=label, fill=INK,
                               font=(ui.FONT, 8))
            canvas.create_text(x1 - 8, row_y, anchor="ne", text=value, fill=INK,
                               font=(ui.FONT, 8))
            row_y += row_h
        canvas.create_line(box_x + 6, row_y - 2, x1 - 6, row_y - 2, fill=INK, width=1)
        row_y += 3
        for label, value in (
            ("GRAND TOTAL", f"{symbol} {float(bill.get('total') or 0):,.2f}"),
            ("Amount paid", f"{float(bill.get('paid') or 0):,.2f}"),
            ("Balance", f"{float(bill.get('balance') or 0):,.2f}"),
            ("Status", payment_status(bill.get("total") or 0, bill.get("paid") or 0)),
        ):
            strong = label == "GRAND TOTAL"
            canvas.create_text(box_x + 8, row_y, anchor="nw", text=label, fill=INK,
                               font=(ui.FONT, 9, "bold") if strong else (ui.FONT, 8))
            canvas.create_text(x1 - 8, row_y, anchor="ne", text=value, fill=INK,
                               font=(ui.FONT, 9, "bold") if strong else (ui.FONT, 8))
            row_y += row_h
        y += box_h + 10

        # ----------------------------------------------------- amount in words
        total = float(bill.get("total") or 0)
        words = (
            nepali.amount_in_words(total) if language == "ne" else amount_in_words(total)
        )
        canvas.create_text(x0, y, anchor="nw", text="AMOUNT IN WORDS", fill=MUTED,
                           font=(ui.FONT, 7, "bold"))
        canvas.create_text(x0, y + 11, anchor="nw", text=words, fill=INK,
                           font=(ui.FONT, 9, "bold"))
        y += 30

        # ---------------------------------------------------------- footer
        canvas.create_line(x0, y, x1, y, fill=RULE, width=0.6)
        y += 12
        notes = " · ".join(
            part for part in (
                f"Payment terms: {bill.get('payment_terms')}" if bill.get("payment_terms") else "",
                f"Notes: {bill.get('notes')}" if bill.get("notes") else "",
                settings.get("return_policy") or "",
            ) if part
        )
        if notes:
            canvas.create_text(x0, y, anchor="nw", text=notes[:120], fill=MUTED,
                               font=(ui.FONT, 7))
            y += 12
        y += 26
        signatures = ["Prepared by", "Received by", "Customer signature", "Authorized"]
        column = (x1 - x0) / len(signatures)
        for index, label in enumerate(signatures):
            cx = x0 + column * index
            canvas.create_line(cx + 6, y, cx + column - 12, y, fill=RULE, width=0.6)
            canvas.create_text(cx + column / 2 - 3, y + 3, anchor="n", text=label,
                               fill=MUTED, font=(ui.FONT, 7))
        y += 26
        canvas.create_text((x0 + x1) / 2, y, anchor="n",
                           text=settings.get("footer_note") or "Thank you for your business.",
                           fill=MUTED, font=(ui.FONT, 8, "italic"))

        self._height = y + 40
        self.canvas.configure(scrollregion=(0, 0, PAGE_WIDTH, self._height))
