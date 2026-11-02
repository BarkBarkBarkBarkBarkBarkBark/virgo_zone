from __future__ import annotations

import dataclasses
import os
import threading
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.settings import Settings
from app.citations.bridge import CitationsBridge


CITATIONS_SOURCE = Path(
    os.getenv("CITATIONS_SOURCE", str(Path(__file__).resolve().parents[2] / "hosaka_citations/extension"))
).resolve()
HAS_SOURCE = (CITATIONS_SOURCE / "main.py").is_file() and (CITATIONS_SOURCE / "citations" / "__init__.py").is_file()
needs_source = pytest.mark.skipif(not HAS_SOURCE, reason="hosaka_citations checkout not available")


def test_read_does_not_wait_for_network_synchronization():
    bridge = object.__new__(CitationsBridge)
    bridge.context = object()
    bridge._lock = threading.Lock()
    bridge._sync_lock = threading.Lock()
    entered, finish = threading.Event(), threading.Event()

    def run(action, params, context):
        if action == "sync-now":
            entered.set()
            assert finish.wait(2)
        return {"success": True}

    bridge._run = run
    worker = threading.Thread(target=bridge.run, args=("sync-now",))
    worker.start()
    try:
        assert entered.wait(1)
        assert bridge.run("get", {"citation": "synthetic"})["success"]
    finally:
        finish.set()
        worker.join(timeout=3)


@pytest.fixture
def citations_settings(settings: Settings) -> Settings:
    return dataclasses.replace(
        settings,
        citations_source=CITATIONS_SOURCE,
        citations_data_dir=settings.data_dir / "citations",
        citations_sync_enabled=False,
        citations_allow_network=False,
    )


@pytest.fixture
def citations_client(citations_settings: Settings):
    with TestClient(create_app(citations_settings)) as test_client:
        yield test_client


def login(client: TestClient) -> None:
    assert client.post("/api/admin/login", json={"password": "neuro"}).status_code == 204


def test_wall_degrades_without_source(client: TestClient) -> None:
    status = client.get("/api/citations/status").json()
    assert status["available"] is False
    assert "CITATIONS_SOURCE" in status["error"]
    assert client.get("/api/citations/wall").status_code == 503
    page = client.get("/citations")
    assert page.status_code == 200
    assert "Wall of shame" in page.text


@needs_source
def test_issue_filter_sort_and_detail(citations_client: TestClient, citations_settings: Settings) -> None:
    client = citations_client
    assert client.get("/api/citations/status").json()["available"] is True

    # Mutations need the organizer cookie.
    denied = client.post("/api/citations/actions", json={"action": "issue-for-attendee", "params": {"display_name": "X", "violation": "no-costume"}})
    assert denied.status_code == 401

    login(client)
    violations = client.get("/api/citations/violations").json()["items"]
    assert violations, "default violation templates should exist"
    codes = [row["code"] for row in violations]

    first = client.post("/api/citations/actions", json={
        "action": "issue-for-attendee",
        "params": {"display_name": "Alice Ghoul", "violation": codes[0], "description": "Arrived uncostumed", "actor": "Test"},
    })
    assert first.status_code == 200, first.text
    second = client.post("/api/citations/actions", json={
        "action": "issue-for-attendee",
        "params": {"display_name": "Bob Bones", "violation": codes[-1], "remedy": "Howl once", "actor": "Test"},
    })
    assert second.status_code == 200, second.text
    alice = first.json()["record"]

    wall = client.get("/api/citations/wall", params={"sort": "person", "order": "asc"}).json()
    assert [row["offender"] for row in wall["items"]] == ["Alice Ghoul", "Bob Bones"]
    assert set(wall["facets"]["persons"]) == {"Alice Ghoul", "Bob Bones"}

    by_person = client.get("/api/citations/wall", params={"person": "bob bones"}).json()
    assert by_person["total"] == 1 and by_person["items"][0]["offender"] == "Bob Bones"

    by_type = client.get("/api/citations/wall", params={"violation": alice["violation"]}).json()
    assert alice["id"] in {row["id"] for row in by_type["items"]}

    # Resolve Alice; the status filter must separate open from resolved.
    resolved = client.post("/api/citations/actions", json={
        "action": "resolve", "params": {"citation": alice["id"], "expected_revision": alice["revision"], "actor": "Test", "override_reason": "Test override"},
    })
    assert resolved.status_code == 200, resolved.text
    assert client.get("/api/citations/wall", params={"status": "open"}).json()["total"] == 1
    assert client.get("/api/citations/wall", params={"status": "resolved"}).json()["items"][0]["id"] == alice["id"]

    stale = client.post("/api/citations/actions", json={
        "action": "reopen", "params": {"citation": alice["id"], "expected_revision": alice["revision"], "reason": "Nope", "actor": "Test"},
    })
    assert stale.status_code in (400, 409)

    detail = client.get(f"/api/citations/{alice['id']}").json()
    assert detail["record"]["status"] == "resolved"
    assert "VIOLATION NOTICE" in detail["receipt"]
    assert any(event["event_type"] for event in detail["history"])


    # The replica lives in VirgoZone's own data directory, never in the extension source.
    assert (citations_settings.data_dir / "citations" / "citations.db").exists()
    assert not (CITATIONS_SOURCE / "citations.db").exists()


