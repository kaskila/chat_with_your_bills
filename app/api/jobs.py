"""Processing job status (the frontend polls this while a receipt is processed)."""

import sqlite3
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import get_conn
from app.db import repo

router = APIRouter(prefix="/api/jobs", tags=["jobs"])

Conn = Annotated[sqlite3.Connection, Depends(get_conn)]


@router.get("")
def list_jobs(conn: Conn, active: bool = False) -> list[dict]:
    return repo.list_jobs(conn, active_only=active)


@router.get("/{job_id}")
def get_job(conn: Conn, job_id: str) -> dict:
    job = repo.get_job(conn, job_id)
    if job is None:
        raise HTTPException(404, f"Job {job_id} not found.")
    if job["stage"] == "queued":
        job["queue_position"] = repo.queue_position(conn, job_id)
    receipt = repo.get_receipt(conn, job["receipt_id"]) if job["receipt_id"] else None
    if receipt and job["stage"] in ("done", "failed"):
        job["receipt"] = {k: receipt[k] for k in ("id", "status", "vendor", "date", "total", "currency",
                                                   "warnings", "error", "timings")}
    return job
