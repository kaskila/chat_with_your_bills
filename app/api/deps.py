"""Shared request dependencies."""

import sqlite3
from collections.abc import Iterator

from fastapi import Request

from app.db.database import connect
from app.worker import Worker


def get_conn(request: Request) -> Iterator[sqlite3.Connection]:
    """One SQLite connection per request (cheap; WAL lets reads run while the worker writes)."""
    conn = connect(request.app.state.db_path)
    try:
        yield conn
    finally:
        conn.close()


def get_worker(request: Request) -> Worker:
    return request.app.state.worker
