from __future__ import annotations

import logging
import socket
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.db import Database
from app.ollama_client import OllamaClient
from app.rate_limit import RateLimiter
from app.routes import api_router
from app.settings import Settings, get_settings
from app.websocket import ConnectionManager, router as websocket_router


LOGGER = logging.getLogger("virgozone")
APP_DIR = Path(__file__).resolve().parent


def preferred_lan_ip() -> str | None:
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.connect(("192.0.2.1", 9))
        address = probe.getsockname()[0]
        return address if not address.startswith("127.") else None
    except OSError:
        return None
    finally:
        probe.close()


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        resolved.ensure_directories()
        app.state.database.initialize()
        LOGGER.info("VirgoZone ready at http://virgozone.local:%s", resolved.port)
        lan_ip = preferred_lan_ip()
        if lan_ip:
            LOGGER.info("VirgoZone LAN fallback: http://%s:%s", lan_ip, resolved.port)
        yield

    app = FastAPI(
        title=resolved.app_name,
        docs_url=None,
        redoc_url=None,
        lifespan=lifespan,
    )
    app.state.settings = resolved
    app.state.database = Database(resolved.database_path)
    app.state.ollama = OllamaClient(
        resolved.ollama_base_url,
        resolved.ollama_model,
        resolved.ollama_vision_model,
        resolved.ollama_vision_enabled,
        resolved.ollama_timeout_seconds,
    )
    app.state.connections = ConnectionManager()
    app.state.rate_limiter = RateLimiter()
    app.include_router(api_router)
    app.include_router(websocket_router)
    app.mount("/static", StaticFiles(directory=APP_DIR / "static"), name="static")
    app.mount(
        "/media/uploads",
        StaticFiles(directory=resolved.uploads_dir, check_dir=False),
        name="media-uploads",
    )
    app.mount(
        "/media/thumbnails",
        StaticFiles(directory=resolved.thumbnails_dir, check_dir=False),
        name="media-thumbnails",
    )

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; img-src 'self' data: blob:; media-src 'self' blob:; "
            "style-src 'self'; script-src 'self'; connect-src 'self' ws: wss:; "
            "object-src 'none'; base-uri 'none'; frame-ancestors 'none'"
        )
        return response

    @app.get("/", include_in_schema=False)
    async def index() -> FileResponse:
        return FileResponse(APP_DIR / "templates" / "index.html")

    return app


app = create_app()
