"""Turn values as printed on receipts into clean Python values.

Used by validation (Phase 2) and by the evaluation scoring, so that a value is
judged on its content, not its format ("K1,470.00" == 1470, "27/08/2026" ==
"2026-08-27").
"""

import re
from datetime import date, datetime

from dateutil import parser as date_parser

_NUMBER_RE = re.compile(r"-?\d[\d,\s]*(?:\.\d+)?|-?\.\d+")
_EMPTY = {"", "unknown", "none", "null", "n/a", "na", "-"}


def is_empty(value) -> bool:
    return value is None or (isinstance(value, str) and value.strip().lower() in _EMPTY)


def to_number(value) -> float | None:
    """Parse amounts such as 50, "K50", "1,470.00", "ZMW 126.98", "160.00 ^#"."""
    if is_empty(value):
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    match = _NUMBER_RE.search(str(value))
    if not match:
        return None
    text = match.group(0).replace(" ", "")
    # "1,470.00" -> thousands separator; "126,98" -> decimal comma
    if "," in text and "." not in text and re.fullmatch(r"-?\d+,\d{2}", text):
        text = text.replace(",", ".")
    else:
        text = text.replace(",", "")
    try:
        return float(text)
    except ValueError:
        return None


def to_iso_date(value, *, dayfirst: bool = True) -> str | None:
    """Parse "27/08/2026", "2026/8/28", "21 Jul, 2026" -> "YYYY-MM-DD".

    Receipts in this project are day-first (Zambia), except year-first forms.
    """
    if is_empty(value):
        return None
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    text = str(value).strip()
    yearfirst = bool(re.match(r"^\d{4}[-/.]", text))
    try:
        parsed = date_parser.parse(text, dayfirst=dayfirst and not yearfirst, yearfirst=yearfirst, fuzzy=True)
    except (ValueError, OverflowError):
        return None
    return parsed.date().isoformat()


def to_hhmm(value) -> str | None:
    """Parse "6:55:44 pm", "10:48:00", "11:25" -> 24-hour "HH:MM"."""
    if is_empty(value):
        return None
    match = re.search(r"(\d{1,2})[:.](\d{2})(?:[:.]\d{2})?\s*([ap]\.?m\.?)?", str(value), re.IGNORECASE)
    if not match:
        return None
    hour, minute = int(match.group(1)), int(match.group(2))
    meridiem = (match.group(3) or "").lower().replace(".", "")
    if meridiem == "pm" and hour < 12:
        hour += 12
    elif meridiem == "am" and hour == 12:
        hour = 0
    if hour > 23 or minute > 59:
        return None
    return f"{hour:02d}:{minute:02d}"


def clean_text(value) -> str | None:
    """Collapse whitespace; empty/"Unknown" -> None."""
    if is_empty(value):
        return None
    return re.sub(r"\s+", " ", str(value)).strip()


def compact_id(value) -> str | None:
    """Receipt numbers / tax IDs: uppercase, no spaces."""
    text = clean_text(value)
    return re.sub(r"\s+", "", text).upper() if text else None
