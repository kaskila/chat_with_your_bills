"""Receipts: upload, list, read, edit, reprocess, delete, image."""

import sqlite3
from pathlib import Path
from typing import Annotated, Literal

import cv2
from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel

from app.api.deps import get_conn, get_worker
from app.config import get_settings
from app.db import repo
from app.ingest import image_file, register_image
from app.pipeline.preprocess import crop_receipt, load_image
from app.pipeline.validate import check
from app.schemas import ReceiptData
from app.test_cases import save_test_case, test_case_path
from app.worker import Worker, enqueue

router = APIRouter(prefix="/api/receipts", tags=["receipts"])

Conn = Annotated[sqlite3.Connection, Depends(get_conn)]
WorkerDep = Annotated[Worker, Depends(get_worker)]

# File signatures: JPEG, PNG, WEBP (RIFF....WEBP)
_SIGNATURES = (b"\xff\xd8\xff", b"\x89PNG\r\n\x1a\n")


class UploadResult(BaseModel):
    filename: str
    receipt_id: int | None = None
    job_id: str | None = None
    duplicate: bool = False
    status: str | None = None
    error: str | None = None


def _looks_like_image(data: bytes) -> bool:
    return data.startswith(_SIGNATURES) or (data[:4] == b"RIFF" and data[8:12] == b"WEBP")


def _get_or_404(conn: sqlite3.Connection, receipt_id: int) -> dict:
    record = repo.get_receipt(conn, receipt_id)
    if record is None:
        raise HTTPException(404, f"Receipt {receipt_id} not found.")
    return record


@router.post("", response_model=list[UploadResult])
async def upload(conn: Conn, worker: WorkerDep, files: list[UploadFile] = File(...)) -> list[UploadResult]:
    """Upload one or more receipt photos. Each new image is queued for processing."""
    limit = get_settings().max_upload_mb * 1024 * 1024
    results = []
    for upload_file in files:
        name = Path(upload_file.filename or "upload.jpg").name
        data = await upload_file.read(limit + 1)
        if len(data) > limit:
            results.append(UploadResult(filename=name, error=f"File larger than {limit // 1024 // 1024} MB."))
            continue
        if not _looks_like_image(data):
            results.append(UploadResult(filename=name, error="Not a JPEG, PNG or WEBP image."))
            continue
        try:  # a damaged or half-uploaded photo is refused now, not after waiting in the queue
            await run_in_threadpool(load_image, data)
        except ValueError:
            results.append(UploadResult(filename=name, error="The photo could not be opened (damaged or "
                                                             "incomplete file). Take or upload it again."))
            continue
        registered = register_image(conn, data, name)
        if registered.already_processed:
            results.append(UploadResult(filename=name, receipt_id=registered.receipt_id, duplicate=True,
                                        status=registered.status))
            continue
        job_id = enqueue(conn, registered.receipt_id)
        results.append(UploadResult(filename=name, receipt_id=registered.receipt_id, job_id=job_id,
                                    status="processing"))
    worker.notify()
    return results


@router.get("")
def list_receipts(conn: Conn, status: str | None = None, vendor: str | None = None,
                  category: str | None = None, date_from: Annotated[str | None, Query(alias="from")] = None,
                  date_to: Annotated[str | None, Query(alias="to")] = None, q: str | None = None,
                  limit: int = Query(200, le=1000), offset: int = 0) -> list[dict]:
    return repo.list_receipts(conn, status=status, vendor=vendor, category=category, date_from=date_from,
                              date_to=date_to, search=q, limit=limit, offset=offset)


@router.get("/{receipt_id}")
def get_receipt(conn: Conn, receipt_id: int) -> dict:
    record = _get_or_404(conn, receipt_id)
    record.pop("extraction_raw", None)
    jobs = conn.execute("SELECT id, stage, progress, error FROM jobs WHERE receipt_id = ? ORDER BY rowid DESC "
                        "LIMIT 1", (receipt_id,)).fetchone()
    record["latest_job"] = dict(jobs) if jobs else None
    record["test_case"] = test_case_path(receipt_id).exists()
    return record


