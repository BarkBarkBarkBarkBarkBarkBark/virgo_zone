from __future__ import annotations

from app.ollama_client import FairyUnavailableError
from tests.test_media_upload import FORM, make_image


def test_fairy_unavailable_does_not_break_media(client) -> None:
    uploaded = client.post(
        "/api/media",
        data=FORM,
        files={"file": ("sleeping.jpg", make_image(size=(320, 240)), "image/jpeg")},
    ).json()

    response = client.post(f"/api/media/{uploaded['id']}/fairy")

    assert response.status_code == 503
    assert response.json()["detail"] == "fairy is sleeping"
    assert client.get("/api/media").status_code == 200


def test_fairy_comment_is_persisted_and_broadcast(client, monkeypatch) -> None:
    uploaded = client.post(
        "/api/media",
        data=FORM,
        files={"file": ("fairy.jpg", make_image(size=(320, 240)), "image/jpeg")},
    ).json()

    async def fake_photo(caption, media_type, image_path):
        assert caption == FORM["caption"]
        assert image_path.exists()
        return "the council says this goes hard"

    monkeypatch.setattr(client.app.state.ollama, "fairy_photo", fake_photo)
    with client.websocket_connect("/ws") as websocket:
        websocket.receive_json()
        response = client.post(f"/api/media/{uploaded['id']}/fairy")
        typing = websocket.receive_json()
        created = websocket.receive_json()
        finished = websocket.receive_json()

    assert response.status_code == 200
    assert response.json()["is_ai"] is True
    assert [typing["type"], created["type"], finished["type"]] == [
        "fairy_typing",
        "media_comment_created",
        "fairy_finished",
    ]
    history = client.get(f"/api/media/{uploaded['id']}/comments").json()
    assert history["items"][0]["text"] == "the council says this goes hard"


def test_fairy_chat_failure_returns_sleeping(client, monkeypatch) -> None:
    async def unavailable(prompt, context):
        raise FairyUnavailableError("offline")

    monkeypatch.setattr(client.app.state.ollama, "fairy_chat", unavailable)
    response = client.post("/api/fairy/chat", json={"prompt": "say something"})

    assert response.status_code == 503
    assert response.json()["detail"] == "fairy is sleeping"
