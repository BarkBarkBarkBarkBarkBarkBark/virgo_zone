from __future__ import annotations

from io import BytesIO

import pytest

from app.media import MediaService, MediaValidationError
from app.rate_limit import RateLimiter


@pytest.mark.anyio
async def test_rate_limiter_rejects_excess_requests() -> None:
    limiter = RateLimiter()
    await limiter.enforce("chat:browser", 2, 60)
    await limiter.enforce("chat:browser", 2, 60)

    with pytest.raises(Exception) as captured:
        await limiter.enforce("chat:browser", 2, 60)

    assert captured.value.status_code == 429


def test_streaming_upload_limit_removes_partial_file(settings) -> None:
    small_settings = settings.__class__(
        **{**settings.__dict__, "image_max_bytes": 64}
    )
    small_settings.ensure_directories()
    service = MediaService(small_settings)

    with pytest.raises(MediaValidationError) as captured:
        service.store(BytesIO(b"\xff\xd8\xff" + b"x" * 100), "image/jpeg")

    assert captured.value.status_code == 413
    assert list((small_settings.uploads_dir / ".incoming").glob("*.part")) == []
