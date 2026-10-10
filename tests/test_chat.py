from datetime import date

import pytest

from app.chat import agent, tools
from app.chat.agent import ToolCall, run
from app.chat.dates import resolve
from app.db import repo
from app.db.database import connect
from app.schemas import LineItem, ReceiptData
from tests.test_api import api  # noqa: F401  (fixture)

TODAY = date(2026, 10, 10)


def call(function, **args) -> ToolCall:
    base = dict(period=None, category=None, vendor=None, item=None, limit=None, group_by=None, status=None,
                receipt_id=None)
    return ToolCall(function=function, **{**base, **args})


def add(conn, n, vendor, day, total, items, currency="ZMW", status="verified"):
    receipt_id = repo.insert_receipt(conn, image_sha256=f"sha{n}", image_path=f"{n}.jpg", original_filename=None)
    receipt = ReceiptData(vendor=vendor, date=day, currency=currency, total=total,
                          items=[LineItem(description=d, quantity=q, amount=a, category=c) for d, q, a, c in items])
    repo.save_extraction(conn, receipt_id, receipt, status=status, warnings=[], notes=[])
    return receipt_id


@pytest.fixture
def conn():
    connection = connect(":memory:")
    add(connection, 1, "MUKUBA SUPERMART", "2026-08-05", 100.0,
        [("Fresh Milk 1L", 2, 40.0, "Grocery"), ("Bread", None, 60.0, "Grocery")])
    add(connection, 2, "MUKUBA SUPERMART", "2026-09-10", 50.0, [("3 x Fresh Milk 1L", 3, 50.0, "Grocery")])
    add(connection, 3, "TASTY BITES CAFE", "2026-09-20", 200.0,
        [("Milk shake", 2, 120.0, "Drinks"), ("Burger", 1, 80.0, "Food")], status="needs_review")
    add(connection, 4, "SHOPZED ONLINE", "2026-10-03", 40.0, [("USB cable", 1, 40.0, "Other")], currency="USD")
    add(connection, 5, "FAILED SHOP", "2026-10-04", 999.0, [("Ghost", 1, 999.0, "Other")], status="failed")
    yield connection
    connection.close()


# ---------------------------------------------------------------- dates

@pytest.mark.parametrize("text, expected", [
    ("How much did I spend in August?", ("2026-08-01", "2026-08-31")),
    ("last month", ("2026-09-01", "2026-09-30")),
    ("this year", ("2026-01-01", "2026-12-31")),
    ("last 30 days", ("2026-09-11", "2026-10-10")),
    ("last week", ("2026-09-28", "2026-10-04")),
    ("since July", ("2026-07-01", "2026-10-10")),
    ("between August and September", ("2026-08-01", "2026-09-30")),
    ("in December", ("2025-12-01", "2025-12-31")),  # most recent December, not a future one
    ("on 3 Oct", ("2026-10-03", "2026-10-03")),
    ("before September", (None, "2026-08-31")),
    ("all time", (None, None)),
])
def test_resolve_periods(text, expected):
    assert resolve(text, today=TODAY).iso() == expected


def test_resolve_ignores_text_without_time_and_may_as_a_verb():
    assert resolve("How much on groceries?", today=TODAY) is None
    assert resolve("What may I have bought at Mukuba market?", today=TODAY) is None
    assert resolve("receipts in May", today=TODAY).iso() == ("2026-05-01", "2026-05-31")


# ---------------------------------------------------------------- queries and answers

def test_total_spend_per_currency_excludes_failed(conn):
    result = run(conn, call("total_spend"), "How much have I spent?", today=TODAY)
    totals = {r["currency"]: r["total"] for r in result.rows}
    assert totals == {"ZMW": 350.0, "USD": 40.0}
    assert result.answer.startswith("You spent K350.00 (3 receipts) and $40.00 (1 receipt)")


def test_total_spend_dates_come_from_the_question_not_the_model(conn):
    # The model's period is ignored: the question's own words decide.
    result = run(conn, call("total_spend", period="this year"), "How much did I spend in September?", today=TODAY)
    assert (result.arguments["date_from"], result.arguments["date_to"]) == ("2026-09-01", "2026-09-30")
    assert result.rows[0]["total"] == 250.0
    assert "in September 2026" in result.answer


