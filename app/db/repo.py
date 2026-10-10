"""Reading and writing receipts. All SQL lives here, parameterized."""

import json
import sqlite3
from typing import Any

from app.schemas import LineItem, ReceiptData

_RECEIPT_FIELDS = (
    "vendor", "vendor_tax_id", "receipt_no", "date", "time", "currency", "subtotal", "discount",
    "service_charge", "tax", "total", "amount_paid", "change", "payment_method",
)
_JSON_COLUMNS = ("warnings", "notes", "timings", "models")


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    data = dict(row)
    for column in _JSON_COLUMNS:
        if column in data and data[column] is not None:
            data[column] = json.loads(data[column])
    data["user_edited"] = bool(data.get("user_edited"))
    return data


def find_by_hash(conn: sqlite3.Connection, sha256: str) -> dict | None:
    row = conn.execute("SELECT id, status FROM receipts WHERE image_sha256 = ?", (sha256,)).fetchone()
    return dict(row) if row else None


def find_duplicates(conn: sqlite3.Connection, receipt: ReceiptData, exclude_id: int | None = None) -> list[int]:
    """Other receipts with the same vendor, receipt number and total (a re-photographed receipt)."""
    if not (receipt.vendor and receipt.receipt_no and receipt.total is not None):
        return []
    rows = conn.execute(
        """SELECT id FROM receipts
           WHERE lower(vendor) = lower(?) AND receipt_no = ? AND abs(total - ?) < 0.005 AND id != ?""",
        (receipt.vendor, receipt.receipt_no, receipt.total, exclude_id or -1),
    ).fetchall()
    return [r["id"] for r in rows]


