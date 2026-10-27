"""Invoice arithmetic for Arati Hotel.

A hotel bill is issued as a **Tax Invoice** (service charge + 13% VAT) or a
**Bill of Supply** (no VAT). Amounts are computed with :class:`decimal.Decimal`
internally and rounded half-up to paisa, then handed back as floats so the rest
of the app keeps its simple API. One function feeds the entry form, the saved
bill and the PDF, so the three can never disagree.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

CENT = Decimal("0.01")
ZERO = Decimal("0.00")
RATE = Decimal("100")

ONES = (
    "Zero", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine",
    "Ten", "Eleven", "Twelve", "Thirteen", "Fourteen", "Fifteen", "Sixteen",
    "Seventeen", "Eighteen", "Nineteen",
)
TENS = ("", "", "Twenty", "Thirty", "Forty", "Fifty", "Sixty", "Seventy", "Eighty", "Ninety")

BILL_TYPES = ("tax", "supply")
BILL_TYPE_LABELS = {"tax": "Tax Invoice", "supply": "Bill of Supply"}
CUSTOMER_TYPES = ("individual", "business")


def _dec(value) -> Decimal:
    """Decimal from any numeric input, via str so 0.1 stays 0.1."""
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value if value is not None else 0))


def _cents(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)



def to_paisa(value) -> int:
    """Rupees -> integer paisa. The storage unit for ledger amounts.

    Every rupee amount that has to survive a round trip through the database
    is stored as an integer number of paisa, so 0.1 + 0.2 problems cannot
    creep into a report.
    """
    return int((_dec(value) * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))



@dataclass(frozen=True)
class Line:
    """One invoice line.

    ``taxable`` excludes the line from the VAT base. ``discount`` is the
    discount applied to this line in rupees; it is capped at the line total.
    """

    description: str
    qty: float
    unit_price: float
    taxable: bool = True
    category: str = "food"
    item_id: int | None = None
    unit: str = "pcs"
    code: str = ""
    discount: float = 0.0

    @property
    def total(self) -> float:
        return float(_cents(_dec(self.qty) * _dec(self.unit_price)))

    @property
    def net(self) -> float:
        """Line total after this line's own discount."""
        return float(_cents(max(ZERO, _dec(self.total) - _dec(self.discount))))


@dataclass(frozen=True)
class Totals:
    subtotal: float
    discount: float
    net_subtotal: float
    taxable_net: float
    service_charge: float
    service_charge_rate: float
    vat: float
    vat_rate: float
    total: float
    paid: float = 0.0
    balance: float = 0.0
    vat_applicable: bool = True
    bill_type: str = "tax"
    item_discount: float = 0.0

    @property
    def status(self) -> str:
        return payment_status(self.total, self.paid)

    def as_dict(self) -> dict:
        return {
            "subtotal": self.subtotal,
            "discount": self.discount,
            "item_discount": self.item_discount,
            "net_subtotal": self.net_subtotal,
            "taxable_net": self.taxable_net,
            "service_charge": self.service_charge,
            "service_charge_rate": self.service_charge_rate,
            "vat": self.vat,
            "vat_rate": self.vat_rate,
            "total": self.total,
            "paid": self.paid,
            "balance": self.balance,
            "bill_type": self.bill_type,
        }


def payment_status(total: float, paid: float) -> str:
    """Paid / Partially Paid / Unpaid, from the settled amount."""
    total_d, paid_d = _dec(total), _dec(paid)
    if total_d <= ZERO or paid_d >= total_d - CENT / 2:
        return "Paid"
    if paid_d <= CENT / 2:
        return "Unpaid"
    return "Partially Paid"


def discount_from_input(subtotal: float, kind: str, value: float) -> float:
    """Turn a user discount entry ("amount" or "percent") into a rupee amount."""
    value_d = max(ZERO, _dec(value))
    if kind == "percent":
        value_d = _dec(subtotal) * min(value_d, RATE) / RATE
    return float(_cents(min(value_d, _dec(subtotal))))


