"""Print-ready A4 invoice (HTML → PDF through WeasyPrint).

Devanagari needs a shaping engine, which reportlab does not have, so the A4
invoice is laid out in HTML and rendered by WeasyPrint/Pango. All amounts come
from the stored bill, which was computed by :func:`arati.money.compute_totals`,
so preview, PDF and receipt always agree.

The visual design follows the standard invoice reference: a navy company block
on the left with the accent-coloured document title and meta grid on the
right, a navy ``BILL TO`` banner, a three column line item table with zebra
rows, and a two column summary (comments on the left, totals on the right)
closed by a centred thank-you footer.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from html import escape
from pathlib import Path

from . import nepali
from .money import BILL_TYPE_LABELS, amount_in_words, payment_status, round2
from .nepali import format_date

FONT_DIR = Path(__file__).resolve().parent / "fonts"
FONT_FILE = FONT_DIR / "NotoSansDevanagari.ttf"

COPIES = {"customer": ("Customer copy", "ग्राहक प्रति"), "office": ("Office copy", "कार्यालय प्रति")}
# Column headings that carry a money value, so the currency mark can be added.
MONEY_COLUMNS = {"rate", "discount", "taxable_amount", "vat_amount", "total"}

# Palette of the reference invoice.
NAVY = "#3F4687"
ACCENT = "#7984C5"
STRIPE = "#F2F2F2"
HILITE = "#D0D6EC"
INK = "#1F2430"
MUTED = "#8A93A6"


def _money(value) -> str:
    try:
        return f"{float(value):,.2f}"
    except (TypeError, ValueError):
        return "0.00"


def _currency(settings: dict) -> str:
    return str(settings.get("currency_symbol") or "रु.")


def _escape(value) -> str:
    return escape(str(value if value is not None else ""))


def _cents(value) -> Decimal:
    return Decimal(str(value or 0)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def line_amounts(bill: dict, lines: list) -> list[dict]:
    """Split a bill across its lines so every printed column ties out.

    A line can carry its own discount and the bill can carry an overall
    discount. The overall discount is pushed down onto the lines (proportional
    to the value left after the line's own discount) and the VAT is spread over
    the taxable lines. The rounding residual is placed on the last row of each
    column, so every column sums to the stored total exactly — no invented
    paisa, and the printed bill can never disagree with the saved one.
    """
    subtotal = _cents(bill.get("subtotal"))
    discount = _cents(bill.get("discount"))
    taxable_net = _cents(bill.get("taxable_net"))
    vat = _cents(bill.get("vat"))
    vat_rate = float(bill.get("vat_rate") or 0)
    taxable_flag = float(bill.get("vat_rate") or 0) > 0 and (
        bill.get("bill_type") or "tax"
    ) == "tax"

    rows: list[dict] = []
    for line in lines:
        gross = _cents(line.get("line_total"))
        own = min(_cents(line.get("discount")), gross)
        rows.append(
            {
                "line": line,
                "gross": gross,
                "own_discount": own,
                "after_own": _cents(gross - own),
                "discount": own,
                "taxable": bool(line.get("taxable", 1)) and taxable_flag,
                "vat": Decimal("0.00"),
            }
        )

    # Push the overall discount onto the lines, proportional to what is left.
    base = sum((row["after_own"] for row in rows), Decimal("0.00"))
    if rows and base > 0:
        for row in rows:
            row["overall_share"] = _cents(discount * row["after_own"] / base)
        allocated = sum((row["overall_share"] for row in rows), Decimal("0.00"))
        rows[-1]["overall_share"] += discount - allocated
    else:
        for row in rows:
            row["overall_share"] = Decimal("0.00")

    for row in rows:
        row["discount"] = _cents(row["own_discount"] + row["overall_share"])
        row["net"] = _cents(row["after_own"] - row["overall_share"])

    taxable_rows = [row for row in rows if row["taxable"]]
    if taxable_rows:
        # Match the stored taxable base exactly (rounding residual on last row).
        for row in taxable_rows:
            row["taxable_net"] = row["net"]
        allocated = sum((row["taxable_net"] for row in taxable_rows), Decimal("0"))
        taxable_rows[-1]["taxable_net"] += taxable_net - allocated
        total_taxable = sum((row["taxable_net"] for row in taxable_rows), Decimal("0"))
        for row in taxable_rows:
            row["vat"] = (
                _cents(vat * row["taxable_net"] / total_taxable) if total_taxable else Decimal("0")
            )
        residual = vat - sum((row["vat"] for row in taxable_rows), Decimal("0"))
        taxable_rows[-1]["vat"] += residual

    for row in rows:
        row.setdefault("taxable_net", Decimal("0.00"))
        row["total"] = row["net"] + row["vat"]
        row["vat_rate"] = vat_rate if row["taxable"] else 0.0
    return rows


def _label(key: str, language: str, english: str | None = None) -> str:
    """Nepali label with a small English gloss under it, or plain English."""
    nep = nepali.label(key, "ne")
    eng = english or nepali.label(key, "en")
    if language == "ne":
        return f'{_escape(nep)}<span class="en">{_escape(eng)}</span>'
    return _escape(eng)


def _style(options: dict | None = None) -> str:
    options = options or {}
    font_uri = FONT_FILE.as_uri() if FONT_FILE.exists() else ""
    face = (
        f"@font-face {{ font-family: 'AratiNepali'; src: url('{font_uri}'); }}"
        if font_uri
        else ""
    )
    page_size = str(options.get("page_size") or "A4")
    margin = float(options.get("margin_mm") or 13)
    return f"""
{face}
@page {{
  size: {page_size} portrait;
  margin: {margin:g}mm {margin:g}mm {margin + 2:g}mm {margin:g}mm;
  @bottom-center {{
    content: "Page " counter(page) " of " counter(pages);
    font-size: 6.8pt; color: #98A0AE;
  }}
}}
* {{ box-sizing: border-box; }}
body {{
  font-family: 'Inter', 'Lato', 'AratiNepali', 'Noto Sans Devanagari', 'DejaVu Sans', sans-serif;
  font-size: 8.5pt; line-height: 1.35; color: {INK}; margin: 0;
}}
table {{ width: 100%; border-collapse: collapse; }}
td, th {{ vertical-align: top; }}
p {{ margin: 0; }}
.en {{ font-size: 0.78em; color: #98A0AE; display: block; font-weight: normal; }}
.cur {{ font-size: 0.72em; color: #98A0AE; display: block; font-weight: normal; }}

/* ---------- company header ---------- */
.top td {{ vertical-align: top; }}
.top-l {{ width: 54%; padding-right: 8mm; }}
.logo {{ max-height: 40px; max-width: 92px; margin-bottom: 4px; }}
.company {{ font-size: 26pt; font-weight: 700; color: {NAVY}; line-height: 1.05; }}
.company-ne {{ font-size: 11pt; font-weight: 600; color: {NAVY}; margin-top: 2px; }}
.hotel-line {{ font-size: 8.5pt; color: #2A3145; margin-top: 2.5px; }}
.hotel-line .k {{ color: #98A0AE; }}
.top-r {{ width: 46%; text-align: right; }}
.doc-title {{
  font-size: 25pt; font-weight: 700; color: {ACCENT};
  letter-spacing: 2pt; line-height: 1;
}}
.doc-sub {{ font-size: 8pt; font-weight: 700; color: {NAVY}; letter-spacing: 1pt; margin-top: 5px; }}
.doc-sub .en {{ display: inline; margin-left: 5pt; color: #A8B0C4; }}
.doc-copy {{ font-size: 7.5pt; color: #98A0AE; letter-spacing: 0.6pt; margin-top: 2px; }}

/* ---------- meta grid ---------- */
.meta {{ margin-top: 9px; margin-left: auto; width: 84mm; }}
.meta td {{ padding: 3.4pt 6pt; }}
.meta .k {{
  width: 40%; font-size: 6.6pt; color: #98A0AE; text-align: right;
  text-transform: uppercase; letter-spacing: 0.8pt; white-space: nowrap;
}}
.meta .k .en {{ display: inline; margin-left: 4pt; text-transform: none; letter-spacing: 0; }}
.meta .v {{ font-size: 9pt; font-weight: 600; color: {INK}; text-align: center; }}
.meta .v .sub {{ display: block; font-size: 6.8pt; font-weight: 400; color: #98A0AE; margin-top: 1px; }}
.meta tr.hi .v {{ background: {HILITE}; }}

/* ---------- banners ---------- */
.banner {{
  background: {NAVY}; color: #FFFFFF; font-size: 8pt; font-weight: 700;
  letter-spacing: 1.4pt; text-transform: uppercase; padding: 4.2pt 7pt;
}}
.banner .en {{ display: inline; margin-left: 6pt; color: #C3C9DE; letter-spacing: 0.4pt; }}

/* ---------- bill to ---------- */
.billto {{ margin-top: 7mm; break-inside: avoid; }}
.billto .banner {{ width: 42%; }}
.party {{ margin-top: 4pt; padding-left: 4.5mm; }}
.party .p-name {{ font-size: 11pt; font-weight: 700; color: {INK}; }}
.party .p-org {{ font-size: 9pt; font-weight: 600; color: {NAVY}; margin-top: 2px; }}
.party .p-ln {{ font-size: 8.5pt; color: #2A3145; margin-top: 2px; }}
.party .p-ln .k {{ color: #98A0AE; }}

/* ---------- line items ---------- */
.items {{ margin-top: 4mm; break-inside: avoid; }}
.items th {{
  background: {NAVY}; color: #FFFFFF; font-size: 8pt; font-weight: 700;
  letter-spacing: 1pt; text-transform: uppercase; padding: 4.6pt 7pt;
}}
.items th .cur {{ display: inline; margin-left: 4pt; color: #C3C9DE; }}
.items .c-desc {{ width: 62%; }}
.items .c-taxed {{ width: 16mm; text-align: center; }}
.items .c-amount {{ width: 27mm; text-align: right; }}
.items td {{ padding: 3.4pt 7pt; font-size: 8.5pt; }}
.items th.c-desc, .items td.c-desc {{ border-left: 0.6pt solid #000; }}
.items th.c-taxed, .items td.c-taxed {{
  border-left: 0.6pt solid #000; border-right: 0.6pt solid #000; text-align: center;
}}
.items th.c-amount, .items td.c-amount {{ border-right: 0.6pt solid #000; text-align: right; }}
.items tbody tr:nth-child(even) td {{ background: {STRIPE}; }}
.items tr:last-child td {{ border-bottom: 0.6pt solid #000; }}
.items .desc {{ font-weight: 600; }}
.items .meta-line {{ font-size: 7pt; font-weight: 400; color: {MUTED}; margin-top: 1px; }}
.items .taxed {{ color: {NAVY}; font-weight: 700; }}

/* ---------- summary ---------- */
.lower {{ margin-top: 5mm; break-inside: avoid; }}
.lower td {{ vertical-align: top; }}
.lower .lo-l {{ width: 56%; padding-right: 6mm; }}
.lower .lo-r {{ width: 40%; }}
.cmt {{ margin-top: 5pt; padding-left: 4.5mm; }}
.cmt p {{ font-size: 8.5pt; color: #2A3145; margin-bottom: 2.6pt; }}
.cmt p.muted {{ color: {MUTED}; font-size: 7.8pt; }}
.totals td {{ padding: 2.8pt 0; font-size: 8.5pt; }}
.totals td.k {{ color: #55607A; }}
.totals td.k .en {{ display: inline; margin-left: 5pt; font-size: 0.72em; color: #A0A8B8; }}
.totals td.v {{ text-align: right; white-space: nowrap; font-weight: 600; }}
.totals tr.grand td.k {{
  border-top: 0.6pt solid #000; font-size: 11pt; font-weight: 700; color: {NAVY}; padding-top: 5pt;
}}
.totals tr.grand td.v {{
  border: 0.6pt solid #000; background: {HILITE}; font-size: 11pt; font-weight: 700;
  color: {NAVY}; padding: 3.4pt 6pt;
}}
.totals tr.settle td {{ font-size: 7.8pt; color: {MUTED}; }}
.totals tr.settle td.v {{ color: #55607A; font-weight: 400; }}
.words {{ margin-top: 6pt; font-size: 8pt; color: #55607A; }}
.words .k {{ color: {MUTED}; font-size: 7pt; text-transform: uppercase; letter-spacing: 0.6pt; }}
.words .k .en {{ display: inline; margin-left: 4pt; }}
.words .v {{ font-weight: 600; color: {INK}; }}
.words .alt {{ color: {MUTED}; }}
.paynote {{ margin-top: 5pt; font-size: 8pt; color: {MUTED}; }}
.paynote .en {{ display: inline; margin-left: 4pt; }}

/* ---------- footer ---------- */
.foot {{ margin-top: 7mm; text-align: center; break-inside: avoid; }}
.foot .f-contact {{ font-size: 8pt; color: #767676; }}
.foot .f-contact .en {{ display: inline; margin-left: 4pt; }}
.foot .f-thanks {{
  margin-top: 4pt; font-size: 13pt; font-weight: 700; font-style: italic; color: {NAVY};
}}
.foot .f-thanks .en {{ display: inline; margin-left: 6pt; font-size: 0.7em; color: #A8B0C4; }}
.foot .f-sub {{ margin-top: 4pt; font-size: 7.5pt; color: #A0A8B8; }}
"""


def _header(settings: dict, bill: dict, language: str, options: dict | None = None) -> str:
    options = options or {}
    show_header = options.get("show_header", True)
    show_logo = options.get("show_logo", True)
    show_contact = options.get("show_contact", True)
    show_tax = options.get("show_tax", True)
    lang = "ne" if language == "ne" else "en"

    logo = settings.get("logo_path") or ""
    logo_html = ""
    if show_logo and logo and Path(logo).exists():
        logo_html = f'<div><img class="logo" src="{Path(logo).resolve().as_uri()}"></div>'

    name = _escape(settings.get("hotel_name", "Arati Hotel"))
    name_ne = _escape(settings.get("hotel_name_ne", ""))

    hotel_lines: list[str] = []
    for key in ("hotel_address1", "hotel_address2"):
        value = settings.get(key) or ""
        if value:
            hotel_lines.append(_escape(value))
    if show_contact:
        if settings.get("hotel_phone"):
            hotel_lines.append(
                f'<span class="k">{_escape(nepali.label("phone", lang))}</span>'
                f' {_escape(settings["hotel_phone"])}'
            )
        if settings.get("hotel_email"):
            hotel_lines.append(_escape(settings["hotel_email"]))
        if settings.get("hotel_website"):
            hotel_lines.append(_escape(settings["hotel_website"]))
    if show_tax:
        ids = " · ".join(
            part
            for part in (
                f"PAN: {_escape(settings['hotel_pan'])}" if settings.get("hotel_pan") else "",
                f"VAT No.: {_escape(settings['hotel_vat'])}" if settings.get("hotel_vat") else "",
            )
            if part
        )
        if ids:
            hotel_lines.append(ids)
    lines_html = "".join(f'<div class="hotel-line">{line}</div>' for line in hotel_lines)

    bill_type = bill.get("bill_type") or "tax"
    title = _label(
        "tax_invoice" if bill_type == "tax" else "bill_of_supply",
        language,
        BILL_TYPE_LABELS.get(bill_type, "Tax Invoice").upper(),
    )
    copy_key = "office" if (bill.get("copy") or "customer") == "office" else "customer"
    copy_en, copy_ne = COPIES[copy_key]
    # The hotel can rename the copies in Settings; use that when it is set.
    configured = settings.get(
        "invoice_copy_office" if copy_key == "office" else "invoice_copy"
    )
    copy_text = configured or (copy_ne if language == "ne" else copy_en)

    if not show_header:
        return f"""
<table class="top"><tr><td class="top-r" style="width:100%">
  <div class="doc-title">INVOICE</div>
  <div class="doc-sub">{title}</div>
  <div class="doc-copy">{_escape(copy_text)}</div>
</td></tr></table>
"""

    return f"""
<table class="top">
  <tr>
    <td class="top-l">
      {logo_html}
      <div class="company">{name}</div>
      {f'<div class="company-ne">{name_ne}</div>' if name_ne else ''}
      {lines_html}
    </td>
    <td class="top-r">
      <div class="doc-title">INVOICE</div>
      <div class="doc-sub">{title}</div>
      <div class="doc-copy">{_escape(copy_text)}</div>
      {_meta(settings, bill, language)}
    </td>
  </tr>
</table>
"""


def _meta(settings: dict, bill: dict, language: str) -> str:
    """The invoice meta grid: date, invoice number, customer id and due date."""
    bs = nepali.to_bs(bill.get("bill_date"))
    bs_value = "—"
    if bs:
        bs_value = _escape(nepali.to_latin(bs[0]) if language == "en" else bs[1])
    date_format = settings.get("date_format") or "DD/MM/YYYY"
    bill_date = _escape(format_date(bill.get("bill_date"), date_format))

    customer = bill.get("customer_id")
    if customer:
        customer_value = f"CUS-{int(customer):04d}"
    else:
        customer_value = _escape(bill.get("guest_name") or "—")

    due_date = bill.get("check_out")
    due_value = _escape(format_date(due_date, date_format)) if due_date else "—"

    cells = [
        (_label("date", language), f'{bill_date}<span class="sub">{bs_value}</span>', False),
        (_label("invoice_no", language), _escape(bill.get("bill_no", "")), False),
        (_label("customer_id", language), customer_value, False),
        (_label("due_date", language), due_value, True),
    ]
    body = "".join(
        f'<tr class="{"hi" if hi else ""}"><td class="k">{key}</td>'
        f'<td class="v">{value}</td></tr>'
        for key, value, hi in cells
    )
    return f'<table class="meta">{body}</table>'


def _party(bill: dict, language: str) -> str:
    """The ``BILL TO`` banner and the customer block below it."""
    lang = "ne" if language == "ne" else "en"
    name = _escape(
        bill.get("guest_name") or ("Walk-in guest" if language == "en" else "आगन्तुक ग्राहक")
    )
    address = _escape(bill.get("guest_address") or "—")
    phone = _escape(bill.get("guest_phone") or "—")
    pan = _escape(bill.get("guest_pan") or "")
    is_business = (bill.get("customer_type") or "individual") == "business"

    details = [
        f'<div class="p-ln"><span class="k">{_escape(nepali.label("address", lang))}</span> {address}</div>',
        f'<div class="p-ln"><span class="k">{_escape(nepali.label("phone", lang))}</span> {phone}</div>',
    ]
    if pan:
        details.append(
            f'<div class="p-ln"><span class="k">{_escape(nepali.label("pan", lang))}</span> {pan}</div>'
        )
    if bill.get("room_no"):
        stay = _escape(
            f"{bill['room_no']} · {bill.get('check_in') or ''} → "
            f"{bill.get('check_out') or ''} ({int(bill.get('nights') or 0)}N)"
        )
        details.append(
            f'<div class="p-ln"><span class="k">'
            f'{_escape("Room / stay" if language == "en" else "कोठा / बसाइ")}</span> {stay}</div>'
        )

    org = ""
    if is_business:
        org = (
            f'<div class="p-org">{_escape(nepali.label("business", lang))} · '
            f'{_escape(nepali.label("customer_type", lang).lower())}</div>'
        )

    return f"""
<div class="billto">
  <div class="banner">{_label('bill_to', language)}</div>
  <div class="party">
    <div class="p-name">{name}</div>
    {org}
    {''.join(details)}
  </div>
</div>
"""


def _items(bill: dict, lines: list, language: str, settings: dict) -> str:
    """The line item table: description, tax flag and amount."""
    rows = line_amounts(bill, lines)
    symbol = _currency(settings)

    head = (
        f'<th class="c-desc">{_label("description", language)}</th>'
        f'<th class="c-taxed">{_label("taxed", language)}</th>'
        f'<th class="c-amount">{_label("amount", language)}'
        f'<span class="cur">{_escape(symbol)}</span></th>'
    )

    body = []
    for row in rows:
        line = row["line"]
        bits = []
        qty = float(line.get("qty") or 0)
        if qty:
            unit = _escape(line.get("unit") or "")
            bits.append(f"{qty:g} {unit} × {_money(line.get('unit_price'))}".strip())
        if line.get("code"):
            bits.append(_escape(line["code"]))
        meta = (
            f'<div class="meta-line">{_escape(" · ".join(bits))}</div>' if bits else ""
        )
        taxed = "X" if row["taxable"] else ""
        body.append(
            f'<tr><td class="c-desc"><div class="desc">'
            f'{_escape(line.get("description", ""))}</div>{meta}</td>'
            f'<td class="c-taxed">{taxed}</td>'
            f'<td class="c-amount">{_money(row["net"])}</td></tr>'
        )
    if not body:
        body.append(
            '<tr><td class="c-desc" colspan="3" style="text-align:center">'
            + ("कुनै विवरण छैन" if language == "ne" else "No items")
            + "</td></tr>"
        )

    return f"""
<table class="items">
  <thead><tr>{head}</tr></thead>
  <tbody>{''.join(body)}</tbody>
</table>
"""


def _summary(bill: dict, language: str, settings: dict, options: dict | None = None) -> str:
    """The summary band: comments on the left, the totals block on the right."""
    options = options or {}
    show_tax = options.get("show_tax", True)
    lang = "ne" if language == "ne" else "en"
    symbol = _currency(settings)

    net_subtotal = float(bill.get("net_subtotal") or 0)
    taxable = float(bill.get("taxable_net") or 0)
    exempt = round2(max(0.0, net_subtotal - taxable))
    service = float(bill.get("service_charge") or 0)
    service_rate = float(bill.get("service_charge_rate") or 0)
    vat_rate = float(bill.get("vat_rate") or 0)
    vat_applicable = (
        show_tax
        and (bill.get("bill_type") or "tax") == "tax"
        and vat_rate > 0
    )
    # VAT is charged on the taxable net plus the taxable share of the service
    # charge, so that is the base the printed rows have to add up to.
    exempt_service = (service * exempt / net_subtotal) if net_subtotal else 0.0
    vat_base = round2(net_subtotal + service - exempt_service)

    rows = [("subtotal", _money(net_subtotal))]
    if service > 0:
        rows.append(("other", f"{_money(service)} ({service_rate:g}%)"))
    if vat_applicable:
        rows.append(("taxable_amount", _money(vat_base)))
        if exempt > 0:
            rows.append(("exempt_amount", _money(exempt)))
        rows.append(("tax_rate", f"{vat_rate:g}%"))
        rows.append(("vat_amount", _money(bill.get("vat"))))
    else:
        rows.append(("taxable_amount", _money(taxable)))
        rows.append(("vat_amount", nepali.label("not_applicable", lang)))

    body = "".join(
        f'<tr><td class="k">{_label(key, language)}</td><td class="v">{value}</td></tr>'
        for key, value in rows
    )
    status_key = {
        "Paid": "paid", "Partially Paid": "partially_paid", "Unpaid": "unpaid",
    }.get(payment_status(bill.get("total") or 0, bill.get("paid") or 0), "unpaid")

    totals = f"""
<table class="totals">
  {body}
  <tr class="grand"><td class="k">{_label('grand_total', language)}</td>
      <td class="v">{symbol} {_money(bill.get('total'))}</td></tr>
  <tr class="settle"><td class="k">{_label('amount_paid', language)}</td>
      <td class="v">{_money(bill.get('paid'))}</td></tr>
  <tr class="settle"><td class="k">{_label('balance', language)}</td>
      <td class="v">{_money(bill.get('balance'))}</td></tr>
  <tr class="settle"><td class="k">{_label('payment_method', language)}</td>
      <td class="v">{_escape(bill.get('payment_method') or '—')}</td></tr>
  <tr class="settle"><td class="k">{_label('payment_status', language)}</td>
      <td class="v">{_escape(nepali.label(status_key, lang))}</td></tr>
</table>
"""

    comments = _comments(bill, language, settings)
    payable = (
        f'<div class="paynote">{_label("payable_to", language)} '
        f'{_escape(settings.get("hotel_name", "Arati Hotel"))}</div>'
    )
    return f"""
<table class="lower">
  <tr>
    <td class="lo-l">
      <div class="banner">{_label('other_comments', language)}</div>
      <div class="cmt">{comments}</div>
    </td>
    <td class="lo-r">
      {totals}
      {_words(bill, language)}
      {payable}
    </td>
  </tr>
</table>
"""


def _comments(bill: dict, language: str, settings: dict) -> str:
    """The numbered notes shown under the ``OTHER COMMENTS`` banner."""
    lang = "ne" if language == "ne" else "en"
    terms = _escape(bill.get("payment_terms") or settings.get("payment_terms", ""))
    notes = _escape(bill.get("notes") or "")
    policy = _escape(settings.get("return_policy", ""))

    entries = [part for part in (terms, notes, policy) if part]
    if not entries:
        entries = [
            "Total payment due upon checkout."
            if language == "en"
            else "चेकआउट समयमा भुक्तानी गर्नुपर्नेछ।",
            "Direct transfers accepted."
            if language == "en"
            else "बैंक ट्रान्सफर स्वीकार्य छ।",
        ]
    lines = "".join(f"<p>{index}. {entry}</p>" for index, entry in enumerate(entries, 1))
    return lines


def _words(bill: dict, language: str) -> str:
    total = float(bill.get("total") or 0)
    english = amount_in_words(total)
    nepal = nepali.amount_in_words(total)
    if language == "ne":
        primary, secondary = nepal, english
    else:
        primary, secondary = english, ""
    return (
        f'<div class="words"><span class="k">{_label("in_words", language)}</span> '
        f'<span class="v">{_escape(primary)}</span>'
        + (f' <span class="alt">{_escape(secondary)}</span>' if secondary else "")
        + "</div>"
    )


def _footer(settings: dict, bill: dict, language: str, options: dict | None = None) -> str:
    options = options or {}
    if not options.get("show_footer", True):
        return ""
    contact = ", ".join(
        part
        for part in (
            _escape(settings.get("hotel_name", "")),
            _escape(settings.get("hotel_phone", "")),
            _escape(settings.get("hotel_email", "")),
        )
        if part
    )
    sub = " · ".join(
        part
        for part in (
            f"{_label('prepared_by', language)}: {_escape(bill.get('prepared_by') or '')}"
            if bill.get("prepared_by")
            else "",
            f"{_label('received_by', language)}: {_escape(bill.get('received_by') or '')}"
            if bill.get("received_by")
            else "",
        )
        if part
    )
    return f"""
<div class="foot">
  <div class="f-contact">{_label('questions_contact', language)} {contact}</div>
  <div class="f-thanks">{_label('thank_you_business', language)}</div>
  {f'<div class="f-sub">{sub}</div>' if sub else ''}
</div>
"""


def build_html(
    bill: dict, lines: list, settings: dict, options: dict | None = None
) -> str:
    """Full invoice document as one HTML string.

    ``options`` carries the printer settings: page size, margins and the
    header/footer/logo/contact/tax visibility switches.
    """
    options = options or {}
    language = (bill.get("language") or settings.get("invoice_language") or "en").lower()
    if language not in nepali.LANGUAGES:
        language = "en"
    body = "".join(
        (
            _header(settings, bill, language, options),
            _party(bill, language),
            _items(bill, lines, language, settings),
            _summary(bill, language, settings, options),
            _footer(settings, bill, language, options),
        )
    )
    return (
        "<!DOCTYPE html><html lang="
        f'"{language}"><head><meta charset="utf-8">'
        f"<title>{_escape(bill.get('bill_no', 'Invoice'))}</title>"
        f"<style>{_style(options)}</style></head><body>{body}</body></html>"
    )


def build_a4_pdf(
    path: str | Path,
    bill: dict,
    lines: list,
    settings: dict,
    options: dict | None = None,
) -> Path:
    """Render the A4 invoice to ``path`` and return it."""
    from weasyprint import HTML

    settings = settings or {}
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    HTML(
        string=build_html(bill, lines, settings, options), base_url=str(path.parent)
    ).write_pdf(str(path))
    return path