def test_invented_period_without_time_words_is_ignored(conn):
    result = run(conn, call("total_spend", period="this month"), "How much have I spent?", today=TODAY)
    assert result.arguments["period"] == "in total"


def test_follow_up_keeps_the_earlier_period(conn):
    history = [{"role": "user", "content": "How much did I spend in September?"},
               {"role": "assistant", "tool": "total_spend", "call": {"period": "in September"}}]
    result = run(conn, call("total_spend", period="in September", category="Drinks"), "And on drinks?",
                 history=history, today=TODAY)
    assert result.arguments["date_from"] == "2026-09-01"
    assert result.rows == [{"currency": "ZMW", "total": 120.0, "receipts": 1, "items": 1}]


def test_category_total_sums_items(conn):
    result = run(conn, call("total_spend", category="Grocery"), "How much on groceries?", today=TODAY)
    assert result.rows[0]["total"] == 150.0 and result.rows[0]["items"] == 3


def test_vendor_is_matched_loosely_and_unknown_vendor_is_explained(conn):
    result = run(conn, call("total_spend", vendor="mukuba"), "How much at mukuba?", today=TODAY)
    assert result.arguments["vendors"] == ["MUKUBA SUPERMART"] and result.rows[0]["total"] == 150.0
    result = run(conn, call("total_spend", vendor="Tasty Bytes"), "How much at Tasty Bytes?", today=TODAY)
    assert result.arguments["vendors"] == ["TASTY BITES CAFE"]
    result = run(conn, call("total_spend", vendor="Shoprite"), "How much at Shoprite?", today=TODAY)
    assert result.rows == [] and "could not find a shop called 'Shoprite'" in result.answer


def test_spend_by_category_and_vendor(conn):
    by_category = run(conn, call("spend_by_category"), "By category?", today=TODAY).rows
    assert [(r["category"], r["amount"]) for r in by_category if r["currency"] == "ZMW"] == [
        ("Grocery", 150.0), ("Drinks", 120.0), ("Food", 80.0)]
    result = run(conn, call("spend_by_vendor", limit=1), "Top shop?", today=TODAY)
    assert [(r["currency"], r["vendor"]) for r in result.rows] == [("USD", "SHOPZED ONLINE"),
                                                                    ("ZMW", "TASTY BITES CAFE")]
    assert result.answer.startswith("Where your money went in total: 1. TASTY BITES CAFE K200.00")


def test_spend_over_time_by_month(conn):
    result = run(conn, call("spend_over_time"), "Monthly spending this year", today=TODAY)
    assert [(r["period"], r["amount"]) for r in result.rows if r["currency"] == "ZMW"] == [
        ("2026-08", 100.0), ("2026-09", 250.0)]
    assert "Aug 2026 K100.00, Sep 2026 K250.00; highest Sep 2026" in result.answer


def test_largest_purchases_limit_from_question(conn):
    result = run(conn, call("largest_purchases"), "What were my 2 biggest purchases?", today=TODAY)
    assert result.arguments["limit"] == 2
    assert [r["description"] for r in result.rows] == ["Milk shake", "Burger"]


def test_search_items_matches_words_and_plurals(conn):
    result = run(conn, call("search_items", item="milk"), "When did I last buy milk?", today=TODAY)
    assert [r["receipt_id"] for r in result.rows] == [3, 2, 1]
    assert "Most recently on 20 Sep 2026 at TASTY BITES CAFE: 2 x Milk shake" in result.answer
    result = run(conn, call("search_items", item="milkshakes"), "Milkshakes?", today=TODAY)
    assert [r["description"] for r in result.rows] == ["Milk shake"]
    result = run(conn, call("search_items", item="fresh milk"), "fresh milk?", today=TODAY)
    assert "3 x Fresh Milk 1L for K50.00" in result.answer  # quantity not repeated


