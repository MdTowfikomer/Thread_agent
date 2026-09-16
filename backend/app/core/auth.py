import time
import jwt
from typing import Optional, Dict, Any
from fastapi import Request, Header, Cookie, HTTPException, status
from pydantic import BaseModel
from app.core.config import settings
from app.core.canonical import AccessContext, PermissionLevel
from app.core.membership import membership_store

class AuthenticatedPrincipal(BaseModel):
    user_id: str
    organization_id: str
    is_guest: bool = False
    access_context: AccessContext

ALLOWED_DEV_DEMO_USERS = {"demo_organizer", "demo_community"}

def create_access_token(
    user_id: str,
    organization_id: str = "gdg_mcet",
    expires_in_seconds: int = 86400,
    secret: Optional[str] = None
) -> str:
    """Generate a verified HMAC-SHA256 JWT bearer token."""
    signing_secret = secret or settings.jwt_secret
    if not signing_secret:
        raise ValueError("Cannot sign token: THREAD_JWT_SECRET is not configured.")
    now = int(time.time())
    payload = {
        "sub": user_id,
        "org": organization_id,
        "iat": now,
        "exp": now + expires_in_seconds
    }
    return jwt.encode(payload, signing_secret, algorithm=settings.JWT_ALGORITHM)

def verify_access_token(token: str) -> Dict[str, Any]:
    """Verify signature and expiration of bearer token."""
    secret = settings.jwt_secret
    if not secret:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication token cannot be verified: server secret not configured",
            headers={"WWW-Authenticate": "Bearer"}
        )
    try:
        payload = jwt.decode(
            token,
            secret,
            algorithms=[settings.JWT_ALGORITHM]
        )
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session token has expired",
            headers={"WWW-Authenticate": "Bearer"}
        )
    except jwt.InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication token",
            headers={"WWW-Authenticate": "Bearer"}
        )

def get_current_principal(
    request: Request,
    authorization: Optional[str] = Header(None),
    thread_session: Optional[str] = Cookie(None, alias="thread_session"),
    x_dev_demo_user: Optional[str] = Header(None, alias="X-Dev-Demo-User")
) -> AuthenticatedPrincipal:
    """
    Authoritative authentication dependency.
    In production, identity MUST derive from a verified Bearer token OR secure HttpOnly 'thread_session' cookie.
    Body user_id and X-User-Id are strictly ignored.
    X-Dev-Demo-User is strictly restricted to explicit demo identities.
    """
    # 0. Restrict X-Dev-Demo-User to explicit demo identities only
    if x_dev_demo_user is not None:
        if x_dev_demo_user not in ALLOWED_DEV_DEMO_USERS:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Forbidden: X-Dev-Demo-User '{x_dev_demo_user}' is not an authorized demo identity. Allowed: {sorted(ALLOWED_DEV_DEMO_USERS)}"
            )

    # 1. Resolve Token from Bearer Header or Secure HttpOnly Cookie
    token = None
    if authorization:
        parts = authorization.split()
        if len(parts) == 2 and parts[0].lower() == "bearer":
            token = parts[1]
        else:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid authorization header format. Expected 'Bearer <token>'",
                headers={"WWW-Authenticate": "Bearer"}
            )
    else:
        token = thread_session or request.cookies.get("thread_session")

    if token:
        payload = verify_access_token(token)
        user_id = payload.get("sub")
        org_id = payload.get("org", "gdg_mcet")

        if not user_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Malformed token payload: missing sub claim",
                headers={"WWW-Authenticate": "Bearer"}
            )

        # Derive permissions strictly from MembershipStore using verified token subject
        ctx = membership_store.derive_access_context(user_id=user_id, organization_id=org_id)
        return AuthenticatedPrincipal(
            user_id=user_id,
            organization_id=org_id,
            is_guest=False,
            access_context=ctx
        )

    # 2. Isolated Development-Only Demo Identity:
    # Requires BOTH APP_ENV=development AND THREAD_DEMO_AUTH_ENABLED=true
    if settings.is_development and settings.demo_auth_enabled:
        demo_user = x_dev_demo_user or "demo_organizer"
        org_id = "gdg_mcet"
        ctx = membership_store.derive_access_context(user_id=demo_user, organization_id=org_id)
        return AuthenticatedPrincipal(
            user_id=demo_user,
            organization_id=org_id,
            is_guest=False,
            access_context=ctx
        )

    # 3. Explicit Public Guest Mode (if enabled)
    if settings.allow_guest_mode:
        org_id = "gdg_mcet"
        guest_ctx = AccessContext(
            user_id="guest",
            organization_id=org_id,
            role_id="guest",
            user_permission=PermissionLevel.PUBLIC_COMMUNITY,
            allowed_scopes=[PermissionLevel.PUBLIC_COMMUNITY]
        )
        return AuthenticatedPrincipal(
            user_id="guest",
            organization_id=org_id,
            is_guest=True,
            access_context=guest_ctx
        )

    # 4. Default: Reject unauthenticated request with HTTP 401
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authentication credentials were not provided",
        headers={"WWW-Authenticate": "Bearer"}
    )
