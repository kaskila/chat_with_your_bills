"""Background worker: processes queued receipts one at a time.

Processing is CPU-bound (OCR + local LLM), so running jobs in parallel would only
make each one slower. One thread takes the oldest queued job, runs the pipeline
and records the stage/progress so the frontend can show it.
"""

import logging
import threading
import uuid
from pathlib import Path

from app import ingest
from app.db import repo
from app.db.database import connect
from app.config import get_settings
from app.keepawake import keep_awake
from app.llm import client as llm

log = logging.getLogger("bills.worker")

# Rough share of total time each stage starts at (extraction dominates).
STAGE_PROGRESS = {
    "waiting_for_ollama": 0.01, "starting": 0.02, "preprocess": 0.03, "ocr": 0.05, "extract": 0.15,
    "validate": 0.55, "vlm": 0.6, "vlm_extract": 0.8, "saving": 0.97,
}


def enqueue(conn, receipt_id: int, *, force_vlm: bool = False) -> str:
    job_id = uuid.uuid4().hex
    repo.create_job(conn, job_id, receipt_id, force_vlm=force_vlm)
    return job_id


class Worker:
    def __init__(self, db_path: Path | str | None = None):
        self.db_path = db_path
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.current_job: str | None = None

    # -- lifecycle -------------------------------------------------------
    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="receipt-worker", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        self._wake.set()
        if self._thread:
            self._thread.join(timeout)

    def notify(self) -> None:
        """Wake the worker: a job was queued."""
        self._wake.set()

    @property
    def alive(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    # -- processing ------------------------------------------------------
    def _loop(self) -> None:
        conn = connect(self.db_path)
        try:
            while not self._stop.is_set():
                try:
                    worked = self.run_once(conn)
                except Exception:  # e.g. the database was busy: log it and keep the worker alive
                    log.exception("Worker loop error; retrying in 5 s")
                    worked = False
                if not worked:
                    self._wake.wait(timeout=5)
                    self._wake.clear()
        finally:
            conn.close()

    def _ollama_ready(self, conn, job: dict) -> bool:
        """Ollama must answer before a receipt is processed; a stopped local Ollama is started."""
        if llm.ollama_reachable():
            return True
        repo.update_job(conn, job["id"], stage="waiting_for_ollama", progress=STAGE_PROGRESS["waiting_for_ollama"])
        if llm.ensure_ollama():
            return True
        host = get_settings().ollama_host
        message = (f"Ollama is not running at {host} and could not be started. Start the Ollama app on the "
                   "computer, then reprocess this receipt (or use 'Reprocess all failed').")
        repo.mark_failed(conn, job["receipt_id"], message)
        repo.finish_job(conn, job["id"], failed=True, error=message)
        return False

    def run_once(self, conn) -> bool:
        """Process the next queued job, if any. Returns True if a job was processed."""
        job = repo.claim_next_job(conn)
        if job is None:
            return False
        self.current_job = job["id"]
        if not self._ollama_ready(conn, job):
            self.current_job = None
            return True

        def on_stage(stage: str) -> None:
            repo.update_job(conn, job["id"], stage=stage, progress=STAGE_PROGRESS.get(stage, 0.5))

        try:
            with keep_awake():  # a sleeping laptop would pause the job and hit the time limit
                status = ingest.process_receipt(conn, job["receipt_id"], on_stage=on_stage,
                                                force_vlm=bool(job["force_vlm"]))
        except Exception as error:  # never let one receipt kill the worker
            log.exception("Job %s crashed", job["id"])
            repo.mark_failed(conn, job["receipt_id"], f"Unexpected error: {error}")
            repo.finish_job(conn, job["id"], failed=True, error=f"Unexpected error: {error}")
        else:
            if status == "failed":
                record = repo.get_receipt(conn, job["receipt_id"]) or {}
                repo.finish_job(conn, job["id"], failed=True, error=record.get("error"))
            else:
                repo.finish_job(conn, job["id"], failed=False)
        finally:
            self.current_job = None
        return True
