from __future__ import annotations

from io import BytesIO

from PIL import Image


FORM = {
    "browser_id": "9cd4bd86-f0db-4900-bd5e-63197d370286",
    "author": "Fern",
    "caption": "first light on the LAN",
}


def make_image(format_name: str = "JPEG", size: tuple[int, int] = (1600, 900)) -> bytes:
    output = BytesIO()
    Image.new("RGB", size, (42, 180, 137)).save(output, format=format_name)
    return output.getvalue()


def test_image_upload_creates_original_derivatives_and_metadata(client, settings) -> None:
    original = make_image()

    response = client.post(
        "/api/media",
        data=FORM,
        files={"file": ("camera.jpg", original, "image/jpeg")},
    )

    assert response.status_code == 201
    post = response.json()
    assert post["media_type"] == "image/jpeg"
    assert post["width"] == 1600
    assert post["height"] == 900
    assert post["thumbnail_url"].endswith("-feed.webp")
    original_path = settings.uploads_dir / post["original_url"].removeprefix("/media/uploads/")
    thumbnail_path = settings.thumbnails_dir / post["thumbnail_url"].removeprefix(
        "/media/thumbnails/"
    )
    assert original_path.read_bytes() == original
    assert thumbnail_path.stat().st_size < len(original)
    assert list(settings.thumbnails_dir.rglob("*-vision.jpg"))

    page = client.get("/api/media").json()
    assert page["items"][0] == post


def test_upload_rejects_mime_signature_mismatch(client) -> None:
    response = client.post(
        "/api/media",
        data=FORM,
        files={"file": ("lie.png", make_image(), "image/png")},
    )

    assert response.status_code == 415
    assert "do not match" in response.json()["detail"]


def test_upload_rejects_unsupported_and_empty_files(client) -> None:
    unsupported = client.post(
        "/api/media",
        data=FORM,
        files={"file": ("page.svg", b"<svg></svg>", "image/svg+xml")},
    )
    empty = client.post(
        "/api/media",
        data=FORM,
        files={"file": ("empty.jpg", b"", "image/jpeg")},
    )

    assert unsupported.status_code == 415
    assert empty.status_code == 400


def test_media_broadcast_reaches_connected_client(client) -> None:
    with client.websocket_connect("/ws") as websocket:
        websocket.receive_json()
        response = client.post(
            "/api/media",
            data=FORM,
            files={"file": ("camera.png", make_image("PNG", (320, 200)), "image/png")},
        )

        event = websocket.receive_json()
        assert response.status_code == 201
        assert event["type"] == "media_created"
        assert event["payload"]["id"] == response.json()["id"]
