"""Normalize extracted values and check that the receipt adds up.

The model's output is never trusted blindly: every number is checked against
the others, and anything that does not add up becomes a warning. A receipt with
no warnings is "verified"; otherwise it "needs_review".
"""

import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from itertools import product

from app.config import get_settings
from app.pipeline.extract import LlmReceipt
from app.pipeline.normalize import clean_text, compact_id, to_hhmm, to_iso_date
from app.schemas import CATEGORIES, LineItem, ReceiptData

# Item descriptions that are really summary lines, not purchases.
_NOT_ITEMS = re.compile(
    r"^(sub\s*-?\s*total|total|grand\s*total|sale\s*total|excl\.?\s*total|tax(\s*total)?|vat(\s*\d+%?)?|"
    r"service\s*charge|discount|cash|change|balance|paid(\s*amount)?|payable|amount\s*due|"
    r"tot\s*\d*%?|rounding|tip)\W*$",
    re.IGNORECASE,
)

_DISCOUNT_LINE = re.compile(r"\b(discount|promo(tion)?|coupon|voucher|rebate)\b", re.IGNORECASE)
# Dates as printed: 15/09/2026, 2026-10-01, 05-10-2026, 28.09.2026, 30/09/26, 08 Oct 2026, Oct 03, 2026
_DATE_IN_TEXT = re.compile(
    r"\b(\d{4}[-/.]\d{1,2}[-/.]\d{1,2}|\d{1,2}[-/.]\d{1,2}[-/.]\d{2,4}|"
    r"\d{1,2}\s+[A-Za-z]{3,9}\.?,?\s+\d{4}|[A-Za-z]{3,9}\.?\s+\d{1,2},?\s+\d{4})\b")

_CURRENCY_ALIASES = {"K": "ZMW", "ZK": "ZMW", "KWACHA": "ZMW", "ZMK": "ZMW"}

# Warnings that mean the numbers may be wrong (Phase 4 uses these to trigger the VLM pass).
NUMBER_WARNINGS = {"NO_ITEMS", "NO_TOTAL", "ITEMS_SUM_MISMATCH", "TOTAL_MISMATCH", "LINE_MATH_MISMATCH",
                   "VALUE_NOT_IN_TEXT", "PAYMENT_MISMATCH"}

# Numbers as printed: 1,470.00 | 126.98 | K50 | .33.02 | 6.897
_TEXT_NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")
# Tax IDs are short runs of letters/digits (TPIN 1002131502).
_TAX_ID = re.compile(r"^[A-Z0-9-]{5,20}$")


@dataclass
class ReceiptWarning:
    code: str
    message: str
    field: str | None = None

    def to_dict(self) -> dict:
        return {"code": self.code, "message": self.message, "field": self.field}


@dataclass
class Validated:
    receipt: ReceiptData
    warnings: list[ReceiptWarning] = field(default_factory=list)
    dropped_items: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)  # informational, do not affect status

    @property
    def status(self) -> str:
        return "needs_review" if self.warnings else "verified"

    @property
    def codes(self) -> list[str]:
        return [w.code for w in self.warnings]


def _money(value: float | None) -> float | None:
    return None if value is None else round(float(value), 2)


def close(a: float, b: float) -> bool:
    s = get_settings()
    return abs(a - b) <= max(s.sum_tolerance_abs, s.sum_tolerance_rel * max(abs(a), abs(b)))


def numbers_in_text(text: str) -> set[float]:
    """Every number printed in the OCR text, plus its 2-decimal rounding (6.897 -> 6.9)."""
    values = set()
    for match in _TEXT_NUMBER.finditer(text):
        token = match.group(0).rstrip(",")
        for candidate in {token.replace(",", ""), token.replace(",", ".")}:
            try:
                number = float(candidate)
            except ValueError:
                continue
            values.update({number, round(number, 2)})
    return values


def _grounded(value: float, printed: set[float]) -> bool:
    """Printed somewhere (the sign is ignored: discounts are printed as -79.00 or 79.00)."""
    return any(abs(abs(value) - p) < 0.005 for p in printed)


