"""Mobile money messages (Airtel Money, MTN MoMo, Zamtel Kwacha): rules applied in Python.

A screenshot of a payment or transfer confirmation is not a shop receipt:

- The vendor is the mobile money provider (Airtel). Who was paid is stored separately:
  recipient (name or account), recipient phone, and the transaction type
  ("Mobile money payment" to a merchant account, "Money transfer to individual").
- The amount is the payment ("of ZMW 10.00", "Amount K50"), never the balance; the balance
  after the transaction is kept in its own field.
- Airtel transaction IDs carry the date and time: MP261010.1142.C40203 = 2026-10-10 11:42.
  The date is only taken from an ID in exactly that pattern and only if it is a real date,
  not in the future; otherwise nothing is guessed and the missing date stays flagged.
  The same pattern identifies Airtel when the message does not name it.
- A message reporting a failed transaction is flagged.

Only short messages with a transaction ID that read like a confirmation are treated this way,
so a shop receipt "paid by Airtel Money" is unaffected.
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
AIRTEL = ("Airtel", "Airtel Money")

# "Txn. ID : MP261010.1055.H32285.Your ..." -> MP261010.1055.H32285 (a dot-segment that runs into
# a lower-case word, ".Your", is the next sentence, not part of the ID).
_ID = r"([A-Z0-9]+(?:\.[A-Z0-9]+(?![a-z]))*)"
_TXN_ID = re.compile(r"(?i:\b(?:txn|trans(?:action)?)\.?\s*(?:id|ref(?:erence)?)\b)\.?\s*[:.]?\s*" + _ID)
# Airtel Money: two letters, YYMMDD, ".", HHMM, ".", reference.
_AIRTEL_ID = re.compile(r"^[A-Z]{2}(\d{2})(\d{2})(\d{2})\.(\d{2})(\d{2})\.[A-Z0-9]+$")
_AIRTEL_ID_IN_TEXT = re.compile(r"\b[A-Z]{2}\d{6}\.\d{4}\.[A-Z0-9]{3,12}(?![a-z])")

_CONFIRMATION = re.compile(r"\b(is successful|successful(ly)?|balance is|new balance|you have (sent|paid|received))\b", re.I)
_FAILED = re.compile(r"\b(failed|unsuccessful|not successful|declined|insufficient (funds|balance)|could not be completed)\b", re.I)
_MONEY = r"(?:ZMW|ZK|K)\s*([\d,]+(?:\.\d{1,2})?)"
_PHONE = r"(\+?260\s?\d{9}|0\d{9})"
# "Payment to AMMOBILE Account NA of ZMW 10.00 is successful"
_PAYMENT = re.compile(rf"\bpayment (?:of {_MONEY} )?to (.+?) (?:of|for) {_MONEY}", re.I)
# "You have sent Money to Isaac Kasikila on 0968223362.Amount K50."
_SENT_MONEY_TO = re.compile(rf"\bsent money to (.+?) on {_PHONE}\s*\.?\s*amount\s*{_MONEY}", re.I)
# "You have sent K50 to Isaac Kasikila 0968223362."
_SENT = re.compile(rf"\b(?:you have )?(?:sent|paid|transferred) {_MONEY} to (.+?)(?:[.,](?!\d)| on | at |\s+txn|$)", re.I)
_BALANCE = re.compile(rf"\bbalance(?: is|:)?\s*{_MONEY}", re.I)
MAX_MESSAGE_LINES = 15

PAYMENT, TRANSFER = "Mobile money payment", "Money transfer to individual"


@dataclass
class MobileMoney:
    provider: str
    notes: list[str] = field(default_factory=list)
    warnings: list[ReceiptWarning] = field(default_factory=list)
    complete: bool = False  # ID, amount and date all read: photo-quality warnings do not apply


def _amount(text: str) -> float:
    return round(float(text.replace(",", "")), 2)


def txn_id(text: str) -> str | None:
    """The transaction ID after its label, or an Airtel-pattern ID anywhere in the text."""
    if m := _TXN_ID.search(text):
        return m.group(1).rstrip(".")
    if m := _AIRTEL_ID_IN_TEXT.search(text):
        return m.group(0)
    return None


def detect(ocr_text: str | None) -> tuple[str, str] | None:
    """(provider, payment method) if the text is a mobile money confirmation message."""
    if not ocr_text:
        return None
    lines = [line for line in ocr_text.splitlines() if line.strip()]
    found_id = txn_id(ocr_text)
    if len(lines) > MAX_MESSAGE_LINES or not found_id or not _CONFIRMATION.search(ocr_text):
        return None
    for provider, pattern, method in PROVIDERS:
        if pattern.search(ocr_text):
            return provider, method
    if _AIRTEL_ID.match(found_id):  # Airtel's own ID pattern identifies the provider
        return AIRTEL
    return None


def date_from_txn_id(txn: str, today: date) -> tuple[str, str] | None:
    """('2026-10-10', '11:42') from MP261010.1142.C40203; None unless the ID has exactly that
    pattern and gives a real date and time that is not in the future."""
    m = _AIRTEL_ID.match(txn)
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


def _split_phone(name: str) -> tuple[str, str | None]:
    """'Isaac Kasikila 0968223362' -> ('Isaac Kasikila', '0968223362')."""
    if m := re.search(_PHONE, name):
        return clean_text(name[:m.start()] + name[m.end():]).strip(" ,-") or None, m.group(1).replace(" ", "")
    return clean_text(name), None


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
    receipt.currency = "ZMW" if receipt.currency in (None, "K", "ZK") else receipt.currency

    txn = txn_id(ocr_text).upper()
    receipt.receipt_no = txn
    when = date_from_txn_id(txn, today)
    if when:
        if (receipt.date, receipt.time) != when:
            result.notes.append(f"Date and time {when[0]} {when[1]} taken from the transaction ID {txn}.")
        receipt.date, receipt.time = when
    else:
        result.notes.append(f"Transaction ID {txn} is not in the known Airtel date format; the date was not "
                            "taken from it.")

    # Who was paid, how much, and never the balance.
    paid, recipient, phone, kind = None, None, None, None
    if m := _PAYMENT.search(text):
        recipient, paid, kind = m.group(2), _amount(m.group(3)), PAYMENT
    elif m := _SENT_MONEY_TO.search(text):
        recipient, phone, paid, kind = m.group(1), m.group(2), _amount(m.group(3)), TRANSFER
    elif m := _SENT.search(text):
        paid, recipient, kind = _amount(m.group(1)), m.group(2), TRANSFER
    if recipient:
        name, phone_in_name = _split_phone(recipient)
        receipt.recipient = name
        receipt.recipient_phone = phone or phone_in_name
    receipt.transaction_type = kind
    balance = _amount(m.group(1)) if (m := _BALANCE.search(text)) else None
    receipt.balance = balance
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
        who = receipt.recipient or receipt.recipient_phone
        description = (f"Money sent to {who}" if kind == TRANSFER else f"Payment to {who}") if who else f"{method} payment"
        receipt.items = [LineItem(description=description, amount=receipt.total, category=category)]

    if paid is None:
        amounts = {_amount(a) for a in re.findall(_MONEY, text)}
        if len(amounts) > 1:  # e.g. payment and balance, but the wording was not recognised
            result.warnings.append(ReceiptWarning(
                "AMOUNT_UNCLEAR", f"The message has several amounts ({', '.join(f'{a:.2f}' for a in sorted(amounts))}) "
                "and it is not clear which one was paid; the balance must not be counted as spending.", "total"))
    if _FAILED.search(text):
        result.warnings.append(ReceiptWarning(
            "PAYMENT_FAILED", "The message says the transaction was not successful: it may not be real spending.",
            "total"))
    result.complete = bool(when and paid is not None)
    return result
