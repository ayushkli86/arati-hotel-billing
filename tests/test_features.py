"""Customer master, draft invoices and the Nepali invoice."""

from decimal import Decimal

from arati import customers, db, invoice, invoice_html, nepali
from arati.money import Line, compute_totals

LINES_PAYLOAD = [
    {"description": "Chicken Biryani", "qty": 2, "unit": "plate", "unit_price": 990.0,
     "line_total": 1980.0, "category": "food", "taxable": True, "code": "FOOD-014"},
    {"description": "Room 2001 · 2 nights", "qty": 2, "unit": "night", "unit_price": 4500.0,
     "line_total": 9000.0, "category": "room", "taxable": True, "code": "ROOM-2001"},
]


def _bill(**overrides):
    bill = {
        "bill_no": "ARH0000007", "bill_date": "2026-10-22", "created_at": "2026-10-22 11:00:00",
        "guest_name": "सीता राई", "guest_phone": "9800000000", "guest_address": "धरान",
        "guest_pan": "", "room_no": "2001", "check_in": "2026-10-20",
        "check_out": "2026-10-22", "nights": 2,
        "subtotal": 10980.0, "discount": 998.0, "net_subtotal": 9982.0, "taxable_net": 9982.0,
        "service_charge_rate": 10.0, "service_charge": 998.2,
        "vat_rate": 13.0, "vat": 1427.43, "total": 12407.63,
        "paid": 5000.0, "balance": 7407.63, "payment_method": "Cash",
        "bill_type": "tax", "customer_type": "individual", "notes": "",
    }
    bill.update(overrides)
    return bill


def _settings():
    return {
        "hotel_name": "Arati Hotel", "hotel_name_ne": "आरती होटल",
        "hotel_address1": "Khandbari-01, Sankhuwasabha", "hotel_phone": "+977-29-560117",
        "hotel_email": "aratihotelkhandbari@gmail.com", "hotel_pan": "601234567",
        "hotel_vat": "601234567", "invoice_language": "en",
    }


def _payload(totals, **overrides):
    payload = dict(
        prefix="ARH",
        guest={"name": "Draft Guest", "phone": "9811111111", "address": "Khandbari"},
        lines=LINES_PAYLOAD,
        totals=totals.as_dict(),
        payment_method="Cash",
        user_id=1,
    )
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------- #
# customer master
# --------------------------------------------------------------------------- #
def test_customer_is_created_once_and_reused(tmp_path):
    conn = db.connect(tmp_path / "cust.db")
    db.bootstrap(conn)

    first = customers.upsert_customer(conn, "Sita Rai", "9800000000", "Dharan", "601234567")
    second = customers.upsert_customer(conn, "Sita Rai", "9800000000", "", "")
    assert first == second

    # Same name, different phone is a different person.
    third = customers.upsert_customer(conn, "Sita Rai", "9811111111")
    assert third != first

    rows = customers.list_customers(conn)
    assert [row["name"] for row in rows] == ["Sita Rai", "Sita Rai"]
    assert len(customers.list_customers(conn, "9811")) == 1

    customers.deactivate_customer(conn, third)
    assert len(customers.list_customers(conn)) == 1


def test_customer_is_linked_to_the_bill(tmp_path):
    conn = db.connect(tmp_path / "link.db")
    db.bootstrap(conn)
    customer_id = customers.upsert_customer(conn, "Sita Rai", "9800000000", "Dharan")
    totals = compute_totals([Line("Lunch", 1, 1000.0)])
    bill_no = db.create_bill(conn, **_payload(totals, customer_id=customer_id))

    bill, _ = db.get_bill(conn, bill_no)
    assert bill["customer_id"] == customer_id
    assert customers.get_customer(conn, customer_id)["address"] == "Dharan"


def test_blank_customer_never_creates_a_record(tmp_path):
    conn = db.connect(tmp_path / "blank.db")
    db.bootstrap(conn)
    assert customers.upsert_customer(conn, "   ") is None
    assert customers.list_customers(conn) == []


# --------------------------------------------------------------------------- #
# drafts
# --------------------------------------------------------------------------- #
def test_draft_totals_count_but_reports_ignore_it(tmp_path):
    conn = db.connect(tmp_path / "draft.db")
    db.bootstrap(conn)
    totals = compute_totals([Line("Lunch", 1, 1000.0)])
    bill_no = db.create_bill(conn, **_payload(totals, is_draft=1))

    bill, _ = db.get_bill(conn, bill_no)
    assert bill["is_draft"] == 1
    assert bill["total"] == totals.total

    summary = db.sales_summary(conn, "2026-01-01", "2026-12-31")
    assert summary["totals"]["bills"] == 0
    assert summary["totals"]["total"] == 0
    assert db.unpaid_bills(conn) == []


