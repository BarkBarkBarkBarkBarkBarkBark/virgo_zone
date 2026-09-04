from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class SocialDecision:
    speak: bool
    score: float
    reason: str
    direct: bool = False


class SocialAwareness:
    """Serialize Hosaka's response to each committed human chat turn."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()

    def decide(self, messages: list[dict[str, Any]]) -> SocialDecision:
        if not messages or messages[-1].get("is_ai"):
            return SocialDecision(False, 0.0, "no_human_turn")
        return SocialDecision(True, 1.0, "always_respond")

    async def consider(
        self,
        app: Any,
        source_message_id: str,
        prompt: str,
    ) -> dict[str, Any]:
        async with self._lock:
            from app.fairy import create_fairy_chat

            return await create_fairy_chat(app, prompt, source_message_id)
