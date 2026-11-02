from __future__ import annotations

import shutil

from fastapi import APIRouter, Request
from starlette.concurrency import run_in_threadpool

from app.models import StatusResponse


router = APIRouter()


@router.get("/status", response_model=StatusResponse)
async def get_status(request: Request) -> StatusResponse:
    settings = request.app.state.settings
    database = request.app.state.database
    ollama = await request.app.state.ollama.status()
    database_status = await run_in_threadpool(database.health)
    media_bytes = await run_in_threadpool(database.media_bytes)
    disk = await run_in_threadpool(shutil.disk_usage, settings.data_dir)
    return StatusResponse(
        server={"status": "ok"},
        database=database_status,
        ollama={
            **ollama,
            "configured_model": settings.ollama_model,
            "configured_vision_model": settings.ollama_vision_model,
        },
        ffmpeg_available=shutil.which("ffmpeg") is not None,
        disk_free_bytes=disk.free,
        media_bytes=media_bytes,
        websocket_clients=request.app.state.connections.connected_count,
    )