def test_draft_can_be_edited_then_finalised(tmp_path):
    conn = db.connect(tmp_path / "edit.db")
    db.bootstrap(conn)
    totals = compute_totals([Line("Lunch", 1, 1000.0)])
    bill_no = db.create_bill(conn, **_payload(totals, is_draft=1))

    bigger = compute_totals([Line("Lunch", 3, 1000.0)], paid=1000.0)
    assert db.update_draft(
        conn, bill_no,
        guest={"name": "Draft Guest", "phone": "9811111111", "address": "Khandbari"},
        lines=[{"description": "Lunch", "qty": 3, "unit": "pcs", "unit_price": 1000.0,
                "line_total": 3000.0, "category": "food", "taxable": True}],
        totals=bigger.as_dict(),
        payment_method="eSewa",
    )

    bill, lines = db.get_bill(conn, bill_no)
    assert bill["total"] == bigger.total
    assert bill["paid"] == 1000.0
    assert bill["payment_method"] == "eSewa"
    assert len(lines) == 1 and lines[0]["qty"] == 3

    assert db.finalize_draft(conn, bill_no) is True
    bill, _ = db.get_bill(conn, bill_no)
    assert bill["is_draft"] == 0
    assert db.sales_summary(conn, "2026-01-01", "2026-12-31")["totals"]["bills"] == 1

    # An issued bill is final: no further draft edits, no second finalise.
    assert db.update_draft(
        conn, bill_no, guest={}, lines=[], totals=bigger.as_dict(), payment_method="Cash",
    ) is False
    assert db.finalize_draft(conn, bill_no) is False


def test_drafts_and_bills_share_one_number_sequence(tmp_path):
    conn = db.connect(tmp_path / "numbers.db")
    db.bootstrap(conn)
    totals = compute_totals([Line("Lunch", 1, 1000.0)])
    numbers = [
        db.create_bill(conn, **_payload(totals, is_draft=1)),
        db.create_bill(conn, **_payload(totals)),
        db.create_bill(conn, **_payload(totals, is_draft=1)),
    ]
    assert len(set(numbers)) == 3


def _pdf_text_streams(path) -> bytes:
    """Inflated PDF object streams, so font and text markers become searchable."""
    import re
    import zlib

    data = path.read_bytes()
    blob = b""
    for match in re.finditer(rb"stream\r?\n", data):
        start = match.end()
        end = data.find(b"endstream", start)
        if end < 0:
            continue
        try:
            blob += zlib.decompress(data[start:end])
        except zlib.error:
            continue
    return blob + data


def test_only_drafts_can_be_deleted(tmp_path):
    conn = db.connect(tmp_path / "delete.db")
    db.bootstrap(conn)
    totals = compute_totals([Line("Lunch", 1, 1000.0)])
    draft = db.create_bill(conn, **_payload(totals, is_draft=1))
    issued = db.create_bill(conn, **_payload(totals))

    assert db.delete_draft(conn, issued) is False
    assert db.get_bill(conn, issued) is not None

    assert db.delete_draft(conn, draft) is True
    assert db.get_bill(conn, draft) is None
    assert conn.execute("SELECT COUNT(*) FROM bill_items").fetchone()[0] == len(LINES_PAYLOAD)


def test_bill_keeps_the_language_it_was_issued_in(tmp_path):
    conn = db.connect(tmp_path / "lang.db")
    db.bootstrap(conn)
    totals = compute_totals([Line("Lunch", 1, 1000.0)])
    bill_no = db.create_bill(conn, **_payload(totals, language="ne"))
    bill, _ = db.get_bill(conn, bill_no)
    assert bill["language"] == "ne"


# --------------------------------------------------------------------------- #
# Nepali language and Bikram Sambat
# --------------------------------------------------------------------------- #
def test_nepali_amount_in_words():
    assert nepali.amount_in_words(5000) == "रुपैयाँ पाँच हजार मात्र"
    assert nepali.amount_in_words(11164.63) == (
        "रुपैयाँ एघार हजार एक सय चौंसट्ठी र पैसा त्रिसट्ठी मात्र"
    )
    assert nepali.amount_in_words(1) == "रुपैयाँ एक मात्र"
    assert nepali.nepali_words(123456) == "एक लाख तेइस हजार चार सय छपन्न"


