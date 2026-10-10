"""Downloads: receipts and items as CSV, everything as JSON, a full backup as ZIP."""

import sqlite3
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, JSONResponse, Response
from starlette.background import BackgroundTask

from app import export
from app.api.deps import get_conn

router = APIRouter(prefix="/api/export", tags=["export"])

Conn = Annotated[sqlite3.Connection, Depends(get_conn)]


def _name(stem: str, suffix: str) -> str:
    return f"bills-{stem}-{datetime.now():%Y-%m-%d}.{suffix}"


def _attachment(filename: str) -> dict:
    return {"Content-Disposition": f'attachment; filename="{filename}"', "Cache-Control": "no-store"}


@router.get("/receipts.csv")
def receipts_csv(conn: Conn) -> Response:
    body = export.to_csv(export.receipt_rows(conn), export.RECEIPT_COLUMNS)
    return Response(body, media_type="text/csv; charset=utf-8", headers=_attachment(_name("receipts", "csv")))


@router.get("/items.csv")
def items_csv(conn: Conn) -> Response:
    body = export.to_csv(export.item_rows(conn), export.ITEM_COLUMNS)
    return Response(body, media_type="text/csv; charset=utf-8", headers=_attachment(_name("items", "csv")))


@router.get("/data.json")
def data_json(conn: Conn) -> JSONResponse:
    return JSONResponse(export.all_data(conn), headers=_attachment(_name("data", "json")))


@router.get("/backup.zip")
async def backup_zip(request: Request) -> FileResponse:
    folder = Path(tempfile.mkdtemp(prefix="bills-backup-"))
    path = folder / _name("backup", "zip")
    await run_in_threadpool(export.write_backup, request.app.state.db_path, path)

    def cleanup() -> None:
        path.unlink(missing_ok=True)
        folder.rmdir()

    return FileResponse(path, media_type="application/zip", filename=path.name,
                        headers={"Cache-Control": "no-store"}, background=BackgroundTask(cleanup))
