"""Printable PDF for any report produced by :mod:`arati.reports`.

The document is laid out in HTML and rendered by WeasyPrint, so long tables
repeat their header on every page, page numbers are automatic, and the
font handles Devanagari. Zero values print as ``0.00`` rather than blank,
negative amounts keep their sign, and a report with no rows says so
explicitly instead of showing an empty page.
"""

from __future__ import annotations

from html import escape
from pathlib import Path

from .reports import Report


def _money(value) -> str:
    try:
        number = float(value or 0)
    except (TypeError, ValueError):
        return "0.00"
    return f"{number:,.2f}"


def _cell(value) -> str:
    if isinstance(value, float):
        return _money(value)
    if isinstance(value, int):
        return str(value)
    return escape(str(value if value is not None else ""))


def _style() -> str:
    return """
@page {
  size: A4 portrait;
  margin: 14mm 12mm 16mm 12mm;
  @bottom-center {
    content: "Page " counter(page) " of " counter(pages);
    font-size: 7.5pt; color: #555;
  }
}
* { box-sizing: border-box; }
body {
  font-family: 'AratiNepali', 'Noto Sans Devanagari', 'DejaVu Sans', sans-serif;
  font-size: 9pt; color: #1b1b1b; margin: 0;
}
.head { border-bottom: 1.2pt solid #7A1F2B; padding-bottom: 8px; margin-bottom: 10px; }
.hotel { font-size: 15pt; font-weight: 700; color: #7A1F2B; }
.sub { font-size: 8pt; color: #555; margin-top: 2px; }
.title { font-size: 13pt; font-weight: 700; margin-top: 8px; }
.meta { font-size: 8pt; color: #444; margin-top: 2px; }
table { width: 100%; border-collapse: collapse; margin-top: 8px; }
thead { display: table-header-group; }
tr { page-break-inside: avoid; }
th {
  border: 0.5pt solid #999; background: #f1ece3; padding: 4px 5px;
  font-size: 7.6pt; text-align: left; vertical-align: bottom;
}
td { border: 0.5pt solid #bbb; padding: 3px 5px; font-size: 8.2pt; }
td.num, th.num { text-align: right; white-space: nowrap; }
tfoot td { font-weight: 700; background: #f7f4ee; }
.empty { margin-top: 14px; padding: 12px; border: 0.6pt dashed #999; color: #555; }
.formulas { margin-top: 12px; font-size: 7.6pt; color: #444; }
.formulas li { margin-bottom: 2px; }
.foot { margin-top: 14px; font-size: 7.4pt; color: #666; border-top: 0.5pt solid #ccc;
        padding-top: 6px; }
"""


def build_report_html(report: Report, settings: dict, title: str | None = None) -> str:
    """Render a report as a printable HTML document."""
    hotel = escape(settings.get("hotel_name", "Arati Hotel"))
    address = " · ".join(
        part
        for part in (
            settings.get("hotel_address1", ""),
            settings.get("hotel_address2", ""),
            settings.get("hotel_phone", ""),
        )
        if part
    )
    heading = escape(title or report.title)

    head_cells = []
    body_cells = []
    for key, label, _width in report.columns:
        numeric = any(
            isinstance(row.get(key), (int, float)) for row in report.rows
        )
        cls = ' class="num"' if numeric else ""
        head_cells.append(f"<th{cls}>{escape(label)}</th>")
        for row in report.rows:
            body_cells.append((key, cls))

    rows_html = []
    for row in report.rows:
        cells = "".join(
            f"<td{cls}>{_cell(row.get(key))}</td>" for key, cls in body_cells
        )
        rows_html.append(f"<tr>{cells}</tr>")

    foot_cells = ""
    if report.totals:
        pieces = []
        for key, label, _width in report.columns:
            if key in report.totals:
                value = report.totals[key]
                if isinstance(value, float):
                    pieces.append(f"<td class='num'>{_money(value)}</td>")
                elif isinstance(value, int):
                    pieces.append(f"<td class='num'>{value}</td>")
                else:
                    pieces.append(f"<td>{_cell(value)}</td>")
            else:
                pieces.append("<td></td>")
        foot_cells = f"<tfoot><tr>{''.join(pieces)}</tr></tfoot>"

    if report.rows:
        table = (
            "<table><thead><tr>"
            + "".join(head_cells)
            + "</tr></thead><tbody>"
            + "".join(rows_html)
            + "</tbody>"
            + foot_cells
            + "</table>"
        )
    else:
        table = f'<div class="empty">{escape(report.empty_message)}</div>'

    formulas = ""
    if report.formulas:
        items = "".join(f"<li>{escape(formula)}</li>" for formula in report.formulas)
        formulas = f'<div class="formulas"><b>How these figures are calculated</b><ul>{items}</ul></div>'

    footer = (
        f"Report generated {escape(report.generated_at)} · "
        f"{escape(report.period)} · {escape(settings.get('hotel_name', ''))}"
    )

    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>{heading}</title>
<style>{_style()}</style></head>
<body>
<div class="head">
  <div class="hotel">{hotel}</div>
  <div class="sub">{escape(address)}</div>
  <div class="title">{heading}</div>
  <div class="meta">{escape(report.subtitle)}</div>
  <div class="meta">Period: {escape(report.period)}</div>
  <div class="meta">Generated: {escape(report.generated_at)}</div>
</div>
{table}
{formulas}
<div class="foot">{footer}</div>
</body></html>
"""


def build_report_pdf(
    path: str | Path, report: Report, settings: dict, title: str | None = None
) -> Path:
    """Render a report to PDF and return the path."""
    from weasyprint import HTML

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    html = build_report_html(report, settings, title)
    HTML(string=html, base_url=str(path.parent)).write_pdf(str(path))
    return path