def _write_items(conn: sqlite3.Connection, receipt_id: int, items: list[LineItem]) -> None:
    conn.execute("DELETE FROM line_items WHERE receipt_id = ?", (receipt_id,))
    conn.executemany(
        """INSERT INTO line_items (receipt_id, position, description, quantity, unit_price, amount, category)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        [(receipt_id, i, it.description, it.quantity, it.unit_price, it.amount, it.category)
         for i, it in enumerate(items)],
    )


def insert_receipt(conn: sqlite3.Connection, *, image_sha256: str, image_path: str,
                   original_filename: str | None, status: str = "processing") -> int:
    with conn:
        cur = conn.execute(
            "INSERT INTO receipts (image_sha256, image_path, original_filename, status) VALUES (?, ?, ?, ?)",
            (image_sha256, image_path, original_filename, status),
        )
    return cur.lastrowid


def save_extraction(conn: sqlite3.Connection, receipt_id: int, receipt: ReceiptData, *, status: str,
                    warnings: list[dict], notes: list[str], ocr_text_rapid: str | None = None,
                    ocr_text_vlm: str | None = None, ocr_confidence: float | None = None,
                    extraction_raw: str | None = None, timings: dict | None = None,
                    models: dict | None = None, user_edited: bool | None = None) -> None:
    """Store pipeline (or user-edited) data for a receipt and replace its items, in one transaction."""
    values = {f: getattr(receipt, f) for f in _RECEIPT_FIELDS}
    values.update(status=status, warnings=json.dumps(warnings), notes=json.dumps(notes), error=None)
    optional = dict(ocr_text_rapid=ocr_text_rapid, ocr_text_vlm=ocr_text_vlm, ocr_confidence=ocr_confidence,
                    extraction_raw=extraction_raw,
                    timings=json.dumps(timings) if timings is not None else None,
                    models=json.dumps(models) if models is not None else None,
                    user_edited=int(user_edited) if user_edited is not None else None)
    values.update({k: v for k, v in optional.items() if v is not None})
    assignments = ", ".join(f"{column} = ?" for column in values)
    with conn:
        conn.execute(f"UPDATE receipts SET {assignments}, updated_at = datetime('now') WHERE id = ?",
                     (*values.values(), receipt_id))
        _write_items(conn, receipt_id, receipt.items)


def mark_failed(conn: sqlite3.Connection, receipt_id: int, error: str) -> None:
    with conn:
        conn.execute("UPDATE receipts SET status = 'failed', error = ?, updated_at = datetime('now') WHERE id = ?",
                     (error, receipt_id))


def get_receipt(conn: sqlite3.Connection, receipt_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM receipts WHERE id = ?", (receipt_id,)).fetchone()
    if row is None:
        return None
    receipt = _row_to_dict(row)
    receipt["items"] = [dict(r) for r in conn.execute(
        """SELECT id, position, description, quantity, unit_price, amount, category
           FROM line_items WHERE receipt_id = ? ORDER BY position""", (receipt_id,))]
    return receipt


def receipt_data(record: dict) -> ReceiptData:
    """The ReceiptData part of a stored receipt (e.g. to re-validate after an edit)."""
    return ReceiptData(**{f: record.get(f) for f in _RECEIPT_FIELDS},
                       items=[LineItem(**{k: it[k] for k in ("description", "quantity", "unit_price",
                                                             "amount", "category")})
                              for it in record.get("items", [])])


def list_receipts(conn: sqlite3.Connection, *, status: str | None = None, vendor: str | None = None,
                  category: str | None = None, date_from: str | None = None, date_to: str | None = None,
                  search: str | None = None, limit: int = 200, offset: int = 0) -> list[dict]:
    """Receipts (without items) newest first, with an item count. Filters are optional."""
    where, params = [], []
    if status:
        where.append("r.status = ?"); params.append(status)
    if vendor:
        where.append("r.vendor LIKE ?"); params.append(f"%{vendor}%")
    if date_from:
        where.append("r.date >= ?"); params.append(date_from)
    if date_to:
        where.append("r.date <= ?"); params.append(date_to)
    if category:
        where.append("EXISTS (SELECT 1 FROM line_items c WHERE c.receipt_id = r.id AND c.category = ?)")
        params.append(category)
    if search:
        where.append("""(r.vendor LIKE ? OR r.receipt_no LIKE ? OR EXISTS (
                         SELECT 1 FROM line_items s WHERE s.receipt_id = r.id AND s.description LIKE ?))""")
        params += [f"%{search}%"] * 3
    sql = f"""SELECT r.id, r.vendor, r.receipt_no, r.date, r.time, r.currency, r.total, r.status,
                     r.warnings, r.original_filename, r.user_edited, r.created_at,
                     (SELECT count(*) FROM line_items i WHERE i.receipt_id = r.id) AS item_count
              FROM receipts r {"WHERE " + " AND ".join(where) if where else ""}
              ORDER BY coalesce(r.date, '') DESC, r.id DESC LIMIT ? OFFSET ?"""
    return [_row_to_dict(row) for row in conn.execute(sql, (*params, limit, offset))]


def delete_receipt(conn: sqlite3.Connection, receipt_id: int) -> str | None:
    """Delete a receipt and its items. Returns its image path (for the caller to remove), or None."""
    row = conn.execute("SELECT image_path FROM receipts WHERE id = ?", (receipt_id,)).fetchone()
    if row is None:
        return None
    with conn:
        conn.execute("DELETE FROM receipts WHERE id = ?", (receipt_id,))
    return row["image_path"]


# --------------------------------------------------------------------------
# Jobs (background processing queue)
# --------------------------------------------------------------------------

def create_job(conn: sqlite3.Connection, job_id: str, receipt_id: int, *, force_vlm: bool = False) -> None:
    with conn:
        conn.execute("UPDATE receipts SET status = 'processing', error = NULL WHERE id = ?", (receipt_id,))
        conn.execute("INSERT INTO jobs (id, receipt_id, stage, force_vlm) VALUES (?, ?, 'queued', ?)",
                     (job_id, receipt_id, int(force_vlm)))


def get_job(conn: sqlite3.Connection, job_id: str) -> dict | None:
    row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    return dict(row) if row else None


def list_jobs(conn: sqlite3.Connection, *, active_only: bool = False, limit: int = 50) -> list[dict]:
    where = "WHERE stage NOT IN ('done', 'failed')" if active_only else ""
    return [dict(r) for r in conn.execute(
        f"SELECT * FROM jobs {where} ORDER BY created_at DESC, rowid DESC LIMIT ?", (limit,))]


def queue_position(conn: sqlite3.Connection, job_id: str) -> int:
    """How many queued jobs were created before this one (0 = next)."""
    return conn.execute(
        """SELECT count(*) FROM jobs WHERE stage = 'queued'
           AND rowid < (SELECT rowid FROM jobs WHERE id = ?)""", (job_id,)).fetchone()[0]


def claim_next_job(conn: sqlite3.Connection) -> dict | None:
    """Atomically take the oldest queued job."""
    with conn:
        row = conn.execute("SELECT id FROM jobs WHERE stage = 'queued' ORDER BY rowid LIMIT 1").fetchone()
        if row is None:
            return None
        claimed = conn.execute(
            """UPDATE jobs SET stage = 'starting', started_at = datetime('now')
               WHERE id = ? AND stage = 'queued'""", (row["id"],)).rowcount
    return get_job(conn, row["id"]) if claimed else None


def update_job(conn: sqlite3.Connection, job_id: str, *, stage: str, progress: float) -> None:
    with conn:
        conn.execute("UPDATE jobs SET stage = ?, progress = ? WHERE id = ?", (stage, progress, job_id))


def finish_job(conn: sqlite3.Connection, job_id: str, *, failed: bool, error: str | None = None) -> None:
    with conn:
        conn.execute(
            """UPDATE jobs SET stage = ?, progress = ?, error = ?, finished_at = datetime('now')
               WHERE id = ?""", ("failed" if failed else "done", 0 if failed else 1, error, job_id))


def recover_interrupted_jobs(conn: sqlite3.Connection) -> int:
    """After a crash/restart, jobs that were running are marked failed (their receipts too)."""
    message = "Interrupted: the app stopped while this receipt was being processed. Reprocess it."
    with conn:
        conn.execute(
            """UPDATE receipts SET status = 'failed', error = ? WHERE id IN (
                   SELECT receipt_id FROM jobs WHERE stage NOT IN ('queued', 'done', 'failed'))""", (message,))
        return conn.execute(
            """UPDATE jobs SET stage = 'failed', error = ?, finished_at = datetime('now')
               WHERE stage NOT IN ('queued', 'done', 'failed')""", (message,)).rowcount
