"""Chat over the stored receipts (see app/chat)."""

import sqlite3
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from app.api.deps import get_conn
from app.chat import agent
from app.llm.client import LLMError

router = APIRouter(prefix="/api", tags=["chat"])

Conn = Annotated[sqlite3.Connection, Depends(get_conn)]


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=500)
    # Earlier turns: {"role": "user", "content": ...} and {"role": "assistant", "tool": ..., "call": {...}}
    history: list[dict] = Field(default_factory=list, max_length=20)


@router.post("/chat")
async def post_chat(body: ChatRequest, conn: Conn) -> dict:
    try:
        result = await run_in_threadpool(agent.ask, conn, body.message, history=body.history)
    except LLMError as error:
        raise HTTPException(503, str(error)) from error
    return result.to_dict()
