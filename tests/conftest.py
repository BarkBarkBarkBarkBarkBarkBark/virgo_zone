from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.main import create_app
from app.settings import Settings


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    data_dir = tmp_path / "data"
    return Settings(
        app_name="VirgoZone Test",
        host="127.0.0.1",
        port=8080,
        data_dir=data_dir,
        database_path=data_dir / "app.db",
        uploads_dir=data_dir / "uploads",
        thumbnails_dir=data_dir / "thumbnails",
        admin_password="neuro",
        image_max_bytes=20 * 1024 * 1024,
        video_max_bytes=250 * 1024 * 1024,
        min_free_bytes=128 * 1024 * 1024,
        ollama_base_url="http://127.0.0.1:9",
        ollama_model="qwen2.5:0.5b",
        ollama_vision_model="moondream:1.8b",
        ollama_vision_enabled=False,
        ollama_timeout_seconds=5,
        fairy_auto_comment=False,
        admin_session_seconds=3_600,
    )


@pytest.fixture
def client(settings: Settings):
    with TestClient(create_app(settings)) as test_client:
        yield test_client
