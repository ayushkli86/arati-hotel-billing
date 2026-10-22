"""Printer configuration and print rendering.

The till prints through the operating system's print dialog: the invoice is
rendered to a self-contained HTML document with print CSS, and the browser
(or the PDF viewer) turns that into paper. The same HTML string is used for
the downloadable PDF, so what the guest reads on paper and what the guest
takes away as a PDF are the same document, computed from the same stored
bill.

Three paper sizes are supported:

``A4``
    The full tax invoice, with the itemised table.
``80``
    A thermal receipt, 80 mm wide.
``58``
    A thermal receipt, 58 mm wide.

What the printer can actually do is decided by the browser, the operating
system and the printer driver, not by this application: the page size and
margins are set in the document, but choosing a physical printer and
silent printing are outside our control. The app never claims that a
document reached a specific printer.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

# Paper sizes the till can produce. ``height_mm`` of None means "as long as
# the content needs" (a thermal roll).
PAPER_SIZES: dict[str, dict] = {
    "A4": {"label": "A4 (210 × 297 mm)", "width_mm": 210.0, "height_mm": 297.0},
    "80": {"label": "80 mm thermal receipt", "width_mm": 80.0, "height_mm": None},
    "58": {"label": "58 mm thermal receipt", "width_mm": 58.0, "height_mm": None},
}

PAPER_CHOICES = ("A4", "80", "58")

# ``printer_margins`` setting -> margin in millimetres.
MARGIN_PRESETS = {
    "narrow": 8.0,
    "normal": 12.0,
    "wide": 18.0,
}

# ``printer_default_workflow`` setting.
WORKFLOWS = {
    "preview": "Open a print preview before printing",
    "direct": "Open the print dialog straight away",
}


class PrintError(ValueError):
    """Raised when the printer configuration cannot be used."""


@dataclass(frozen=True)
class PrintConfig:
    """The resolved printer configuration for one document."""

    paper: str = "A4"
    margin_mm: float = 12.0
    show_logo: bool = True
    show_header: bool = True
    show_footer: bool = True
    show_contact: bool = True
    show_tax: bool = True
    copies: int = 1
    workflow: str = "preview"

    @property
    def width_mm(self) -> float:
        return float(PAPER_SIZES[self.paper]["width_mm"])

    @property
    def is_thermal(self) -> bool:
        return self.paper in ("80", "58")

    @property
    def label(self) -> str:
        return str(PAPER_SIZES[self.paper]["label"])


def resolve(settings: dict | None) -> PrintConfig:
    """Read the printer settings and turn them into a configuration.

    Unknown or missing values fall back to the safe defaults (A4, normal
    margins, everything shown), so a half-filled settings screen can never
    produce an unreadable invoice.
    """
    settings = settings or {}
    paper = str(settings.get("printer_paper_size") or "A4").strip().upper()
    if paper not in PAPER_SIZES:
        paper = "A4"

    margin_key = str(settings.get("printer_margins") or "normal").strip().lower()
    margin_mm = MARGIN_PRESETS.get(margin_key, MARGIN_PRESETS["normal"])

    def flag(name: str, default: bool = True) -> bool:
        raw = settings.get(name)
        if raw is None or raw == "":
            return default
        return str(raw).strip().lower() not in ("0", "false", "no", "off")

    try:
        copies = int(float(settings.get("printer_copies") or 1))
    except (TypeError, ValueError):
        copies = 1
    copies = max(1, min(5, copies))

    workflow = str(settings.get("printer_default_workflow") or "preview").strip().lower()
    if workflow not in WORKFLOWS:
        workflow = "preview"

    return PrintConfig(
        paper=paper,
        margin_mm=margin_mm,
        show_logo=flag("printer_show_logo"),
        show_header=flag("printer_header"),
        show_footer=flag("printer_footer"),
        show_contact=flag("printer_contact_details"),
        show_tax=flag("printer_tax_details"),
        copies=copies,
        workflow=workflow,
    )


# --------------------------------------------------------------------------- #
# document
# --------------------------------------------------------------------------- #
def build_html(
    bill: dict, lines: list, settings: dict, config: PrintConfig | None = None
) -> str:
    """Render the invoice as a print-ready HTML document.

    A4 documents reuse the invoice layout the app already shows on screen.
    Thermal documents get a narrow single-column layout with a page size
    that matches the roll width.
    """
    config = config or resolve(settings)
    if config.is_thermal:
        return _thermal_html(bill, lines, settings, config)

    from . import invoice_html

    options = {
        "page_size": config.paper,
        "margin_mm": config.margin_mm,
        "show_logo": config.show_logo,
        "show_header": config.show_header,
        "show_footer": config.show_footer,
        "show_contact": config.show_contact,
        "show_tax": config.show_tax,
    }
    return invoice_html.build_html(bill, lines, settings, options=options)


def _thermal_html(
    bill: dict, lines: list, settings: dict, config: PrintConfig
) -> str:
    """A narrow receipt layout for 80 mm and 58 mm thermal printers."""
    from html import escape

    from .money import BILL_TYPE_LABELS, amount_in_words, payment_status
    from .nepali import format_date

    def money(value) -> str:
        try:
            return f"{float(value or 0):,.2f}"
        except (TypeError, ValueError):
            return "0.00"

    symbol = settings.get("currency_symbol") or "रु."
    language = (bill.get("language") or settings.get("invoice_language") or "en").lower()
    date_format = settings.get("date_format") or "DD/MM/YYYY"

    def head(text: str, size: int = 9, bold: bool = True, align: str = "center") -> str:
        weight = "bold" if bold else "normal"
        css_align = {"center": "center", "left": "left", "right": "right"}[align]
        return (
            f'<div style="text-align:{css_align};font-size:{size}pt;'
            f'font-weight:{weight};margin:1px 0;">{escape(text)}</div>'
        )

    def row(label: str, value: str, bold: bool = False) -> str:
        weight = "bold" if bold else "normal"
        return (
            '<div style="display:flex;justify-content:space-between;'
            f'font-size:8pt;font-weight:{weight};margin:1px 0;">'
            f"<span>{escape(label)}</span><span>{escape(value)}</span></div>"
        )

    parts: list[str] = []
    if config.show_header:
        if config.show_logo:
            logo = settings.get("logo_path") or ""
            if logo and Path(logo).exists():
                parts.append(
                    f'<div style="text-align:center;"><img src="{Path(logo).resolve().as_uri()}" '
                    'style="max-height:28px;max-width:60px;"></div>'
                )
        parts.append(head(settings.get("hotel_name", "Arati Hotel"), 11))
        if settings.get("hotel_address1"):
            parts.append(head(settings.get("hotel_address1"), 7, False))
        if settings.get("hotel_address2"):
            parts.append(head(settings.get("hotel_address2"), 7, False))
        if config.show_contact and settings.get("hotel_phone"):
            parts.append(head(f"Tel: {settings['hotel_phone']}", 7, False))
        if config.show_tax and settings.get("hotel_pan"):
            parts.append(head(f"PAN/VAT: {settings['hotel_pan']}", 7, False))
        parts.append('<div style="border-top:0.5pt dashed #000;margin:3px 0;"></div>')
        title = BILL_TYPE_LABELS.get(bill.get("bill_type") or "tax", "Tax Invoice")
        parts.append(head(title.upper(), 9))
        copy_label = settings.get("invoice_copy") or "Customer Copy"
        parts.append(head(copy_label, 7, False))
        parts.append('<div style="border-top:0.5pt dashed #000;margin:3px 0;"></div>')

    parts.append(row("Bill No", str(bill.get("bill_no") or "")))
    parts.append(
        row("Date", format_date(bill.get("bill_date"), date_format))
    )
    parts.append(row("Time", str(bill.get("created_at") or "")[11:16]))
    if bill.get("guest_name"):
        parts.append(row("Guest", str(bill["guest_name"])))
    if bill.get("guest_phone"):
        parts.append(row("Phone", str(bill["guest_phone"])))
    if bill.get("room_no"):
        parts.append(
            row("Room", f"{bill['room_no']} · {int(bill.get('nights') or 0)}N")
        )
    if bill.get("prepared_by"):
        parts.append(row("Cashier", str(bill["prepared_by"])))
    parts.append('<div style="border-top:0.5pt dashed #000;margin:3px 0;"></div>')

    for line in lines:
        parts.append(
            f'<div style="font-size:8pt;margin:2px 0 0;">'
            f"{escape(str(line.get('description', '')))}</div>"
        )
        parts.append(
            '<div style="display:flex;justify-content:space-between;font-size:8pt;">'
            f"<span>&nbsp;&nbsp;{float(line.get('qty') or 0):g} × "
            f"{money(line.get('unit_price'))}</span>"
            f"<span>{money(line.get('line_total'))}</span></div>"
        )

    parts.append('<div style="border-top:0.5pt dashed #000;margin:3px 0;"></div>')
    parts.append(row("Subtotal", money(bill.get("subtotal"))))
    if float(bill.get("discount") or 0):
        parts.append(row("Discount", f"-{money(bill.get('discount'))}"))
    vat_applicable = (
        (bill.get("bill_type") or "tax") == "tax" and float(bill.get("vat_rate") or 0) > 0
    )
    if config.show_tax:
        if vat_applicable:
            parts.append(
                row(f"VAT {float(bill.get('vat_rate') or 0):g}%", money(bill.get("vat")))
            )
        else:
            parts.append(row("VAT", "Not applicable"))
    if float(bill.get("service_charge") or 0):
        parts.append(row("Service charge", money(bill.get("service_charge"))))
    parts.append(row("TOTAL", f"{symbol} {money(bill.get('total'))}", True))
    parts.append(row("Paid", money(bill.get("paid"))))
    if float(bill.get("balance") or 0):
        parts.append(row("Balance", money(bill.get("balance")), True))
    parts.append(row("Payment", str(bill.get("payment_method") or "—")))
    parts.append(
        row("Status", payment_status(bill.get("total") or 0, bill.get("paid") or 0))
    )
    parts.append('<div style="border-top:0.5pt dashed #000;margin:3px 0;"></div>')

    if config.show_footer:
        parts.append(head(amount_in_words(float(bill.get("total") or 0)), 6, False))
        if bill.get("payment_terms"):
            parts.append(head(str(bill["payment_terms"]), 6, False))
        parts.append(head(settings.get("footer_note") or "Thank you!", 7, False))
        parts.append(head("Computer generated invoice", 6, False))

    width = config.width_mm
    margin = min(config.margin_mm, 5.0)
    body = "".join(parts)
    copies = ""
    for _ in range(config.copies):
        copies += f'<section class="copy">{body}</section>'
    page_size = f"{width}mm auto" if config.paper != "A4" else "A4 portrait"
    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<title>{escape(str(bill.get('bill_no') or 'Receipt'))}</title>
<style>
@page {{ size: {page_size}; margin: {margin}mm {margin}mm {margin}mm {margin}mm; }}
* {{ box-sizing: border-box; }}
body {{
  margin: 0; padding: 0; color: #000; background: #fff;
  font-family: 'AratiNepali', 'Noto Sans Devanagari', 'DejaVu Sans', sans-serif;
  font-size: 8pt; line-height: 1.25;
}}
.copy {{ page-break-after: always; }}
.copy:last-child {{ page-break-after: auto; }}
@media screen {{
  body {{ background: #f2f2f2; padding: 12px; }}
  .copy {{
    background: #fff; width: {width}mm; margin: 0 auto 12px auto; padding: 4mm;
    box-shadow: 0 1px 4px rgba(0,0,0,.25);
  }}
}}
@media print {{
  .copy {{ box-shadow: none; padding: 0; }}
}}
</style></head>
<body>{copies}</body></html>
"""


