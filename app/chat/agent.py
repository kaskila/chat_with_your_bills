"""Answer a question about the stored receipts.

1. qwen3:4b picks one query function and its arguments. Its reply is forced into a JSON
   schema whose ``function`` is an enum, so it cannot invent a function.
2. Python checks the arguments: dates come from the question's own words (``dates.py``),
   vendor names are matched to stored ones, numbers are clamped.
3. The function runs fixed SQL; the answer is written from the rows by a template.
4. Optionally the model rewords the answer; the rewording is only kept if every number survives.
"""

import json
import re
import sqlite3
import time
from dataclasses import dataclass, field
from datetime import date
from typing import Literal

from pydantic import BaseModel, ValidationError

from app.chat import tools
from app.chat.dates import ALL_TIME, Period, resolve
from app.config import get_settings
from app.llm.client import LLMError, chat
from app.llm.prompts import CHAT_SYSTEM
from app.schemas import Category

Function = Literal["total_spend", "spend_by_category", "spend_by_vendor", "spend_over_time",
                   "largest_purchases", "search_items", "list_receipts", "receipt_details", "none"]


class ToolCall(BaseModel):
    # Field order is generation order: the function first.
    function: Function
    period: str | None
    category: Category | None
    vendor: str | None
    item: str | None
    limit: int | None
    group_by: Literal["month", "week", "day"] | None
    status: Literal["verified", "needs_review", "failed"] | None
    receipt_id: int | None


CALL_SCHEMA = ToolCall.model_json_schema()

# What each function uses; other arguments the model fills in are ignored.
USES = {
    "total_spend": {"period", "category", "vendor"},
    "spend_by_category": {"period", "vendor"},
    "spend_by_vendor": {"period", "category", "limit"},
    "spend_over_time": {"period", "category", "vendor", "group_by"},
    "largest_purchases": {"period", "category", "vendor", "limit"},
    "search_items": {"period", "item", "vendor"},
    "list_receipts": {"period", "vendor", "status", "category"},
    "receipt_details": {"receipt_id"},
    "none": set(),
}

HELP = ("I can answer questions about your stored receipts, for example: how much you spent in a month or "
        "on a category, spending by category, by shop or over time, your biggest purchases, when you bought "
        "a product, which receipts need review, or what was on a receipt.")


@dataclass
class ChatAnswer:
    answer: str
    tool: str
    arguments: dict
    rows: list[dict] = field(default_factory=list)
    seconds: float = 0.0
    notes: list[str] = field(default_factory=list)
    llm: dict | None = None

    def to_dict(self) -> dict:
        return {"answer": self.answer, "tool": self.tool, "arguments": self.arguments, "rows": self.rows,
                "seconds": round(self.seconds, 2), "notes": self.notes, "llm": self.llm}


# ---------------------------------------------------------------- 1. choose the function

def _messages(question: str, history: list[dict]) -> list[dict]:
    """System prompt, then the last few questions with the call chosen for each."""
    turns = get_settings().chat_history_turns
    messages = [{"role": "system", "content": CHAT_SYSTEM}]
    for turn in history[-turns * 2:] if turns else []:
        if turn.get("role") == "user":
            messages.append({"role": "user", "content": str(turn.get("content", ""))})
        elif turn.get("role") == "assistant" and turn.get("tool"):
            call = {"function": turn["tool"], **(turn.get("call") or {})}
            messages.append({"role": "assistant", "content": json.dumps(call)})
    messages.append({"role": "user", "content": question})
    return messages


def choose(question: str, history: list[dict] | None = None) -> tuple[ToolCall, dict]:
    s = get_settings()
    result = chat(s.chat_model or s.extract_model, _messages(question, history or []), format=CALL_SCHEMA,
                  timeout=s.chat_timeout_s, num_predict=200)
    try:
        call = ToolCall.model_validate(json.loads(result.content))
    except (json.JSONDecodeError, ValidationError) as error:
        raise LLMError(f"The model returned an invalid function call: {error}") from error
    return call, result.stats()


# ---------------------------------------------------------------- 2. check the arguments

def _period(question: str, call: ToolCall, history: list[dict], today: date) -> Period:
    """Dates come from the user's words, never from the model. A question without a time
    keeps the time of an earlier question only when the model says it carries over."""
    if found := resolve(question, today=today):
        return found
    if call.period:
        for turn in reversed(history):
            if turn.get("role") == "user" and (found := resolve(str(turn.get("content", "")), today=today)):
                return found
    return ALL_TIME


