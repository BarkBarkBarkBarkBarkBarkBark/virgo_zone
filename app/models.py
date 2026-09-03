from __future__ import annotations

import re
from typing import Any, Literal

from datetime import datetime

from pydantic import BaseModel, Field, field_validator, model_validator


class ComponentStatus(BaseModel):
    status: Literal["ok", "unreachable", "error"]
    detail: str | None = None


class OllamaStatus(ComponentStatus):
    configured_model: str
    configured_vision_model: str
    installed_models: list[str] = Field(default_factory=list)
    vision_ready: bool = False


class StatusResponse(BaseModel):
    server: ComponentStatus
    database: dict[str, Any]
    ollama: OllamaStatus
    ffmpeg_available: bool
    disk_free_bytes: int
    media_bytes: int
    websocket_clients: int


class BootstrapResponse(BaseModel):
    app_name: str
    feature_flags: dict[str, bool]
    ollama_online: bool
    schedule: list[dict[str, Any]]
    media: list[dict[str, Any]]
    chat: list[dict[str, Any]]


class ChatCreate(BaseModel):
    browser_id: str = Field(min_length=8, max_length=100)
    author: str = Field(min_length=1, max_length=40)
    text: str = Field(min_length=1, max_length=2_000)
    reply_to: str | None = Field(default=None, max_length=36)

    @field_validator("browser_id")
    @classmethod
    def validate_browser_id(cls, value: str) -> str:
        if not re.fullmatch(r"[A-Za-z0-9-]+", value):
            raise ValueError("browser_id contains unsupported characters")
        return value

    @field_validator("author", "text")
    @classmethod
    def normalize_text(cls, value: str) -> str:
        normalized = re.sub(r"[\t ]+", " ", value.strip())
        if not normalized or not any(character.isprintable() and not character.isspace() for character in normalized):
            raise ValueError("value must contain visible text")
        return normalized


class ChatMessage(BaseModel):
    id: str
    author_id: str | None
    author_name: str
    text: str
    created_at: str
    is_ai: bool
    reply_to: str | None


class ChatPage(BaseModel):
    items: list[ChatMessage]
    next_cursor: str | None


class MediaPost(BaseModel):
    id: str
    author_id: str | None
    author_name: str
    caption: str | None
    media_type: str
    byte_size: int
    width: int | None
    height: int | None
    duration_seconds: float | None
    created_at: str
    comment_count: int
    original_url: str
    thumbnail_url: str | None


class MediaPage(BaseModel):
    items: list[MediaPost]
    next_cursor: str | None


class MediaCommentCreate(BaseModel):
    browser_id: str = Field(min_length=8, max_length=100)
    author: str = Field(min_length=1, max_length=40)
    text: str = Field(min_length=1, max_length=2_000)

    @field_validator("browser_id")
    @classmethod
    def validate_browser_id(cls, value: str) -> str:
        if not re.fullmatch(r"[A-Za-z0-9-]+", value):
            raise ValueError("browser_id contains unsupported characters")
        return value

    @field_validator("author", "text")
    @classmethod
    def normalize_text(cls, value: str) -> str:
        normalized = re.sub(r"[\t ]+", " ", value.strip())
        if not normalized or not any(character.isprintable() and not character.isspace() for character in normalized):
            raise ValueError("value must contain visible text")
        return normalized


class MediaComment(BaseModel):
    id: str
    media_id: str
    author_id: str | None
    author_name: str
    text: str
    created_at: str
    is_ai: bool


class MediaCommentPage(BaseModel):
    items: list[MediaComment]
    next_cursor: str | None


class AdminLogin(BaseModel):
    password: str = Field(min_length=1, max_length=256)


class ScheduleEventWrite(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=2_000)
    starts_at: datetime
    ends_at: datetime | None = None
    location: str | None = Field(default=None, max_length=160)

    @field_validator("title", "description", "location")
    @classmethod
    def normalize_fields(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = re.sub(r"[\t ]+", " ", value.strip())
        return normalized or None

    @field_validator("starts_at", "ends_at")
    @classmethod
    def require_timezone(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("schedule datetimes must include a timezone")
        return value

    @model_validator(mode="after")
    def validate_event(self) -> "ScheduleEventWrite":
        if self.title is None:
            raise ValueError("title must contain visible text")
        if self.ends_at is not None and self.ends_at <= self.starts_at:
            raise ValueError("ends_at must be later than starts_at")
        return self


class ScheduleEvent(ScheduleEventWrite):
    id: str
    created_at: str
    updated_at: str


class FairyChatRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=1_000)

    @field_validator("prompt")
    @classmethod
    def normalize_prompt(cls, value: str) -> str:
        normalized = re.sub(r"[\t ]+", " ", value.strip())
        if not normalized:
            raise ValueError("prompt must contain visible text")
        return normalized
