"""Invoice documents for Arati Hotel.

A4 tax invoice / bill of supply, 80mm thermal receipt and raw ESC/POS bytes.
The printed values come from the bill row saved by :func:`arati.db.create_bill`,
so the form, the stored bill and the paper always agree.
"""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas as pdf_canvas
from reportlab.platypus import (
    HRFlowable,
    Image,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from .money import BILL_TYPE_LABELS, amount_in_words

INK = colors.HexColor("#111111")
MUTED = colors.HexColor("#555555")
RULE = colors.HexColor("#9A9A9A")
LIGHT = colors.HexColor("#F4F4F4")

CONTENT_WIDTH_MM = 178


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _rs(amount: float) -> str:
    return f"{amount:,.2f}"


def _fmt_date(value: str | None, date_format: str = "DD/MM/YYYY") -> str:
    if not value:
        return ""
    text = str(value).strip()
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return value
    if date_format == "YYYY-MM-DD":
        day = parsed.strftime("%Y-%m-%d")
    else:
        day = parsed.strftime("%d/%m/%Y")
    if parsed.hour or parsed.minute:
        day += f" {parsed.strftime('%H:%M')}"
    return day


def _styles():
    base = getSampleStyleSheet()
    return {
        "name": ParagraphStyle(
            "name", parent=base["Normal"], fontName="Helvetica-Bold", fontSize=17,
            leading=20, textColor=INK,
        ),
        "contact": ParagraphStyle(
            "contact", parent=base["Normal"], fontSize=8, leading=10.5, textColor=MUTED,
        ),
        "title": ParagraphStyle(
            "title", parent=base["Normal"], fontName="Helvetica-Bold", fontSize=14,
            leading=17, textColor=INK, alignment=TA_RIGHT,
        ),
        "copy": ParagraphStyle(
            "copy", parent=base["Normal"], fontSize=7.5, leading=9.5, textColor=MUTED,
            alignment=TA_RIGHT,
        ),
        "meta": ParagraphStyle(
            "meta", parent=base["Normal"], fontSize=8.3, leading=11, textColor=INK,
            alignment=TA_RIGHT,
        ),
        "label": ParagraphStyle(
            "label", parent=base["Normal"], fontSize=6.8, leading=8.5, textColor=MUTED,
        ),
        "body": ParagraphStyle(
            "body", parent=base["Normal"], fontSize=8.6, leading=11.2, textColor=INK,
        ),
        "value": ParagraphStyle(
            "value", parent=base["Normal"], fontSize=8.6, leading=11.2, textColor=INK,
        ),
        "cell": ParagraphStyle(
            "cell", parent=base["Normal"], fontSize=7.9, leading=9.8, textColor=INK,
        ),
        "small": ParagraphStyle(
            "small", parent=base["Normal"], fontSize=7, leading=9.2, textColor=MUTED,
        ),
        "words": ParagraphStyle(
            "words", parent=base["Normal"], fontSize=8.4, leading=11, textColor=INK,
        ),
        "sign": ParagraphStyle(
            "sign", parent=base["Normal"], fontSize=8, leading=10, textColor=INK,
            alignment=TA_CENTER,
        ),
    }


def _filled(bill: dict, key: str, default=None):
    value = bill.get(key)
    return value if value not in (None, "") else default


# --------------------------------------------------------------------------- #
# A4 document
# --------------------------------------------------------------------------- #
class _NumberedCanvas(pdf_canvas.Canvas):
    """Canvas that prints 'Page x of y' once the total page count is known."""

    def __init__(self, *args, footer_note: str = "", **kwargs):
        super().__init__(*args, **kwargs)
        self._footer_note = footer_note
        self._page_states: list[dict] = []

    def showPage(self):
        self._page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        total = len(self._page_states)
        for state in self._page_states:
            self.__dict__.update(state)
            self._draw_footer(total)
            pdf_canvas.Canvas.showPage(self)
        pdf_canvas.Canvas.save(self)

    def _draw_footer(self, total: int) -> None:
        width, _ = self._pagesize
        self.setFont("Helvetica", 6.8)
        self.setFillColor(MUTED)
        if self._footer_note:
            self.drawString(16 * mm, 9 * mm, self._footer_note[:120])
        self.drawRightString(
            width - 16 * mm, 9 * mm, f"Page {self._pageNumber} of {total}"
        )


def _header(settings: dict, bill: dict, styles: dict) -> Table:
    name = escape(settings.get("hotel_name", "Hotel"))
    lines = [
        escape(settings.get("hotel_address1", "")) or "",
        escape(settings.get("hotel_address2", "")) or "",
    ]
    contact = []
    if settings.get("hotel_phone"):
        contact.append(f"Tel: {escape(settings['hotel_phone'])}")
    if settings.get("hotel_email"):
        contact.append(escape(settings["hotel_email"]))
    if settings.get("hotel_website"):
        contact.append(escape(settings["hotel_website"]))
    if contact:
        lines.append(" · ".join(contact))
    if settings.get("hotel_pan"):
        lines.append(f"PAN / VAT No.: {escape(settings['hotel_pan'])}")

    identity = [Paragraph(name, styles["name"]), Spacer(1, 1.5)]
    for line in [l for l in lines if l]:
        identity.append(Paragraph(line, styles["contact"]))

    logo_path = settings.get("logo_path", "")
    logo_cell = ""
    if logo_path and Path(logo_path).exists():
        try:
            logo_cell = Image(logo_path, width=16 * mm, height=16 * mm, kind="proportional")
        except Exception:  # noqa: BLE001 - a bad logo must not block the invoice
            logo_cell = ""

    bill_type = bill.get("bill_type", "tax")
    title = BILL_TYPE_LABELS.get(bill_type, "Tax Invoice").upper()
    copy_label = settings.get("invoice_copy", "")
    meta = [Paragraph(title, styles["title"])]
    if copy_label:
        meta.append(Paragraph(escape(copy_label), styles["copy"]))
    meta += [
        Spacer(1, 3),
        Paragraph(f"Invoice No.: <b>{escape(str(bill['bill_no']))}</b>", styles["meta"]),
        Paragraph(
            f"Date: {_fmt_date(bill.get('bill_date'), settings.get('date_format', 'DD/MM/YYYY'))}",
            styles["meta"],
        ),
        Paragraph(f"Time: {str(bill.get('created_at', ''))[11:16]}", styles["meta"]),
    ]

    if logo_cell:
        grid = Table([[logo_cell, identity, meta]],
                     colWidths=[18 * mm, 90 * mm, 70 * mm])
    else:
        grid = Table([[identity, meta]], colWidths=[108 * mm, 70 * mm])
    grid.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
    ]))
    return grid