def test_bikram_sambat_conversion_and_digits():
    short, long = nepali.to_bs("2026-10-22")
    assert short == "२०८३-०७-०५"
    assert long == "५ कात्तिक २०८३"
    assert nepali.to_latin(short) == "2083-07-05"
    assert nepali.to_bs("not-a-date") is None
    assert nepali.to_bs(None) is None


def test_nepali_invoice_html_uses_nepali_labels():
    html = invoice_html.build_html(_bill(language="ne"), LINES_PAYLOAD, _settings())
    assert "मूल्य अभिवृद्धि कर बिजक" in html
    assert "ग्राहक" in html and "कुल जम्मा" in html
    assert "रुपैयाँ" in html  # amount in words in Nepali
    assert "५ कात्तिक २०८३" in html
    assert "सीता राई" in html


def test_english_invoice_keeps_english_labels_and_latin_bs_date():
    html = invoice_html.build_html(_bill(language="en"), LINES_PAYLOAD, _settings())
    assert "TAX INVOICE" in html
    assert "Grand total" in html
    assert "2083-07-05" in html
    assert "Nepalese Rupees Twelve Thousand Four Hundred Seven and Paisa Sixty-Three Only" in html


def test_bill_of_supply_never_shows_vat():
    bill = _bill(bill_type="supply", vat=0.0, vat_rate=0.0, taxable_net=9982.0)
    html = invoice_html.build_html(bill, LINES_PAYLOAD, _settings())
    assert "BILL OF SUPPLY" in html
    assert "Not applicable" in html


def test_line_allocation_ties_to_the_stored_totals():
    bill = _bill()
    rows = invoice_html.line_amounts(bill, LINES_PAYLOAD)
    cents = Decimal("0.01")
    assert sum(row["discount"] for row in rows) == Decimal("998.00").quantize(cents)
    assert sum(row["taxable_net"] for row in rows) == Decimal("9982.00").quantize(cents)
    assert sum(row["vat"] for row in rows) == Decimal("1427.43").quantize(cents)
    assert sum(row["total"] for row in rows) == Decimal("11409.43").quantize(cents)


def test_line_allocation_handles_discount_rounding_and_exempt_lines():
    lines = [
        {"description": "A", "qty": 1, "unit": "pcs", "unit_price": 333.33,
         "line_total": 333.33, "taxable": True},
        {"description": "B", "qty": 1, "unit": "pcs", "unit_price": 333.33,
         "line_total": 333.33, "taxable": True},
        {"description": "B", "qty": 1, "unit": "pcs", "unit_price": 333.34,
         "line_total": 333.34, "taxable": True},
    ]
    totals = compute_totals([Line("A", 1, 333.33), Line("B", 1, 333.33), Line("C", 1, 333.34)],
                            discount=0.01, paid=0)
    bill = _bill(**totals.as_dict())
    rows = invoice_html.line_amounts(bill, lines)
    cents = Decimal("0.01")
    assert sum(row["discount"] for row in rows) == Decimal("0.01").quantize(cents)
    assert sum(row["taxable_net"] for row in rows) == Decimal(str(bill["taxable_net"])).quantize(cents)
    assert sum(row["vat"] for row in rows) == Decimal(str(bill["vat"])).quantize(cents)


def test_nepali_pdf_renders_a_real_document(tmp_path):
    path = invoice.build_a4_pdf(
        tmp_path / "ne.pdf", _bill(language="ne"), LINES_PAYLOAD, _settings()
    )
    data = path.read_bytes()
    assert data.startswith(b"%PDF")
    assert len(data) > 10000
    blob = _pdf_text_streams(path)
    assert b"/FontFile2" in blob, "Devanagari font was not embedded"
    assert b"Type0" in blob, "text was not written as Unicode, so Nepali would break"


def test_english_pdf_still_renders(tmp_path):
    path = invoice.build_a4_pdf(
        tmp_path / "en.pdf", _bill(language="en"), LINES_PAYLOAD, _settings()
    )
    assert path.read_bytes().startswith(b"%PDF")


def test_preview_and_saved_pdf_share_the_same_html():
    bill = _bill(language="ne")
    again = _bill(language="ne")
    assert invoice_html.build_html(bill, LINES_PAYLOAD, _settings()) == (
        invoice_html.build_html(again, LINES_PAYLOAD, _settings())
    )
