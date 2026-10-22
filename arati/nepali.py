"""Nepali labels, Devanagari numerals, amount in words and Bikram Sambat dates.

Presentation helpers only — all arithmetic still comes from :mod:`arati.money`,
so the Nepali invoice and the English invoice can never disagree on a number.
"""

from __future__ import annotations

from datetime import date
from decimal import ROUND_HALF_UP, Decimal

LANGUAGES = ("en", "ne")
LANGUAGE_LABELS = {"en": "English", "ne": "नेपाली"}
LANGUAGE_CODES = {label: code for code, label in LANGUAGE_LABELS.items()}

DEVANAGARI_DIGITS = "०१२३४५६७८९"

MONTHS_NE = (
    "बैशाख", "जेठ", "असार", "साउन", "भदौ", "असोज",
    "कात्तिक", "मंसिर", "पुष", "माघ", "फागुन", "चैत",
)

# Key -> (English, Nepali). Short forms that fit an A4 table header.
LABELS: dict[str, tuple[str, str]] = {
    "tax_invoice": ("TAX INVOICE", "मूल्य अभिवृद्धि कर बिजक"),
    "bill_of_supply": ("BILL OF SUPPLY", "आपूर्ति बिजक"),
    "invoice_no": ("Invoice No.", "बिजक नं."),
    "date": ("Date", "मिति"),
    "bs_date": ("BS date", "मिति (वि.सं.)"),
    "customer": ("Customer", "ग्राहक"),
    "name": ("Name", "नाम"),
    "address": ("Address", "ठेगाना"),
    "phone": ("Phone", "फोन"),
    "pan": ("PAN / VAT No.", "प्यान / भ्याट नं."),
    "customer_type": ("Customer type", "ग्राहक प्रकार"),
    "sn": ("S.N.", "क्र.सं."),
    "description": ("Description", "विवरण"),
    "code": ("Code / SKU", "कोड"),
    "unit": ("Unit", "इकाई"),
    "qty": ("Qty", "परिमाण"),
    "rate": ("Rate", "दर"),
    "discount": ("Discount", "छुट"),
    "item_discount": ("Item discount", "वस्तु छुट"),
    "taxable_amount": ("Taxable amount", "करयोग्य रकम"),
    "exempt_amount": ("Exempt / non-taxable", "कर छुट / अकरयोग्य"),
    "vat_rate": ("VAT %", "मू.अ.कर दर"),
    "vat_amount": ("VAT amount", "मू.अ.कर रकम"),
    "total": ("Total", "जम्मा"),
    "subtotal": ("Subtotal", "उप-जम्मा"),
    "net_amount": ("Net amount", "जम्मा रकम"),
    "service_charge": ("Service charge", "सेवा शुल्क"),
    "grand_total": ("Grand total", "कुल जम्मा"),
    "amount_paid": ("Amount paid", "भुक्तानी रकम"),
    "balance": ("Balance due", "बाँकी रकम"),
    "payment_method": ("Payment method", "भुक्तानी विधि"),
    "payment_status": ("Payment status", "भुक्तानी स्थिति"),
    "in_words": ("Amount in words", "अक्षरमा रकम"),
    "paid": ("PAID", "भुक्तानी भयो"),
    "partially_paid": ("PARTIALLY PAID", "आंशिक भुक्तानी"),
    "unpaid": ("UNPAID", "भुक्तानी बाँकी"),
    "prepared_by": ("Prepared by", "तयार गर्ने"),
    "received_by": ("Amount received by", "रकम बुझ्ने"),
    "authorized_signature": ("Authorized signature", "अधिकृत हस्ताक्षर"),
    "customer_signature": ("Customer signature", "ग्राहकको हस्ताक्षर"),
    "payment_terms": ("Payment terms", "भुक्तानी सर्त"),
    "notes": ("Notes", "कैफियत"),
    "thank_you": ("Thank you for your business.", "धन्यवाद!"),
    "thank_you_business": ("Thank You For Your Business!", "तपाईंको व्यवसायका लागि धन्यवाद!"),
    "questions_contact": (
        "If you have any questions about this invoice, please contact",
        "यस बिजकसम्बन्धी कुनै प्रश्न छ भने कृपया सम्पर्क गर्नुहोस्",
    ),
    "payable_to": (
        "Make all checks/transfers payable to",
        "सबै चेक तथा ट्रान्सफरको भुक्तानी यसै ठेगानामा गर्नुहोस्",
    ),
    "bill_to": ("Bill To", "प्राप्तकर्ता"),
    "other_comments": ("Other Comments", "अन्य टिप्पणी"),
    "amount": ("Amount", "रकम"),
    "taxed": ("Taxed", "कर लागु"),
    "customer_id": ("Customer ID", "ग्राहक आईडी"),
    "due_date": ("Due Date", "भुक्तानी मिति"),
    "tax_rate": ("Tax Rate", "कर दर"),
    "not_applicable": ("Not applicable", "लागू हुँदैन"),
    "individual": ("Individual", "व्यक्ति"),
    "business": ("Business", "व्यवसाय"),
}

