"""Turn time phrases into date ranges, in Python (a small model is unreliable at date math).

``resolve("last month", today=date(2026, 10, 10))`` -> Period(2026-09-01, 2026-09-30, "in September 2026").
Phrases are searched for anywhere in the text, so a whole question works too.
"""

import calendar
import re
from dataclasses import dataclass
from datetime import date, timedelta

MONTHS = {name.lower(): number for number, name in enumerate(calendar.month_name) if name}
MONTHS.update({name.lower(): number for number, name in enumerate(calendar.month_abbr) if name})
MONTHS["sept"] = 9
_MONTH = r"(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|sept?(?:ember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
_NUMBER_WORDS = {"a": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
                 "eight": 8, "nine": 9, "ten": 10, "twelve": 12}


@dataclass(frozen=True)
class Period:
    date_from: date | None
    date_to: date | None
    label: str  # for answers: "in September 2026", "from 1 Aug to 10 Oct 2026", "in total"

    def iso(self) -> tuple[str | None, str | None]:
        return (self.date_from.isoformat() if self.date_from else None,
                self.date_to.isoformat() if self.date_to else None)


ALL_TIME = Period(None, None, "in total")


def _month_end(year: int, month: int) -> date:
    return date(year, month, calendar.monthrange(year, month)[1])


def _add_months(day: date, months: int) -> date:
    index = day.year * 12 + day.month - 1 + months
    year, month = divmod(index, 12)
    return date(year, month + 1, min(day.day, calendar.monthrange(year, month + 1)[1]))


def _fmt(day: date) -> str:
    return f"{day.day} {calendar.month_abbr[day.month]} {day.year}"


def label(date_from: date | None, date_to: date | None) -> str:
    """Human wording for a range: a whole month, year or day reads naturally."""
    if date_from is None and date_to is None:
        return "in total"
    if date_from is None:
        return f"up to {_fmt(date_to)}"
    if date_to is None:
        return f"since {_fmt(date_from)}"
    if date_from == date_to:
        return f"on {_fmt(date_from)}"
    if date_from.day == 1 and date_to == _month_end(date_from.year, date_from.month):
        return f"in {calendar.month_name[date_from.month]} {date_from.year}"
    if (date_from.month, date_from.day) == (1, 1) and (date_to.month, date_to.day) == (12, 31) \
            and date_from.year == date_to.year:
        return f"in {date_from.year}"
    return f"from {_fmt(date_from)} to {_fmt(date_to)}"


def _period(date_from: date | None, date_to: date | None) -> Period:
    return Period(date_from, date_to, label(date_from, date_to))


def _number(token: str | None) -> int:
    if not token:
        return 1
    return int(token) if token.isdigit() else _NUMBER_WORDS.get(token.lower(), 1)


def _month_year(month_token: str, year_token: str | None, today: date) -> tuple[int, int]:
    """Month without a year = its most recent occurrence that is not in the future."""
    month = MONTHS[month_token.lower().rstrip(".")]
    if year_token:
        year = int(year_token)
        return (year + 2000 if year < 100 else year), month
    return (today.year if month <= today.month else today.year - 1), month


def _single(text: str, today: date) -> tuple[date, date] | None:
    """One point in time -> its (first day, last day)."""
    t = text.strip().lower()
    if m := re.fullmatch(r"(\d{4})-(\d{1,2})-(\d{1,2})", t):
        day = date(int(m[1]), int(m[2]), int(m[3]))
        return day, day
    if m := re.fullmatch(r"(\d{1,2})[/.](\d{1,2})[/.](\d{2,4})", t):  # day first, as printed in Zambia
        year = int(m[3]) + (2000 if len(m[3]) == 2 else 0)
        day = date(year, int(m[2]), int(m[1]))
        return day, day
    if m := re.fullmatch(r"(\d{4})-(\d{1,2})", t):
        year, month = int(m[1]), int(m[2])
        return date(year, month, 1), _month_end(year, month)
    if m := re.fullmatch(rf"(\d{{1,2}})(?:st|nd|rd|th)?\s+(?:of\s+)?{_MONTH}\.?,?(?:\s+(\d{{4}}))?", t):
        year, month = _month_year(m[2], m[3], today)
        day = date(year, month, int(m[1]))
        return day, day
    if m := re.fullmatch(rf"{_MONTH}\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?(?:,?\s+(\d{{4}}))?", t):
        year, month = _month_year(m[1], m[3], today)
        day = date(year, month, int(m[2]))
        return day, day
    if m := re.fullmatch(rf"{_MONTH}\.?,?(?:\s+(\d{{4}}|'?\d{{2}}))?", t):
        year, month = _month_year(m[1], m[2].lstrip("'") if m[2] else None, today)
        return date(year, month, 1), _month_end(year, month)
    if m := re.fullmatch(r"(20\d{2})", t):
        year = int(m[1])
        return date(year, 1, 1), date(year, 12, 31)
    if t == "today":
        return today, today
    if t == "yesterday":
        day = today - timedelta(days=1)
        return day, day
    return None


