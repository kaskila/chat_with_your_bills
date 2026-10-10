"""The fixed query functions the chat can call.

The model never writes SQL: it picks one of these functions and its arguments,
which are validated here and passed as SQL parameters. Every function returns
rows (plain dicts) per currency, so amounts in different currencies are never
added together. Failed receipts are never counted (as on the dashboard).
"""

import difflib
import re
import sqlite3
from dataclasses import dataclass, field

from app.schemas import CATEGORIES

COUNTED = "r.status IN ('verified', 'needs_review')"
STATUSES = ("verified", "needs_review", "failed", "processing")
MAX_LIMIT = 50


@dataclass
class Filters:
    date_from: str | None = None
    date_to: str | None = None
    category: str | None = None
    vendors: list[str] | None = None  # exact vendor names (resolved from what the user typed)

    def where(self, *, items: bool = False) -> tuple[str, list]:
        """SQL condition on receipts r (and line_items i when ``items``)."""
        where, params = [COUNTED], []
        if self.date_from:
            where.append("r.date >= ?"); params.append(self.date_from)
        if self.date_to:
            where.append("r.date <= ?"); params.append(self.date_to)
        if self.vendors:
            where.append(f"r.vendor IN ({', '.join('?' * len(self.vendors))})"); params += self.vendors
        if self.category:
            if items:
                where.append("i.category = ?")
            else:  # receipts that contain at least one item of the category
                where.append("EXISTS (SELECT 1 FROM line_items c WHERE c.receipt_id = r.id AND c.category = ?)")
            params.append(self.category)
        return " AND ".join(where), params


@dataclass
class VendorMatch:
    names: list[str] = field(default_factory=list)
    asked: str | None = None

    @property
    def missing(self) -> bool:
        return bool(self.asked) and not self.names


