from __future__ import annotations

import asyncio
import sqlite3
from datetime import datetime, timezone
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query, Request, status
from starlette.concurrency import run_in_threadpool

from app.admin import COOKIE_NAME, verify_admin_token
from app.citations.bridge import MUTATING, CitationsUnavailable
from app.models import CitationAction, CitationComment, CitationCommentCreate


router = APIRouter(prefix="/citations")

SORT_KEYS = {
    "date": lambda row: (row.get("issued_at") or "", row.get("id") or ""),
    "person": lambda row: ((row.get("offender") or "").casefold(), row.get("issued_at") or ""),
    "type": lambda row: ((row.get("violation") or "").casefold(), row.get("issued_at") or ""),
    "status": lambda row: (
        {"open": 0, "resolved": 1, "void": 2}.get(row.get("status"), 3),
        0 if row.get("overdue") else 1,
        row.get("issued_at") or "",
    ),
    "due": lambda row: (row.get("due_at") is None, row.get("due_at") or "", row.get("issued_at") or ""),
    "comments": lambda row: (row.get("comment_count", 0), row.get("issued_at") or ""),
}
# Operations the public wall can perform without the organizer cookie (if enabled).
PUBLIC_WRITE_ACTIONS = {"issue-for-attendee", "add-remedy", "complete-remedy"}


def _bridge(request: Request):
    bridge = getattr(request.app.state, "citations", None)
    if bridge is None or not bridge.available:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(bridge.error if bridge is not None else None) or "Citations integration is not configured.",
        )
    return bridge


def _is_admin(request: Request) -> bool:
    settings = request.app.state.settings
    return settings.admin_password is not None and verify_admin_token(
        request.cookies.get(COOKIE_NAME), settings.admin_password
    )


async def _run(request: Request, action: str, params: dict[str, Any]) -> dict[str, Any]:
    bridge = _bridge(request)
    try:
        return await run_in_threadpool(bridge.run, action, params)
    except CitationsUnavailable as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


def _raise_for_failure(result: dict[str, Any]) -> dict[str, Any]:
    if not result.get("success"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT if "changed" in (result.get("error") or "") else status.HTTP_400_BAD_REQUEST,
            detail=result.get("error") or result.get("message") or "Citation action rejected.",
        )
    return result


@router.get("/status")
async def citations_status(request: Request) -> dict[str, Any]:
    bridge = getattr(request.app.state, "citations", None)
    settings = request.app.state.settings
    base = {
        "available": bool(bridge and bridge.available),
        "error": bridge.error if bridge is not None else "Citations integration is not configured.",
        "session_present": bool(bridge and bridge.session_present()),
        "admin": _is_admin(request),
        "public_write": settings.citations_public_write,
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }
    if not base["available"]:
        return {**base, "synchronization": None, "dashboard": None}
    sync_result = await _run(request, "sync-status", {})
    dashboard = await _run(request, "dashboard", {})
    return {
        **base,
        "synchronization": sync_result.get("record"),
        "dashboard": (dashboard.get("record") or {}) if dashboard.get("success") else None,
    }


@router.get("/wall")
async def citations_wall(
    request: Request,
    q: str = Query(default="", max_length=200),
    status_filter: Literal["all", "open", "resolved", "void"] = Query(default="all", alias="status"),
    offense: Literal["all", "first", "repeat"] = "all",
    overdue_only: bool = False,
    person: str = Query(default="", max_length=100),
    violation: str = Query(default="", max_length=120),
    issued_after: str = Query(default="", max_length=40),
    issued_before: str = Query(default="", max_length=40),
    sort: Literal["date", "person", "type", "status", "due", "comments"] = "date",
    order: Literal["asc", "desc"] = "desc",
) -> dict[str, Any]:
    params: dict[str, Any] = {"status": status_filter, "offense": offense, "overdue_only": overdue_only}
    if q:
        params["query"] = q
    if issued_after:
        params["issued_after"] = issued_after
    if issued_before:
        params["issued_before"] = issued_before
    result = _raise_for_failure(await _run(request, "search", params))
    rows = result.get("rows") or []
    if person:
        rows = [row for row in rows if row.get("offender", "").casefold() == person.casefold()]
    if violation:
        rows = [row for row in rows if row.get("violation", "").casefold() == violation.casefold()]
    counts = await run_in_threadpool(request.app.state.database.citation_comment_counts)
    for row in rows:
        row["comment_count"] = counts.get(row["id"], 0)
    rows.sort(key=SORT_KEYS[sort], reverse=order == "desc")
    facets = {
        "persons": sorted({row["offender"] for row in result.get("rows") or []}, key=str.casefold),
        "violations": sorted({row["violation"] for row in result.get("rows") or []}, key=str.casefold),
    }
    return {"items": rows, "total": len(rows), "facets": facets, "message": result.get("message", "")}


