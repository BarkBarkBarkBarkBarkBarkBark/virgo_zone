from __future__ import annotations

import asyncio
import base64
import re
import time
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

import httpx

from app.identity import build_hosaka_prompt


def clean_hosaka_response(content: str) -> str:
    cleaned = content.strip().strip('"')
    prefix = re.compile(
        r"^\s*(?:(?:LAN\s+FAIRY|HOSAKA|ASSISTANT)|[A-Za-z0-9_][A-Za-z0-9_ ]{0,39})\s*:\s*",
        re.IGNORECASE,
    )
    for _ in range(3):
        updated = prefix.sub("", cleaned, count=1).strip()
        if updated == cleaned:
            break
        cleaned = updated
    return cleaned.strip().strip('"')


def is_echo_response(response: str, prompt: str) -> bool:
    def normalize(value: str) -> str:
        return " ".join(re.findall(r"[a-z0-9]+", value.lower()))

    cleaned_response = normalize(response)
    cleaned_prompt = normalize(prompt)
    if not cleaned_response:
        return True
    if cleaned_response in cleaned_prompt or cleaned_prompt in cleaned_response:
        return True
    return SequenceMatcher(None, cleaned_response, cleaned_prompt).ratio() >= 0.72


def is_generic_assistant_response(response: str) -> bool:
    normalized = response.lower()
    markers = (
        "i'm sorry",
        "i am sorry",
        "i can't assist",
        "i cannot assist",
        "feel free to ask",
        "as an ai",
        "as a language model",
    )
    return any(marker in normalized for marker in markers)


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
        identity_dir: Path,
    ) -> None:
        self.base_url = base_url
        self.model = model
        self.vision_model = vision_model
        self.vision_enabled = vision_enabled
        self.timeout_seconds = timeout_seconds
        self.system_prompt = build_hosaka_prompt(identity_dir)
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
        messages: list[dict[str, Any]] = [{"role": "system", "content": self.system_prompt}]
        background = "\n".join(
            message["content"].strip()
            for message in (context or [])
            if message.get("role") == "user" and message.get("content", "").strip()
        )
        request = ""
        if background:
            request += f"Recent group chat, background only:\n{background}\n\n"
        request += f"Latest message:\n{prompt}\n\nReply to the latest message only."
        if re.search(r"\bjokes?\b", prompt, re.IGNORECASE):
            request += " The latest message is asking for a joke: tell one concise dry joke; do not answer yes or no."
        messages.append({"role": "user", "content": request})
        response = clean_hosaka_response(
            await self._generate(
                self.model,
                messages,
                timeout_seconds=max(self.timeout_seconds, 120),
            )
        )
        if is_echo_response(response, prompt) or is_generic_assistant_response(response):
            raise FairyUnavailableError("Hosaka chose silence")
        return response

    async def fairy_photo(
        self,
        caption: str | None,
        media_type: str,
        image_path: Path | None,
    ) -> str:
        prompt = "Comment on this uploaded image in Hosaka's concise voice."
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
            f"Write a concise Hosaka comment for a shared {media_type} post. "
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
            await asyncio.wait_for(
                self._inference.acquire(),
                timeout=float(timeout_seconds or self.timeout_seconds),
            )
        except asyncio.TimeoutError as exc:
            raise FairyBusyError("Hosaka is busy") from exc
        try:
            timeout = httpx.Timeout(float(timeout_seconds or self.timeout_seconds), connect=1.0)
            payload = {
                "model": model,
                "messages": messages,
                "stream": False,
                "keep_alive": "5m",
                "options": {
                    "num_ctx": 4_096,
                    "num_predict": -1,
                    "temperature": 0.55,
                    "repeat_penalty": 1.15,
                },
            }
            try:
                async with httpx.AsyncClient(base_url=self.base_url, timeout=timeout) as client:
                    response = await client.post("/api/chat", json=payload)
                    response.raise_for_status()
                content = response.json().get("message", {}).get("content", "").strip()
            except (httpx.HTTPError, ValueError, KeyError) as exc:
                raise FairyUnavailableError("Hosaka is offline") from exc
            if not content:
                raise FairyUnavailableError("Hosaka is offline")
            return content
        finally:
            self._inference.release()
