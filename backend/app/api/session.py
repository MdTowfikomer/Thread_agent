from fastapi import APIRouter, Depends
from app.core.auth import AuthenticatedPrincipal, get_current_principal

router = APIRouter(prefix="/session", tags=["Session"])

@router.get("")
async def get_session(
    principal: AuthenticatedPrincipal = Depends(get_current_principal)
):
    """
    Protected session validation endpoint.
    Verifies Bearer authentication and returns identity context.
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