def normalize(raw: LlmReceipt) -> tuple[ReceiptData, list[str]]:
    """Clean values; drop summary lines the model listed as items; move discount lines
    listed as items into the discount field."""
    items, dropped, discount_lines = [], [], []
    for item in raw.items:
        description = clean_text(item.description)
        if not description or _NOT_ITEMS.match(description):
            dropped.append(description or "(empty)")
            continue
        if item.amount < 0 or _DISCOUNT_LINE.search(description):
            discount_lines.append((description, abs(item.amount)))
            continue
        items.append(LineItem(
            description=description,
            quantity=item.quantity,
            unit_price=_money(item.unit_price),
            amount=_money(item.amount),
            category=item.category if item.category in CATEGORIES else "Other",
        ))

    currency = clean_text(raw.currency)
    if currency:
        currency = _CURRENCY_ALIASES.get(currency.upper().rstrip("."), currency.upper())

    receipt = ReceiptData(
        vendor=clean_text(raw.vendor),
        vendor_tax_id=_tax_id(raw.vendor_tax_id),
        receipt_no=compact_id(raw.receipt_no),
        date=to_iso_date(raw.date),
        time=to_hhmm(raw.time),
        currency=currency,
        items=items,
        subtotal=_money(raw.subtotal),
        discount=_money(abs(raw.discount)) if raw.discount is not None else None,
        service_charge=_money(raw.service_charge),
        tax=_money(raw.tax),
        total=_money(raw.total),
        amount_paid=_money(raw.amount_paid),
        change=_money(raw.change),
        payment_method=clean_text(raw.payment_method),
    )
    if discount_lines:
        if receipt.discount is None:
            receipt.discount = _money(sum(amount for _, amount in discount_lines))
        dropped += [f"{d} (discount {a:.2f})" for d, a in discount_lines]
    return receipt, dropped


def _tax_id(value) -> str | None:
    tax_id = compact_id(value)
    return tax_id if tax_id and _TAX_ID.match(tax_id) else None


def _totals_consistent(r: ReceiptData) -> bool:
    """Does subtotal relate to total in any normal way?

    Tax and service charge may be added on top, already included in the prices,
    or the service charge may be part of the printed tax figure. Try each.
    """
    discount = r.discount or 0.0
    extras = [x for x in (r.tax, r.service_charge) if x]
    for use in product((False, True), repeat=len(extras)):
        added = sum(x for x, on in zip(extras, use) if on)
        if close(r.subtotal - discount + added, r.total):
            return True
    return False


def _items_consistent(items_sum: float, r: ReceiptData) -> bool:
    """Items may be priced with or without tax/service and before or after discount."""
    discount = r.discount or 0.0
    targets = [t for t in (r.total, r.subtotal) if t is not None]
    if r.total is not None:
        targets += [r.total + discount, r.total - (r.tax or 0) - (r.service_charge or 0),
                    r.total - (r.tax or 0), r.total - (r.service_charge or 0)]
    if r.subtotal is not None:
        targets.append(r.subtotal + discount)
    return any(close(items_sum, t) for t in targets)


