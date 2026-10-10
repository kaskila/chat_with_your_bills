"""Mobile money messages (Airtel Money, MTN MoMo, Zamtel Kwacha): rules applied in Python.

A screenshot of a payment confirmation is not a shop receipt:

- The vendor is the mobile money provider (Airtel), not the account paid (the recipient,
  stored separately).
- The amount is the payment ("of ZMW 10.00"), never the balance ("balance is ZMW 539.40").
- Airtel transaction IDs carry the date and time: MP261010.1142.C40203 = 2026-10-10 11:42.
  The date is only taken from an ID in exactly that pattern and only if it is a real date,
  not in the future; otherwise nothing is guessed and the missing date stays flagged.
- A message reporting a failed transaction is flagged.

Only short messages that name a provider, contain a transaction ID and read like a
confirmation are treated this way, so a shop receipt "paid by Airtel Money" is unaffected.
"""

import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from app.pipeline.normalize import clean_text
from app.pipeline.validate import ReceiptWarning, close
from app.schemas import LineItem, ReceiptData

# Provider, how it appears in messages, payment method name.
PROVIDERS = (
    ("Airtel", re.compile(r"\bairtel\s*money\b", re.I), "Airtel Money"),
    ("MTN", re.compile(r"\b(mtn\s*mobile\s*money|mtn\s*momo|momo)\b", re.I), "MTN MoMo"),
    ("Zamtel", re.compile(r"\bzamtel\s*kwacha\b", re.I), "Zamtel Kwacha"),
)
_TXN_ID = re.compile(r"\b(?:txn|trans(?:action)?)\.?\s*(?:id|ref(?:erence)?)\b\.?\s*[:.]?\s*([A-Z0-9][A-Z0-9.]{5,40}?)\.?(?=\s|$)",
                     re.I | re.M)
# Airtel Money: two letters, YYMMDD, ".", HHMM, ".", reference.
_AIRTEL_ID = re.compile(r"^[A-Z]{2}(\d{2})(\d{2})(\d{2})\.(\d{2})(\d{2})\.[A-Z0-9]+$")
_CONFIRMATION = re.compile(r"\b(is successful|successful(ly)?|balance is|new balance|you have (sent|paid|received))\b", re.I)
_FAILED = re.compile(r"\b(failed|unsuccessful|not successful|declined|insufficient (funds|balance)|could not be completed)\b", re.I)
_MONEY = r"(?:ZMW|ZK|K)\s*([\d,]+(?:\.\d{1,2})?)"
_PAYMENT = re.compile(rf"\bpayment (?:of {_MONEY} )?to (.+?) (?:of|for) {_MONEY}", re.I | re.S)
_SENT = re.compile(rf"\b(?:you have )?(?:sent|paid|transferred) {_MONEY} to (.+?)(?:[.,]| on | at |\s+txn|\s*$)", re.I | re.S)
_BALANCE = re.compile(rf"\bbalance(?: is|:)?\s*{_MONEY}", re.I)
MAX_MESSAGE_LINES = 15


@dataclass
class MobileMoney:
    provider: str
    notes: list[str] = field(default_factory=list)
    warnings: list[ReceiptWarning] = field(default_factory=list)
    complete: bool = False  # ID, amount and date all read: photo-quality warnings do not apply


def _amount(text: str) -> float:
    return round(float(text.replace(",", "")), 2)


def detect(ocr_text: str | None) -> tuple[str, str] | None:
    """(provider, payment method) if the text is a mobile money confirmation message."""
    if not ocr_text:
        return None
    lines = [line for line in ocr_text.splitlines() if line.strip()]
    if len(lines) > MAX_MESSAGE_LINES or not _TXN_ID.search(ocr_text) or not _CONFIRMATION.search(ocr_text):
        return None
    for provider, pattern, method in PROVIDERS:
        if pattern.search(ocr_text):
            return provider, method
    return None


def date_from_txn_id(txn_id: str, today: date) -> tuple[str, str] | None:
    """('2026-10-10', '11:42') from MP261010.1142.C40203; None unless the ID has exactly that
    pattern and gives a real date and time that is not in the future."""
    m = _AIRTEL_ID.match(txn_id)
    if not m:
        return None
    yy, mm, dd, hh, mi = (int(g) for g in m.groups())
    try:
        when = datetime(2000 + yy, mm, dd, hh, mi)
    except ValueError:
        return None
    if when.date() > today + timedelta(days=1) or when.year < 2010:
        return None
    return when.date().isoformat(), f"{hh:02d}:{mi:02d}"


def apply(receipt: ReceiptData, ocr_text: str | None, *, today: date | None = None) -> MobileMoney | None:
    """Apply the mobile money rules to ``receipt`` in place. None when the text is not such a message."""
    found = detect(ocr_text)
    if not found:
        return None
    provider, method = found
    today = today or date.today()
    result = MobileMoney(provider)
    text = " ".join(ocr_text.split())

    if receipt.vendor != provider:
        result.notes.append(f"Mobile money message: vendor set to the provider {provider}"
                            + (f" (was '{receipt.vendor}')." if receipt.vendor else "."))
        receipt.vendor = provider
    receipt.payment_method = method
    receipt.currency = receipt.currency or "ZMW"

    txn_id = _TXN_ID.search(ocr_text).group(1).rstrip(".").upper()
    receipt.receipt_no = txn_id
    when = date_from_txn_id(txn_id, today)
    if when:
        if (receipt.date, receipt.time) != when:
            result.notes.append(f"Date and time {when[0]} {when[1]} taken from the transaction ID {txn_id}.")
        receipt.date, receipt.time = when
    else:
        result.notes.append(f"Transaction ID {txn_id} is not in the known Airtel date format; the date was not "
                            "taken from it.")

    # The payment, its recipient, and never the balance.
    paid, recipient = None, None
    if m := _PAYMENT.search(text):
        recipient, paid = m.group(2), _amount(m.group(3))
    elif m := _SENT.search(text):
        paid, recipient = _amount(m.group(1)), m.group(2)
    if recipient:
        receipt.recipient = clean_text(recipient)
    balance = _amount(m.group(1)) if (m := _BALANCE.search(text)) else None
    if paid is not None and (receipt.total is None or not close(receipt.total, paid)):
        old = receipt.total
        receipt.total = paid
        result.notes.append(f"Amount set to the payment {paid:.2f}"
                            + (f" (was {old:.2f}{', the balance' if balance is not None and close(old, balance) else ''})."
                               if old is not None else "."))
    if balance is not None and receipt.amount_paid is not None and close(receipt.amount_paid, balance):
        receipt.amount_paid = None  # the balance is not money handed over
    receipt.subtotal = None  # a payment message has no subtotal (the model sometimes copies the amount)

    # A message is one payment: one item, so it counts on the dashboard. The model's category is
    # kept when it gave one item; otherwise "Other" (it can be changed on the receipt page).
    if receipt.total is not None:
        category = receipt.items[0].category if len(receipt.items) == 1 else "Other"
        receipt.items = [LineItem(description=f"Payment to {receipt.recipient}" if receipt.recipient else
                                  f"{method} payment", amount=receipt.total, category=category)]

    if _FAILED.search(text):
        result.warnings.append(ReceiptWarning(
            "PAYMENT_FAILED", "The message says the transaction was not successful: it may not be real spending.",
            "total"))
    result.complete = bool(when and paid is not None)
    return result
