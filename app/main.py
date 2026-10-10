"""FastAPI application.

Run:  .\\.venv\\Scripts\\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
Then open http://127.0.0.1:8000 (frontend) or http://127.0.0.1:8000/docs (API).
"""

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app import access
from app.api import chat, evals, jobs, lab, receipts, stats, system
from app.config import PROJECT_ROOT, get_settings
from app.db import repo
from app.db.database import connect
from app.worker import Worker

FRONTEND_DIR = PROJECT_ROOT / "frontend"


def create_app(*, db_path: Path | str | None = None, start_worker: bool = True, warm_up: bool = True) -> FastAPI:
    """``start_worker``/``warm_up`` are turned off in tests."""

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        conn = connect(app.state.db_path)
        recovered = repo.recover_interrupted_jobs(conn)
        conn.close()
        if recovered:
            logging.getLogger("bills").warning("Marked %d interrupted job(s) as failed.", recovered)
        if start_worker:
            app.state.worker.start()
        if warm_up:
            system.start_warmup(app)
        yield
        app.state.worker.stop()

    app = FastAPI(title="Chat With Your Bills", version="0.5.0", lifespan=lifespan,
                  description="Receipt photos -> validated, categorized spending data. Runs locally on CPU.")
    app.state.db_path = db_path or get_settings().db_path
    app.state.worker = Worker(app.state.db_path)
    app.state.warmup = {"running": False, "seconds": None, "error": None}
    app.state.eval = {}

    app.middleware("http")(access.guard)
    for module in (receipts, jobs, stats, chat, lab, system, evals):
        app.include_router(module.router)

    if FRONTEND_DIR.is_dir():
        app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
    return app


app = create_app()
