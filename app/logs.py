"""Log files in data/logs (``BILLS_LOG_DIR``).

- ``app.log``: the app's own messages (worker, start-up), 5 MB x 3 files.
- ``receipts.jsonl``: one JSON line per processed receipt (status, warnings, which reading was
  used, seconds per stage), for troubleshooting and for measuring speed over time.
- ``server.log`` (written by ``serve --log-file``): web server output, without the routine
  polling requests the pages make every few seconds.
"""

import json
import logging
import re
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path

from app.config import get_settings

_FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"
# Successful polling: job progress, health dot, eval status.
_ROUTINE = re.compile(r'"GET /api/(jobs/[0-9a-f]+|system/health|eval/status)[^"]*" 200')


class _SkipRoutine(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return not _ROUTINE.search(record.getMessage())


def setup() -> None:
    """Configure logging once (called when the server starts)."""
    log_dir = get_settings().log_dir
    log_dir.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("bills")
    if any(isinstance(h, RotatingFileHandler) for h in logger.handlers):
        return
    logger.setLevel(logging.INFO)
    file_handler = RotatingFileHandler(log_dir / "app.log", maxBytes=5_000_000, backupCount=3, encoding="utf-8")
    file_handler.setFormatter(logging.Formatter(_FORMAT))
    console = logging.StreamHandler()
    console.setFormatter(logging.Formatter(_FORMAT))
    logger.addHandler(file_handler)
    logger.addHandler(console)
    logger.propagate = False
    logging.getLogger("uvicorn.access").addFilter(_SkipRoutine())


def rotate_if_large(path: Path, max_bytes: int = 10_000_000) -> None:
    """Keep one previous copy (``.1``) when a log file has grown too large."""
    if path.exists() and path.stat().st_size > max_bytes:
        path.replace(path.with_name(path.name + ".1"))


def record_receipt(entry: dict) -> None:
    """Append one processed receipt to receipts.jsonl (never raises: logging must not break processing)."""
    try:
        path = get_settings().log_dir / "receipts.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        rotate_if_large(path)
        line = {"time": datetime.now().isoformat(timespec="seconds"), **entry}
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(line, ensure_ascii=False) + "\n")
    except OSError:
        logging.getLogger("bills").warning("Could not write receipts.jsonl", exc_info=True)