def _party_block(bill: dict, settings: dict, styles: dict) -> Table:
    """Customer and stay details, three fields per row inside one exact-width box."""
    stay = "—"
    if bill.get("room_no"):
        stay = f"Room {bill['room_no']}"
        if bill.get("check_in") or bill.get("check_out"):
            stay += (
                f" · {_fmt_date(bill.get('check_in'), settings.get('date_format'))}"
                f" to {_fmt_date(bill.get('check_out'), settings.get('date_format'))}"
            )
        if bill.get("nights"):
            stay += f" · {bill['nights']} night(s)"

    fields = [
        ("Customer", str(bill.get("guest_name") or "Walk-in customer")),
        ("Address", str(bill.get("guest_address") or "—")),
        ("Phone", str(bill.get("guest_phone") or "—")),
        ("PAN / VAT No.", str(bill.get("guest_pan") or "—")),
        ("Customer type", str(bill.get("customer_type", "individual")).title()),
        ("Stay", stay),
    ]

    data = []
    for row_fields in (fields[:3], fields[3:]):
        data.append([
            Paragraph(label.upper(), styles["label"]) for label, _ in row_fields
        ])
        data.append([
            Paragraph(escape(value), styles["body"]) for _, value in row_fields
        ])

    block = Table(data, colWidths=[62 * mm, 60 * mm, 56 * mm])
    block.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.5, RULE),
        ("LINEBELOW", (0, 1), (-1, 1), 0.25, colors.HexColor("#DDDDDD")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, 0), 6),
        ("BOTTOMPADDING", (0, 0), (-1, 1), 1),
        ("TOPPADDING", (0, 1), (-1, 1), 0),
        ("TOPPADDING", (0, 2), (-1, 2), 5),
        ("BOTTOMPADDING", (0, 2), (-1, 2), 1),
        ("TOPPADDING", (0, 3), (-1, 3), 0),
        ("BOTTOMPADDING", (0, 3), (-1, 3), 6),
    ]))
    return block


