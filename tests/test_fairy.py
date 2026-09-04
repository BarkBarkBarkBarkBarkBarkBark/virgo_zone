from __future__ import annotations

from app.fairy import split_hosaka_messages
from app.identity import build_hosaka_prompt
from app.ollama_client import (
    FairyUnavailableError,
    clean_hosaka_response,
    is_echo_response,
    is_generic_assistant_response,
)
from app.social_awareness import SocialAwareness
from tests.test_media_upload import FORM, make_image


def test_fairy_unavailable_does_not_break_media(client) -> None:
    uploaded = client.post(
        "/api/media",
        data=FORM,
        files={"file": ("sleeping.jpg", make_image(size=(320, 240)), "image/jpeg")},
    ).json()

    response = client.post(f"/api/media/{uploaded['id']}/fairy")

    assert response.status_code == 503
    assert response.json()["detail"] == "Hosaka is offline"
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
    assert response.json()["detail"] == "Hosaka is offline"


def test_hosaka_identity_prompt_uses_canonical_files(settings) -> None:
    prompt = build_hosaka_prompt(settings.hosaka_identity_dir)

    identity = prompt.split("\n\n", 1)[0]
    assert identity.startswith("You are Hosaka,")
    assert identity.count(".") == 2
    assert "Cascade" in identity
    assert "accuracy, safety, simplicity" in identity
    assert len(prompt) < 1_000
    assert "several sentences" in prompt
    assert "one message or several" in prompt
    assert "usually in one sentence" not in prompt
    assert "absolutely wizard behavior" not in prompt


def test_hosaka_response_removes_transcript_prefixes() -> None:
    assert clean_hosaka_response(
        "LAN FAIRY: MARCO AT WORK: what do you mean where would it fit."
    ) == "what do you mean where would it fit."


def test_hosaka_echo_detection_suppresses_paraphrase() -> None:
    assert is_echo_response("Does anyone know a joke?", "does anybody know a joke")
    assert not is_echo_response(
        "Why did the chair seek therapy? It had too many unresolved issues.",
        "does anybody know a joke",
    )
    assert is_generic_assistant_response(
        "I'm sorry, but I can't assist. Feel free to ask something else."
    )
    assert not is_generic_assistant_response("A folding chair summit. Civilization persists.")


def test_hosaka_can_split_one_generation_into_multiple_messages() -> None:
    messages = split_hosaka_messages(
        "First transmission.\n\nSecond transmission, same signal.",
        "say more",
    )

    assert messages == ["First transmission.", "Second transmission, same signal."]


def test_hosaka_long_paragraph_is_chunked_without_losing_text() -> None:
    paragraph = " ".join(["signal"] * 400)

    messages = split_hosaka_messages(paragraph, "continue")

    assert len(messages) > 1
    assert " ".join(messages) == paragraph


def test_one_hosaka_generation_broadcasts_multiple_messages(client, monkeypatch) -> None:
    async def multiple_messages(prompt, context):
        return "First thought.\n\nSecond thought."

    monkeypatch.setattr(client.app.state.ollama, "fairy_chat", multiple_messages)
    with client.websocket_connect("/ws") as websocket:
        websocket.receive_json()
        response = client.post(
            "/api/chat",
            json={
                "browser_id": "multiple-message-user",
                "author": "Multi",
                "text": "say whatever comes to mind",
                "reply_to": None,
            },
        )
        source = response.json()
        events = [websocket.receive_json() for _ in range(5)]

    assert [event["type"] for event in events] == [
        "chat_created",
        "fairy_typing",
        "chat_created",
        "chat_created",
        "fairy_finished",
    ]
    replies = [event["payload"] for event in events if event["type"] == "chat_created"][1:]
    assert [reply["text"] for reply in replies] == ["First thought.", "Second thought."]
    assert all(reply["reply_to"] == source["id"] for reply in replies)


def test_social_gate_responds_to_immediate_followup() -> None:
    messages = [
        {"author_name": "marco_at_work", "text": "does anybody know a joke", "created_at": "2026-09-03T22:55:29+00:00", "is_ai": False},
        {"author_name": "LAN FAIRY", "text": "bad leaked response", "created_at": "2026-09-03T22:55:56+00:00", "is_ai": True},
        {"author_name": "marco_at_work", "text": "what do you mean where would it fit", "created_at": "2026-09-03T22:56:37+00:00", "is_ai": False},
    ]

    decision = SocialAwareness().decide(messages)

    assert decision.speak is True
    assert decision.reason == "always_respond"


def test_social_gate_allows_worthwhile_question_after_human_turns() -> None:
    messages = [
        {"author_id": "a", "text": "we found chairs", "created_at": "2026-09-03T20:00:00+00:00", "is_ai": False},
        {"author_id": "b", "text": "seven of them", "created_at": "2026-09-03T20:01:00+00:00", "is_ai": False},
        {"author_id": "a", "text": "put them by the fire", "created_at": "2026-09-03T20:02:00+00:00", "is_ai": False},
        {"author_id": "b", "text": "does anybody know a joke", "created_at": "2026-09-03T20:03:00+00:00", "is_ai": False},
    ]

    decision = SocialAwareness().decide(messages)

    assert decision.speak is True
    assert decision.reason == "always_respond"


def test_social_chat_calls_model_for_every_human_message(client, monkeypatch) -> None:
    calls: list[str] = []
    contexts: list[list[str]] = []

    async def fake_chat(prompt, context):
        calls.append(prompt)
        contexts.append([message["content"] for message in context])
        return "A folding chair summit. Civilization persists."

    monkeypatch.setattr(client.app.state.ollama, "fairy_chat", fake_chat)
    messages = [
        ("speaker-a", "we found chairs"),
        ("speaker-b", "seven of them"),
        ("speaker-a", "put them by the fire"),
        ("speaker-b", "does anybody know a joke"),
    ]
    for index, (speaker, text) in enumerate(messages):
        response = client.post(
            "/api/chat",
            json={
                "browser_id": f"browser-{speaker}",
                "author": speaker,
                "text": text,
                "reply_to": None,
            },
        )
        assert response.status_code == 201

    assert calls == [text for _, text in messages]
    assert contexts == [
        [],
        ["we found chairs"],
        ["we found chairs", "seven of them"],
        ["we found chairs", "seven of them", "put them by the fire"],
    ]
    history = client.get("/api/chat").json()["items"]
    assert history[0]["author_name"] == "HOSAKA"
    assert sum(message["is_ai"] for message in history) == 4
    for message in history:
        if message["is_ai"]:
            assert message["reply_to"] is not None

    followup = client.post(
        "/api/chat",
        json={
            "browser_id": "browser-speaker-b",
            "author": "speaker-b",
            "text": "what do you mean",
            "reply_to": None,
        },
    )
    assert followup.status_code == 201
    assert calls == [text for _, text in messages] + ["what do you mean"]


def test_social_gate_does_not_respond_to_ai_rows() -> None:
    decision = SocialAwareness().decide(
        [{"author_name": "HOSAKA", "text": "hello", "is_ai": True}]
    )

    assert decision.speak is False
    assert decision.reason == "no_human_turn"
