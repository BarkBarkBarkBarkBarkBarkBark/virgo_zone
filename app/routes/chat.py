from __future__ import annotations

import sqlite3

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, Request, status
from starlette.concurrency import run_in_threadpool

from app.models import ChatCreate, ChatMessage, ChatPage
from app.fairy import background_fairy_chat


router = APIRouter()


@router.get("/chat", response_model=ChatPage)
async def get_chat(
    request: Request,
    before: str | None = None,
    limit: int = Query(default=50, ge=1, le=100),
) -> ChatPage:
    rows = await run_in_threadpool(request.app.state.database.chat_page, limit + 1, before)
    has_more = len(rows) > limit
    items = rows[:limit]
    return ChatPage(
        items=[ChatMessage.model_validate(item) for item in items],
        next_cursor=items[-1]["id"] if has_more and items else None,
    )


@router.post("/chat", response_model=ChatMessage, status_code=status.HTTP_201_CREATED)
async def post_chat(
    body: ChatCreate,
    request: Request,
    background_tasks: BackgroundTasks,
) -> ChatMessage:
    await request.app.state.rate_limiter.enforce(f"chat:{body.browser_id}", 30, 60)
    try:
        row = await run_in_threadpool(
            request.app.state.database.create_chat,
            body.browser_id,
            body.author,
            body.text,
            body.reply_to,
        )
    except sqlite3.IntegrityError as exc:
        raise HTTPException(status_code=400, detail="Invalid reply target") from exc
    message = ChatMessage.model_validate(row)
    await request.app.state.connections.broadcast("chat_created", message.model_dump())
    if "@fairy" in body.text.lower():
        background_tasks.add_task(background_fairy_chat, request.app, body.text)
    return message