# --------------------------------------------------------------------------- #
# output
# --------------------------------------------------------------------------- #
def build_pdf(
    path: str | Path,
    bill: dict,
    lines: list,
    settings: dict,
    config: PrintConfig | None = None,
) -> Path:
    """Render the print document to PDF.

    The PDF is produced from the *same* HTML that the browser prints, so the
    two cannot disagree about the numbers.
    """
    from weasyprint import HTML

    config = config or resolve(settings)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    html = build_html(bill, lines, settings, config)
    HTML(string=html, base_url=str(path.parent)).write_pdf(str(path))
    return path


def build_print_file(
    path: str | Path,
    bill: dict,
    lines: list,
    settings: dict,
    config: PrintConfig | None = None,
) -> Path:
    """Write the print document to an HTML file for the browser to print."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(build_html(bill, lines, settings, config), encoding="utf-8")
    return path


def describe(settings: dict | None) -> str:
    """A one-line summary of the current printer configuration."""
    config = resolve(settings)
    parts = [config.label, f"{config.margin_mm:g} mm margins"]
    if config.copies > 1:
        parts.append(f"{config.copies} copies")
    hidden = [
        name
        for name, on in (
            ("logo", config.show_logo),
            ("header", config.show_header),
            ("footer", config.show_footer),
            ("contact", config.show_contact),
            ("tax", config.show_tax),
        )
        if not on
    ]
    if hidden:
        parts.append("hidden: " + ", ".join(hidden))
    return " · ".join(parts)