def _items_table(bill: dict, lines: list, settings: dict, styles: dict) -> Table:
    vat_applicable = bill.get("bill_type", "tax") == "tax" and float(bill.get("vat_rate") or 0) > 0
    vat_rate = float(bill.get("vat_rate") or 0)

    head = ["S.N.", "Description", "Code", "Unit", "Qty", "Rate", "Taxable",
            "VAT %", "VAT", "Amount"]
    data = [[Paragraph(h, styles["cell"]) for h in head]]
    for index, line in enumerate(lines, start=1):
        taxable = bool(line.get("taxable", 1))
        line_total = float(line.get("line_total") or 0)
        taxable_amount = line_total if (vat_applicable and taxable) else 0.0
        line_vat = round(taxable_amount * vat_rate / 100.0, 2) if vat_applicable else 0.0
        data.append([
            Paragraph(str(index), styles["cell"]),
            Paragraph(escape(str(line.get("description", ""))), styles["cell"]),
            Paragraph(escape(str(line.get("code") or "—")), styles["cell"]),
            Paragraph(escape(str(line.get("unit") or "")), styles["cell"]),
            Paragraph(f"{line.get('qty', 0):g}", styles["cell"]),
            Paragraph(_rs(float(line.get("unit_price") or 0)), styles["cell"]),
            Paragraph(_rs(taxable_amount) if vat_applicable and taxable else "—", styles["cell"]),
            Paragraph(f"{vat_rate:g}%" if vat_applicable and taxable else "—", styles["cell"]),
            Paragraph(_rs(line_vat) if vat_applicable and taxable else "—", styles["cell"]),
            Paragraph(_rs(line_total), styles["cell"]),
        ])

    widths = [8, 44, 20, 12, 10, 18, 18, 11, 17, 20]
    table = Table(data, colWidths=[w * mm for w in widths], repeatRows=1)
    table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 7.6),
        ("TEXTCOLOR", (0, 0), (-1, 0), INK),
        ("LINEABOVE", (0, 0), (-1, 0), 0.8, INK),
        ("LINEBELOW", (0, 0), (-1, 0), 0.8, INK),
        ("LINEBELOW", (0, 1), (-1, -1), 0.25, colors.HexColor("#D0D0D0")),
        ("LINEBELOW", (0, -1), (-1, -1), 0.8, INK),
        ("ALIGN", (0, 0), (0, -1), "CENTER"),
        ("ALIGN", (4, 1), (-1, -1), "RIGHT"),
        ("ALIGN", (4, 0), (-1, 0), "RIGHT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 3),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3),
    ]))
    if not lines:
        table = Table(
            [[Paragraph("No items on this invoice.", styles["body"])]],
            colWidths=[CONTENT_WIDTH_MM * mm],
        )
        table.setStyle(TableStyle([
            ("BOX", (0, 0), (-1, -1), 0.5, RULE),
            ("TOPPADDING", (0, 0), (-1, -1), 10),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
        ]))
    return table


