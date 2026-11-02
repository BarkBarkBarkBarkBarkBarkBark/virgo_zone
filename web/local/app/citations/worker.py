from __future__ import annotations

import asyncio
import logging
from typing import Any

from starlette.concurrency import run_in_threadpool

from app.citations.bridge import CitationsBridge, CitationsUnavailable

LOGGER = logging.getLogger("virgozone.citations.worker")


def digest(status: dict[str, Any]) -> tuple:
    """The parts of sync status whose change means browsers should refresh."""
    return tuple(status.get(key) for key in ("remote_cursor", "pending_changes", "last_error", "unresolved_conflicts", "pull_incomplete"))


class CitationsWorker:
    """Periodic background-tick against the shared workspace; broadcasts `citations_updated`."""

    def __init__(self, bridge: CitationsBridge, connections, interval_seconds: int) -> None:
        self.bridge = bridge
        self.connections = connections
        self.interval = max(15, interval_seconds)
        self._task: asyncio.Task | None = None
        self._last: tuple | None = None

    def start(self) -> None:
        if self.bridge.available and self._task is None:
            self._task = asyncio.create_task(self._loop(), name="citations-sync")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
            self._task = None

    async def _loop(self) -> None:
        while True:
            try:
                await self.tick("background-tick")
            except Exception:  # pragma: no cover - defensive; the loop must survive
                LOGGER.exception("Citations sync tick failed")
            await asyncio.sleep(self.interval)

    async def tick(self, action: str = "background-tick") -> dict[str, Any]:
        try:
            result = await run_in_threadpool(self.bridge.run, action, {})
        except CitationsUnavailable as exc:
            return {"success": False, "message": "Citations unavailable.", "error": str(exc), "record": {}}
        status = result.get("record") or {}
        current = digest(status)
        if current != self._last:
            self._last = current
            await self.connections.broadcast("citations_updated", {"synchronization": status})
        return result

    async def notify_local_change(self) -> None:
        """A VirgoZone user mutated a citation: push promptly (ignoring the interval) and tell every browser."""
        self._last = None
        await self.tick("sync-now")
