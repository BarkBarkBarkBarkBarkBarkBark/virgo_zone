from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Request
from starlette.concurrency import run_in_threadpool

from app.media import media_to_public
from app.models import BootstrapResponse


router = APIRouter()


@router.get("/bootstrap", response_model=BootstrapResponse)
async def get_bootstrap(request: Request) -> BootstrapResponse:
    settings = request.app.state.settings
    database = request.app.state.database
    ollama = await request.app.state.ollama.status()
    now_utc = datetime.now(timezone.utc).isoformat()
    schedule = await run_in_threadpool(database.upcoming_schedule, now_utc)
    media = await run_in_threadpool(database.latest_media, settings.media_page_size)
    chat = await run_in_threadpool(database.latest_chat, settings.chat_bootstrap_limit)
    installed = set(ollama["installed_models"])
    return BootstrapResponse(
        app_name=settings.app_name,
        feature_flags={
            "chat": True,
            "media": True,
            "schedule": True,
            "fairy": ollama["status"] == "ok" and settings.ollama_model in installed,
            "vision": ollama["status"] == "ok" and ollama["vision_ready"],
            "fairy_auto_comment": settings.fairy_auto_comment,
            "admin": settings.admin_password is not None,
        },
        ollama_online=ollama["status"] == "ok",
        schedule=schedule,
        media=[media_to_public(item) for item in media],
        chat=chat,
    )
