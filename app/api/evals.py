"""Run the evaluation set and read past reports.

An evaluation runs ``python -m eval.run_eval`` in a separate process (it can take
many minutes). Only one runs at a time.
"""

import json
import os
import subprocess
import sys
import threading
from collections import deque
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app.config import PROJECT_ROOT, get_settings

router = APIRouter(prefix="/api/eval", tags=["eval"])


class EvalRequest(BaseModel):
    kind: Literal["ocr", "extraction"] = "extraction"
    sets: list[Literal["tuning", "dev", "test"]] = ["test"]
    name: str | None = None


@router.get("/results")
def list_results() -> list[dict]:
    """Saved reports, newest first (summary only)."""
    out = []
    for path in sorted(get_settings().eval_results_dir.glob("*_*_*.json"), reverse=True):
        try:
            report = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if "summary" not in report:
            continue
        out.append({"file": path.name, "kind": report.get("kind"), "name": report.get("name"),
                    "created": report.get("created"), "summary": report["summary"],
                    "summary_by_set": report.get("summary_by_set")})
    return out


@router.get("/results/{file}")
def get_result(file: str) -> dict:
    path = get_settings().eval_results_dir / file
    if path.parent != get_settings().eval_results_dir or not path.is_file():
        raise HTTPException(404, "Report not found.")
    return json.loads(path.read_text(encoding="utf-8"))


@router.post("/run")
def run_eval(request: Request, body: EvalRequest) -> dict:
    state = request.app.state.eval
    if state.get("process") and state["process"].poll() is None:
        raise HTTPException(409, "An evaluation is already running.")
    if request.app.state.worker.current_job:
        raise HTTPException(409, "Receipts are being processed; run the evaluation when the queue is empty "
                                 "(both need the whole CPU).")
    name = body.name or f"ui-{body.kind}-{'-'.join(body.sets)}-{datetime.now():%H%M}"
    cmd = [sys.executable, "-m", "eval.run_eval", body.kind, "--name", name]
    cmd += ["--rapid"] if body.kind == "ocr" else ["--pipeline"]
    for s in body.sets:
        cmd += ["--set", s]
    process = subprocess.Popen(cmd, cwd=PROJECT_ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                               text=True, encoding="utf-8", errors="replace", env={**os.environ, "PYTHONIOENCODING": "utf-8"})
    log: deque[str] = deque(maxlen=200)

    def pump() -> None:
        for line in process.stdout:
            if not line.startswith("[INFO]"):
                log.append(line.rstrip())

    threading.Thread(target=pump, daemon=True).start()
    state.update(process=process, log=log, name=name, started=datetime.now().isoformat(timespec="seconds"))
    return status(request)


@router.get("/status")
def status(request: Request) -> dict:
    state = request.app.state.eval
    process = state.get("process")
    if process is None:
        return {"running": False}
    code = process.poll()
    return {"running": code is None, "exit_code": code, "name": state.get("name"),
            "started": state.get("started"), "log": list(state.get("log", []))[-40:]}