def _totals_table(bill: dict, styles: dict) -> Table:
    vat_applicable = bill.get("bill_type", "tax") == "tax" and float(bill.get("vat_rate") or 0) > 0
    rows: list[tuple[str, str, bool]] = [
        ("Subtotal", _rs(float(bill.get("subtotal") or 0)), False),
        ("Discount", f"- {_rs(float(bill.get('discount') or 0))}", False),
        ("Taxable amount", _rs(float(bill.get("taxable_net") or 0)) if vat_applicable else "—", False),
    ]
    if vat_applicable:
        rows.append((f"VAT ({float(bill.get('vat_rate') or 0):g}%)",
                     _rs(float(bill.get("vat") or 0)), False))
    else:
        rows.append(("VAT", "Not applicable", False))
    if float(bill.get("service_charge") or 0):
        rows.append((f"Service charge ({float(bill.get('service_charge_rate') or 0):g}%)",
                     _rs(float(bill.get("service_charge") or 0)), False))
    balance = float(bill.get("balance") or 0)
    paid = float(bill.get("paid") or 0)
    status = "Paid" if balance <= 0 else ("Partially paid" if paid > 0 else "Unpaid")
    rows += [
        ("Grand total", _rs(float(bill.get("total") or 0)), True),
        ("Amount paid", _rs(paid), False),
        ("Balance due", _rs(balance), False),
        ("Payment method", escape(str(bill.get("payment_method") or "—")), False),
        ("Payment status", status, False),
    ]
    grand_index = next(i for i, r in enumerate(rows) if r[0] == "Grand total")

    data = []
    for label, value, strong in rows:
        style = styles["body"] if not strong else styles["value"]
        data.append([
            Paragraph(f"<b>{label}</b>" if strong else label, style),
            Paragraph(f"<b>{value}</b>" if strong else value,
                      ParagraphStyle("amt", parent=style, alignment=TA_RIGHT)),
        ])
    table = Table(data, colWidths=[46 * mm, 34 * mm], hAlign="RIGHT")
    table.setStyle(TableStyle([
        ("LINEABOVE", (0, grand_index), (-1, grand_index), 0.8, INK),
        ("BACKGROUND", (0, grand_index), (-1, grand_index), LIGHT),
        ("TOPPADDING", (0, 0), (-1, -1), 2.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
    ]))
    return table


def _signatures(styles: dict) -> Table:
    cells = []
    for label in ("Received by", "Prepared by", "Authorised signatory"):
        cells.append([
            Spacer(1, 12 * mm),
            HRFlowable(color=INK, thickness=0.5, width=44 * mm),
            Spacer(1, 1.2),
            Paragraph(label, styles["sign"]),
        ])
    table = Table([cells], colWidths=[59 * mm] * 3)
    table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "BOTTOM"),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
    ]))
    return table


