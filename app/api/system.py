"""Health, configuration and model warm-up."""

import io
import platform
import sqlite3
import threading
from typing import Annotated

import httpx
import ollama
import segno
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response

from app import access
from app.api.deps import get_conn
from app.config import get_settings
from app.db import repo
from app.db.database import schema_version
from app.llm.client import LLMError, warm_up
from app.llm.prompts import EXTRACTION_SYSTEM

router = APIRouter(prefix="/api/system", tags=["system"])

Conn = Annotated[sqlite3.Connection, Depends(get_conn)]

_PUBLIC_SETTINGS = (
    "ollama_host", "extract_model", "vlm_model", "keep_alive", "num_ctx", "num_thread", "extract_timeout_s",
    "vlm_timeout_s", "rapid_ocr_version", "rapid_model_type", "rapid_engine", "rapid_box_thresh",
    "rapid_use_crop", "rapid_remove_shadows", "crop_receipt", "vlm_mode", "ocr_confidence_threshold",
    "max_upload_mb",
)


def _ollama_status() -> dict:
    s = get_settings()
    client = ollama.Client(host=s.ollama_host, timeout=5)
    try:
        installed = [m.model for m in client.list().models]
        loaded = [m.model for m in client.ps().models]
    except (httpx.HTTPError, ConnectionError, ollama.ResponseError) as error:
        return {"reachable": False, "error": str(error), "host": s.ollama_host}

    def present(name: str, names: list[str]) -> bool:
        wanted = name if ":" in name else f"{name}:latest"
        return wanted in names or name in names

    return {
        "reachable": True, "host": s.ollama_host,
        "models": {
            role: {"name": name, "installed": present(name, installed), "loaded": present(name, loaded)}
            for role, name in (("extract", s.extract_model), ("vlm", s.vlm_model))
        },
    }


@router.get("/health")
def health(request: Request, conn: Conn) -> dict:
    s = get_settings()
    worker = request.app.state.worker
    queued = conn.execute("SELECT count(*) FROM jobs WHERE stage = 'queued'").fetchone()[0]
    counts = {r["status"]: r["n"] for r in conn.execute("SELECT status, count(*) AS n FROM receipts GROUP BY 1")}
    ollama_status = _ollama_status()
    extract_ok = ollama_status.get("models", {}).get("extract", {}).get("installed", False)
    return {
        "ok": ollama_status["reachable"] and extract_ok and worker.alive,
        "ollama": ollama_status,
        "worker": {"alive": worker.alive, "current_job": worker.current_job, "queued": queued},
        "database": {"path": str(request.app.state.db_path or s.db_path), "schema_version": schema_version(conn),
                     "receipts": counts},
        "warmup": request.app.state.warmup,
        "versions": {"python": platform.python_version()},
        # The links contain the access key: only shown on this computer.
        "access": {"lan": bool(s.lan_key),
                   "phone_links": access.phone_links() if access.is_local(request) else [],
                   "tailscale": access.tailscale_info()},
        "settings": {k: getattr(s, k) for k in _PUBLIC_SETTINGS},
    }


def start_warmup(app) -> None:
    """Load the extraction model (with its instructions cached) in the background."""
    state = app.state.warmup
    if state.get("running"):
        return
    state.update(running=True, error=None, seconds=None)

    def run() -> None:
        try:
            state["seconds"] = round(warm_up(get_settings().extract_model, EXTRACTION_SYSTEM), 1)
        except LLMError as error:
            state["error"] = str(error)
        finally:
            state["running"] = False

    threading.Thread(target=run, name="warmup", daemon=True).start()


@router.post("/warmup")
def warmup(request: Request) -> dict:
    start_warmup(request.app)
    return request.app.state.warmup


@router.get("/phone-qr.svg")
def phone_qr(request: Request) -> Response:
    """QR code of the phone link (contains the access key, so only served to this computer)."""
    links = access.phone_links()
    if not access.is_local(request) or not links:
        raise HTTPException(404, "Phone access is off: run scripts\\phone-access.ps1 (Tailscale) or start with --lan.")
    buffer = io.BytesIO()  # a standalone SVG (with xmlns), so it renders in <img>
    segno.make(links[0], error="m").save(buffer, kind="svg", scale=5, border=2, dark="#000", light="#fff")
    return Response(buffer.getvalue(), media_type="image/svg+xml", headers={"Cache-Control": "no-store"})


@router.get("/jobs/recent")
def recent_failures(conn: Conn) -> list[dict]:
    """Recent failed jobs, for troubleshooting."""
    return [j for j in repo.list_jobs(conn, limit=20) if j["stage"] == "failed"]