def _receipt_id(question: str, call: ToolCall) -> int | None:
    if m := re.search(r"(?:\breceipt|#|\bnumber|\bno\.?|\bid)\s*#?\s*(\d+)", question, re.IGNORECASE):
        return int(m[1])
    return call.receipt_id


def _limit(question: str, call: ToolCall, default: int) -> int:
    n = call.limit
    if n is None and (m := re.search(r"\b(?:top|biggest|largest|first|last)\s+(\d+)\b|\b(\d+)\s+(?:biggest|largest|most)",
                                     question, re.IGNORECASE)):
        n = int(m[1] or m[2])
    return max(1, min(n or default, tools.MAX_LIMIT))


# ---------------------------------------------------------------- 3. answer templates

_SYMBOLS = {"ZMW": "K", "USD": "$", "EUR": "€", "GBP": "£"}


def money(value: float | None, currency: str | None) -> str:
    if value is None:
        return "–"
    symbol = _SYMBOLS.get(currency or "")
    text = f"{value:,.2f}"
    return f"{symbol}{text}" if symbol else text if currency in (None, "unknown") else f"{text} {currency}"


def _day(iso: str | None) -> str:
    if not iso:
        return "an unknown date"
    d = date.fromisoformat(iso)
    return f"{d.day} {d.strftime('%b')} {d.year}"


def _n(count: int, word: str) -> str:
    return f"{count} {word}{'' if count == 1 else 's'}"


def _join(parts: list[str]) -> str:
    return parts[0] if len(parts) == 1 else ", ".join(parts[:-1]) + " and " + parts[-1]


def _scope(args: dict) -> str:
    """' on Grocery at MUKUBA SUPERMART in August 2026'"""
    text = ""
    if args.get("category"):
        text += f" on {args['category']}"
    if args.get("vendors"):
        text += f" at {_join(args['vendors'])}"
    return f"{text} {args['period']}"


def _by_currency(rows: list[dict], order: list[str]) -> dict[str, list[dict]]:
    """Rows per currency, the user's main currency (most receipts) first."""
    groups: dict[str, list[dict]] = {}
    for row in rows:
        groups.setdefault(row["currency"], []).append(row)
    rank = {currency: i for i, currency in enumerate(order)}
    return dict(sorted(groups.items(), key=lambda kv: rank.get(kv[0], len(rank))))


def _sections(parts: dict[str, str]) -> str:
    """'main text' or 'main text. In USD: other text'"""
    texts = list(parts.items())
    return texts[0][1] + "".join(f". In {currency}: {text}" for currency, text in texts[1:])


def _qty(row: dict) -> str:
    """'3 x ' unless the quantity is 1 or already part of the description ('3 x Fresh Milk')."""
    q = row.get("quantity")
    if not q or q == 1 or re.match(r"^\d+(\.\d+)?\s*[x@*]", row.get("description") or "", re.I):
        return ""
    return f"{q:g} x "


def _period_name(key: str) -> str:
    if re.fullmatch(r"\d{4}-\d{2}", key):
        return date.fromisoformat(key + "-01").strftime("%b %Y")
    return _day(key) if re.fullmatch(r"\d{4}-\d{2}-\d{2}", key) else key


def answer_total(rows, args, order):
    if not rows:
        return f"I found no spending{_scope(args)}."
    parts = []
    rows = [r for group in _by_currency(rows, order).values() for r in group]
    for row in rows:
        counted = _n(row["items"], "item") + " on " + _n(row["receipts"], "receipt") if "items" in row \
            else _n(row["receipts"], "receipt")
        parts.append(f"{money(row['total'], row['currency'])} ({counted})")
    text = f"You spent {_join(parts)}{_scope(args)}."
    missing = sum(row.get("without_total") or 0 for row in rows)
    if missing:
        text += f" {_n(missing, 'receipt')} without a total {'is' if missing == 1 else 'are'} not included."
    return text


