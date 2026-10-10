"""Get your data out: CSV for spreadsheets, JSON for everything, and a full backup ZIP.

The backup holds a consistent copy of the database (SQLite's backup API, safe while the app
runs) and every stored photo, so ``restore_backup`` can rebuild the app's data on any computer.
"""

import csv
import io
import json
import shutil
import sqlite3
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path

from app.config import PROJECT_ROOT, get_settings
from app.db import repo

RECEIPT_COLUMNS = ["receipt_id", "date", "time", "vendor", "vendor_tax_id", "receipt_no", "currency", "subtotal",
                   "discount", "service_charge", "tax", "total", "amount_paid", "change", "payment_method", "recipient", "recipient_phone", "transaction_type", "balance",
                   "items", "status", "warnings", "user_edited", "original_filename", "created_at"]
ITEM_COLUMNS = ["receipt_id", "date", "vendor", "currency", "position", "description", "quantity", "unit_price",
                "amount", "category", "receipt_total", "status"]

_README = """Chat With Your Bills backup ({stamp})

bills.db   the database (receipts, items, processing jobs)
uploads/   the receipt photos, named by their SHA-256

Restore on a computer with the app installed (the app must be stopped):
    .venv\\Scripts\\python.exe -m app.cli restore <this file>.zip
The current database is kept as bills.db.before-restore-<time>.
"""


def receipt_rows(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        """SELECT r.*, (SELECT count(*) FROM line_items i WHERE i.receipt_id = r.id) AS items
           FROM receipts r ORDER BY r.date IS NULL, r.date, r.id""").fetchall()
    out = []
    for row in rows:
        r = dict(row)
        r["receipt_id"] = r["id"]
        r["warnings"] = "; ".join(w["code"] for w in json.loads(r["warnings"] or "[]"))
        r["user_edited"] = "yes" if r["user_edited"] else ""
        out.append({c: r.get(c) for c in RECEIPT_COLUMNS})
    return out


def item_rows(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        """SELECT i.receipt_id, r.date, r.vendor, r.currency, i.position, i.description, i.quantity, i.unit_price,
                  i.amount, i.category, r.total AS receipt_total, r.status
           FROM line_items i JOIN receipts r ON r.id = i.receipt_id
           ORDER BY r.date IS NULL, r.date, i.receipt_id, i.position""").fetchall()
    return [dict(row) for row in rows]


def to_csv(rows: list[dict], columns: list[str]) -> bytes:
    """UTF-8 with a byte-order mark, so Excel shows names like "MAMA NKANDU'S" and "K" correctly."""
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=columns, extrasaction="ignore", lineterminator="\r\n")
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue().encode("utf-8-sig")


def all_data(conn: sqlite3.Connection) -> dict:
    """Every receipt with its items, warnings, notes and OCR text (not the raw model output)."""
    receipts = []
    for (rid,) in conn.execute("SELECT id FROM receipts ORDER BY id"):
        record = repo.get_receipt(conn, rid)
        record.pop("extraction_raw", None)
        receipts.append(record)
    return {"exported_at": datetime.now().isoformat(timespec="seconds"), "receipts": receipts}


def write_backup(db_path: Path | str, out: Path) -> dict:
    """Database snapshot + all photos referenced by it (and any others in uploads) into ``out``."""
    uploads = get_settings().uploads_dir
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    with tempfile.TemporaryDirectory() as tmp:
        snapshot = Path(tmp) / "bills.db"
        source = sqlite3.connect(str(db_path))
        target = sqlite3.connect(str(snapshot))
        try:
            source.backup(target)  # consistent copy even while the worker writes
        finally:
            target.close()
            source.close()
        photos = sorted(p for p in uploads.glob("*") if p.is_file()) if uploads.is_dir() else []
        with zipfile.ZipFile(out, "w") as zf:
            zf.writestr("README.txt", _README.format(stamp=stamp))
            zf.write(snapshot, "bills.db", compress_type=zipfile.ZIP_DEFLATED)
            for photo in photos:  # photos are already compressed: store them as they are (fast)
                zf.write(photo, f"uploads/{photo.name}", compress_type=zipfile.ZIP_STORED)
    return {"photos": len(photos), "bytes": out.stat().st_size}


def restore_backup(archive: Path, db_path: Path | str | None = None) -> dict:
    """Put a backup's database and photos in place. The current database is moved aside first;
    photos are only added (they are named by content, so nothing is overwritten)."""
    s = get_settings()
    db_path = Path(db_path or s.db_path)
    with zipfile.ZipFile(archive) as zf:
        names = zf.namelist()
        if "bills.db" not in names:
            raise ValueError(f"{archive} is not a Chat With Your Bills backup (no bills.db inside).")
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        kept = None
        if db_path.exists():
            kept = db_path.with_name(f"{db_path.name}.before-restore-{stamp}")
            db_path.replace(kept)
        for extra in (db_path.with_name(db_path.name + "-wal"), db_path.with_name(db_path.name + "-shm")):
            extra.unlink(missing_ok=True)  # belonged to the old database
        db_path.parent.mkdir(parents=True, exist_ok=True)
        with zf.open("bills.db") as src, db_path.open("wb") as dst:
            shutil.copyfileobj(src, dst)
        s.uploads_dir.mkdir(parents=True, exist_ok=True)
        added = 0
        for name in names:
            if name.startswith("uploads/") and not name.endswith("/"):
                target = s.uploads_dir / Path(name).name
                if not target.exists():
                    with zf.open(name) as src, target.open("wb") as dst:
                        shutil.copyfileobj(src, dst)
                    added += 1
    conn = sqlite3.connect(str(db_path))
    try:
        receipts = conn.execute("SELECT count(*) FROM receipts").fetchone()[0]
        missing = sum(1 for (p,) in conn.execute("SELECT image_path FROM receipts")
                      if not (Path(p) if Path(p).is_absolute() else PROJECT_ROOT / p).exists())
    finally:
        conn.close()
    return {"receipts": receipts, "photos_added": added, "photos_missing": missing,
            "previous_database": str(kept) if kept else None}
