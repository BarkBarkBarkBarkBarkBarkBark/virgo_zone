from __future__ import annotations

from tests.test_media_upload import FORM, make_image


EVENT = {
    "title": "River council",
    "description": "Bring improbable hats",
    "starts_at": "2030-07-12T18:30:00-07:00",
    "ends_at": "2030-07-12T19:30:00-07:00",
    "location": "Main camp",
}


def login(client) -> None:
    response = client.post("/api/admin/login", json={"password": "neuro"})
    assert response.status_code == 204


def test_schedule_requires_admin_and_supports_crud(client) -> None:
    assert client.get("/api/admin/session").json() == {
        "configured": True,
        "authenticated": False,
    }
    assert client.post("/api/schedule", json=EVENT).status_code == 401
    assert client.post("/api/admin/login", json={"password": "wrong"}).status_code == 401
    login(client)
    assert client.get("/api/admin/session").json()["authenticated"] is True

    created_response = client.post("/api/schedule", json=EVENT)
    assert created_response.status_code == 201
    created = created_response.json()
    assert created["starts_at"] == "2030-07-13T01:30:00Z"
    assert client.get("/api/schedule").json()[0]["id"] == created["id"]

    updated_response = client.patch(
        f"/api/schedule/{created['id']}",
        json={**EVENT, "title": "Moonlit river council"},
    )
    assert updated_response.status_code == 200
    assert updated_response.json()["title"] == "Moonlit river council"
    assert client.delete(f"/api/schedule/{created['id']}").status_code == 204
    assert client.get("/api/schedule").json() == []


def test_schedule_validation_rejects_bad_range(client) -> None:
    login(client)
    response = client.post(
        "/api/schedule",
        json={**EVENT, "ends_at": "2030-07-12T17:30:00-07:00"},
    )

    assert response.status_code == 422


def test_schedule_broadcasts_to_read_only_client(client) -> None:
    login(client)
    with client.websocket_connect("/ws") as websocket:
        websocket.receive_json()
        created = client.post("/api/schedule", json=EVENT)
        event = websocket.receive_json()

    assert created.status_code == 201
    assert event["type"] == "schedule_created"
    assert event["payload"]["id"] == created.json()["id"]


def test_media_delete_requires_admin_and_removes_files(client, settings) -> None:
    uploaded = client.post(
        "/api/media",
        data=FORM,
        files={"file": ("delete.jpg", make_image(size=(400, 300)), "image/jpeg")},
    ).json()
    original = settings.uploads_dir / uploaded["original_url"].removeprefix("/media/uploads/")
    assert original.exists()
    assert client.delete(f"/api/media/{uploaded['id']}").status_code == 401

    login(client)
    response = client.delete(f"/api/media/{uploaded['id']}")

    assert response.status_code == 204
    assert not original.exists()