def answer_by_category(rows, args, order):
    if not rows:
        return f"I found no spending{_scope(args)}."
    parts = {}
    for currency, group in _by_currency(rows, order).items():
        whole = sum(r["amount"] for r in group) or 1
        top = [f"{r['category']} {money(r['amount'], currency)} ({r['amount'] / whole:.0%})" for r in group[:3]]
        parts[currency] = f"most went on {_join(top)}" + (f", out of {money(whole, currency)} in item amounts"
                                                          if len(group) > 3 else "")
    return f"By category{_scope(args)}: {_sections(parts)}."


def answer_by_vendor(rows, args, order):
    if not rows:
        return f"I found no spending{_scope(args)}."
    parts = {currency: "; ".join(f"{r['rank']}. {r['vendor']} {money(r['amount'], currency)} "
                                 f"({_n(r['receipts'], 'receipt')})" for r in group)
             for currency, group in _by_currency(rows, order).items()}
    return f"Where your money went{_scope(args)}: {_sections(parts)}."


def answer_over_time(rows, args, order):
    if not rows:
        return f"I found no spending{_scope(args)}."
    unit = args.get("group_by", "month")
    parts = {}
    for currency, group in _by_currency(rows, order).items():
        series = ", ".join(f"{_period_name(r['period'])} {money(r['amount'], currency)}" for r in group[:12])
        if len(group) > 12:
            series += f" … ({len(group)} {unit}s in all, see the table)"
        top = max(group, key=lambda r: r["amount"])
        if len(group) > 1:
            series += f"; highest {_period_name(top['period'])}"
        parts[currency] = series
    return f"Spending per {unit}{_scope(args)}: {_sections(parts)}."


def answer_largest(rows, args, order):
    if not rows:
        return f"I found no purchases{_scope(args)}."
    listed = [f"{i}. {r['description']} {money(r['amount'], r['currency'])} ({r['vendor'] or 'unknown shop'}, "
              f"{_day(r['date'])})" for i, r in enumerate(rows, 1)]
    return f"Your {_n(len(rows), 'biggest purchase')}{_scope(args)}: " + "; ".join(listed) + "."


def answer_search(rows, args, order):
    what = f"'{args['item']}'"
    if not rows:
        return f"I found no items matching {what}{_scope(args)}."
    last = rows[0]
    text = (f"Found {_n(len(rows), 'purchase')} of {what}{_scope(args)}. Most recently on {_day(last['date'])} "
            f"at {last['vendor'] or 'an unknown shop'}: {_qty(last)}{last['description']} for "
            f"{money(last['amount'], last['currency'])}.")
    if len(rows) > 1:
        totals = [money(sum(r["amount"] for r in g), c) for c, g in _by_currency(rows, order).items()]
        text += f" In all: {_join(totals)}."
    return text


def answer_list(rows, args, order):
    status = args.get("status")
    one = len(rows) == 1
    kind = {"needs_review": f" that need{'s' if one else ''} review",
            "verified": f" that {'is' if one else 'are'} verified", "failed": " that failed"}.get(status, "")
    scope = _scope(args).removesuffix(" in total")
    if not rows:
        return f"I found no receipts{kind}{scope}."
    text = f"{_n(len(rows), 'receipt')}{kind}{scope}"
    if len(rows) >= tools.MAX_LIMIT:
        text = f"The latest {tools.MAX_LIMIT} receipts{kind}{scope}"
    if len(rows) <= 5:
        listed = [f"#{r['receipt_id']} {r['vendor'] or 'unknown shop'} {money(r['total'], r['currency'])} "
                  f"({_day(r['date'])})" for r in rows]
        return f"{text}: " + "; ".join(listed) + "."
    totals = [money(sum(r["total"] or 0 for r in g), c) for c, g in _by_currency(rows, order).items()]
    return f"{text}, totalling {_join(totals)}. They are listed below."


def answer_details(rows, args, order):
    if not rows:
        return f"There is no receipt {args['receipt_id']}."
    r = rows[0]
    status = {"needs_review": " (needs review)", "failed": " (could not be read)"}.get(r["status"], "")
    text = (f"Receipt #{r['receipt_id']}: {r['vendor'] or 'unknown shop'}, {_day(r['date'])}, "
            f"total {money(r['total'], r['currency'])}{status}.")
    items = [f"{_qty(x)}{x['description']} {money(x['amount'], r['currency'])}" for x in rows if x["description"]]
    return text + (f" Items: {'; '.join(items)}." if items else " No items were read.")


# ---------------------------------------------------------------- 4. putting it together

