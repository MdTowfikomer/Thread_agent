import logging
from typing import Optional, List, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from app.core.config import settings
from app.core.canonical import ChannelType, PermissionLevel, LinkVerificationType
from app.core.auth import AuthenticatedPrincipal, get_current_principal
from app.core.membership import membership_store
from app.identity.service import identity_service, AccountAlreadyLinkedError, IdentityPersistenceError
from app.identity.oauth import (
    oauth_state_manager,
    github_oauth_client,
    OAuthStateError,
    OAuthStatePersistenceError,
    GitHubOAuthError
)

logger = logging.getLogger("thread.api.identity")

router = APIRouter(tags=["identity"])

def require_authenticated_member(
    principal: AuthenticatedPrincipal = Depends(get_current_principal)
) -> AuthenticatedPrincipal:
    """Ensures the caller is an active, authenticated member of the organization (not a guest)."""
    if principal.is_guest:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required: guest users cannot perform identity operations."
        )
    ident_ctx = membership_store.get_identity_context(
        user_id=principal.user_id,
        organization_id=principal.organization_id
    )
    if not ident_ctx.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Forbidden: Member '{principal.user_id}' is not an active member of organization '{principal.organization_id}'."
        )
    return principal

def require_organizer(
    principal: AuthenticatedPrincipal = Depends(require_authenticated_member)
) -> AuthenticatedPrincipal:
    """Ensures the caller holds an organizer/internal core role in the organization."""
    has_internal = (
        PermissionLevel.INTERNAL_CORE in principal.access_context.allowed_scopes
        or principal.access_context.user_permission == PermissionLevel.INTERNAL_CORE
    )
    is_organizer_role = (
        principal.access_context.role_id in ("organizer_lead", "lead_organizer", "tech_lead", "organizer", "admin")
        or has_internal
    )
    if not is_organizer_role:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden: Organizer role is required to perform or review this identity operation."
        )
    return principal

# =========================================================================
# Request / Response Schemas
# =========================================================================

class RevokeLinkRequest(BaseModel):
    account_id: Optional[str] = Field(None, description="GitHub account ID to revoke. Defaults to caller's linked account.")
    reason: Optional[str] = Field(None, description="Reason for revoking the account link.")

class ManualLinkSubmission(BaseModel):
    account_id: str = Field(..., description="Immutable numeric GitHub user ID (e.g. '583231').")
    username: Optional[str] = Field(None, description="GitHub handle/login.")
    reason: str = Field(..., description="Justification for exceptional manual account link.")
    evidence_notes: Optional[str] = Field(None, description="Additional verification evidence notes.")

class ManualLinkReviewSubmission(BaseModel):
    action: str = Field(..., description="Review decision: 'approve' or 'reject'.")
    review_notes: Optional[str] = Field(None, description="Organizer review comments or rationale.")


# =========================================================================
# GitHub OAuth Account Linking Flow
# =========================================================================

@router.get("/identity/github/connect")
def initiate_github_connect(
    principal: AuthenticatedPrincipal = Depends(require_authenticated_member)
):
    """
    Initiates the production GitHub account linking flow.
    Generates a cryptographically signed state token embedding the caller's verified person_id
    and organization boundary, and returns the GitHub OAuth authorization URL.
    """
    state_token = oauth_state_manager.generate_state_token(
        person_id=principal.user_id,
        organization_id=principal.organization_id
    )

    auth_url = github_oauth_client.get_authorization_url(
        state=state_token
    )

    return {
        "status": "ready",
        "authorization_url": auth_url,
        "state": state_token,
        "organization_id": principal.organization_id,
        "person_id": principal.user_id,
        "expires_in_seconds": 600
    }

