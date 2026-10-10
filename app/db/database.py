"""SQLite connection and schema migrations.

Migrations are numbered SQL scripts applied in order; the current version is
kept in ``PRAGMA user_version``. Add new migrations to the end of ``MIGRATIONS``;
never edit one that has already shipped.
"""

import sqlite3
from pathlib import Path

from app.config import get_settings

MIGRATIONS: list[str] = [
    # 1: initial schema
    """
    CREATE TABLE receipts (
        id                INTEGER PRIMARY KEY,
        image_sha256      TEXT NOT NULL UNIQUE,
        image_path        TEXT NOT NULL,
        original_filename TEXT,
        vendor            TEXT,
        vendor_tax_id     TEXT,
        receipt_no        TEXT,
        date              TEXT,            -- ISO YYYY-MM-DD
        time              TEXT,            -- HH:MM
        currency          TEXT,
        subtotal          REAL,
        discount          REAL,
        service_charge    REAL,
        tax               REAL,
        total             REAL,
        amount_paid       REAL,
        change            REAL,
        payment_method    TEXT,
        status            TEXT NOT NULL CHECK (status IN ('processing', 'verified', 'needs_review', 'failed')),
        warnings          TEXT NOT NULL DEFAULT '[]',   -- JSON list of {code, message, field}
        notes             TEXT NOT NULL DEFAULT '[]',   -- JSON list of strings
        error             TEXT,
        ocr_text_rapid    TEXT,
        ocr_text_vlm      TEXT,
        ocr_confidence    REAL,
        extraction_raw    TEXT,
        timings           TEXT,            -- JSON
        models            TEXT,            -- JSON
        user_edited       INTEGER NOT NULL DEFAULT 0,
        created_at        TEXT NOT NULL DEFAULT (datetime('now')),
        updated_at        TEXT NOT NULL DEFAULT (datetime('now'))
    );
    CREATE INDEX idx_receipts_date ON receipts(date);
    CREATE INDEX idx_receipts_vendor ON receipts(vendor);
    CREATE INDEX idx_receipts_status ON receipts(status);

    CREATE TABLE line_items (
        id          INTEGER PRIMARY KEY,
        receipt_id  INTEGER NOT NULL REFERENCES receipts(id) ON DELETE CASCADE,
        position    INTEGER NOT NULL,
        description TEXT NOT NULL,
        quantity    REAL,
        unit_price  REAL,
        amount      REAL NOT NULL,
        category    TEXT NOT NULL,
        UNIQUE (receipt_id, position)
    );
    CREATE INDEX idx_items_category ON line_items(category);

    CREATE TABLE jobs (
        id          TEXT PRIMARY KEY,      -- uuid
        receipt_id  INTEGER REFERENCES receipts(id) ON DELETE SET NULL,
        image_path  TEXT,
        stage       TEXT NOT NULL,         -- queued | preprocess | ocr | extract | validate | vlm | saving | done | failed
        progress    REAL NOT NULL DEFAULT 0,
        error       TEXT,
        force_vlm   INTEGER NOT NULL DEFAULT 0,
        created_at  TEXT NOT NULL DEFAULT (datetime('now')),
        started_at  TEXT,
        finished_at TEXT
    );
    CREATE INDEX idx_jobs_stage ON jobs(stage);
    """,
]


def connect(path: Path | str | None = None) -> sqlite3.Connection:
    """Open the database (creating folders and schema as needed). ``":memory:"`` works for tests."""
    path = path if path is not None else get_settings().db_path
    if str(path) != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), check_same_thread=False, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    if str(path) != ":memory:":
        conn.execute("PRAGMA journal_mode = WAL")  # readers don't block the writer
    migrate(conn)
    return conn


def schema_version(conn: sqlite3.Connection) -> int:
    return conn.execute("PRAGMA user_version").fetchone()[0]


def migrate(conn: sqlite3.Connection) -> int:
    """Apply pending migrations. Returns the new schema version."""
    version = schema_version(conn)
    for number, script in enumerate(MIGRATIONS[version:], start=version + 1):
        # One transaction per migration: either all of it applies, or none.
        conn.executescript(f"BEGIN;\n{script}\nPRAGMA user_version = {number};\nCOMMIT;")
    return schema_version(conn)