def build_a4_pdf(path: str | Path, bill: dict, lines: list, settings: dict) -> Path:
    """Render the A4 invoice / bill of supply for one bill.

    Devanagari needs a shaping engine, so the HTML/WeasyPrint renderer is used
    whenever it is installed; reportlab stays as the offline fallback.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        from . import invoice_html

        return invoice_html.build_a4_pdf(path, bill, lines, settings)
    except ImportError:
        pass
    styles = _styles()
    title = BILL_TYPE_LABELS.get(bill.get("bill_type", "tax"), "Tax Invoice")

    doc = SimpleDocTemplate(
        str(path), pagesize=A4,
        leftMargin=16 * mm, rightMargin=16 * mm,
        topMargin=13 * mm, bottomMargin=15 * mm,
        title=f"{title} {bill['bill_no']}",
        author=settings.get("hotel_name", ""),
        subject=title,
    )

    story = [
        _header(settings, bill, styles),
        Spacer(1, 2.5 * mm),
        HRFlowable(color=INK, thickness=1.0),
        Spacer(1, 3 * mm),
        _party_block(bill, settings, styles),
        Spacer(1, 5 * mm),
        _items_table(bill, lines, settings, styles),
        Spacer(1, 4 * mm),
        _totals_table(bill, styles),
        Spacer(1, 4 * mm),
        Table(
            [[Paragraph(
                f"<b>Amount in words:</b> {escape(amount_in_words(float(bill.get('total') or 0)))}",
                styles["words"],
            )]],
            colWidths=[CONTENT_WIDTH_MM * mm],
            style=TableStyle([
                ("BOX", (0, 0), (-1, -1), 0.5, RULE),
                ("BACKGROUND", (0, 0), (-1, -1), LIGHT),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]),
        ),
    ]

    terms = settings.get("payment_terms", "")
    policy = settings.get("return_policy", "")
    footnote = settings.get("footer_note", "")
    if terms or policy:
        story += [Spacer(1, 3 * mm)]
        if terms:
            story.append(Paragraph(f"<b>Payment terms:</b> {escape(terms)}", styles["small"]))
        if policy:
            story.append(Paragraph(f"<b>Return / exchange:</b> {escape(policy)}", styles["small"]))
    if bill.get("notes"):
        story.append(Spacer(1, 1.5 * mm))
        story.append(Paragraph(f"<b>Notes:</b> {escape(str(bill['notes']))}", styles["small"]))

    story += [
        Spacer(1, 7 * mm),
        _signatures(styles),
        Spacer(1, 4 * mm),
        HRFlowable(color=RULE, thickness=0.5),
        Spacer(1, 1.5 * mm),
        Paragraph(
            escape(footnote or "Thank you for your business."),
            ParagraphStyle("thanks", parent=styles["small"], alignment=TA_CENTER),
        ),
        Paragraph(
            escape(
                f"{settings.get('hotel_name', '')} · {settings.get('hotel_address1', '')} · "
                f"{settings.get('hotel_phone', '')} · Computer generated document"
            ),
            ParagraphStyle("legal", parent=styles["small"], alignment=TA_CENTER),
        ),
    ]

    doc.build(
        story,
        canvasmaker=lambda *a, **k: _NumberedCanvas(
            *a, footer_note=settings.get("hotel_name", ""), **k
        ),
    )
    return path


# --------------------------------------------------------------------------- #
# thermal receipt
# --------------------------------------------------------------------------- #
def build_thermal_pdf(path: str | Path, bill: dict, lines: list, settings: dict,
                      width_mm: float = 80) -> Path:
    """Render an 80mm-wide receipt PDF for thermal printers."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    width = width_mm * mm
    margin = 4 * mm
    rows = 14 + len(lines) * 2 + 6
    height = (30 + rows * 4.2) * mm

    c = pdf_canvas.Canvas(str(path), pagesize=(width, height))
    y = height - margin

    def line(text="", size=7.6, bold=False, align="left"):
        nonlocal y
        c.setFont("Helvetica-Bold" if bold else "Helvetica", size)
        text = str(text)
        if align == "center":
            c.drawCentredString(width / 2, y, text[:52])
        elif align == "right":
            c.drawRightString(width - margin, y, text)
        else:
            c.drawString(margin, y, text[:52])
        y -= size + 1.6

    def pair(left, right, bold=False):
        nonlocal y
        c.setFont("Helvetica-Bold" if bold else "Helvetica", 7.6)
        c.drawString(margin, y, left[:34])
        c.drawRightString(width - margin, y, right)
        y -= 9.2

    def rule():
        nonlocal y
        c.setDash(1, 1.6)
        c.line(margin, y + 4, width - margin, y + 4)
        c.setDash()
        y -= 3

    vat_applicable = bill.get("bill_type", "tax") == "tax" and float(bill.get("vat_rate") or 0) > 0
    title = BILL_TYPE_LABELS.get(bill.get("bill_type", "tax"), "Tax Invoice").upper()

    line(settings.get("hotel_name", "Hotel").upper(), 10, bold=True, align="center")
    line(settings.get("hotel_address1", ""), 6.8, align="center")
    line(settings.get("hotel_address2", ""), 6.8, align="center")
    line(f"Tel {settings.get('hotel_phone', '')}", 6.8, align="center")
    if settings.get("hotel_pan"):
        line(f"PAN/VAT {settings['hotel_pan']}", 6.8, align="center")
    rule()
    line(title, 8.5, bold=True, align="center")
    rule()
    line(f"Bill: {bill['bill_no']}", 7.2)
    line(f"Date: {_fmt_date(bill.get('bill_date'), settings.get('date_format', 'DD/MM/YYYY'))}", 7.2)
    if bill.get("guest_name"):
        line(f"Customer: {bill['guest_name']}", 7.2)
    if bill.get("guest_pan"):
        line(f"PAN: {bill['guest_pan']}", 7.2)
    if bill.get("room_no"):
        line(f"Room: {bill['room_no']}  Nights: {bill.get('nights', 0)}", 7.2)
    rule()
    for item in lines:
        line(item["description"][:46], 7.2)
        pair(f"  {item['qty']:g} x {float(item['unit_price']):,.2f}",
             f"{float(item['line_total']):,.2f}")
    rule()
    pair("Subtotal", f"{float(bill.get('subtotal') or 0):,.2f}")
    if float(bill.get("discount") or 0):
        pair("Discount", f"-{float(bill['discount']):,.2f}")
    if vat_applicable:
        pair(f"VAT {float(bill.get('vat_rate') or 0):g}%", f"{float(bill.get('vat') or 0):,.2f}")
    else:
        pair("VAT", "Not applicable")
    if float(bill.get("service_charge") or 0):
        pair("Service charge", f"{float(bill['service_charge']):,.2f}")
    pair("TOTAL", f"{float(bill.get('total') or 0):,.2f}", bold=True)
    pair("Paid", f"{float(bill.get('paid') or 0):,.2f}")
    if float(bill.get("balance") or 0):
        pair("Balance", f"{float(bill['balance']):,.2f}", bold=True)
    rule()
    line(f"Paid via {bill.get('payment_method', '-')}", 7.2)
    line(settings.get("footer_note", "Thank you!"), 7.2, align="center")
    line("Computer generated invoice", 6.4, align="center")

    c.showPage()
    c.save()
    return path