@router.get("/{receipt_id}/image")
def get_image(conn: Conn, receipt_id: int, variant: Literal["original", "cropped"] = "original"):
    record = _get_or_404(conn, receipt_id)
    path = image_file(record)
    if not path.exists():
        raise HTTPException(404, "Image file is missing.")
    if variant == "original":
        return FileResponse(path)
    cached = path.with_name(f"{path.stem}_crop.jpg")
    if not cached.exists():
        cropped, *_ = crop_receipt(load_image(path))
        ok, buffer = cv2.imencode(".jpg", cropped, [cv2.IMWRITE_JPEG_QUALITY, 90])
        if not ok:
            raise HTTPException(500, "Could not encode the cropped image.")
        cached.write_bytes(buffer.tobytes())
    return Response(cached.read_bytes(), media_type="image/jpeg")


@router.patch("/{receipt_id}")
def update_receipt(conn: Conn, receipt_id: int, data: ReceiptData) -> dict:
    """Replace the receipt's fields and items with corrected values and re-run the checks.

    The "value appears on the receipt" check is skipped: the user is the authority
    when they correct something the OCR misread."""
    record = _get_or_404(conn, receipt_id)
    if record["status"] == "processing":
        raise HTTPException(409, "The receipt is still being processed.")
    warnings = [w.to_dict() for w in check(data)]
    duplicates = repo.find_duplicates(conn, data, exclude_id=receipt_id)
    if duplicates:
        warnings.append({"code": "POSSIBLE_DUPLICATE", "field": None,
                         "message": f"Same vendor, receipt number and total as receipt "
                                    f"{', '.join(f'#{d}' for d in duplicates)}."})
    notes = [*record["notes"], "Edited by the user."] if "Edited by the user." not in record["notes"] \
        else record["notes"]
    repo.save_extraction(conn, receipt_id, data, status="needs_review" if warnings else "verified",
                         warnings=warnings, notes=notes, user_edited=True)
    return get_receipt(conn, receipt_id)


@router.post("/{receipt_id}/reprocess", response_model=UploadResult)
def reprocess(conn: Conn, worker: WorkerDep, receipt_id: int, force_vlm: bool = False) -> UploadResult:
    record = _get_or_404(conn, receipt_id)
    if record["status"] == "processing":
        raise HTTPException(409, "The receipt is already being processed.")
    job_id = enqueue(conn, receipt_id, force_vlm=force_vlm)
    worker.notify()
    return UploadResult(filename=record["original_filename"] or "", receipt_id=receipt_id, job_id=job_id,
                        status="processing")


@router.post("/{receipt_id}/test-case")
def make_test_case(conn: Conn, receipt_id: int) -> dict:
    """Save this receipt, as currently stored, as an evaluation test case (set "real").
    Only after the user has checked every field and item against the photo."""
    record = _get_or_404(conn, receipt_id)
    if record["status"] in ("processing", "failed"):
        raise HTTPException(409, "Only a processed receipt can be a test case.")
    path = save_test_case(record)
    return {"saved": True, "file": path.name}


@router.post("/reprocess-failed")
def reprocess_failed(conn: Conn, worker: WorkerDep) -> dict:
    """Queue every failed receipt again (e.g. after Ollama was not running)."""
    ids = [row[0] for row in conn.execute("SELECT id FROM receipts WHERE status = 'failed' ORDER BY id")]
    jobs = [{"receipt_id": rid, "job_id": enqueue(conn, rid)} for rid in ids]
    worker.notify()
    return {"queued": len(jobs), "jobs": jobs}


@router.delete("/{receipt_id}", status_code=204)
def delete_receipt(conn: Conn, receipt_id: int) -> Response:
    record = _get_or_404(conn, receipt_id)
    if record["status"] == "processing":
        raise HTTPException(409, "The receipt is being processed; delete it when it is done.")
    repo.delete_receipt(conn, receipt_id)
    path = image_file(record)
    for file in (path, path.with_name(f"{path.stem}_crop.jpg")):
        file.unlink(missing_ok=True)
    return Response(status_code=204)
