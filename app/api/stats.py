"""Spending summaries for the dashboard.

Amounts in different currencies are never added together: every summary is for
one currency (by default the most common one).
"""

import sqlite3
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.api.deps import get_conn

router = APIRouter(prefix="/api/stats", tags=["stats"])

Conn = Annotated[sqlite3.Connection, Depends(get_conn)]

# Failed receipts have no trustworthy numbers; everything else counts.
_COUNTED = "r.status IN ('verified', 'needs_review')"


def summary(conn: sqlite3.Connection, *, date_from: str | None = None, date_to: str | None = None,
            currency: str | None = None) -> dict:
    currencies = [dict(r) for r in conn.execute(
        f"""SELECT coalesce(r.currency, 'unknown') AS currency, count(*) AS receipts
            FROM receipts r WHERE {_COUNTED} GROUP BY 1 ORDER BY 2 DESC""")]
    currency = currency or (currencies[0]["currency"] if currencies else None)

    where, params = [_COUNTED, "coalesce(r.currency, 'unknown') = ?"], [currency]
    if date_from:
        where.append("r.date >= ?"); params.append(date_from)
    if date_to:
        where.append("r.date <= ?"); params.append(date_to)
    cond = " AND ".join(where)

    totals = conn.execute(
        f"""SELECT count(*) AS receipts, coalesce(sum(r.total), 0) AS total,
                   sum(r.status = 'needs_review') AS needs_review,
                   min(r.date) AS first_date, max(r.date) AS last_date
            FROM receipts r WHERE {cond}""", params).fetchone()
    by_category = conn.execute(
        f"""SELECT i.category, round(sum(i.amount), 2) AS amount, count(*) AS items
            FROM line_items i JOIN receipts r ON r.id = i.receipt_id
            WHERE {cond} GROUP BY i.category ORDER BY amount DESC""", params).fetchall()
    by_vendor = conn.execute(
        f"""SELECT coalesce(r.vendor, 'Unknown') AS vendor, round(sum(r.total), 2) AS amount, count(*) AS receipts
            FROM receipts r WHERE {cond} GROUP BY 1 ORDER BY amount DESC LIMIT 10""", params).fetchall()
    by_month = conn.execute(
        f"""SELECT substr(r.date, 1, 7) AS month, round(sum(r.total), 2) AS amount, count(*) AS receipts
            FROM receipts r WHERE {cond} AND r.date IS NOT NULL GROUP BY 1 ORDER BY 1""", params).fetchall()
    return {
        "currency": currency,
        "currencies": currencies,
        "receipts": totals["receipts"],
        "total": round(totals["total"], 2),
        "needs_review": totals["needs_review"] or 0,
        "first_date": totals["first_date"],
        "last_date": totals["last_date"],
        "by_category": [dict(r) for r in by_category],
        "by_vendor": [dict(r) for r in by_vendor],
        "by_month": [dict(r) for r in by_month],
        "note": "Category amounts are item amounts (as printed, usually including tax); "
                "totals are receipt totals.",
    }


@router.get("/summary")
def get_summary(conn: Conn, date_from: Annotated[str | None, Query(alias="from")] = None,
                date_to: Annotated[str | None, Query(alias="to")] = None, currency: str | None = None) -> dict:
    return summary(conn, date_from=date_from, date_to=date_to, currency=currency)
