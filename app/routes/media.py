from __future__ import annotations

import re
import sqlite3
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, Query, Request, Response, UploadFile, status
from starlette.concurrency import run_in_threadpool

from app.admin import require_admin
from app.fairy import background_fairy_comment
from app.media import MediaService, MediaValidationError, media_to_public
from app.models import MediaComment, MediaCommentCreate, MediaCommentPage, MediaPage, MediaPost


router = APIRouter()


def _normalize_name(value: str) -> str:
    normalized = re.sub(r"[\t ]+", " ", value.strip())
    if not normalized or len(normalized) > 40:
        raise HTTPException(status_code=422, detail="Display name must be 1 to 40 characters")
    return normalized


def _normalize_caption(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = re.sub(r"[\t ]+", " ", value.strip())
    if not normalized:
        return None
    if len(normalized) > 500:
        raise HTTPException(status_code=422, detail="Caption must be at most 500 characters")
    return normalized


@router.get("/media", response_model=MediaPage)
async def get_media(
    request: Request,
    before: str | None = None,
    limit: int = Query(default=30, ge=1, le=60),
) -> MediaPage:
    rows = await run_in_threadpool(request.app.state.database.media_page, limit + 1, before)
    has_more = len(rows) > limit
    items = rows[:limit]
    posts = [MediaPost.model_validate(media_to_public(item)) for item in items]
    return MediaPage(items=posts, next_cursor=posts[-1].id if has_more and posts else None)


@router.post("/media", response_model=MediaPost, status_code=status.HTTP_201_CREATED)
async def post_media(
    request: Request,
    background_tasks: BackgroundTasks,
    file: Annotated[UploadFile, File()],
    browser_id: Annotated[str, Form(min_length=8, max_length=100)],
    author: Annotated[str, Form(min_length=1, max_length=40)],
    caption: Annotated[str | None, Form(max_length=500)] = None,
) -> MediaPost:
    if not re.fullmatch(r"[A-Za-z0-9-]+", browser_id):
        raise HTTPException(status_code=422, detail="Invalid browser identity")
    settings = request.app.state.settings
    await request.app.state.rate_limiter.enforce(f"upload:{browser_id}", 8, 600)
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            request_bytes = int(content_length)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Invalid Content-Length") from exc
        if request_bytes > settings.video_max_bytes + 1024 * 1024:
            raise HTTPException(status_code=413, detail="Upload exceeds the configured size limit")
    service = MediaService(settings)
    try:
        stored = await run_in_threadpool(service.store, file.file, file.content_type)
    except MediaValidationError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    values = {
        **stored.database_values(),
        "author_id": browser_id,
        "author_name": _normalize_name(author),
        "caption": _normalize_caption(caption),
    }
    try:
        row = await run_in_threadpool(request.app.state.database.create_media, values)
    except sqlite3.Error:
        await run_in_threadpool(service.cleanup, stored)
        raise
    post = MediaPost.model_validate(media_to_public(row))
    await request.app.state.connections.broadcast("media_created", post.model_dump())
    if settings.fairy_auto_comment and stored.media_type.startswith("image/"):
        background_tasks.add_task(background_fairy_comment, request.app, row)
    return post


@router.get("/media/{media_id}/comments", response_model=MediaCommentPage)
async def get_comments(
    media_id: str,
    request: Request,
    before: str | None = None,
    limit: int = Query(default=100, ge=1, le=100),
) -> MediaCommentPage:
    if not await run_in_threadpool(request.app.state.database.media_exists, media_id):
        raise HTTPException(status_code=404, detail="Media not found")
    rows = await run_in_threadpool(
        request.app.state.database.comment_page,
        media_id,
        limit + 1,
        before,
    )
    has_more = len(rows) > limit
    items = rows[:limit]
    comments = [MediaComment.model_validate(item) for item in reversed(items)]
    return MediaCommentPage(
        items=comments,
        next_cursor=items[-1]["id"] if has_more and items else None,
    )


@router.post(
    "/media/{media_id}/comments",
    response_model=MediaComment,
    status_code=status.HTTP_201_CREATED,
)
async def post_comment(
    media_id: str,
    body: MediaCommentCreate,
    request: Request,
) -> MediaComment:
    await request.app.state.rate_limiter.enforce(
        f"comment:{body.browser_id}",
        30,
        60,
    )
    try:
        row = await run_in_threadpool(
            request.app.state.database.create_comment,
            media_id,
            body.browser_id,
            body.author,
            body.text,
        )
    except sqlite3.IntegrityError as exc:
        raise HTTPException(status_code=404, detail="Media not found") from exc
    comment = MediaComment.model_validate(row)
    await request.app.state.connections.broadcast(
        "media_comment_created",
        comment.model_dump(),
    )
    return comment


@router.delete(
    "/media/{media_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
async def delete_media(media_id: str, request: Request) -> Response:
    require_admin(request)
    database = request.app.state.database
    files = await run_in_threadpool(database.get_media_files, media_id)
    if files is None:
        raise HTTPException(status_code=404, detail="Media not found")
    deleted = await run_in_threadpool(database.delete_media, media_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Media not found")
    settings = request.app.state.settings
    paths = [
        settings.uploads_dir / files["original_path"],
        settings.thumbnails_dir / files["thumbnail_path"] if files["thumbnail_path"] else None,
        settings.thumbnails_dir / files["vision_path"] if files["vision_path"] else None,
    ]
    for path in {path for path in paths if path is not None}:
        await run_in_threadpool(path.unlink, True)
    await request.app.state.connections.broadcast("media_deleted", {"id": media_id})
    return Response(status_code=status.HTTP_204_NO_CONTENT)