@needs_source
def test_new_violation_title_creates_a_template(citations_client: TestClient) -> None:
    client = citations_client
    login(client)
    issued = client.post("/api/citations/actions", json={
        "action": "issue-for-attendee",
        "params": {"display_name": "Sandal Ghost", "violation": "Socks with sandals"},
    })
    assert issued.status_code == 200, issued.text
    assert issued.json()["record"]["violation"] == "Socks with sandals"
    titles = [row["title"] for row in client.get("/api/citations/violations").json()["items"]]
    assert titles.count("Socks with sandals") == 1
    again = client.post("/api/citations/actions", json={
        "action": "issue-for-attendee",
        "params": {"display_name": "Sandal Ghost", "violation": "socks with sandals"},
    })
    assert again.status_code == 200, again.text
    assert again.json()["record"]["violation_type_id"] == issued.json()["record"]["violation_type_id"]
    titles = [row["title"] for row in client.get("/api/citations/violations").json()["items"]]
    assert titles.count("Socks with sandals") == 1


@needs_source
def test_comments_are_local_and_counted(citations_client: TestClient) -> None:
    client = citations_client
    login(client)
    code = client.get("/api/citations/violations").json()["items"][0]["code"]
    issued = client.post("/api/citations/actions", json={
        "action": "issue-for-attendee", "params": {"display_name": "Cara Crypt", "violation": code},
    }).json()["record"]

    missing = client.post("/api/citations/00000000-0000-0000-0000-000000000000/comments", json={
        "browser_id": "browser-1234", "author": "Guest", "text": "boo",
    })
    assert missing.status_code == 404

    created = client.post(f"/api/citations/{issued['id']}/comments", json={
        "browser_id": "browser-1234", "author": "Guest", "text": "Deserved."
    })
    assert created.status_code == 201, created.text
    assert created.json()["citation_id"] == issued["id"]

    detail = client.get(f"/api/citations/{issued['id']}").json()
    assert [comment["text"] for comment in detail["comments"]] == ["Deserved."]
    wall = client.get("/api/citations/wall", params={"sort": "comments"}).json()
    assert wall["items"][0]["comment_count"] == 1
    # Comments never enter the extension's outbox.
    assert client.get("/api/citations/status").json()["synchronization"]["pending_changes"] >= 1  # the citation itself


@needs_source
def test_forbidden_actions_and_public_write(citations_client: TestClient) -> None:
    client = citations_client
    login(client)
    assert client.post("/api/citations/actions", json={"action": "export", "params": {}}).status_code == 403
    assert client.post("/api/citations/actions", json={"action": "bogus", "params": {}}).status_code == 400
    assert client.post("/api/citations/actions", json={"action": "sync-now", "params": {}}).json()["record"]["enabled"] is False


def test_gate_token_guards_citations(settings: Settings) -> None:
    gated = dataclasses.replace(settings, citations_gate_token="gate-secret")
    with TestClient(create_app(gated), client=("203.0.113.9", 4000)) as remote:
        assert remote.get("/citations").status_code == 403
        assert remote.get("/api/citations/status").status_code == 403
        assert remote.get("/").status_code == 200  # the party feed is not gated
        assert remote.get("/citations", headers={"X-Gate-Token": "gate-secret"}).status_code == 200
    with TestClient(create_app(gated), client=("127.0.0.1", 5000)) as loopback:
        assert loopback.get("/citations").status_code == 200
        # Tailscale Funnel proxies from loopback but reports the public client in X-Forwarded-For.
        assert loopback.get("/citations", headers={"X-Forwarded-For": "198.51.100.7"}).status_code == 403
        assert loopback.get("/citations", headers={"X-Forwarded-For": "198.51.100.7", "X-Gate-Token": "gate-secret"}).status_code == 200
    with TestClient(create_app(gated), client=("192.168.1.42", 5000)) as lan:
        assert lan.get("/citations").status_code == 200  # party guests on the LAN stay ungated


def test_settings_reject_secret_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CITATIONS_PUBLISHABLE_KEY", "sb_secret_nope")
    with pytest.raises(ValueError):
        Settings.from_env()
    monkeypatch.setenv("CITATIONS_PUBLISHABLE_KEY", "sb_publishable_ok")
    monkeypatch.setenv("CITATIONS_SUPABASE_URL", "http://insecure.example")
    with pytest.raises(ValueError):
        Settings.from_env()