def run(conn: sqlite3.Connection, call: ToolCall, question: str, *, history: list[dict] | None = None,
        today: date | None = None) -> ChatAnswer:
    """Validate the call, run the query, write the answer (no LLM involved: testable)."""
    history, today = history or [], today or date.today()
    if call.function == "spend_by_vendor" and call.vendor:
        # A ranking of one named vendor is that vendor's total ("How much have I paid Quickride?").
        call = call.model_copy(update={"function": "total_spend"})
    name, uses = call.function, USES[call.function]
    if name == "none":
        return ChatAnswer(HELP, "none", {})

    args: dict = {}
    filters = tools.Filters()
    if "period" in uses:
        period = _period(question, call, history, today)
        filters.date_from, filters.date_to = period.iso()
        args.update(date_from=filters.date_from, date_to=filters.date_to, period=period.label)
    if "category" in uses and call.category:
        filters.category = args["category"] = call.category
    if "vendor" in uses and call.vendor:
        match = tools.match_vendor(conn, call.vendor)
        if match.missing:
            known = tools.known_vendors(conn)
            text = f"I could not find a shop called '{call.vendor}'."
            if known:
                text += f" Known shops include {_join(known)}."
            return ChatAnswer(text, name, {**args, "vendor": call.vendor})
        filters.vendors = args["vendors"] = match.names
        args["vendor"] = call.vendor

    if name == "total_spend":
        rows, text = tools.total_spend(conn, filters), answer_total
    elif name == "spend_by_category":
        rows, text = tools.spend_by_category(conn, filters), answer_by_category
    elif name == "spend_by_vendor":
        args["limit"] = _limit(question, call, 5)
        rows, text = tools.spend_by_vendor(conn, filters, args["limit"]), answer_by_vendor
    elif name == "spend_over_time":
        args["group_by"] = call.group_by or ("week" if re.search(r"\bweek", question, re.I) else
                                             "day" if re.search(r"\b(daily|per day|each day)\b", question, re.I)
                                             else "month")
        rows, text = tools.spend_over_time(conn, filters, args["group_by"]), answer_over_time
    elif name == "largest_purchases":
        args["limit"] = _limit(question, call, 5)
        rows, text = tools.largest_purchases(conn, filters, args["limit"]), answer_largest
    elif name == "search_items":
        if not call.item or not call.item.strip():
            return ChatAnswer("Which product should I look for?", name, args)
        args["item"] = call.item.strip()
        rows, text = tools.search_items(conn, filters, args["item"]), answer_search
    elif name == "list_receipts":
        if call.status:
            args["status"] = call.status
        rows, text = tools.list_receipts(conn, filters, call.status), answer_list
    else:  # receipt_details
        receipt_id = _receipt_id(question, call)
        if receipt_id is None:
            return ChatAnswer("Which receipt? Give its number, e.g. 'What was on receipt 12?'", name, {})
        args["receipt_id"] = receipt_id
        rows, text = tools.receipt_details(conn, receipt_id), answer_details
    return ChatAnswer(text(rows, args, tools.currencies(conn)), name, args, rows)


def _numbers(text: str) -> set[str]:
    return set(re.findall(r"\d[\d,]*(?:\.\d+)?", text))


def rephrase(question: str, answer: str) -> str:
    """Reword the template answer; keep the template unless every number survives unchanged."""
    s = get_settings()
    result = chat(s.chat_model or s.extract_model, [
        {"role": "system", "content": "Rewrite the answer to the user's question in one or two friendly "
                                      "sentences. Keep every number, amount and date exactly as written."},
        {"role": "user", "content": f"Question: {question}\nAnswer: {answer}"},
    ], timeout=s.chat_timeout_s, num_predict=200)
    reworded = result.content.strip()
    return reworded if reworded and _numbers(answer) <= _numbers(reworded) else answer


def ask(conn: sqlite3.Connection, question: str, *, history: list[dict] | None = None,
        today: date | None = None) -> ChatAnswer:
    started = time.perf_counter()
    question = question.strip()
    call, stats = choose(question, history)
    result = run(conn, call, question, history=history, today=today)
    result.llm = stats
    result.arguments["call"] = call.model_dump(exclude_none=True, exclude={"function"})
    if get_settings().chat_rephrase and result.rows:
        result.answer = rephrase(question, result.answer)
    result.seconds = time.perf_counter() - started
    return result
