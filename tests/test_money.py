import pytest

from arati.money import Line, compute_totals, discount_from_input, round2, stay_nights


def test_service_charge_then_vat():
    lines = [Line("Room", 2, 4500.0)]
    totals = compute_totals(lines, service_charge_rate=10, vat_rate=13)

    assert totals.subtotal == 9000.00
    assert totals.service_charge == 900.00
    assert totals.vat == 1287.00          # 13% of (9000 + 900)
    assert totals.total == 11187.00
    assert totals.balance == 11187.00


def test_discount_reduces_taxable_base():
    lines = [Line("Dinner", 1, 1000.0)]
    totals = compute_totals(lines, discount=100.0, service_charge_rate=10, vat_rate=13)

    assert totals.net_subtotal == 900.00
    assert totals.service_charge == 90.00
    assert totals.vat == 128.70           # 13% of 990
    assert totals.total == 1118.70


def test_percent_discount_is_capped_at_subtotal():
    assert discount_from_input(1000.0, "percent", 25) == 250.00
    assert discount_from_input(1000.0, "percent", 150) == 1000.00
    assert discount_from_input(1000.0, "amount", 5000) == 1000.00
    assert discount_from_input(1000.0, "amount", -50) == 0.0


def test_non_taxable_lines_excluded_from_vat():
    lines = [Line("Room", 1, 1000.0), Line("Airport transfer", 1, 1000.0, taxable=False)]
    totals = compute_totals(lines, service_charge_rate=10, vat_rate=13)

    # Half the bill is taxable, so half of the service charge enters the VAT base.
    assert totals.service_charge == 200.00
    assert totals.vat == 143.00           # 13% of (1000 + 100)
    assert totals.total == 2343.00


def test_partial_payment_balance():
    lines = [Line("Lunch", 2, 500.0)]
    totals = compute_totals(lines, service_charge_rate=10, vat_rate=13, paid=600)
    assert totals.total == 1243.00
    assert totals.balance == 643.00
    assert totals.paid == 600.00


def test_overpayment_is_clamped():
    totals = compute_totals([Line("Tea", 1, 100.0)], paid=9999)
    assert totals.balance == 0.0
    assert totals.paid == totals.total


def test_rounding_avoids_float_drift():
    assert round2(1.005) == 1.01
    assert round2(2.675) == 2.68
    totals = compute_totals([Line("Item", 3, 333.33)], vat_rate=13, service_charge_rate=10)
    assert totals.total == round2(totals.net_subtotal + totals.service_charge + totals.vat)


def test_stay_nights():
    assert stay_nights("2026-10-20", "2026-10-23") == 3
    assert stay_nights("2026-10-20", "2026-10-20") == 1
    with pytest.raises(ValueError):
        stay_nights("2026-10-23", "2026-10-20")


def test_empty_bill_has_zero_totals():
    totals = compute_totals([])
    assert totals.total == 0
    assert totals.vat == 0


# --------------------------------------------------------------------------- #
# Tax invoice vs bill of supply, words and status
# --------------------------------------------------------------------------- #
from arati.money import amount_in_words, integer_to_words, payment_status


def test_bill_of_supply_charges_no_vat():
    lines = [Line("Dinner", 1, 1000.0)]
    totals = compute_totals(lines, service_charge_rate=10, vat_rate=13, bill_type="supply")

    assert totals.vat == 0
    assert totals.vat_applicable is False
    assert totals.service_charge == 100.00          # charges still apply
    assert totals.total == 1100.00
    assert totals.as_dict()["bill_type"] == "supply"


def test_tax_invoice_keeps_vat():
    totals = compute_totals([Line("Dinner", 1, 1000.0)], bill_type="tax")
    assert totals.vat_applicable is True
    assert totals.vat == 143.00
    assert totals.total == 1243.00


def test_unknown_bill_type_is_rejected():
    with pytest.raises(ValueError):
        compute_totals([Line("x", 1, 10)], bill_type="proforma")


def test_payment_status_labels():
    assert payment_status(1000, 1000) == "Paid"
    assert payment_status(1000, 0) == "Unpaid"
    assert payment_status(1000, 250) == "Partially Paid"
    assert payment_status(0, 0) == "Paid"


def test_amount_in_words():
    assert amount_in_words(0) == "Nepalese Rupees Zero Only"
    assert amount_in_words(5000) == "Nepalese Rupees Five Thousand Only"
    assert amount_in_words(11164.63) == (
        "Nepalese Rupees Eleven Thousand One Hundred Sixty-Four and Paisa Sixty-Three Only"
    )
    assert integer_to_words(1234567) == (
        "Twelve Lakh Thirty-Four Thousand Five Hundred Sixty-Seven"
    )
    assert amount_in_words(12345678) == "Nepalese Rupees One Crore Twenty-Three Lakh Forty-Five Thousand Six Hundred Seventy-Eight Only"
