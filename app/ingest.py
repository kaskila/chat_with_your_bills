"""From an uploaded image to a stored receipt.

Two steps so the background worker (Phase 5) can do the slow part later:
1. ``register_image``: hash the bytes, keep a copy under data/uploads, create the
   receipt row (or find the existing one for the same image).
2. ``process_receipt``: run the pipeline on the stored image and save the result.
"""

import hashlib
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from app.config import PROJECT_ROOT, get_settings
from app.db import repo
from app.llm.client import LLMError
from app.pipeline.run import PipelineResult, process_image
from app.pipeline.validate import ReceiptWarning

ALLOWED_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}


@dataclass
class Registered:
    receipt_id: int
    already_processed: bool  # same image stored before (and not failed)
    status: str


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _stored_path(sha: str, filename: str) -> Path:
    suffix = Path(filename).suffix.lower()
    return get_settings().uploads_dir / f"{sha}{suffix if suffix in ALLOWED_SUFFIXES else '.jpg'}"


def image_file(record: dict) -> Path:
    """Absolute path of a stored receipt image."""
    path = Path(record["image_path"])
    return path if path.is_absolute() else PROJECT_ROOT / path


def register_image(conn: sqlite3.Connection, data: bytes, filename: str, *, force: bool = False) -> Registered:
    """Store the image and create its receipt row. Same image again -> the existing receipt,
    unless it failed before or ``force`` is set (then it is processed again)."""
    sha = sha256_bytes(data)
    existing = repo.find_by_hash(conn, sha)
    if existing and existing["status"] != "failed" and not force:
        return Registered(existing["id"], True, existing["status"])

    path = _stored_path(sha, filename)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_bytes(data)
    try:
        relative = str(path.relative_to(PROJECT_ROOT))
    except ValueError:
        relative = str(path)

    if existing:
        return Registered(existing["id"], False, existing["status"])
    receipt_id = repo.insert_receipt(conn, image_sha256=sha, image_path=relative, original_filename=filename)
    return Registered(receipt_id, False, "processing")


def save_result(conn: sqlite3.Connection, receipt_id: int, result: PipelineResult) -> str:
    """Store a pipeline result, adding a duplicate warning if the same receipt exists. Returns the status."""
    warnings = list(result.warnings)
    duplicates = repo.find_duplicates(conn, result.receipt, exclude_id=receipt_id)
    if duplicates:
        warnings.append(ReceiptWarning(
            "POSSIBLE_DUPLICATE",
            f"Same vendor, receipt number and total as receipt {', '.join(f'#{d}' for d in duplicates)}.",
        ))
    status = "needs_review" if warnings else "verified"
    repo.save_extraction(
        conn, receipt_id, result.receipt, status=status,
        warnings=[w.to_dict() for w in warnings],
        notes=[*result.notes, *(f"Dropped non-item line: {d}" for d in result.dropped_items)],
        ocr_text_rapid=result.ocr.text, ocr_text_vlm=result.ocr_text_vlm, ocr_confidence=result.ocr.mean_confidence,
        extraction_raw=result.extraction_raw, timings=result.timings, models=result.models,
        user_edited=False,
    )
    return status


def process_receipt(conn: sqlite3.Connection, receipt_id: int,
                    on_stage: Callable[[str], None] | None = None, *, force_vlm: bool = False) -> str:
    """Run the pipeline on a registered receipt's image and store the result. Returns the status."""
    record = repo.get_receipt(conn, receipt_id)
    if record is None:
        raise KeyError(f"Receipt {receipt_id} not found.")
    try:
        result = process_image(image_file(record), on_stage=on_stage, force_vlm=force_vlm)
    except (LLMError, ValueError, OSError) as error:
        repo.mark_failed(conn, receipt_id, str(error))
        return "failed"
    if on_stage:
        on_stage("saving")
    return save_result(conn, receipt_id, result)


def ingest_file(conn: sqlite3.Connection, path: Path, *, force: bool = False,
                on_stage: Callable[[str], None] | None = None) -> tuple[Registered, str]:
    """Register + process one image file. Returns (registration, final status)."""
    registered = register_image(conn, path.read_bytes(), path.name, force=force)
    if registered.already_processed:
        return registered, registered.status
    return registered, process_receipt(conn, registered.receipt_id, on_stage=on_stage)
