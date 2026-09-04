from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from starlette.concurrency import run_in_threadpool

from app.ollama_client import FairyUnavailableError, is_echo_response, is_generic_assistant_response


LOGGER = logging.getLogger("virgozone.fairy")
FAIRY_ID = "hosaka-system"
FAIRY_NAME = "HOSAKA"


def split_hosaka_messages(text: str, prompt: str, limit: int = 1_900) -> list[str]:
    paragraphs = [paragraph.strip() for paragraph in text.split("\n\n") if paragraph.strip()]
    messages: list[str] = []
    for paragraph in paragraphs:
        if is_echo_response(paragraph, prompt) or is_generic_assistant_response(paragraph):
            continue
        remaining = paragraph
        while len(remaining) > limit:
            boundary = remaining.rfind(" ", 0, limit + 1)
            if boundary < limit // 2:
                boundary = limit
            messages.append(remaining[:boundary].strip())
            remaining = remaining[boundary:].strip()
        if remaining:
            messages.append(remaining)
    if not messages:
        raise FairyUnavailableError("Hosaka chose silence")
    return messages


async def create_fairy_chat(
    app: Any,
    prompt: str,
    source_message_id: str | None = None,
) -> dict[str, Any]:
    database = app.state.database
    if source_message_id:
        contextual_rows = await run_in_threadpool(
            database.chat_before,
            source_message_id,
            12,
        )
    else:
        contextual_rows = await run_in_threadpool(database.latest_chat, 12)
    context = [
        {
            "role": "user",
            "content": item["text"],
        }
        for item in contextual_rows[-6:]
        if not item["is_ai"]
    ]
    await app.state.connections.broadcast(
        "fairy_typing",
        {"scope": "chat", "source_message_id": source_message_id},
    )
    try:
        text = await app.state.ollama.fairy_chat(prompt, context)
        rows: list[dict[str, Any]] = []
        for message in split_hosaka_messages(text, prompt):
            row = await run_in_threadpool(
                database.create_chat,
                FAIRY_ID,
                FAIRY_NAME,
                message,
                source_message_id,
                is_ai=True,
            )
            rows.append(row)
            await app.state.connections.broadcast("chat_created", row)
        return rows[-1]
    finally:
        await app.state.connections.broadcast(
            "fairy_finished",
            {"scope": "chat", "source_message_id": source_message_id},
        )


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


async def background_social_chat(app: Any, source_message_id: str, prompt: str) -> None:
    try:
        await app.state.social_awareness.consider(app, source_message_id, prompt)
    except Exception as exc:
        LOGGER.warning("social participation failed: %s", exc)


async def background_fairy_comment(app: Any, media: dict[str, Any]) -> None:
    try:
        await create_fairy_comment(app, media)
    except Exception as exc:
        LOGGER.warning("automatic Hosaka comment skipped: %s", exc)
