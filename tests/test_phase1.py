from __future__ import annotations

import sqlite3

from app.db import Database


def test_database_initialization_is_idempotent_and_uses_wal(settings) -> None:
    settings.ensure_directories()
    database = Database(settings.database_path)
    database.initialize()
    database.initialize()

    with sqlite3.connect(settings.database_path) as connection:
        tables = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        journal_mode = connection.execute("PRAGMA journal_mode").fetchone()[0]

    assert journal_mode == "wal"
    assert {
        "schema_migrations",
        "users",
        "chat_messages",
        "media",
        "media_comments",
        "schedule_events",
    } <= tables


def test_status_reports_degraded_ollama_without_breaking_server(client) -> None:
    response = client.get("/api/status")

    assert response.status_code == 200
    payload = response.json()
    assert payload["server"]["status"] == "ok"
    assert payload["database"]["journal_mode"] == "wal"
    assert payload["ollama"]["status"] == "unreachable"
    assert payload["websocket_clients"] == 0


def test_bootstrap_contains_authoritative_initial_state(client) -> None:
    response = client.get("/api/bootstrap")

    assert response.status_code == 200
    assert response.json() == {
        "app_name": "VirgoZone Test",
        "feature_flags": {
            "chat": True,
            "media": True,
            "schedule": True,
            "fairy": False,
            "vision": False,
            "fairy_auto_comment": False,
            "admin": True,
        },
        "ollama_online": False,
        "schedule": [],
        "media": [],
        "chat": [],
    }


def test_index_has_offline_security_headers(client) -> None:
    response = client.get("/")

    assert response.status_code == 200
    assert response.headers["x-content-type-options"] == "nosniff"
    assert "default-src 'self'" in response.headers["content-security-policy"]
    assert "VirgoZone" in response.text