@router.get("/identity/github/callback")
@router.get("/auth/github/callback")
def handle_github_oauth_callback(
    code: str = Query(..., description="GitHub temporary OAuth authorization code."),
    state: str = Query(..., description="Cryptographic state token returned from GitHub.")
):
    """
    Handles the GitHub OAuth callback.
    
    SECURITY CONTRACT:
    1. NEVER accepts a GitHub user ID or target internal person ID from the request body or query.
    2. Validates and atomically consumes the single-use state token to extract person_id and organization_id.
    3. Server-to-server exchanges code with GitHub for an access token.
    4. Retrieves GitHub profile authoritatively from GitHub API, extracting the IMMUTABLE NUMERIC USER ID.
    5. Rejects any attempt to steal or map an account already actively bound to another person.
    6. Persists link, evidence, and audit event durably in Supabase PostgreSQL.
    """
    # 1. Authoritatively validate and consume state token
    person_id, organization_id = oauth_state_manager.validate_and_consume_state_token(state)

    # 2. Server-side code exchange
    access_token = github_oauth_client.exchange_code_for_token(code)

    # 3. Server-side profile retrieval (Authoritative immutable numeric ID)
    user_profile = github_oauth_client.fetch_user_profile(access_token)
    account_id = user_profile["account_id"]
    username = user_profile.get("username")
    display_name = user_profile.get("display_name")
    email = user_profile.get("email")

    # 4. Check whether account is already actively linked to another person
    # Note: identity_service.link_account also authoritatively verifies this
    # in an atomic database transaction with SELECT ... FOR UPDATE row-locking across workers.
    account_key = identity_service._account_key(organization_id, ChannelType.GITHUB, account_id)
    existing = identity_service._account_links.get(account_key)
    if existing and existing.is_active and existing.person_id != person_id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Conflict: GitHub numeric user ID '{account_id}' is already actively linked to person '{existing.person_id}'."
        )

    # 5. Persist the verified account link in Supabase
    from datetime import datetime, timezone
    verified_at = datetime.now(timezone.utc).isoformat()

    try:
        link = identity_service.link_account(
            organization_id=organization_id,
            person_id=person_id,
            channel_type=ChannelType.GITHUB,
            account_id=account_id,
            username=username,
            display_name=display_name,
            email=email,
            link_type=LinkVerificationType.OAUTH_VERIFIED,
            confidence=1.0,
            evidence={
                "oauth_provider": "github",
                "github_numeric_id": account_id,
                "github_login": username,
                "verified_at": verified_at
            }
        )
    except AccountAlreadyLinkedError as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(e)
        )
    except IdentityPersistenceError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Durable identity persistence failure: {e}"
        )

    # 6. Record immutable audit event
    identity_service.record_audit_event(
        organization_id=organization_id,
        person_id=person_id,
        channel_type=ChannelType.GITHUB,
        account_id=account_id,
        event_type="oauth_linked",
        actor_person_id=person_id,
        evidence={
            "oauth_provider": "github",
            "github_numeric_id": account_id,
            "github_login": username,
            "link_id": link.id
        }
    )

    return {
        "status": "linked",
        "organization_id": organization_id,
        "person_id": person_id,
        "channel_type": "github",
        "account_id": account_id,
        "username": username,
        "display_name": display_name,
        "email": email,
        "link_type": link.link_type.value,
        "is_verified": link.is_verified,
        "linked_at": link.linked_at
    }


# =========================================================================
# Revocation & Listing Endpoints
# =========================================================================

@router.post("/identity/github/revoke")
def revoke_github_link(
    body: Optional[RevokeLinkRequest] = None,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_member)
):
    """
    Revokes an active GitHub account link.
    Members may revoke their own link. Organizers may revoke any member's link.
    """
    org_id = principal.organization_id
    target_account_id = body.account_id if body else None
    reason = body.reason if body else None

    # If account_id not provided, find the caller's active GitHub link
    if not target_account_id:
        caller_links = identity_service.get_person_accounts(org_id, principal.user_id)
        gh_link = next((l for l in caller_links if l.channel_type == ChannelType.GITHUB and l.is_active), None)
        if not gh_link:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No active GitHub account link found for the current member."
            )
        target_account_id = gh_link.account_id

    # Check permission if revoking another member's account
    key = identity_service._account_key(org_id, ChannelType.GITHUB, target_account_id)
    existing = identity_service._account_links.get(key)
    if existing and existing.person_id != principal.user_id:
        # Requires organizer privilege
        has_internal = (
            PermissionLevel.INTERNAL_CORE in principal.access_context.allowed_scopes
            or principal.access_context.user_permission == PermissionLevel.INTERNAL_CORE
        )
        if not has_internal:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Forbidden: Only organizers may revoke account links belonging to another member."
            )

    identity_service.revoke_account_link(
        organization_id=org_id,
        channel_type=ChannelType.GITHUB,
        account_id=target_account_id,
        actor_person_id=principal.user_id,
        reason=reason or "User or administrator requested revocation."
    )

    return {
        "status": "revoked",
        "organization_id": org_id,
        "channel_type": "github",
        "account_id": target_account_id,
        "revoked_by": principal.user_id
    }