@router.get("/persons")
async def citations_persons(request: Request, q: str = Query(default="", max_length=100)) -> dict[str, Any]:
    result = _raise_for_failure(await _run(request, "search-persons", {"query": q} if q else {}))
    return {"items": result.get("rows") or []}


@router.get("/violations")
async def citations_violations(request: Request) -> dict[str, Any]:
    result = _raise_for_failure(await _run(request, "list-violations", {}))
    return {"items": result.get("rows") or []}


@router.get("/conflicts")
async def citations_conflicts(request: Request) -> dict[str, Any]:
    result = _raise_for_failure(await _run(request, "sync-conflicts", {}))
    return {"items": result.get("rows") or [], "message": result.get("message", "")}


@router.get("/{citation_id}")
async def citation_detail(request: Request, citation_id: str) -> dict[str, Any]:
    if not 1 <= len(citation_id) <= 64:
        raise HTTPException(status_code=404, detail="Citation not found")
    result = await _run(request, "get", {"citation": citation_id})
    if not result.get("success"):
        raise HTTPException(status_code=404, detail=result.get("error") or "Citation not found")
    history = await _run(request, "history", {"citation": citation_id})
    record = result.get("record") or {}
    comments = await run_in_threadpool(request.app.state.database.citation_comments, record.get("id", citation_id))
    return {
        "record": record,
        "receipt": result.get("receipt", ""),
        "remedies": result.get("rows") or [],
        "history": history.get("rows") or [],
        "comments": [CitationComment.model_validate(item).model_dump() for item in comments],
    }


@router.post("/{citation_id}/comments", response_model=CitationComment, status_code=status.HTTP_201_CREATED)
async def create_citation_comment(request: Request, citation_id: str, body: CitationCommentCreate) -> CitationComment:
    await request.app.state.rate_limiter.enforce(f"citation-comment:{body.browser_id}", 20, 60)
    lookup = await _run(request, "get", {"citation": citation_id})
    if not lookup.get("success"):
        raise HTTPException(status_code=404, detail="Citation not found")
    record_id = (lookup.get("record") or {}).get("id", citation_id)
    try:
        row = await run_in_threadpool(
            request.app.state.database.create_citation_comment, record_id, body.browser_id, body.author, body.text
        )
    except sqlite3.IntegrityError as exc:
        raise HTTPException(status_code=400, detail="Comment rejected") from exc
    comment = CitationComment.model_validate(row)
    await request.app.state.connections.broadcast("citation_comment_created", comment.model_dump())
    return comment


@router.post("/actions")
async def citation_action(request: Request, body: CitationAction) -> dict[str, Any]:
    """Run a documented citations action. Mutations need the organizer (admin) cookie
    unless CITATIONS_PUBLIC_WRITE allows the small attendee-facing subset."""
    settings = request.app.state.settings
    if body.action in {"export", "initialize"}:
        raise HTTPException(status_code=403, detail="This action is not exposed over the web.")
    if body.action in MUTATING and not _is_admin(request):
        if not (settings.citations_public_write and body.action in PUBLIC_WRITE_ACTIONS):
            raise HTTPException(status_code=401, detail="Organizer authorization required")
        client_host = request.client.host if request.client else "unknown"
        await request.app.state.rate_limiter.enforce(f"citation-public-write:{client_host}", 10, 60)
    if body.action in {"sync-now", "background-tick"}:
        if not _is_admin(request):
            raise HTTPException(status_code=401, detail="Organizer authorization required")
        worker = request.app.state.citations_worker
        return _raise_for_failure(await worker.tick("sync-now"))
    result = _raise_for_failure(await _run(request, body.action, body.params))
    if body.action in MUTATING:
        await request.app.state.connections.broadcast("citations_updated", {"action": body.action})
        worker = getattr(request.app.state, "citations_worker", None)
        if worker is not None:
            asyncio.get_running_loop().create_task(worker.notify_local_change())
    return result
