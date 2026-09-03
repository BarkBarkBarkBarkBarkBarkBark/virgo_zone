from __future__ import annotations


MESSAGE = {
    "browser_id": "ba3f5a68-0dde-43d0-a575-3e6150ad5a80",
    "author": "  Moss   Wizard  ",
    "text": "  hello   local world  ",
    "reply_to": None,
}


def test_chat_creation_persists_normalized_message(client) -> None:
    response = client.post("/api/chat", json=MESSAGE)

    assert response.status_code == 201
    created = response.json()
    assert created["author_name"] == "Moss Wizard"
    assert created["text"] == "hello local world"
    assert created["is_ai"] is False

    page = client.get("/api/chat").json()
    assert page["items"][0] == created


def test_chat_rejects_missing_reply_target(client) -> None:
    response = client.post("/api/chat", json={**MESSAGE, "reply_to": "missing"})

    assert response.status_code == 400
    assert response.json()["detail"] == "Invalid reply target"


def test_chat_broadcast_reaches_two_websocket_clients(client) -> None:
    with client.websocket_connect("/ws") as first:
        with client.websocket_connect("/ws") as second:
            assert first.receive_json()["type"] == "hello"
            assert second.receive_json()["type"] == "hello"

            response = client.post("/api/chat", json=MESSAGE)

            assert response.status_code == 201
            first_event = first.receive_json()
            second_event = second.receive_json()
            assert first_event == second_event
            assert first_event["type"] == "chat_created"
            assert first_event["payload"]["text"] == "hello local world"


def test_invalid_browser_identity_is_rejected(client) -> None:
    response = client.post("/api/chat", json={**MESSAGE, "browser_id": "../../bad"})

    assert response.status_code == 422
