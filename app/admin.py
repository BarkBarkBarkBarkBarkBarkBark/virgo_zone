from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from typing import Any

from fastapi import HTTPException, Request, status


COOKIE_NAME = "virgozone_admin"


def make_admin_token(password: str, lifetime_seconds: int) -> str:
    payload = {"exp": int(time.time()) + lifetime_seconds, "role": "admin"}
    encoded = base64.urlsafe_b64encode(
        json.dumps(payload, separators=(",", ":")).encode("utf-8")
    ).rstrip(b"=")
    signature = hmac.new(password.encode("utf-8"), encoded, hashlib.sha256).digest()
    signed = encoded + b"." + base64.urlsafe_b64encode(signature).rstrip(b"=")
    return signed.decode("ascii")


def verify_admin_token(token: str | None, password: str | None) -> bool:
    if not token or not password:
        return False
    try:
        encoded, supplied = token.encode("ascii").split(b".", 1)
        expected = base64.urlsafe_b64encode(
            hmac.new(password.encode("utf-8"), encoded, hashlib.sha256).digest()
        ).rstrip(b"=")
        if not hmac.compare_digest(supplied, expected):
            return False
        padding = b"=" * (-len(encoded) % 4)
        payload: dict[str, Any] = json.loads(base64.urlsafe_b64decode(encoded + padding))
        return payload.get("role") == "admin" and int(payload.get("exp", 0)) > int(time.time())
    except (ValueError, TypeError, KeyError, json.JSONDecodeError):
        return False


def require_admin(request: Request) -> None:
    settings = request.app.state.settings
    if settings.admin_password is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Admin mode is not configured",
        )
    if not verify_admin_token(request.cookies.get(COOKIE_NAME), settings.admin_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Admin authorization required",
        )
