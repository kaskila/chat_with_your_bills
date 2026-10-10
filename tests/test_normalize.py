import pytest

from app.pipeline.normalize import compact_id, to_hhmm, to_iso_date, to_number


@pytest.mark.parametrize("raw, expected", [
    (50, 50.0),
    ("K50", 50.0),
    ("K 0", 0.0),
    ("1,470.00", 1470.0),
    ("ZMW 126.98", 126.98),
    ("160.00 ^#", 160.0),
    ("126,98", 126.98),
    ("Unknown", None),
    ("", None),
    (None, None),
    ("no digits", None),
])
def test_to_number(raw, expected):
    assert to_number(raw) == expected


@pytest.mark.parametrize("raw, expected", [
    ("27/08/2026", "2026-08-27"),
    ("2026/8/28", "2026-08-28"),
    ("21 Jul, 2026", "2026-07-21"),
    ("2026-07-21", "2026-07-21"),
    ("03/04/2026", "2026-04-03"),  # day first
    ("Unknown", None),
    ("not a date", None),
])
def test_to_iso_date(raw, expected):
    assert to_iso_date(raw) == expected


@pytest.mark.parametrize("raw, expected", [
    ("6:55:44 pm", "18:55"),
    ("10:48:00", "10:48"),
    ("11:25", "11:25"),
    ("12:05 am", "00:05"),
    ("12:30 PM", "12:30"),
    ("25:00", None),
    (None, None),
])
def test_to_hhmm(raw, expected):
    assert to_hhmm(raw) == expected


def test_compact_id():
    assert compact_id(" gph 35206 ") == "GPH35206"
    assert compact_id("Unknown") is None