def check(receipt: ReceiptData, *, ocr_text: str | None = None, ocr_confidence: float | None = None,
          image_warnings: list[str] | None = None, today: date | None = None) -> list[ReceiptWarning]:
    warnings: list[ReceiptWarning] = []
    add = lambda code, message, field=None: warnings.append(ReceiptWarning(code, message, field))  # noqa: E731

    if ocr_text is not None:
        # The model must copy numbers, not compute them: each must be printed somewhere.
        printed = numbers_in_text(ocr_text)
        amounts = [(f, getattr(receipt, f))
                   for f in ("subtotal", "discount", "service_charge", "tax", "total", "amount_paid", "change")]
        for i, item in enumerate(receipt.items):
            amounts += [(f"items[{i}].amount", item.amount), (f"items[{i}].unit_price", item.unit_price)]
        for name, value in amounts:
            if value is not None and value != 0 and not _grounded(value, printed):
                add("VALUE_NOT_IN_TEXT", f"{name} = {value:g} does not appear on the receipt.", name)

    if not receipt.items:
        add("NO_ITEMS", "No purchased items were found.", "items")
    if receipt.total is None:
        add("NO_TOTAL", "No total amount was found.", "total")

    for i, item in enumerate(receipt.items):
        if item.quantity and item.unit_price is not None and not close(item.quantity * item.unit_price, item.amount):
            add("LINE_MATH_MISMATCH",
                f"Item '{item.description}': {item.quantity:g} x {item.unit_price:.2f} != {item.amount:.2f}.",
                f"items[{i}]")

    if receipt.items and (receipt.total is not None or receipt.subtotal is not None):
        items_sum = sum(item.amount for item in receipt.items)
        if not _items_consistent(items_sum, receipt):
            add("ITEMS_SUM_MISMATCH",
                f"Items add up to {items_sum:.2f}, which matches neither the total nor the subtotal.", "items")

    if receipt.subtotal is not None and receipt.total is not None and not _totals_consistent(receipt):
        add("TOTAL_MISMATCH",
            f"Subtotal {receipt.subtotal:.2f}, tax and charges do not add up to the total {receipt.total:.2f}.",
            "total")

    if receipt.amount_paid is not None and receipt.total is not None:
        paid = receipt.amount_paid - (receipt.change or 0)
        # Without a printed change line, handing over more than the total is normal ("Tendered").
        mismatch = not close(paid, receipt.total) if receipt.change is not None else paid < receipt.total - 0.005
        if mismatch:
            add("PAYMENT_MISMATCH",
                f"Paid {receipt.amount_paid:.2f} minus change {receipt.change or 0:.2f} = {paid:.2f}, "
                f"but the total is {receipt.total:.2f}.", "total")

    today = today or date.today()
    if receipt.date is None:
        add("BAD_DATE", "No readable date was found.", "date")
    elif date.fromisoformat(receipt.date) > today + timedelta(days=1):
        add("BAD_DATE", f"Date {receipt.date} is in the future.", "date")

    threshold = get_settings().ocr_confidence_threshold
    if ocr_confidence is not None and ocr_confidence < threshold:
        add("LOW_OCR_CONFIDENCE", f"OCR confidence {ocr_confidence:.2f} is below {threshold:.2f}.")

    for code in image_warnings or []:
        add("IMAGE_QUALITY", f"Photo problem: {code.replace('_', ' ').lower()}. Retaking the photo may help.")

    return warnings


def _fill_total(receipt: ReceiptData) -> str | None:
    """No printed total: use the subtotal, or paid minus change, when it matches the items
    (tax included in prices). Returns a note, or None if nothing was filled."""
    if receipt.total is not None or not receipt.items:
        return None
    items_sum = sum(item.amount for item in receipt.items)
    candidates = []
    if receipt.subtotal is not None:
        candidates.append(("the subtotal", receipt.subtotal - (receipt.discount or 0)))
    if receipt.amount_paid is not None:
        candidates.append(("amount paid minus change", receipt.amount_paid - (receipt.change or 0)))
    for source, value in candidates:
        if close(items_sum, value):
            receipt.total = round(value, 2)
            return f"No total printed; total taken from {source} ({value:.2f}), which matches the items."
    return None


def _fix_cash_as_total(receipt: ReceiptData) -> str | None:
    """Total copied from the cash handed over: when total == amount paid, change was given,
    and paid - change matches the items or the subtotal, the real total is paid - change."""
    r = receipt
    if r.total is None or r.amount_paid is None or not r.change or not close(r.total, r.amount_paid):
        return None
    payable = r.amount_paid - r.change
    evidence = [sum(i.amount for i in r.items)] if r.items else []
    if r.subtotal is not None:
        evidence.append(r.subtotal - (r.discount or 0))
    if any(close(payable, e) for e in evidence):
        old, r.total = r.total, round(payable, 2)
        return (f"Total {old:.2f} was the cash handed over; corrected to {payable:.2f} "
                f"(paid {r.amount_paid:.2f} - change {r.change:.2f}), which matches the items/subtotal.")
    return None