def _squash(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


def match_vendor(conn: sqlite3.Connection, asked: str | None) -> VendorMatch:
    """Stored vendor names for what the user typed: substring either way, ignoring case and
    punctuation ("mama nkandu" -> "MAMA NKANDU'S KITCHEN"), else the closest spelling."""
    if not asked or not asked.strip():
        return VendorMatch()
    known = [row[0] for row in conn.execute("SELECT DISTINCT vendor FROM receipts WHERE vendor IS NOT NULL")]
    key = _squash(asked)
    if not key:
        return VendorMatch(asked=asked)
    names = [v for v in known if key in _squash(v) or (len(_squash(v)) >= 4 and _squash(v) in key)]
    if not names:
        squashed = {_squash(v): v for v in known}
        names = [squashed[s] for s in difflib.get_close_matches(key, list(squashed), n=3, cutoff=0.75)]
        if not names:  # one word of a longer name, misspelt ("sunrize" -> "SUNRISE BAKERY")
            for v in known:
                words = [_squash(w) for w in v.split() if len(w) >= 4]
                if difflib.get_close_matches(key, words, n=1, cutoff=0.8):
                    names.append(v)
    return VendorMatch(names=sorted(names), asked=asked)


def known_vendors(conn: sqlite3.Connection, limit: int = 8) -> list[str]:
    rows = conn.execute(f"""SELECT r.vendor FROM receipts r WHERE {COUNTED} AND r.vendor IS NOT NULL
                            GROUP BY r.vendor ORDER BY count(*) DESC, r.vendor LIMIT ?""", (limit,))
    return [row[0] for row in rows]


def currencies(conn: sqlite3.Connection) -> list[str]:
    """Currencies by number of receipts: the first is the user's main currency."""
    return [row[0] for row in conn.execute(
        f"SELECT coalesce(r.currency, 'unknown') FROM receipts r WHERE {COUNTED} GROUP BY 1 ORDER BY count(*) DESC")]


def _rows(cursor: sqlite3.Cursor) -> list[dict]:
    return [dict(row) for row in cursor]


# ---------------------------------------------------------------- the functions

def total_spend(conn: sqlite3.Connection, f: Filters) -> list[dict]:
    """Total per currency. With a category, the sum of that category's item amounts."""
    if f.category:
        cond, params = f.where(items=True)
        return _rows(conn.execute(
            f"""SELECT coalesce(r.currency, 'unknown') AS currency, round(sum(i.amount), 2) AS total,
                       count(DISTINCT r.id) AS receipts, count(*) AS items
                FROM line_items i JOIN receipts r ON r.id = i.receipt_id
                WHERE {cond} GROUP BY 1 ORDER BY receipts DESC""", params))
    cond, params = f.where()
    return _rows(conn.execute(
        f"""SELECT coalesce(r.currency, 'unknown') AS currency, round(coalesce(sum(r.total), 0), 2) AS total,
                   count(*) AS receipts, sum(r.total IS NULL) AS without_total
            FROM receipts r WHERE {cond} GROUP BY 1 ORDER BY receipts DESC""", params))


def spend_by_category(conn: sqlite3.Connection, f: Filters) -> list[dict]:
    cond, params = f.where(items=True)
    return _rows(conn.execute(
        f"""SELECT coalesce(r.currency, 'unknown') AS currency, i.category, round(sum(i.amount), 2) AS amount,
                   count(*) AS items
            FROM line_items i JOIN receipts r ON r.id = i.receipt_id
            WHERE {cond} GROUP BY 1, 2 ORDER BY 1, amount DESC""", params))


def spend_by_vendor(conn: sqlite3.Connection, f: Filters, limit: int = 5) -> list[dict]:
    cond, params = f.where()
    return _rows(conn.execute(
        f"""SELECT * FROM (
                SELECT coalesce(r.currency, 'unknown') AS currency, coalesce(r.vendor, 'Unknown') AS vendor,
                       round(sum(r.total), 2) AS amount, count(*) AS receipts,
                       row_number() OVER (PARTITION BY coalesce(r.currency, 'unknown')
                                          ORDER BY sum(r.total) DESC) AS rank
                FROM receipts r WHERE {cond} AND r.total IS NOT NULL GROUP BY 1, 2)
            WHERE rank <= ? ORDER BY currency, rank""", [*params, limit]))


def spend_over_time(conn: sqlite3.Connection, f: Filters, group_by: str = "month") -> list[dict]:
    period = {"month": "substr(r.date, 1, 7)", "week": "strftime('%Y-W%W', r.date)",
              "day": "r.date"}[group_by]
    if f.category:
        cond, params = f.where(items=True)
        source, amount = "line_items i JOIN receipts r ON r.id = i.receipt_id", "sum(i.amount)"
    else:
        cond, params = f.where()
        source, amount = "receipts r", "coalesce(sum(r.total), 0)"
    return _rows(conn.execute(
        f"""SELECT {period} AS period, coalesce(r.currency, 'unknown') AS currency,
                   round({amount}, 2) AS amount, count(DISTINCT r.id) AS receipts
            FROM {source} WHERE {cond} AND r.date IS NOT NULL GROUP BY 1, 2 ORDER BY 1, 2""", params))


def largest_purchases(conn: sqlite3.Connection, f: Filters, limit: int = 5) -> list[dict]:
    """The most expensive single items (line amounts)."""
    cond, params = f.where(items=True)
    return _rows(conn.execute(
        f"""SELECT i.description, i.amount, i.quantity, i.category, coalesce(r.currency, 'unknown') AS currency,
                   r.vendor, r.date, r.id AS receipt_id
            FROM line_items i JOIN receipts r ON r.id = i.receipt_id
            WHERE {cond} ORDER BY i.amount DESC LIMIT ?""", [*params, limit]))


def _item_terms(text: str) -> list[str]:
    """Words to look for: "milkshakes" also finds "Milk shake"; very short words are ignored."""
    words = [w for w in re.findall(r"[a-z0-9]+", text.lower()) if len(w) >= 3] or [text.lower().strip()]
    return [w[:-1] if len(w) > 4 and w.endswith("s") and not w.endswith("ss") else w for w in words]


def search_items(conn: sqlite3.Connection, f: Filters, text: str, limit: int = 20) -> list[dict]:
    """Items whose description contains every word of ``text`` (spaces ignored), newest first."""
    cond, params = f.where(items=True)
    for term in _item_terms(text):
        cond += " AND replace(lower(i.description), ' ', '') LIKE ? ESCAPE '\\'"
        params.append("%" + term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%")
    return _rows(conn.execute(
        f"""SELECT i.description, i.quantity, i.amount, i.category, coalesce(r.currency, 'unknown') AS currency,
                   r.vendor, r.date, r.id AS receipt_id
            FROM line_items i JOIN receipts r ON r.id = i.receipt_id
            WHERE {cond} ORDER BY r.date DESC, r.id DESC LIMIT ?""", [*params, limit]))


def list_receipts(conn: sqlite3.Connection, f: Filters, status: str | None = None,
                  limit: int = MAX_LIMIT) -> list[dict]:
    cond, params = f.where()
    if status:  # an explicit status may also ask for failed ones
        cond = cond.replace(COUNTED, "r.status = ?", 1)
        params.insert(0, status)
    return _rows(conn.execute(
        f"""SELECT r.id AS receipt_id, r.date, r.vendor, r.total, coalesce(r.currency, 'unknown') AS currency,
                   r.status, (SELECT count(*) FROM line_items i WHERE i.receipt_id = r.id) AS items
            FROM receipts r WHERE {cond} ORDER BY r.date DESC, r.id DESC LIMIT ?""", [*params, limit]))


def receipt_details(conn: sqlite3.Connection, receipt_id: int) -> list[dict]:
    """One row per item, each carrying the receipt's header fields; a receipt without items
    gives one row with description None."""
    return _rows(conn.execute(
        """SELECT r.id AS receipt_id, r.vendor, r.date, r.time, coalesce(r.currency, 'unknown') AS currency,
                  r.total, r.tax, r.status, r.payment_method,
                  i.description, i.quantity, i.amount, i.category
           FROM receipts r LEFT JOIN line_items i ON i.receipt_id = r.id
           WHERE r.id = ? ORDER BY i.position""", (receipt_id,)))


# ---------------------------------------------------------------- descriptions for the model

TOOLS = {
    "total_spend": "Total amount spent, optionally in a period, for one category or at one vendor. "
                   "'How much did I spend in August?', 'How much on groceries?', 'What did I spend at Mukuba?'",
    "spend_by_category": "Spending split by category. 'Break down my spending by category this month.'",
    "spend_by_vendor": "Where the most money went, ranked by shop/vendor. 'Where do I spend the most?', "
                       "'Top 3 shops last month.'",
    "spend_over_time": "Spending per month, week or day, to see a trend. 'Show my monthly spending this year.', "
                       "'Weekly spending since August.'",
    "largest_purchases": "The most expensive individual items bought. 'What were my 5 biggest purchases?'",
    "search_items": "Find a product by name: when/where it was bought and for how much. "
                    "'When did I last buy milk?', 'How much have I spent on bread?'",
    "list_receipts": "List receipts, optionally by period, vendor or status (verified, needs_review, failed); "
                     "also counts them. 'Show receipts from Grand Palace.', 'Which receipts need review?', "
                     "'How many receipts do I have?'",
    "receipt_details": "Everything on one receipt, by its number/id. 'What was on receipt 12?'",
    "none": "The question is not about the stored receipts or spending (greetings, help, other topics).",
}

CATEGORY_HELP = ", ".join(CATEGORIES)
