from __future__ import annotations

import hmac
import ipaddress
import logging
import socket
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.citations.bridge import CitationsBridge
from app.citations.worker import CitationsWorker
from app.db import Database
from app.ollama_client import OllamaClient
from app.rate_limit import RateLimiter
from app.social_awareness import SocialAwareness
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


LOCAL_NETWORKS = tuple(
    ipaddress.ip_network(cidr)
    for cidr in ("127.0.0.0/8", "::1/128", "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "100.64.0.0/10", "fc00::/7", "fe80::/10")
)


def is_local_client(request: Request) -> bool:
    """Loopback, LAN, or tailnet peers are 'local'. Tailscale Funnel and other proxies
    put the real public client in X-Forwarded-For, which takes precedence."""
    forwarded = request.headers.get("x-forwarded-for", "")
    candidate = forwarded.split(",")[0].strip() if forwarded else (request.client.host if request.client else "")
    try:
        address = ipaddress.ip_address(candidate)
    except ValueError:
        return False
    return any(address in network for network in LOCAL_NETWORKS)


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        resolved.ensure_directories()
        app.state.database.initialize()
        app.state.citations.initialize()
        if app.state.citations.available:
            LOGGER.info("Citations wall at http://virgozone.local:%s/citations", resolved.port)
            app.state.citations_worker.start()
        LOGGER.info("VirgoZone ready at http://virgozone.local:%s", resolved.port)
        lan_ip = preferred_lan_ip()
        if lan_ip:
            LOGGER.info("VirgoZone LAN fallback: http://%s:%s", lan_ip, resolved.port)
        try:
            yield
        finally:
            await app.state.citations_worker.stop()

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
        resolved.hosaka_identity_dir,
    )
    app.state.connections = ConnectionManager()
    app.state.citations = CitationsBridge(
        resolved.citations_source,
        resolved.resolved_citations_data_dir,
        resolved.citations_remote_config(),
        resolved.citations_allow_network,
    )
    app.state.citations_worker = CitationsWorker(
        app.state.citations, app.state.connections, resolved.citations_sync_interval_seconds
    )
    app.state.rate_limiter = RateLimiter()
    app.state.social_awareness = SocialAwareness()
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
        token = resolved.citations_gate_token
        path = request.url.path
        if token and (path == "/citations" or path.startswith("/api/citations")):
            if not is_local_client(request) and not hmac.compare_digest(
                request.headers.get("x-gate-token", ""), token
            ):
                return JSONResponse({"detail": "Reach the citations wall through its gate."}, status_code=403)
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

    @app.get("/citations", include_in_schema=False)
    async def citations_page() -> FileResponse:
        return FileResponse(APP_DIR / "templates" / "citations.html")

    return app


app = create_app()