def _fix_multiplied_amounts(receipt: ReceiptData, ocr_text: str | None) -> list[str]:
    """The model multiplied quantity x printed amount ("2 x Onions 30.00" -> 60). If the amount is not
    printed but amount / quantity is, and using the printed amounts makes the items add up to the
    total (while the current ones do not), the printed amounts are the line amounts."""
    if not ocr_text or receipt.total is None:
        return []
    printed = numbers_in_text(ocr_text)
    candidates = {}
    for i, item in enumerate(receipt.items):
        if item.quantity and item.quantity > 1 and not _grounded(item.amount, printed):
            per_line = round(item.amount / item.quantity, 2)
            if _grounded(per_line, printed):
                candidates[i] = per_line
    if not candidates:
        return []
    current = sum(item.amount for item in receipt.items)
    repaired = sum(candidates.get(i, item.amount) for i, item in enumerate(receipt.items))
    if _items_consistent(current, receipt) or not _items_consistent(repaired, receipt):
        return []
    notes = []
    for i, amount in candidates.items():
        item = receipt.items[i]
        notes.append(f"Item '{item.description}': amount {item.amount:.2f} was quantity x {amount:.2f}; "
                     f"the printed {amount:.2f} is the line amount (items now add up to the total).")
        item.amount, item.unit_price = amount, None
    return notes


def _clear_computed_unit_prices(receipt: ReceiptData, ocr_text: str | None) -> str | None:
    """The model calculated unit prices that are not printed (296 / 2 = 148). Harmless but not
    data from the receipt: clear them when quantity x price equals the printed line amount."""
    if not ocr_text:
        return None
    printed = numbers_in_text(ocr_text)
    cleared = []
    for item in receipt.items:
        if (item.unit_price is not None and item.quantity and not _grounded(item.unit_price, printed)
                and _grounded(item.amount, printed) and close(item.quantity * item.unit_price, item.amount)):
            cleared.append(f"{item.description} ({item.unit_price:.2f})")
            item.unit_price = None
    if not cleared:
        return None
    return f"Unit prices not printed on the receipt were removed (calculated by the model): {', '.join(cleared)}."


def _date_from_text(receipt: ReceiptData, ocr_text: str | None) -> str | None:
    """The model found no date, but a date is printed (e.g. alone on a line): use the first one."""
    if receipt.date is not None or not ocr_text:
        return None
    for match in _DATE_IN_TEXT.finditer(ocr_text):
        iso = to_iso_date(match.group(0))
        if iso:
            receipt.date = iso
            return f"Date {iso} taken from the printed text '{match.group(0)}'."
    return None


def _fix_unit_prices(receipt: ReceiptData) -> list[str]:
    """A 'unit price' equal to the line amount with quantity > 1 is really the line amount."""
    notes = []
    for item in receipt.items:
        if (item.quantity and item.quantity > 1 and item.unit_price is not None
                and close(item.unit_price, item.amount)):
            notes.append(f"Item '{item.description}': {item.unit_price:.2f} is the line amount, "
                         f"not a unit price; unit price cleared.")
            item.unit_price = None
    return notes


def validate(raw: LlmReceipt, *, ocr_text: str | None = None, ocr_confidence: float | None = None,
             image_warnings: list[str] | None = None, today: date | None = None) -> Validated:
    receipt, dropped = normalize(raw)
    notes = _fix_unit_prices(receipt) + _fix_multiplied_amounts(receipt, ocr_text)
    if note := _clear_computed_unit_prices(receipt, ocr_text):
        notes.append(note)
    for fix in (_fix_cash_as_total, _fill_total):
        if note := fix(receipt):
            notes.append(note)
    if note := _date_from_text(receipt, ocr_text):
        notes.append(note)
    warnings = check(receipt, ocr_text=ocr_text, ocr_confidence=ocr_confidence,
                     image_warnings=image_warnings, today=today)
    return Validated(receipt=receipt, warnings=warnings, dropped_items=dropped, notes=notes)
