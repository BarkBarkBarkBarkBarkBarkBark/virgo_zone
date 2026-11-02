from __future__ import annotations

from datetime import timezone

from fastapi import APIRouter, HTTPException, Request, Response, status
from starlette.concurrency import run_in_threadpool

from app.admin import require_admin
from app.models import ScheduleEvent, ScheduleEventWrite


router = APIRouter()


def _database_values(body: ScheduleEventWrite) -> dict[str, str | None]:
    return {
        "title": body.title,
        "description": body.description,
        "starts_at": body.starts_at.astimezone(timezone.utc).isoformat(),
        "ends_at": body.ends_at.astimezone(timezone.utc).isoformat() if body.ends_at else None,
        "location": body.location,
    }


@router.get("/schedule", response_model=list[ScheduleEvent])
async def get_schedule(request: Request) -> list[ScheduleEvent]:
    rows = await run_in_threadpool(request.app.state.database.schedule_all)
    return [ScheduleEvent.model_validate(row) for row in rows]


@router.post("/schedule", response_model=ScheduleEvent, status_code=status.HTTP_201_CREATED)
async def create_schedule(body: ScheduleEventWrite, request: Request) -> ScheduleEvent:
    require_admin(request)
    row = await run_in_threadpool(request.app.state.database.create_schedule, _database_values(body))
    event = ScheduleEvent.model_validate(row)
    await request.app.state.connections.broadcast("schedule_created", event.model_dump(mode="json"))
    return event


@router.patch("/schedule/{event_id}", response_model=ScheduleEvent)
async def update_schedule(
    event_id: str,
    body: ScheduleEventWrite,
    request: Request,
) -> ScheduleEvent:
    require_admin(request)
    row = await run_in_threadpool(
        request.app.state.database.update_schedule,
        event_id,
        _database_values(body),
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Schedule event not found")
    event = ScheduleEvent.model_validate(row)
    await request.app.state.connections.broadcast("schedule_updated", event.model_dump(mode="json"))
    return event


@router.delete("/schedule/{event_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_schedule(event_id: str, request: Request) -> Response:
    require_admin(request)
    deleted = await run_in_threadpool(request.app.state.database.delete_schedule, event_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Schedule event not found")
    await request.app.state.connections.broadcast("schedule_deleted", {"id": event_id})
    return Response(status_code=status.HTTP_204_NO_CONTENT)
