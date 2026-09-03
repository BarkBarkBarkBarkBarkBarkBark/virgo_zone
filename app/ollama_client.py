from __future__ import annotations

import asyncio
import base64
import time
from pathlib import Path
from typing import Any

import httpx


FAIRY_SYSTEM_PROMPT = """You are LAN FAIRY, the tiny weird fairy living inside this local network.
Make one very short, playful observation. Slightly absurd internet humor is welcome.
Never explain yourself. Avoid cruelty, sensitive personal assumptions, and generic assistant language.
Good energy: "the council reviewed this and unfortunately it goes hard"; "absolutely wizard behavior".
Return only the final observation, with no labels or preamble."""


class FairyUnavailableError(Exception):
    pass


class FairyBusyError(Exception):
    pass


class OllamaClient:
    def __init__(
        self,
        base_url: str,
        model: str,
        vision_model: str,
        vision_enabled: bool,
        timeout_seconds: int,
    ) -> None:
        self.base_url = base_url
        self.model = model
        self.vision_model = vision_model
        self.vision_enabled = vision_enabled
        self.timeout_seconds = timeout_seconds
        self._cached: dict[str, Any] | None = None
        self._cached_at = 0.0
        self._status_lock = asyncio.Lock()
        self._inference = asyncio.Semaphore(1)

    async def status(self, max_age_seconds: float = 5.0) -> dict[str, Any]:
        if self._cached is not None and time.monotonic() - self._cached_at < max_age_seconds:
            return self._cached
        async with self._status_lock:
            if self._cached is not None and time.monotonic() - self._cached_at < max_age_seconds:
                return self._cached
            try:
                timeout = httpx.Timeout(2.0, connect=0.5)
                async with httpx.AsyncClient(base_url=self.base_url, timeout=timeout) as client:
                    response = await client.get("/api/tags")
                    response.raise_for_status()
                models = sorted(
                    item["name"]
                    for item in response.json().get("models", [])
                    if isinstance(item, dict) and isinstance(item.get("name"), str)
                )
                vision_ready = False
                if self.vision_enabled and self.vision_model in models:
                    show = await client.post("/api/show", json={"model": self.vision_model})
                    show.raise_for_status()
                    vision_ready = "vision" in show.json().get("capabilities", [])
                value = {
                    "status": "ok",
                    "installed_models": models,
                    "vision_ready": vision_ready,
                    "detail": None,
                }
            except (httpx.HTTPError, ValueError, KeyError) as exc:
                value = {
                    "status": "unreachable",
                    "installed_models": [],
                    "vision_ready": False,
                    "detail": exc.__class__.__name__,
                }
            self._cached = value
            self._cached_at = time.monotonic()
            return value

    async def fairy_chat(self, prompt: str, context: list[dict[str, str]] | None = None) -> str:
        messages: list[dict[str, Any]] = [{"role": "system", "content": FAIRY_SYSTEM_PROMPT}]
        messages.extend(context or [])
        messages.append({"role": "user", "content": prompt})
        return await self._generate(self.model, messages)

    async def fairy_photo(
        self,
        caption: str | None,
        media_type: str,
        image_path: Path | None,
    ) -> str:
        prompt = "Comment on this uploaded image in the LAN FAIRY voice."
        if caption:
            prompt += f" The uploader captioned it: {caption}"
        status = await self.status()
        if self.vision_enabled and status["vision_ready"] and image_path and image_path.exists():
            image = base64.b64encode(image_path.read_bytes()).decode("ascii")
            try:
                return await self._generate(
                    self.vision_model,
                    [{"role": "user", "content": prompt, "images": [image]}],
                    timeout_seconds=max(self.timeout_seconds, 75),
                )
            except FairyUnavailableError:
                pass
        fallback = (
            f"Write a fairy comment for a shared {media_type} post. "
            f"Caption: {caption or 'No caption was provided.'} Do not claim you saw details not provided."
        )
        return await self.fairy_chat(fallback)

    async def _generate(
        self,
        model: str,
        messages: list[dict[str, Any]],
        timeout_seconds: int | None = None,
    ) -> str:
        try:
            await asyncio.wait_for(self._inference.acquire(), timeout=0.1)
        except asyncio.TimeoutError as exc:
            raise FairyBusyError("fairy is busy") from exc
        try:
            timeout = httpx.Timeout(float(timeout_seconds or self.timeout_seconds), connect=1.0)
            payload = {
                "model": model,
                "messages": messages,
                "stream": False,
                "keep_alive": "5m",
                "options": {
                    "num_ctx": 1_024,
                    "num_predict": 64,
                    "temperature": 0.85,
                },
            }
            try:
                async with httpx.AsyncClient(base_url=self.base_url, timeout=timeout) as client:
                    response = await client.post("/api/chat", json=payload)
                    response.raise_for_status()
                content = response.json().get("message", {}).get("content", "").strip()
            except (httpx.HTTPError, ValueError, KeyError) as exc:
                raise FairyUnavailableError("fairy is sleeping") from exc
            if not content:
                raise FairyUnavailableError("fairy is sleeping")
            return content[:500]
        finally:
            self._inference.release()
