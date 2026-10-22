"""Print-ready A4 invoice (HTML → PDF through WeasyPrint).

Devanagari needs a shaping engine, which reportlab does not have, so the A4
invoice is laid out in HTML and rendered by WeasyPrint/Pango. All amounts come
from the stored bill, which was computed by :func:`arati.money.compute_totals`,
so preview, PDF and receipt always agree.
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


def _style() -> str:
    font_uri = FONT_FILE.as_uri() if FONT_FILE.exists() else ""
    face = (
        f"@font-face {{ font-family: 'AratiNepali'; src: url('{font_uri}'); }}"
        if font_uri
        else ""
    )
    return f"""
{face}
@page {{
  size: A4 portrait;
  margin: 12mm 12mm 14mm 12mm;
  @bottom-center {{
    content: "Page " counter(page) " of " counter(pages);
    font-size: 7pt; color: #555;
  }}
}}
* {{ box-sizing: border-box; }}
body {{
  font-family: 'AratiNepali', 'Noto Sans Devanagari', 'DejaVu Sans', sans-serif;
  font-size: 8.6pt; color: #000; margin: 0;
}}
.en {{ font-size: 0.78em; color: #444; display: block; font-weight: normal; }}
.cur {{ font-size: 0.72em; color: #444; display: block; font-weight: normal; }}
table {{ width: 100%; border-collapse: collapse; }}
td, th {{ vertical-align: top; }}
.head {{ border-bottom: 1.1pt solid #000; padding-bottom: 5px; }}
.brand {{ width: 62%; }}
.brand-name {{ font-size: 16pt; font-weight: 700; letter-spacing: 0.4px; }}
.brand-ne {{ font-size: 11pt; }}
.brand-line {{ font-size: 8pt; color: #111; margin-top: 1px; }}
.logo {{ max-height: 54px; max-width: 120px; margin-bottom: 4px; }}
.title-cell {{ width: 38%; text-align: right; }}
.doc-title {{
  display: inline-block; border: 1.2pt solid #000; padding: 5px 9px 6px;
  font-size: 12pt; font-weight: 700; letter-spacing: 0.8px;
}}
.doc-title .en {{ letter-spacing: 0.6px; font-size: 8.4pt; }}
.copy {{ font-size: 7.4pt; margin-top: 3px; color: #222; }}
.meta {{ margin-top: 6px; }}
.meta td {{ border: 0.6pt solid #000; padding: 3px 5px; width: 25%; }}
.meta .k {{ font-size: 6.8pt; color: #333; }}
.meta .v {{ font-size: 9pt; font-weight: 700; }}
.party {{ margin-top: 6px; }}
.party td {{ border: 0.6pt solid #000; padding: 4px 6px; }}
.party .who {{ width: 55%; }}
.party .k {{ font-size: 6.8pt; color: #333; }}
.party .v {{ font-size: 9pt; }}
.grid {{ margin-top: 8px; }}
.grid th {{
  border: 0.6pt solid #000; background: #f1f1f1; padding: 3px 3px;
  font-size: 7.2pt; text-align: center; line-height: 1.15;
}}
.grid td {{ border: 0.6pt solid #000; padding: 2.6px 3px; font-size: 7.6pt; }}
.grid .num {{ text-align: right; white-space: nowrap; }}
.grid .mid {{ text-align: center; }}
.grid tfoot td {{ font-weight: 700; background: #f7f7f7; }}
.desc {{ font-size: 7.8pt; }}
.desc .code {{ color: #333; font-size: 7pt; }}
.totals {{ margin-top: 6px; }}
.totals .box {{ width: 60%; margin-left: 40%; }}
.totals td {{ padding: 2.4px 5px; border-bottom: 0.5pt solid #999; }}
.totals .k {{ width: 62%; }}
.totals .v {{ text-align: right; white-space: nowrap; }}
.totals .grand td {{ border-top: 1pt solid #000; border-bottom: 1.1pt solid #000;
  font-size: 10.5pt; font-weight: 700; }}
.badge {{ font-size: 8pt; font-weight: 700; }}
.words {{ margin-top: 6px; border: 0.6pt solid #000; padding: 4px 6px; }}
.words .k {{ font-size: 6.8pt; color: #333; }}
.words .v {{ font-size: 9pt; font-weight: 700; }}
.words .alt {{ font-size: 7.6pt; color: #333; margin-top: 1px; }}
.foot {{ margin-top: 8px; }}
.foot .notes {{ font-size: 7.4pt; }}
.foot .notes p {{ margin: 1px 0; }}
.signs {{ margin-top: 12px; }}
.signs td {{ width: 25%; text-align: center; padding-top: 22px; font-size: 7.4pt; }}
.signs .line {{ border-top: 0.6pt solid #000; margin: 0 6px; padding-top: 2px; }}
.thanks {{ margin-top: 8px; text-align: center; font-size: 8pt; font-style: italic; }}
.small {{ font-size: 7pt; color: #333; }}
"""


def _header(settings: dict, bill: dict, language: str) -> str:
    logo = settings.get("logo_path") or ""
    logo_html = ""
    if logo and Path(logo).exists():
        logo_html = f'<div><img class="logo" src="{Path(logo).resolve().as_uri()}"></div>'

    name = _escape(settings.get("hotel_name", "Arati Hotel"))
    name_ne = _escape(settings.get("hotel_name_ne", ""))
    lines = [
        _escape(settings.get("hotel_address1", "")),
        _escape(settings.get("hotel_address2", "")),
    ]
    lang = "ne" if language == "ne" else "en"
    contact = " · ".join(
        part
        for part in (
            f"{nepali.label('phone', lang)}: {_escape(settings.get('hotel_phone', ''))}"
            if settings.get("hotel_phone") else "",
            _escape(settings.get("hotel_email", "")),
        )
        if part
    )
    pan = settings.get("hotel_pan") or ""
    vat_no = settings.get("hotel_vat") or ""
    ids = " · ".join(
        part
        for part in (
            f"PAN: {_escape(pan)}" if pan else "",
            f"VAT No.: {_escape(vat_no)}" if vat_no else "",
        )
        if part
    )
    website = _escape(settings.get("hotel_website", ""))

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
    copy_html = _escape(copy_text)

    brand_lines = "".join(
        f'<div class="brand-line">{line}</div>' for line in lines if line
    )
    return f"""
<table class="head">
  <tr>
    <td class="brand">
      {logo_html}
      <div class="brand-name">{name}</div>
      {f'<div class="brand-ne">{name_ne}</div>' if name_ne else ''}
      {brand_lines}
      <div class="brand-line">{contact}</div>
      {f'<div class="brand-line">{ids}</div>' if ids else ''}
      {f'<div class="brand-line">{website}</div>' if website else ''}
    </td>
    <td class="title-cell">
      <div class="doc-title">{title}</div>
      <div class="copy">{copy_html}</div>
    </td>
  </tr>
</table>
"""


def _meta(settings: dict, bill: dict, language: str) -> str:
    bs = nepali.to_bs(bill.get("bill_date"))
    bs_value = "—"
    if bs:
        bs_value = _escape(nepali.to_latin(bs[0]) if language == "en" else bs[1])
    date_format = settings.get("date_format") or "DD/MM/YYYY"
    cells = [
        (_label("invoice_no", language), _escape(bill.get("bill_no", ""))),
        (_label("date", language), _escape(format_date(bill.get("bill_date"), date_format))),
        (_label("bs_date", language), bs_value),
        (_label("payment_method", language), _escape(bill.get("payment_method", ""))),
    ]
    body = "".join(
        f'<td><div class="k">{key}</div><div class="v">{value}</div></td>'
        for key, value in cells
    )
    return f'<table class="meta"><tr>{body}</tr></table>'


def _party(bill: dict, language: str) -> str:
    name = _escape(bill.get("guest_name") or ("Walk-in guest" if language == "en" else "आगन्तुक ग्राहक"))
    address = _escape(bill.get("guest_address") or "—")
    phone = _escape(bill.get("guest_phone") or "—")
    pan = _escape(bill.get("guest_pan") or "—")
    ctype = "business" if (bill.get("customer_type") or "individual") == "business" else "individual"
    ctype_label = nepali.label(ctype, "ne" if language == "ne" else "en")

    right_rows = [
        (nepali.label("address", "ne" if language == "ne" else "en"), address),
        (nepali.label("phone", "ne" if language == "ne" else "en"), phone),
        (nepali.label("pan", "ne" if language == "ne" else "en"), pan),
        (nepali.label("customer_type", "ne" if language == "ne" else "en"), _escape(ctype_label)),
    ]
    if bill.get("room_no"):
        right_rows.append(
            (
                "Room / stay" if language == "en" else "कोठा / बसाइ",
                _escape(
                    f"{bill['room_no']} · {bill.get('check_in') or ''} → "
                    f"{bill.get('check_out') or ''} ({int(bill.get('nights') or 0)}N)"
                ),
            )
        )
    rows = "".join(
        f'<tr><td class="k">{key}</td><td class="v">{value}</td></tr>'
        for key, value in right_rows
    )
    who = nepali.label("customer", "ne" if language == "ne" else "en")
    return f"""
<table class="party">
  <tr>
    <td class="who">
      <div class="k">{who}</div>
      <div class="v"><strong>{name}</strong></div>
    </td>
    <td><table>{rows}</table></td>
  </tr>
</table>
"""


def _items(bill: dict, lines: list, language: str, settings: dict) -> str:
    rows = line_amounts(bill, lines)
    symbol = _currency(settings)
    heads = [
        ("sn", "4%"), ("description", "25%"), ("code", "8%"), ("unit", "6%"),
        ("qty", "7%"), ("rate", "9%"), ("discount", "8%"), ("taxable_amount", "10%"),
        ("vat_rate", "6%"), ("vat_amount", "7%"), ("total", "10%"),
    ]
    head_html = "".join(
        f'<th style="width:{width}">{_label(key, language)}'
        + (f'<span class="cur">{_escape(symbol)}</span>' if key in MONEY_COLUMNS else "")
        + "</th>"
        for key, width in heads
    )

    body = []
    for index, row in enumerate(rows, start=1):
        line = row["line"]
        code = _escape(line.get("code") or "—")
        body.append(
            f"""<tr>
  <td class="mid">{index}</td>
  <td class="desc">{_escape(line.get('description', ''))}</td>
  <td class="mid code">{code}</td>
  <td class="mid">{_escape(line.get('unit') or '')}</td>
  <td class="num">{float(line.get('qty') or 0):g}</td>
  <td class="num">{_money(line.get('unit_price'))}</td>
  <td class="num">{_money(row['discount'])}</td>
  <td class="num">{_money(row['taxable_net'])}</td>
  <td class="num">{f"{row['vat_rate']:g}" if row['vat'] else '—'}</td>
  <td class="num">{_money(row['vat'])}</td>
  <td class="num">{_money(row['total'])}</td>
</tr>"""
        )
    if not body:
        body.append(
            '<tr><td class="mid" colspan="11">'
            + ("कुनै विवरण छैन" if language == "ne" else "No items")
            + "</td></tr>"
        )

    total_taxable = sum((row["taxable_net"] for row in rows), Decimal("0.00"))
    total_vat = sum((row["vat"] for row in rows), Decimal("0.00"))
    total_discount = sum((row["discount"] for row in rows), Decimal("0.00"))
    total_all = sum((row["total"] for row in rows), Decimal("0.00"))
    label_key = "total" if language == "en" else "total"
    foot = f"""<tr>
  <td colspan="6">{_label(label_key, language)}</td>
  <td class="num">{_money(total_discount)}</td>
  <td class="num">{_money(total_taxable)}</td>
  <td></td>
  <td class="num">{_money(total_vat)}</td>
  <td class="num">{_money(total_all)}</td>
</tr>"""
    return f"""
<table class="grid">
  <thead><tr>{head_html}</tr></thead>
  <tbody>{''.join(body)}</tbody>
  <tfoot>{foot}</tfoot>
</table>
"""


def _summary(bill: dict, language: str, settings: dict) -> str:
    lang = "ne" if language == "ne" else "en"
    symbol = _currency(settings)
    vat_applicable = (bill.get("bill_type") or "tax") == "tax" and float(bill.get("vat_rate") or 0) > 0
    net_subtotal = float(bill.get("net_subtotal") or 0)
    taxable = float(bill.get("taxable_net") or 0)
    exempt = round2(max(0.0, net_subtotal - taxable))
    item_discount = float(bill.get("item_discount") or 0)
    overall_discount = float(bill.get("discount") or 0)

    rows = [("subtotal", _money(bill.get("subtotal")))]
    if item_discount > 0:
        rows.append(("item_discount", f"− {_money(item_discount)}"))
    if overall_discount > 0:
        rows.append(("discount", f"− {_money(overall_discount)}"))
    if vat_applicable:
        if exempt > 0:
            rows.append(("taxable_amount", _money(taxable)))
            rows.append(("exempt_amount", _money(exempt)))
        rows.append(
            (
                "service_charge",
                f"{_money(bill.get('service_charge'))} "
                f"({float(bill.get('service_charge_rate') or 0):g}%)",
            )
        )
        rows.append(
            ("vat_amount", f"{_money(bill.get('vat'))} ({float(bill.get('vat_rate') or 0):g}%)")
        )
    else:
        rows.append(("service_charge", _money(bill.get("service_charge"))))
        rows.append(("vat_amount", nepali.label("not_applicable", lang)))

    body = "".join(
        f'<tr><td class="k">{_label(key, language)}</td><td class="v">{value}</td></tr>'
        for key, value in rows
    )
    status_key = {
        "Paid": "paid", "Partially Paid": "partially_paid", "Unpaid": "unpaid",
    }.get(payment_status(bill.get("total") or 0, bill.get("paid") or 0), "unpaid")

    return f"""
<table class="totals"><tr><td>
  <table class="box">
    {body}
    <tr class="grand"><td class="k">{_label('grand_total', language)}</td>
        <td class="v">{symbol} {_money(bill.get('total'))}</td></tr>
    <tr><td class="k">{_label('amount_paid', language)}</td>
        <td class="v">{_money(bill.get('paid'))}</td></tr>
    <tr><td class="k">{_label('balance', language)}</td>
        <td class="v">{_money(bill.get('balance'))}</td></tr>
    <tr><td class="k">{_label('payment_method', language)}</td>
        <td class="v">{_escape(bill.get('payment_method') or '—')}</td></tr>
    <tr><td class="k">{_label('payment_status', language)}</td>
        <td class="v badge">{_label(status_key, language)}</td></tr>
  </table>
</td></tr></table>
"""


def _words(bill: dict, language: str) -> str:
    total = float(bill.get("total") or 0)
    english = amount_in_words(total)
    nepal = nepali.amount_in_words(total)
    if language == "ne":
        primary, secondary = nepal, english
    else:
        primary, secondary = english, ""
    return f"""
<table class="words"><tr><td>
  <div class="k">{_label('in_words', language)}</div>
  <div class="v">{_escape(primary)}</div>
  {f'<div class="alt">{_escape(secondary)}</div>' if secondary else ''}
</td></tr></table>
"""


def _footer(settings: dict, bill: dict, language: str) -> str:
    terms = _escape(bill.get("payment_terms") or settings.get("payment_terms", ""))
    notes = _escape(bill.get("notes") or "")
    policy = _escape(settings.get("return_policy", ""))
    note_html = "".join(
        f"<p>{part}</p>"
        for part in (
            f"<strong>{nepali.label('payment_terms', 'ne' if language == 'ne' else 'en')}:</strong> {terms}"
            if terms else "",
            f"<strong>{nepali.label('notes', 'ne' if language == 'ne' else 'en')}:</strong> {notes}"
            if notes else "",
            policy,
        )
        if part
    )
    prepared = _escape(bill.get("prepared_by") or "")
    received = _escape(bill.get("received_by") or "")
    return f"""
<div class="foot">
  <div class="notes">{note_html}</div>
  <table class="signs"><tr>
    <td><div class="line">{_label('prepared_by', language)}
        {f'<div class="small">{prepared}</div>' if prepared else ''}</div></td>
    <td><div class="line">{_label('received_by', language)}
        {f'<div class="small">{received}</div>' if received else ''}</div></td>
    <td><div class="line">{_label('customer_signature', language)}</div></td>
    <td><div class="line">{_label('authorized_signature', language)}</div></td>
  </tr></table>
  <div class="thanks">{_label('thank_you', language)}</div>
</div>
"""


def build_html(bill: dict, lines: list, settings: dict) -> str:
    """Full invoice document as one HTML string."""
    language = (bill.get("language") or settings.get("invoice_language") or "en").lower()
    if language not in nepali.LANGUAGES:
        language = "en"
    body = "".join(
        (
            _header(settings, bill, language),
            _meta(settings, bill, language),
            _party(bill, language),
            _items(bill, lines, language, settings),
            _summary(bill, language, settings),
            _words(bill, language),
            _footer(settings, bill, language),
        )
    )
    return (
        "<!DOCTYPE html><html lang="
        f'"{language}"><head><meta charset="utf-8">'
        f"<title>{_escape(bill.get('bill_no', 'Invoice'))}</title>"
        f"<style>{_style()}</style></head><body>{body}</body></html>"
    )


def build_a4_pdf(path: str | Path, bill: dict, lines: list, settings: dict) -> Path:
    """Render the A4 invoice to ``path`` and return it."""
    from weasyprint import HTML

    settings = settings or {}
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    HTML(string=build_html(bill, lines, settings), base_url=str(path.parent)).write_pdf(
        str(path)
    )
    return path
