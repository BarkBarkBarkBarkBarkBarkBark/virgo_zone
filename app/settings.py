from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlparse


PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _read_int(name: str, default: int, minimum: int, maximum: int) -> int:
    raw = os.getenv(name, str(default))
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if not minimum <= value <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return value


def _read_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name, str(default)).strip().lower()
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be true or false")


def _validate_ollama_url(raw: str) -> str:
    parsed = urlparse(raw)
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("OLLAMA_BASE_URL must be a loopback HTTP URL")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("OLLAMA_BASE_URL must not contain credentials, a query, or a fragment")
    return raw.rstrip("/")


@dataclass(frozen=True)
class Settings:
    app_name: str
    host: str
    port: int
    data_dir: Path
    database_path: Path
    uploads_dir: Path
    thumbnails_dir: Path
    admin_password: str | None
    image_max_bytes: int
    video_max_bytes: int
    min_free_bytes: int
    ollama_base_url: str
    ollama_model: str
    ollama_vision_model: str
    ollama_vision_enabled: bool
    ollama_timeout_seconds: int
    fairy_auto_comment: bool
    hosaka_identity_dir: Path = Path("/home/jetson/Hosaka/identity")
    admin_session_seconds: int = 28_800
    media_page_size: int = 30
    chat_bootstrap_limit: int = 100
    # Citations: VirgoZone drives the halloween-citations extension API from its checkout.
    citations_source: Path | None = None
    citations_data_dir: Path | None = None
    citations_supabase_url: str | None = None
    citations_publishable_key: str | None = None
    citations_workspace_id: str | None = None
    citations_sync_enabled: bool | None = None
    citations_sync_interval_seconds: int = 60
    citations_allow_network: bool = True
    citations_public_write: bool = False
    # When set, /citations and /api/citations/* require this X-Gate-Token header
    # (sent by the citations.hosaka.xyz gate), except from loopback clients.
    citations_gate_token: str | None = None

    @classmethod
    def from_env(cls) -> "Settings":
        data_dir = Path(os.getenv("DATA_DIR", str(PROJECT_ROOT / "data"))).expanduser().resolve()
        image_max_mb = _read_int("IMAGE_MAX_MB", 20, 1, 100)
        video_max_mb = _read_int("VIDEO_MAX_MB", 250, 1, 2_000)
        min_free_mb = _read_int("MIN_FREE_MB", 1_024, 128, 100_000)
        admin_password = os.getenv("ADMIN_PASSWORD", "neuro").strip() or None
        citations_source = os.getenv("CITATIONS_SOURCE", "").strip()
        citations_key = os.getenv("CITATIONS_PUBLISHABLE_KEY", "").strip()
        if citations_key.startswith("sb_secret_"):
            raise ValueError("CITATIONS_PUBLISHABLE_KEY must be a publishable/anon key, never a secret key")
        citations_url = os.getenv("CITATIONS_SUPABASE_URL", "").strip()
        if citations_url and urlparse(citations_url).scheme != "https":
            raise ValueError("CITATIONS_SUPABASE_URL must be an https origin")
        return cls(
            app_name=os.getenv("APP_NAME", "VirgoZone").strip() or "VirgoZone",
            host=os.getenv("VIRGOZONE_HOST", os.getenv("FAIRYLAN_HOST", "0.0.0.0")).strip(),
            port=_read_int(
                "VIRGOZONE_PORT" if "VIRGOZONE_PORT" in os.environ else "FAIRYLAN_PORT",
                8_080,
                1_024,
                65_535,
            ),
            data_dir=data_dir,
            database_path=data_dir / "app.db",
            uploads_dir=data_dir / "uploads",
            thumbnails_dir=data_dir / "thumbnails",
            admin_password=admin_password,
            image_max_bytes=image_max_mb * 1_024 * 1_024,
            video_max_bytes=video_max_mb * 1_024 * 1_024,
            min_free_bytes=min_free_mb * 1_024 * 1_024,
            ollama_base_url=_validate_ollama_url(
                os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
            ),
            ollama_model=os.getenv("OLLAMA_MODEL", "qwen2.5:0.5b").strip()
            or "qwen2.5:0.5b",
            ollama_vision_model=os.getenv("OLLAMA_VISION_MODEL", "moondream:1.8b").strip()
            or "moondream:1.8b",
            ollama_vision_enabled=_read_bool("OLLAMA_VISION_ENABLED", False),
            ollama_timeout_seconds=_read_int("OLLAMA_TIMEOUT_SECONDS", 45, 2, 300),
            fairy_auto_comment=_read_bool("FAIRY_AUTO_COMMENT", False),
            hosaka_identity_dir=Path(
                os.getenv("HOSAKA_IDENTITY_DIR", "/home/jetson/Hosaka/identity")
            ).expanduser().resolve(),
            admin_session_seconds=_read_int("ADMIN_SESSION_SECONDS", 28_800, 300, 604_800),
            citations_source=Path(citations_source).expanduser().resolve() if citations_source else None,
            citations_data_dir=Path(
                os.getenv("CITATIONS_DATA_DIR", str(data_dir / "citations"))
            ).expanduser().resolve(),
            citations_supabase_url=citations_url or None,
            citations_publishable_key=citations_key or None,
            citations_workspace_id=os.getenv("CITATIONS_WORKSPACE_ID", "").strip() or None,
            citations_sync_enabled=(
                _read_bool("CITATIONS_SYNC_ENABLED", False) if "CITATIONS_SYNC_ENABLED" in os.environ else None
            ),
            citations_sync_interval_seconds=_read_int("CITATIONS_SYNC_INTERVAL_SECONDS", 60, 15, 86_400),
            citations_allow_network=_read_bool("CITATIONS_ALLOW_NETWORK", True),
            citations_public_write=_read_bool("CITATIONS_PUBLIC_WRITE", False),
            citations_gate_token=os.getenv("CITATIONS_GATE_TOKEN", "").strip() or None,
        )

    def ensure_directories(self) -> None:
        for path in (self.data_dir, self.uploads_dir, self.thumbnails_dir):
            path.mkdir(parents=True, exist_ok=True)

    @property
    def resolved_citations_data_dir(self) -> Path:
        return self.citations_data_dir or (self.data_dir / "citations")

    def citations_remote_config(self) -> dict:
        """Fields written into the extension's citations-config.json; None means keep existing."""
        return {
            "supabase_url": self.citations_supabase_url,
            "publishable_key": self.citations_publishable_key,
            "workspace_id": self.citations_workspace_id,
            "sync_enabled": self.citations_sync_enabled,
            "sync_interval_seconds": self.citations_sync_interval_seconds,
        }


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings.from_env()
