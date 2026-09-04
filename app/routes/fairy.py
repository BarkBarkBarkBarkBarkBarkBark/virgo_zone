from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from starlette.concurrency import run_in_threadpool

from app.fairy import create_fairy_chat, create_fairy_comment
from app.models import ChatMessage, FairyChatRequest, MediaComment
from app.ollama_client import FairyBusyError, FairyUnavailableError


router = APIRouter()


def fairy_error(exc: Exception) -> HTTPException:
    if isinstance(exc, FairyBusyError):
        return HTTPException(status_code=429, detail="Hosaka is busy")
    return HTTPException(status_code=503, detail="Hosaka is offline")


@router.post("/fairy/chat", response_model=ChatMessage)
async def fairy_chat(body: FairyChatRequest, request: Request) -> ChatMessage:
    client_host = request.client.host if request.client else "unknown"
    await request.app.state.rate_limiter.enforce(f"fairy:{client_host}", 4, 60)
    try:
        row = await create_fairy_chat(request.app, body.prompt)
    except (FairyBusyError, FairyUnavailableError) as exc:
        raise fairy_error(exc) from exc
    return ChatMessage.model_validate(row)


@router.post("/media/{media_id}/fairy", response_model=MediaComment)
async def fairy_media(media_id: str, request: Request) -> MediaComment:
    client_host = request.client.host if request.client else "unknown"
    await request.app.state.rate_limiter.enforce(f"fairy:{client_host}", 4, 60)
    media = await run_in_threadpool(request.app.state.database.get_media, media_id)
    if media is None:
        raise HTTPException(status_code=404, detail="Media not found")
    try:
        row = await create_fairy_comment(request.app, media)
    except (FairyBusyError, FairyUnavailableError) as exc:
        raise fairy_error(exc) from exc
    return MediaComment.model_validate(row)
