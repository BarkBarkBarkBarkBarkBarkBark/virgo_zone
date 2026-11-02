from __future__ import annotations

import hmac

from fastapi import APIRouter, HTTPException, Request, Response, status

from app.admin import COOKIE_NAME, make_admin_token, verify_admin_token
from app.models import AdminLogin


router = APIRouter(prefix="/admin")


@router.get("/session")
async def admin_session(request: Request) -> dict[str, bool]:
    settings = request.app.state.settings
    return {
        "configured": settings.admin_password is not None,
        "authenticated": bool(request.app.state.gateway_token and request.headers.get("x-hosaka-role") == "organizer") or verify_admin_token(
            request.cookies.get(COOKIE_NAME),
            settings.admin_password,
        ),
    }


@router.post("/login", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
async def admin_login(body: AdminLogin, request: Request, response: Response) -> Response:
    settings = request.app.state.settings
    client_host = request.client.host if request.client else "unknown"
    await request.app.state.rate_limiter.enforce(f"admin-login:{client_host}", 5, 300)
    if settings.admin_password is None or not hmac.compare_digest(
        body.password,
        settings.admin_password,
    ):
        raise HTTPException(status_code=401, detail="Incorrect admin password")
    response.set_cookie(
        COOKIE_NAME,
        make_admin_token(settings.admin_password, settings.admin_session_seconds),
        max_age=settings.admin_session_seconds,
        httponly=True,
        samesite="strict",
        secure=False,
        path="/",
    )
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
async def admin_logout(response: Response) -> Response:
    response.delete_cookie(COOKIE_NAME, path="/")
    response.status_code = status.HTTP_204_NO_CONTENT
    return response