@router.get("/identity/links")
def list_identity_links(
    person_id: Optional[str] = Query(None, description="Optional person ID filter (organizers only)."),
    principal: AuthenticatedPrincipal = Depends(require_authenticated_member)
):
    """Lists linked accounts for the current member or specified member (organizer only)."""
    target_person_id = principal.user_id
    if person_id and person_id != principal.user_id:
        require_organizer(principal)
        target_person_id = person_id

    links = identity_service.get_person_accounts(principal.organization_id, target_person_id)
    return {
        "organization_id": principal.organization_id,
        "person_id": target_person_id,
        "links": [l.model_dump() for l in links if l.is_active]
    }


# =========================================================================
# Organizer-Reviewed Manual Link Fallback Flow
# =========================================================================

@router.post("/identity/manual-link/request")
def request_manual_link(
    body: ManualLinkSubmission,
    principal: AuthenticatedPrincipal = Depends(require_authenticated_member)
):
    """
    Submits an organizer-reviewed manual account linking request for exceptional cases.
    The internal person_id is derived exclusively from the authenticated session.
    """
    try:
        req = identity_service.create_manual_link_request(
            organization_id=principal.organization_id,
            person_id=principal.user_id,
            channel_type=ChannelType.GITHUB,
            account_id=body.account_id,
            reason=body.reason,
            username=body.username,
            evidence_notes=body.evidence_notes
        )
        return req.model_dump()
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

@router.get("/identity/manual-link/requests")
def list_manual_link_requests(
    status_filter: Optional[str] = Query("pending", description="Status filter: pending, approved, rejected, or all"),
    principal: AuthenticatedPrincipal = Depends(require_organizer)
):
    """Lists manual link requests for the organization (organizer only)."""
    s = None if status_filter == "all" else status_filter
    requests = identity_service.get_manual_link_requests(principal.organization_id, status=s)
    return {
        "organization_id": principal.organization_id,
        "count": len(requests),
        "requests": [r.model_dump() for r in requests]
    }

@router.post("/identity/manual-link/{request_id}/review")
def review_manual_link_request(
    request_id: str,
    body: ManualLinkReviewSubmission,
    principal: AuthenticatedPrincipal = Depends(require_organizer)
):
    """
    Reviews a pending manual link request (organizers only).
    Approves and creates a verified manual link, or rejects the request.
    """
    try:
        updated_req = identity_service.review_manual_link_request(
            request_id=request_id,
            reviewer_person_id=principal.user_id,
            action=body.action,
            review_notes=body.review_notes
        )
        return updated_req.model_dump()
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


# =========================================================================
# Audit Log Endpoint (Organizer Only)
# =========================================================================

@router.get("/identity/audit-log")
def list_identity_audit_log(
    person_id: Optional[str] = Query(None, description="Optional person ID filter."),
    limit: int = Query(50, ge=1, le=200, description="Max entries to return."),
    principal: AuthenticatedPrincipal = Depends(require_organizer)
):
    """Returns immutable identity audit logs for the organization (organizers only)."""
    events = identity_service.get_audit_events(
        organization_id=principal.organization_id,
        person_id=person_id,
        limit=limit
    )
    return {
        "organization_id": principal.organization_id,
        "count": len(events),
        "audit_events": [e.model_dump() for e in events]
    }