# --------------------------------------------------------------------------- #
# ESC/POS
# --------------------------------------------------------------------------- #
def escpos_bytes(bill: dict, lines: list, settings: dict) -> bytes:
    """Build ESC/POS command bytes for a thermal printer (no driver needed)."""
    ESC = b"\x1b"
    out = [ESC + b"@", ESC + b"a\x01"]
    vat_applicable = bill.get("bill_type", "tax") == "tax" and float(bill.get("vat_rate") or 0) > 0

    def text(value: str) -> None:
        out.append(value.encode("cp437", errors="replace") + b"\n")

    out.append(ESC + b"!\x30")
    text(settings.get("hotel_name", "Hotel").upper())
    out.append(ESC + b"!\x00")
    text(settings.get("hotel_address1", ""))
    text(settings.get("hotel_address2", ""))
    text(f"Tel: {settings.get('hotel_phone', '')}")
    if settings.get("hotel_pan"):
        text(f"PAN/VAT: {settings['hotel_pan']}")
    text("-" * 42)
    text(BILL_TYPE_LABELS.get(bill.get("bill_type", "tax"), "Tax Invoice").upper())
    text("-" * 42)
    out.append(ESC + b"a\x00")
    text(f"Bill: {bill['bill_no']}")
    text(f"Date: {_fmt_date(bill.get('bill_date'), settings.get('date_format', 'DD/MM/YYYY'))}")
    if bill.get("guest_name"):
        text(f"Customer: {bill['guest_name']}")
    if bill.get("guest_pan"):
        text(f"PAN: {bill['guest_pan']}")
    if bill.get("room_no"):
        text(f"Room: {bill['room_no']}  Nights: {bill.get('nights', 0)}")
    text("-" * 42)
    for item in lines:
        text(str(item["description"])[:42])
        text(f"  {item['qty']:g} x {float(item['unit_price']):>10,.2f}"
             f"{float(item['line_total']):>14,.2f}")
    text("-" * 42)
    for label, key in (
        ("Subtotal", "subtotal"), ("Discount", "discount"),
    ):
        text(f"{label:<24}{float(bill.get(key) or 0):>18,.2f}")
    if vat_applicable:
        text(f"{'VAT':<24}{float(bill.get('vat') or 0):>18,.2f}")
    else:
        text(f"{'VAT':<24}{'Not applicable':>18}")
    text(f"{'Service charge':<24}{float(bill.get('service_charge') or 0):>18,.2f}")
    text(f"{'TOTAL':<24}{float(bill.get('total') or 0):>18,.2f}")
    text(f"{'Paid':<24}{float(bill.get('paid') or 0):>18,.2f}")
    text(f"{'Balance':<24}{float(bill.get('balance') or 0):>18,.2f}")
    text("-" * 42)
    out.append(ESC + b"a\x01")
    text(f"Paid via {bill.get('payment_method', '-')}")
    text(settings.get("footer_note", "Thank you!"))
    text("Computer generated invoice")
    out += [b"\n\n\n", b"\x1dV\x41\x10"]
    return b"".join(out)


def send_to_device(data: bytes, device: str) -> None:
    """Write raw ESC/POS bytes to a printer device (e.g. /dev/usb/lp0)."""
    if not device:
        raise ValueError("No thermal printer device configured")
    if not os.path.exists(device):
        raise FileNotFoundError(device)
    with open(device, "wb") as handle:
        handle.write(data)