def compute_totals(
    lines: Iterable[Line],
    discount: float = 0.0,
    service_charge_rate: float = 10.0,
    vat_rate: float = 13.0,
    paid: float = 0.0,
    bill_type: str = "tax",
) -> Totals:
    """Compute a bill.

    Rates are percentages (10 == 10%). ``discount`` is the overall discount in
    rupees, already capped by :func:`discount_from_input`; each line may also
    carry its own discount, which is applied first. A ``supply`` bill never
    charges VAT.

    Order of operations, so nothing is counted twice::

        subtotal   = Σ line totals
        item disc. = Σ line discounts
        net        = subtotal − item discount − overall discount
        service    = net × service_charge_rate
        VAT        = (taxable net + taxable share of service) × vat_rate
        total      = net + service + VAT
    """
    if bill_type not in BILL_TYPES:
        raise ValueError(f"Unknown bill type: {bill_type}")

    lines = list(lines)
    subtotal = _cents(sum((_dec(line.total) for line in lines), ZERO))

    line_nets = [
        _cents(max(ZERO, _dec(line.total) - _dec(line.discount))) for line in lines
    ]
    item_discount = _cents(subtotal - sum(line_nets, ZERO))
    after_item = _cents(subtotal - item_discount)

    discount_d = _cents(min(max(ZERO, _dec(discount)), after_item))
    net_subtotal = _cents(after_item - discount_d)

    taxable_after_item = _cents(
        sum((net for line, net in zip(lines, line_nets) if line.taxable), ZERO)
    )
    taxable_share = (taxable_after_item / after_item) if after_item else ZERO
    taxable_net = _cents(taxable_after_item - discount_d * taxable_share)

    rate_sc = _dec(service_charge_rate)
    service_charge = _cents(net_subtotal * rate_sc / RATE)
    service_charge_taxable = service_charge * taxable_share

    rate_vat = _dec(vat_rate)
    vat_applicable = bill_type == "tax" and rate_vat > 0
    vat = (
        _cents((taxable_net + service_charge_taxable) * rate_vat / RATE)
        if vat_applicable else ZERO
    )

    total = _cents(net_subtotal + service_charge + vat)
    paid_d = _cents(min(max(ZERO, _dec(paid)), total))
    balance = _cents(total - paid_d)

    return Totals(
        subtotal=float(subtotal),
        discount=float(discount_d),
        net_subtotal=float(net_subtotal),
        taxable_net=float(taxable_net),
        service_charge=float(service_charge),
        service_charge_rate=float(service_charge_rate),
        vat=float(vat),
        vat_rate=float(vat_rate) if vat_applicable else 0.0,
        total=float(total),
        paid=float(paid_d),
        balance=float(balance),
        vat_applicable=vat_applicable,
        bill_type=bill_type,
        item_discount=float(item_discount),
    )



# --------------------------------------------------------------------------- #
# amount in words (Nepali/Indian numbering: thousand, lakh, crore)
# --------------------------------------------------------------------------- #
def _under_hundred(n: int) -> str:
    if n < 20:
        return ONES[n]
    tens, unit = divmod(n, 10)
    return TENS[tens] + (f"-{ONES[unit]}" if unit else "")


def _under_thousand(n: int) -> str:
    hundreds, rest = divmod(n, 100)
    words = []
    if hundreds:
        words.append(f"{ONES[hundreds]} Hundred")
    if rest:
        words.append(_under_hundred(rest))
    return " ".join(words)


def integer_to_words(n: int) -> str:
    """1234567 -> 'Twelve Lakh Thirty-Four Thousand Five Hundred Sixty-Seven'."""
    if n == 0:
        return "Zero"
    if n < 0:
        raise ValueError("Negative amounts cannot be written in words")

    parts = []
    crore, n = divmod(n, 10_000_000)
    lakh, n = divmod(n, 100_000)
    thousand, n = divmod(n, 1000)
    if crore:
        parts.append(f"{integer_to_words(crore)} Crore")
    if lakh:
        parts.append(f"{_under_thousand(lakh)} Lakh")
    if thousand:
        parts.append(f"{_under_thousand(thousand)} Thousand")
    if n:
        parts.append(_under_thousand(n))
    return " ".join(parts)


def amount_in_words(amount: float, currency: str = "Nepalese Rupees") -> str:
    """Grand total in words, with paisa when the amount has decimals."""
    paisa_total = int((_dec(amount) * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    rupees, paisa = divmod(abs(paisa_total), 100)
    words = f"{currency} {integer_to_words(rupees)}"
    if paisa:
        words += f" and Paisa {_under_hundred(paisa)}"
    return words + " Only"