# A single point in time inside free text (longest forms first).
_MONTH_ANY = "(?:" + _MONTH[1:]  # same, non-capturing
_POINT = (rf"\d{{4}}-\d{{1,2}}-\d{{1,2}}|\d{{1,2}}[/.]\d{{1,2}}[/.]\d{{2,4}}|\d{{4}}-\d{{1,2}}|"
          rf"\d{{1,2}}(?:st|nd|rd|th)?\s+(?:of\s+)?{_MONTH_ANY}\.?,?(?:\s+\d{{4}})?|"
          rf"{_MONTH_ANY}\.?\s+\d{{1,2}}(?:st|nd|rd|th)?(?:,?\s+\d{{4}})?|"
          rf"{_MONTH_ANY}\.?,?(?:\s+(?:\d{{4}}|'\d{{2}}))?|20\d{{2}}|today|yesterday")


def resolve(text: str | None, *, today: date | None = None) -> Period | None:
    """The first time expression in ``text`` as a Period; ALL_TIME for "ever"/"all time";
    None when there is no time expression."""
    if not text:
        return None
    today = today or date.today()
    t = " ".join(text.lower().replace("’", "'").split())

    # Ranges: "between August and September", "from 1 Aug to 15 Sep", "since July", "before 2026".
    if m := re.search(rf"\b(?:between|from)\s+({_POINT})\s+(?:and|to|until|till|-)\s+({_POINT})\b", t):
        start, end = _single(m[1], today), _single(m[2], today)
        if start and end:
            return _period(start[0], end[1])
    if m := re.search(rf"\b(?:since|after|from)\s+({_POINT})\b", t):
        if point := _single(m[1], today):
            start = point[0] if m[0].startswith(("since", "from")) else point[1] + timedelta(days=1)
            return _period(start, today)
    if m := re.search(rf"\b(?:before|until|till|up to)\s+({_POINT})\b", t):
        if point := _single(m[1], today):
            end = point[1] if m[0].startswith(("until", "till", "up to")) else point[0] - timedelta(days=1)
            return Period(None, end, label(None, end))

    # Relative: "last 30 days", "past 3 months", "last week", "this month", "last year".
    words = "|".join(_NUMBER_WORDS)
    if m := re.search(rf"\b(?:last|past|previous|recent)\s+(\d+|{words})?\s*(day|week|month|year)s?\b", t):
        count, unit = m[1], m[2]
        if count is None and unit != "day" and not t[m.start():].startswith("past"):
            # "last week/month/year" = the previous calendar period
            if unit == "week":
                start = today - timedelta(days=today.weekday() + 7)
                return _period(start, start + timedelta(days=6))
            if unit == "month":
                start = _add_months(today.replace(day=1), -1)
                return _period(start, _month_end(start.year, start.month))
            return _period(date(today.year - 1, 1, 1), date(today.year - 1, 12, 31))
        n = _number(count)
        if unit == "day":
            start = today - timedelta(days=n - 1)
        elif unit == "week":
            start = today - timedelta(weeks=n) + timedelta(days=1)
        elif unit == "month":
            start = _add_months(today, -n) + timedelta(days=1)
        else:
            start = _add_months(today, -12 * n) + timedelta(days=1)
        return _period(start, today)
    if m := re.search(r"\b(?:this|current)\s+(week|month|year)\b", t):
        start = {"week": today - timedelta(days=today.weekday()), "month": today.replace(day=1),
                 "year": date(today.year, 1, 1)}[m[1]]
        end = {"week": start + timedelta(days=6), "month": _month_end(today.year, today.month),
               "year": date(today.year, 12, 31)}[m[1]]
        return _period(start, end)
    if re.search(r"\b(all\s*time|ever|overall|altogether|in total|so far|all my)\b", t):
        return ALL_TIME

    if m := re.search(rf"\b({_POINT})\b", t):
        # "may" is also a verb: only take it as a month next to a day/year or after "in".
        word = m[1]
        if word == "may" and not re.search(r"\b(in|of|during|for)\s+may\b", t):
            rest = re.sub(r"\bmay\b", " ", t)
            return resolve(rest, today=today) if rest != t else None
        if point := _single(word, today):
            return _period(point[0], point[1])
    return None
