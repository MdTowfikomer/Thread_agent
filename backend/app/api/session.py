from fastapi import APIRouter, Depends, HTTPException, Response, status
from app.core.auth import AuthenticatedPrincipal, get_current_principal, create_access_token
from app.core.config import settings

router = APIRouter(prefix="/session", tags=["Session"])

@router.get("")
async def get_session(
    principal: AuthenticatedPrincipal = Depends(get_current_principal)
):
    """
    Protected session validation endpoint.
    Verifies Bearer token or HttpOnly cookie authentication and returns identity context.
    Raises HTTP 401 if token/session is unauthenticated, expired, or invalid.
    """
    return {
        "authenticated": True,
        "user_id": principal.user_id,
        "organization_id": principal.organization_id,
        "is_guest": principal.is_guest,
        "role_id": principal.access_context.role_id,
        "allowed_scopes": principal.access_context.allowed_scopes,
        "user_permission": principal.access_context.user_permission
    }

@router.post("/demo")
async def create_demo_session(response: Response):
    """Issue a fixed, public-only session for the enabled live demo."""
    if not settings.demo_workspace_enabled:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Demo workspace is unavailable.")

    user_id = "demo_judge"
    organization_id = "gdg_mcet"
    token = create_access_token(user_id=user_id, organization_id=organization_id, expires_in_seconds=3600)

    response.set_cookie(
        key="thread_session",
        value=token,
        httponly=True,
        samesite="lax",
        secure=not settings.is_development,
        max_age=3600
    )
    return {
        "authenticated": True,
        "user_id": user_id,
        "organization_id": organization_id,
        "message": "Demo session established successfully."
    }

@router.post("/logout")
async def logout_session(
    response: Response
):
    """
    Clears the HttpOnly 'thread_session' cookie.
    """
    response.delete_cookie(
        key="thread_session",
        httponly=True,
        samesite="lax",
        secure=not settings.is_development
    )
    return {
        "authenticated": False,
        "message": "Session terminated."
    }
