from __future__ import annotations

from tests.test_media_upload import FORM, make_image


def create_media(client) -> dict:
    response = client.post(
        "/api/media",
        data=FORM,
        files={"file": ("commentable.jpg", make_image(size=(300, 200)), "image/jpeg")},
    )
    assert response.status_code == 201
    return response.json()


def test_comment_creation_and_history(client) -> None:
    media = create_media(client)
    body = {
        "browser_id": "42cd56b5-8bd9-4510-b48e-a5f69955d473",
        "author": "  Rain  Cloud ",
        "text": "  this is extremely enchanted  ",
    }

    response = client.post(f"/api/media/{media['id']}/comments", json=body)

    assert response.status_code == 201
    comment = response.json()
    assert comment["author_name"] == "Rain Cloud"
    assert comment["text"] == "this is extremely enchanted"
    assert comment["is_ai"] is False
    history = client.get(f"/api/media/{media['id']}/comments").json()
    assert history["items"] == [comment]


def test_comment_rejects_missing_media_and_blank_text(client) -> None:
    missing = client.post(
        "/api/media/unknown/comments",
        json={"browser_id": "browser-123", "author": "Fern", "text": "hello"},
    )
    media = create_media(client)
    blank = client.post(
        f"/api/media/{media['id']}/comments",
        json={"browser_id": "browser-123", "author": "Fern", "text": "   "},
    )

    assert missing.status_code == 404
    assert blank.status_code == 422


def test_comment_broadcast_reaches_two_clients(client) -> None:
    media = create_media(client)
    body = {"browser_id": "browser-456", "author": "Iris", "text": "wizard behavior ✨"}
    with client.websocket_connect("/ws") as first:
        with client.websocket_connect("/ws") as second:
            first.receive_json()
            second.receive_json()
            response = client.post(f"/api/media/{media['id']}/comments", json=body)
            first_event = first.receive_json()
            second_event = second.receive_json()

    assert response.status_code == 201
    assert first_event == second_event
    assert first_event["type"] == "media_comment_created"
    assert first_event["payload"]["media_id"] == media["id"]