# 0-99: Nepali number names are irregular, so they are listed rather than derived.
ONES_NE = (
    "शून्य", "एक", "दुई", "तीन", "चार", "पाँच", "छ", "सात", "आठ", "नौ",
    "दश", "एघार", "बाह्र", "तेह्र", "चौध", "पन्ध्र", "सोह्र", "सत्र", "अठार", "उन्नाइस",
    "बीस", "एक्काइस", "बाइस", "तेइस", "चौबीस", "पच्चीस", "छब्बीस", "सत्ताइस", "अठ्ठाइस", "उनन्तीस",
    "तीस", "एकतीस", "बत्तीस", "तेतीस", "चौँतीस", "पैँतीस", "छत्तीस", "सैँतीस", "अठतीस", "उनन्चालीस",
    "चालीस", "एकचालीस", "बयालीस", "त्रिचालीस", "चवालीस", "पैँतालीस", "छयालीस", "सतचालीस",
    "अठचालीस", "उनन्चास",
    "पचास", "एकाउन्न", "बाउन्न", "त्रिपन्न", "चौवन्न", "पचपन्न", "छपन्न", "सन्ताउन्न",
    "अन्ठाउन्न", "उनन्साठी",
    "साठी", "एकसट्ठी", "बयसट्ठी", "त्रिसट्ठी", "चौंसट्ठी", "पैंसट्ठी", "छयसट्ठी", "सतसट्ठी",
    "अठसट्ठी", "उनन्सत्तरी",
    "सत्तरी", "एकहत्तर", "बहत्तर", "त्रिहत्तर", "चौहत्तर", "पचहत्तर", "छयहत्तर", "सतहत्तर",
    "अठहत्तर", "उनासी",
    "असी", "एकासी", "बयासी", "त्रियासी", "चौरासी", "पचासी", "छयासी", "सतासी", "अठासी",
    "उनान्नब्बे",
    "नब्बे", "एकान्नब्बे", "बयान्नब्बे", "त्रियान्नब्बे", "चौरान्नब्बे", "पन्चान्नब्बे",
    "छयान्नब्बे", "सन्तान्नब्बे", "अन्ठान्नब्बे", "उनान्सय",
)


def to_devanagari(value) -> str:
    """Western digits inside ``value`` rendered as Devanagari numerals."""
    return "".join(DEVANAGARI_DIGITS[int(ch)] if ch.isdigit() else ch for ch in str(value))


def to_latin(value) -> str:
    """Devanagari numerals back to Western digits (for the English invoice)."""
    return "".join(
        str(DEVANAGARI_DIGITS.index(ch)) if ch in DEVANAGARI_DIGITS else ch
        for ch in str(value)
    )


def nepali_words(number: int) -> str:
    """Integer to Nepali words using the lakh/crore grouping used in Nepal."""
    if number < 0:
        raise ValueError("Negative amounts cannot be written in words")
    if number < 100:
        return ONES_NE[number]

    parts: list[str] = []
    for unit, name in ((10_000_000, "करोड"), (100_000, "लाख"), (1000, "हजार"), (100, "सय")):
        count, number = divmod(number, unit)
        if count:
            parts.append(f"{nepali_words(count)} {name}")
    if number:
        parts.append(ONES_NE[number])
    return " ".join(parts)


def amount_in_words(amount: float) -> str:
    """1300.5 -> 'रुपैयाँ एक हजार तीन सय र पैसा पचास मात्र'."""
    paisa_total = int(
        (Decimal(str(amount)) * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    )
    rupees, paisa = divmod(abs(paisa_total), 100)
    words = f"रुपैयाँ {nepali_words(rupees)}"
    if paisa:
        words += f" र पैसा {nepali_words(paisa)}"
    return f"{words} मात्र"


def label(key: str, language: str = "en") -> str:
    english, nepali = LABELS.get(key, (key, key))
    return nepali if language == "ne" else english


def format_date(value: str | None, date_format: str = "DD/MM/YYYY") -> str:
    """ISO date -> the configured display format (``DD/MM/YYYY`` or ``YYYY-MM-DD``).

    Unparseable values are returned unchanged, so a bad date never blanks the
    invoice.
    """
    if not value:
        return ""
    try:
        parsed = date.fromisoformat(str(value))
    except (TypeError, ValueError):
        return str(value)
    if date_format == "YYYY-MM-DD":
        return parsed.isoformat()
    return parsed.strftime("%d/%m/%Y")


def to_bs(iso_date: str | None) -> tuple[str, str] | None:
    """ISO date -> (BS ``YYYY-MM-DD``, ``५ कात्तिक २०८३``), or None.

    Returns None when the date is unparseable or ``nepali-datetime`` is missing,
    so a bill can still be printed without a Bikram Sambat line.
    """
    if not iso_date:
        return None
    try:
        from nepali_datetime import date as bs_date
    except ImportError:
        return None
    try:
        converted = bs_date.from_datetime_date(date.fromisoformat(str(iso_date)))
    except (TypeError, ValueError):
        return None
    short = f"{converted.year:04d}-{converted.month:02d}-{converted.day:02d}"
    long = (
        f"{to_devanagari(converted.day)} {MONTHS_NE[converted.month - 1]} "
        f"{to_devanagari(converted.year)}"
    )
    return to_devanagari(short), long
