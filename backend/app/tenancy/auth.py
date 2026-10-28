"""Revocable opaque sessions and per-request membership validation."""
from dataclasses import dataclass
from fastapi import Depends, HTTPException, Request, Response
from app.core.config import settings
from app.tenancy.repository import tenant_repository

COOKIE = "thread_v2_session"


def check_origin(request: Request):
    if request.method in ("GET", "HEAD", "OPTIONS"):
        return
    origin = request.headers.get("origin")
    if request.headers.get("sec-fetch-site") == "cross-site":
        raise HTTPException(403, "Cross-site requests are not permitted.")
    if origin and origin not in settings.allowed_origins and origin != str(request.base_url).rstrip("/"):
        raise HTTPException(403, "Request origin is not permitted.")


def set_session_cookie(response: Response, token: str):
    response.set_cookie(COOKIE, token, httponly=True, secure=not settings.is_development,
                        samesite="lax", max_age=86400, path="/")
    response.headers["Cache-Control"] = "no-store"
    response.delete_cookie("thread_session", path="/")


def get_current_user(request: Request):
    check_origin(request)
    return tenant_repository.session(request.cookies.get(COOKIE))


@dataclass(frozen=True)
class TenantContext:
    organization_id: str
    user_id: str
    role: str


def get_current_membership(org_id: str, user=Depends(get_current_user)):
    membership = tenant_repository.membership(org_id, user["user_id"])
    return TenantContext(org_id, user["user_id"], membership["role"])
