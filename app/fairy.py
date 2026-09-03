from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from starlette.concurrency import run_in_threadpool


LOGGER = logging.getLogger("virgozone.fairy")
FAIRY_ID = "fairy-system"
FAIRY_NAME = "LAN FAIRY"


async def create_fairy_chat(app: Any, prompt: str) -> dict[str, Any]:
    database = app.state.database
    recent = await run_in_threadpool(database.latest_chat, 12)
    context = [
        {
            "role": "assistant" if item["is_ai"] else "user",
            "content": f"{item['author_name']}: {item['text']}",
        }
        for item in recent[-8:]
    ]
    await app.state.connections.broadcast("fairy_typing", {"scope": "chat"})
    try:
        text = await app.state.ollama.fairy_chat(prompt, context)
        row = await run_in_threadpool(
            database.create_chat,
            FAIRY_ID,
            FAIRY_NAME,
            text,
            None,
            is_ai=True,
        )
        await app.state.connections.broadcast("chat_created", row)
        return row
    finally:
        await app.state.connections.broadcast("fairy_finished", {"scope": "chat"})


async def create_fairy_comment(app: Any, media: dict[str, Any]) -> dict[str, Any]:
    settings = app.state.settings
    image_path: Path | None = None
    if media.get("vision_path"):
        image_path = settings.thumbnails_dir / media["vision_path"]
    await app.state.connections.broadcast(
        "fairy_typing",
        {"scope": "media", "media_id": media["id"]},
    )
    try:
        text = await app.state.ollama.fairy_photo(
            media.get("caption"),
            media["media_type"],
            image_path,
        )
        row = await run_in_threadpool(
            app.state.database.create_comment,
            media["id"],
            FAIRY_ID,
            FAIRY_NAME,
            text,
            is_ai=True,
        )
        await app.state.connections.broadcast("media_comment_created", row)
        return row
    finally:
        await app.state.connections.broadcast(
            "fairy_finished",
            {"scope": "media", "media_id": media["id"]},
        )


async def background_fairy_chat(app: Any, prompt: str) -> None:
    try:
        await create_fairy_chat(app, prompt)
    except Exception as exc:
        LOGGER.warning("background fairy response failed: %s", exc)


async def background_fairy_comment(app: Any, media: dict[str, Any]) -> None:
    try:
        await create_fairy_comment(app, media)
    except Exception as exc:
        LOGGER.warning("automatic fairy comment skipped: %s", exc)
