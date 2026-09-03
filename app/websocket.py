from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect


router = APIRouter()


class ConnectionManager:
    def __init__(self) -> None:
        self._connections: set[WebSocket] = set()
        self._broadcast_lock = asyncio.Lock()

    @property
    def connected_count(self) -> int:
        return len(self._connections)

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self._connections.add(websocket)

    def detach(self, websocket: WebSocket) -> None:
        self._connections.discard(websocket)

    async def broadcast(self, event_type: str, payload: dict[str, Any]) -> None:
        envelope = json.dumps(
            {"type": event_type, "payload": payload},
            ensure_ascii=False,
            separators=(",", ":"),
        )
        async with self._broadcast_lock:
            connections = list(self._connections)
            results = await asyncio.gather(
                *(self._send(websocket, envelope) for websocket in connections),
                return_exceptions=True,
            )
            for websocket, result in zip(connections, results):
                if result is not True:
                    self.detach(websocket)

    @staticmethod
    async def _send(websocket: WebSocket, envelope: str) -> bool:
        try:
            await asyncio.wait_for(websocket.send_text(envelope), timeout=2.0)
        except Exception:
            return False
        return True


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    manager: ConnectionManager = websocket.app.state.connections
    await manager.connect(websocket)
    await websocket.send_json({"type": "hello", "payload": {"protocol": 1}})
    try:
        while True:
            message = await websocket.receive_text()
            if message == "ping":
                await websocket.send_json({"type": "pong", "payload": {}})
    except WebSocketDisconnect:
        manager.detach(websocket)
    except Exception:
        manager.detach(websocket)