def test_list_receipts_by_status_can_include_failed(conn):
    result = run(conn, call("list_receipts", status="needs_review"), "Which need review?", today=TODAY)
    assert [r["receipt_id"] for r in result.rows] == [3]
    assert result.answer.startswith("1 receipt that needs review: #3 TASTY BITES CAFE K200.00")
    result = run(conn, call("list_receipts", status="failed"), "Which failed?", today=TODAY)
    assert [r["receipt_id"] for r in result.rows] == [5]
    assert len(run(conn, call("list_receipts"), "All receipts", today=TODAY).rows) == 4


def test_receipt_details_id_from_question(conn):
    result = run(conn, call("receipt_details", receipt_id=99), "What was on receipt 1?", today=TODAY)
    assert result.arguments == {"receipt_id": 1}
    assert result.answer == ("Receipt #1: MUKUBA SUPERMART, 5 Aug 2026, total K100.00. "
                             "Items: 2 x Fresh Milk 1L K40.00; Bread K60.00.")
    assert run(conn, call("receipt_details"), "receipt 42", today=TODAY).answer == "There is no receipt 42."


def test_none_gives_help(conn):
    result = run(conn, call("none"), "Hello!", today=TODAY)
    assert result.tool == "none" and "I can answer" in result.answer


def test_search_text_is_a_parameter_not_sql(conn):
    rows = tools.search_items(conn, tools.Filters(), "%' OR 1=1 --")
    assert rows == []


def test_rephrase_kept_only_if_numbers_survive(monkeypatch):
    class Reply:
        def __init__(self, content):
            self.content = content
    monkeypatch.setattr(agent, "chat", lambda *a, **k: Reply("You spent about K300 in total."))
    assert agent.rephrase("q", "You spent K350.00 in total.") == "You spent K350.00 in total."
    monkeypatch.setattr(agent, "chat", lambda *a, **k: Reply("In total, you have spent K350.00."))
    assert agent.rephrase("q", "You spent K350.00 in total.") == "In total, you have spent K350.00."


def test_chat_endpoint(api, monkeypatch):
    monkeypatch.setattr(agent, "choose", lambda question, history=None: (call("none"), {"seconds": 0.1}))
    response = api.post("/api/chat", json={"message": "hi", "history": []})
    assert response.status_code == 200
    body = response.json()
    assert body["tool"] == "none" and body["llm"] == {"seconds": 0.1}

    def down(question, history=None):
        raise agent.LLMError("Cannot reach Ollama")
    monkeypatch.setattr(agent, "choose", down)
    assert api.post("/api/chat", json={"message": "hi"}).status_code == 503


def test_chat_question_set_passes_with_a_perfect_model(monkeypatch):
    """If the model always picked the expected call, every question would score: the expected
    arguments and the hand-computed answers agree with the queries."""
    import json

    from eval import chat_eval
    from eval.run_eval import load_ground_truth

    spec = json.loads(chat_eval.QUESTIONS.read_text(encoding="utf-8"))
    by_question = {q["question"]: q for q in spec["questions"]}

    def oracle(question, history=None):
        e = by_question[question]["expected"]
        limit = e.get("limit")
        return call(e["function"], period="earlier" if history else None, category=e.get("category"),
                    vendor=(e.get("vendors") or [None])[0], item=e.get("item"),
                    limit=limit[0] if isinstance(limit, list) else limit, group_by=e.get("group_by"),
                    status=e.get("status"), receipt_id=e.get("receipt_id")), {}

    monkeypatch.setattr(agent, "choose", oracle)
    report = chat_eval.run(load_ground_truth())
    failures = {k: r["problems"] for k, r in report["questions"].items() if r["problems"]}
    assert failures == {}
    assert report["summary"]["function_and_arguments_accuracy"] == 1.0


def test_vendor_ranking_for_one_named_vendor_is_its_total(conn):
    result = run(conn, call("spend_by_vendor", vendor="Tasty Bites"), "How much have I paid Tasty Bites?", today=TODAY)
    assert result.tool == "total_spend" and result.rows[0]["total"] == 200.0
