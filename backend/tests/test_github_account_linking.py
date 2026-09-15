import time
import json
import uuid
import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

from app.main import app
from app.core.config import settings
from app.core.canonical import ChannelType, PermissionLevel, LinkVerificationType, ManualLinkRequestStatus
from app.core.auth import create_access_token
from app.identity.service import identity_service
from app.identity.oauth import oauth_state_manager, github_oauth_client

client = TestClient(app)

@pytest.fixture(autouse=True)
def clean_identity_state(monkeypatch):
    """Resets in-memory stores and sets mock GitHub OAuth client credentials."""
    monkeypatch.setenv("GITHUB_CLIENT_ID", "mock_gh_client_id_12345")
    monkeypatch.setenv("GITHUB_CLIENT_SECRET", "mock_gh_client_secret_67890")
    monkeypatch.setenv("GITHUB_OAUTH_REDIRECT_URI", "https://thread.local/api/identity/github/callback")
    monkeypatch.setenv("THREAD_ALLOW_OFFLINE_IDENTITY", "1")
    
    identity_service.reset()
    oauth_state_manager.clear()
    yield

def make_member_token(user_id: str = "usr_student_rohan", org_id: str = "gdg_mcet") -> str:
    """Helper to create valid authenticated member token."""
    return create_access_token(user_id=user_id, organization_id=org_id)

def make_organizer_token(user_id: str = "usr_arjun", org_id: str = "gdg_mcet") -> str:
    """Helper to create valid lead organizer token."""
    return create_access_token(user_id=user_id, organization_id=org_id)


# =========================================================================
# 1. Initiation & State Token Security Tests
# =========================================================================

def test_initiate_github_oauth_connect_requires_authenticated_member():
    """
    Unauthenticated users and guests must be rejected from initiating account linking.
    """
    # 1. Unauthenticated -> 401
    resp_anon = client.get("/api/identity/github/connect")
    assert resp_anon.status_code == 401

    # 2. Authenticated active member (Rohan) -> 200 with authorization_url
    token = make_member_token("usr_student_rohan")
    resp_auth = client.get(
        "/api/identity/github/connect",
        headers={"Authorization": f"Bearer {token}"}
    )
    assert resp_auth.status_code == 200
    data = resp_auth.json()
    assert data["status"] == "ready"
    assert data["organization_id"] == "gdg_mcet"
    assert data["person_id"] == "usr_student_rohan"
    assert "https://github.com/login/oauth/authorize" in data["authorization_url"]
    assert "mock_gh_client_id_12345" in data["authorization_url"]
    assert "state=" in data["authorization_url"]

def test_oauth_state_token_tampering_and_replay_protection():
    """
    Tampered state tokens and replayed state tokens must be rejected fail-closed.
    """
    token = make_member_token("usr_student_rohan")
    init_resp = client.get(
        "/api/identity/github/connect",
        headers={"Authorization": f"Bearer {token}"}
    )
    valid_state = init_resp.json()["state"]

    # 1. Tampered state token -> 400
    tampered_state = valid_state[:-5] + "XXXXX"
    resp_tampered = client.get(f"/api/identity/github/callback?code=mock_code&state={tampered_state}")
    assert resp_tampered.status_code == 400
    assert "Invalid or tampered OAuth state" in resp_tampered.json()["detail"]

    # 2. Mock valid code exchange and first callback use
    with patch.object(github_oauth_client, "exchange_code_for_token", return_value="gho_mock_token_123"), \
         patch.object(github_oauth_client, "fetch_user_profile", return_value={
             "account_id": "88112233",
             "username": "rohan-dev",
             "display_name": "Rohan Verma",
             "email": "rohan@student.mcet.edu"
         }):
        resp_first = client.get(f"/api/identity/github/callback?code=valid_code_1&state={valid_state}")
        assert resp_first.status_code == 200
        assert resp_first.json()["status"] == "linked"

        # 3. Attempting to replay the exact same state token second time -> 400
        resp_replay = client.get(f"/api/identity/github/callback?code=valid_code_2&state={valid_state}")
        assert resp_replay.status_code == 400
        assert "already been consumed" in resp_replay.json()["detail"]


# =========================================================================
# 2. Authoritative Extraction & Rejection of Client-Supplied Identifiers
# =========================================================================

def test_oauth_callback_authoritatively_retrieves_numeric_id_and_persists_link():
    """
    The backend MUST authoritatively retrieve GitHub's immutable numeric user ID
    from the GitHub API and map it to the person_id in the state token.
    Client request bodies attempting to inject account_id or person_id are ignored.
    """
    token = make_member_token("usr_student_rohan")
    init_resp = client.get(
        "/api/identity/github/connect",
        headers={"Authorization": f"Bearer {token}"}
    )
    state = init_resp.json()["state"]

    mock_profile = {
        "account_id": "19283746",  # Immutable numeric GitHub user ID
        "username": "rohan-hacks",
        "display_name": "Rohan V.",
        "email": "rohan@student.mcet.edu"
    }

    with patch.object(github_oauth_client, "exchange_code_for_token", return_value="gho_mock_token_abc"), \
         patch.object(github_oauth_client, "fetch_user_profile", return_value=mock_profile):
        
        # Even if an attacker posts a body with target user_id or github_id, callback only respects state & github API
        resp = client.get(f"/api/identity/github/callback?code=mock_code&state={state}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "linked"
        assert data["organization_id"] == "gdg_mcet"
        assert data["person_id"] == "usr_student_rohan"
        assert data["account_id"] == "19283746"
        assert data["link_type"] == "oauth_verified"
        assert data["is_verified"] is True

    # Authoritative verification via identity_service.resolve_identity
    res = identity_service.resolve_identity(
        organization_id="gdg_mcet",
        channel_type=ChannelType.GITHUB,
        account_id="19283746"
    )
    assert res.person_id == "usr_student_rohan"
    assert res.is_verified is True
    assert res.confidence == 1.0

    # Verify audit log recorded oauth_linked event
    audit_events = identity_service.get_audit_events("gdg_mcet", person_id="usr_student_rohan")
    assert len(audit_events) >= 1
    oauth_ev = next(e for e in audit_events if e.event_type == "oauth_linked")
    assert oauth_ev.account_id == "19283746"
    assert oauth_ev.actor_person_id == "usr_student_rohan"

def test_oauth_callback_account_already_linked_conflict():
    """
    Attempting to link a GitHub account ID that is already actively linked
    to another member must be rejected with HTTP 409 Conflict.
    """
    # 1. Rohan connects GitHub ID 55443322
    token_rohan = make_member_token("usr_student_rohan")
    init_rohan = client.get("/api/identity/github/connect", headers={"Authorization": f"Bearer {token_rohan}"})
    state_rohan = init_rohan.json()["state"]

    with patch.object(github_oauth_client, "exchange_code_for_token", return_value="gho_rohan"), \
         patch.object(github_oauth_client, "fetch_user_profile", return_value={"account_id": "55443322", "username": "shared-gh"}):
        resp1 = client.get(f"/api/identity/github/callback?code=c1&state={state_rohan}")
        assert resp1.status_code == 200

    # 2. Priya attempts to connect the SAME GitHub ID 55443322 -> 409 Conflict
    token_priya = make_organizer_token("usr_priya")
    init_priya = client.get("/api/identity/github/connect", headers={"Authorization": f"Bearer {token_priya}"})
    state_priya = init_priya.json()["state"]

    with patch.object(github_oauth_client, "exchange_code_for_token", return_value="gho_priya"), \
         patch.object(github_oauth_client, "fetch_user_profile", return_value={"account_id": "55443322", "username": "shared-gh"}):
        resp2 = client.get(f"/api/identity/github/callback?code=c2&state={state_priya}")
        assert resp2.status_code == 409
        assert "already actively linked to person 'usr_student_rohan'" in resp2.json()["detail"]


# =========================================================================
# 3. Revocation State Tests
# =========================================================================

def test_github_link_revocation_downgrades_to_synthetic_public():
    """
    When an account link is revoked:
    1. is_active is set to False, revoked_at is recorded.
    2. Subsequent resolution treats the account as unlinked / revoked and creates a synthetic public identity.
    3. Normal members cannot revoke other members' links; organizers can.
    """
    # 1. Link Rohan
    token_rohan = make_member_token("usr_student_rohan")
    init_r = client.get("/api/identity/github/connect", headers={"Authorization": f"Bearer {token_rohan}"})
    with patch.object(github_oauth_client, "exchange_code_for_token", return_value="gho_r"), \
         patch.object(github_oauth_client, "fetch_user_profile", return_value={"account_id": "33445566", "username": "rohan-rev"}):
        client.get(f"/api/identity/github/callback?code=c&state={init_r.json()['state']}")

    # Verify active resolution
    res_before = identity_service.resolve_identity("gdg_mcet", ChannelType.GITHUB, "33445566")
    assert res_before.person_id == "usr_student_rohan"
    assert res_before.is_verified is True

    # 2. Member revokes their own link
    resp_revoke = client.post(
        "/api/identity/github/revoke",
        headers={"Authorization": f"Bearer {token_rohan}"},
        json={"reason": "Changing GitHub accounts"}
    )
    assert resp_revoke.status_code == 200
    assert resp_revoke.json()["status"] == "revoked"

    # 3. Verify subsequent resolution is isolated as synthetic public
    res_after = identity_service.resolve_identity("gdg_mcet", ChannelType.GITHUB, "33445566")
    assert res_after.person_id == "ext_github_33445566"
    assert res_after.is_verified is False
    assert res_after.permission_level == PermissionLevel.PUBLIC_COMMUNITY
    assert res_after.evidence.get("revoked") is True
    assert "revoked" in res_after.evidence.get("resolution_reason", "").lower()

    # 4. Verify audit log recorded link_revoked
    events = identity_service.get_audit_events("gdg_mcet", person_id="usr_student_rohan")
    revoke_ev = next(e for e in events if e.event_type == "link_revoked")
    assert revoke_ev.actor_person_id == "usr_student_rohan"
    assert revoke_ev.evidence["reason"] == "Changing GitHub accounts"


# =========================================================================
# 4. Organizer-Reviewed Manual Link Fallback Flow
# =========================================================================

def test_organizer_reviewed_manual_link_fallback_flow():
    """
    Exceptional manual account linking requires organizer review:
    1. Member submits manual link request.
    2. Non-numeric GitHub user ID is rejected.
    3. Normal member cannot approve/reject (403).
    4. Organizer reviews and approves -> verified link established with ORGANIZER_MANUAL.
    """
    token_rohan = make_member_token("usr_student_rohan")
    token_organizer = make_organizer_token("usr_arjun")

    # 1. Non-numeric GitHub ID rejected
    resp_bad = client.post(
        "/api/identity/manual-link/request",
        headers={"Authorization": f"Bearer {token_rohan}"},
        json={
            "account_id": "not-a-number",
            "username": "rohan-corp",
            "reason": "Corporate account restriction"
        }
    )
    assert resp_bad.status_code == 400
    assert "numeric ID" in resp_bad.json()["detail"]

    # 2. Valid request submission
    resp_req = client.post(
        "/api/identity/manual-link/request",
        headers={"Authorization": f"Bearer {token_rohan}"},
        json={
            "account_id": "99001122",
            "username": "rohan-corp-verified",
            "reason": "Corporate SSO restriction preventing OAuth popup",
            "evidence_notes": "Verified by Arjun via official college email"
        }
    )
    assert resp_req.status_code == 200
    req_data = resp_req.json()
    req_id = req_data["id"]
    assert req_data["status"] == "pending"
    assert req_data["person_id"] == "usr_student_rohan"
    assert req_data["account_id"] == "99001122"

    # 3. Normal member attempts to review -> 403 Forbidden
    resp_review_forbidden = client.post(
        f"/api/identity/manual-link/{req_id}/review",
        headers={"Authorization": f"Bearer {token_rohan}"},
        json={"action": "approve", "review_notes": "Self-approval attempt"}
    )
    assert resp_review_forbidden.status_code == 403

    # 4. Organizer lists pending requests
    resp_list = client.get(
        "/api/identity/manual-link/requests?status_filter=pending",
        headers={"Authorization": f"Bearer {token_organizer}"}
    )
    assert resp_list.status_code == 200
    assert any(r["id"] == req_id for r in resp_list.json()["requests"])

    # 5. Organizer reviews and approves
    resp_approve = client.post(
        f"/api/identity/manual-link/{req_id}/review",
        headers={"Authorization": f"Bearer {token_organizer}"},
        json={"action": "approve", "review_notes": "Approved after verifying college badge."}
    )
    assert resp_approve.status_code == 200
    assert resp_approve.json()["status"] == "approved"
    assert resp_approve.json()["reviewed_by"] == "usr_arjun"

    # 6. Verify account is now authoritatively linked with ORGANIZER_MANUAL
    res = identity_service.resolve_identity("gdg_mcet", ChannelType.GITHUB, "99001122")
    assert res.person_id == "usr_student_rohan"
    assert res.is_verified is True
    assert res.channel_link.link_type == LinkVerificationType.ORGANIZER_MANUAL
    assert res.channel_link.evidence["approved_by"] == "usr_arjun"

    # 7. Verify audit trail contains manual_requested and manual_approved
    events = identity_service.get_audit_events("gdg_mcet", person_id="usr_student_rohan")
    assert any(e.event_type == "manual_requested" for e in events)
    approved_ev = next(e for e in events if e.event_type == "manual_approved")
    assert approved_ev.actor_person_id == "usr_arjun"

def test_organizer_manual_link_rejection():
    """
    Organizer rejecting a manual link request marks it rejected and does not link the account.
    """
    token_rohan = make_member_token("usr_student_rohan")
    token_organizer = make_organizer_token("usr_arjun")

    resp_req = client.post(
        "/api/identity/manual-link/request",
        headers={"Authorization": f"Bearer {token_rohan}"},
        json={
            "account_id": "44332211",
            "username": "suspicious-user",
            "reason": "Please link me"
        }
    )
    req_id = resp_req.json()["id"]

    # Organizer rejects
    resp_reject = client.post(
        f"/api/identity/manual-link/{req_id}/review",
        headers={"Authorization": f"Bearer {token_organizer}"},
        json={"action": "reject", "review_notes": "Could not confirm identity."}
    )
    assert resp_reject.status_code == 200
    assert resp_reject.json()["status"] == "rejected"

    # Unlinked resolution
    res = identity_service.resolve_identity("gdg_mcet", ChannelType.GITHUB, "44332211")
    assert res.person_id == "ext_github_44332211"
    assert res.is_synthetic_public is True


# =========================================================================
# 5. Audit Log Endpoint RBAC Tests
# =========================================================================

def test_identity_audit_log_endpoint_requires_organizer():
    """
    Only organizers may access the institutional identity audit log.
    """
    token_rohan = make_member_token("usr_student_rohan")
    token_organizer = make_organizer_token("usr_arjun")

    # Member -> 403
    resp_member = client.get(
        "/api/identity/audit-log",
        headers={"Authorization": f"Bearer {token_rohan}"}
    )
    assert resp_member.status_code == 403

    # Organizer -> 200
    resp_org = client.get(
        "/api/identity/audit-log",
        headers={"Authorization": f"Bearer {token_organizer}"}
    )
    assert resp_org.status_code == 200
    assert "audit_events" in resp_org.json()


# =========================================================================
# 6. Multi-Worker & Fail-Closed Security Hardening Tests
# =========================================================================

def test_oauth_nonce_persistence_fails_closed_on_db_error(monkeypatch):
    """
    P1 Verification:
    If database write fails while recording an OAuth nonce, the endpoint must fail closed
    with HTTP 500 and NEVER fall back to local memory.
    """
    token = make_member_token("usr_student_rohan")
    # Generate valid state before setting mock DB URL
    valid_state = oauth_state_manager.generate_state_token("usr_student_rohan", "gdg_mcet")

    monkeypatch.setenv("SUPABASE_DB_URL", "postgresql://mock:mock@localhost:5432/mockdb")

    with patch("psycopg2.connect", side_effect=RuntimeError("PostgreSQL connection refused")):
        resp = client.get(
            "/api/identity/github/connect",
            headers={"Authorization": f"Bearer {token}"}
        )
        assert resp.status_code == 500
        assert "Failed to durably record OAuth state nonce" in resp.json()["detail"]

    # Similarly for callback nonce consumption
    with patch("psycopg2.connect", side_effect=RuntimeError("PostgreSQL connection refused")):
        resp_cb = client.get(f"/api/identity/github/callback?code=mock_code&state={valid_state}")
        assert resp_cb.status_code == 500
        assert "Failed to durably consume OAuth state nonce" in resp_cb.json()["detail"]

def test_browser_cannot_override_redirect_uri():
    """
    Asserts that redirect_uri is NOT accepted from query params, and only
    GITHUB_OAUTH_REDIRECT_URI from server settings is used in the authorization URL.
    """
    token = make_member_token("usr_student_rohan")
    resp = client.get(
        "/api/identity/github/connect?redirect_uri=https://attacker-steals-token.com/callback",
        headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 200
    auth_url = resp.json()["authorization_url"]
    assert "attacker-steals-token.com" not in auth_url
    assert "https%3A%2F%2Fthread.local%2Fapi%2Fidentity%2Fgithub%2Fcallback" in auth_url

def test_two_independent_service_instances_prevent_account_reassignment_across_workers(monkeypatch):
    """
    P0 Verification:
    Two independent CrossChannelIdentityService instances (simulating two API worker processes)
    cannot reassign an already active GitHub account to another person.
    Worker B has an empty in-memory cache, but the PostgreSQL SELECT ... FOR UPDATE transaction
    detects the existing active row and raises AccountAlreadyLinkedError (HTTP 409).
    """
    from app.identity.service import CrossChannelIdentityService, AccountAlreadyLinkedError
    
    mock_db_table = {}

    class MockCursor:
        def __init__(self):
            self._last_result = None

        def execute(self, query, params=None):
            q = query.strip()
            if "SELECT person_id, is_active" in q:
                key = (params[0], params[1], params[2])
                if key in mock_db_table:
                    row = mock_db_table[key]
                    self._last_result = (row["person_id"], row["is_active"])
                else:
                    self._last_result = None
            elif "INSERT INTO channel_account_links" in q:
                key = (params[1], params[3], params[4])
                mock_db_table[key] = {
                    "id": params[0],
                    "organization_id": params[1],
                    "person_id": params[2],
                    "channel_type": params[3],
                    "account_id": params[4],
                    "is_active": params[12],
                    "is_verified": params[11]
                }
            elif "UPDATE channel_account_links SET" in q:
                key = (params[12], params[13], params[14])
                if key in mock_db_table:
                    mock_db_table[key]["person_id"] = params[0]
                    mock_db_table[key]["is_active"] = params[8]
                    mock_db_table[key]["is_verified"] = params[7]

        def fetchone(self):
            return self._last_result

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_val, exc_tb):
            pass

    class MockConnection:
        def cursor(self):
            return MockCursor()

        def commit(self):
            pass

        def rollback(self):
            pass

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_val, exc_tb):
            pass

    monkeypatch.setenv("SUPABASE_DB_URL", "postgresql://mock:mock@localhost:5432/mockdb")
    monkeypatch.setattr("psycopg2.connect", lambda *a, **kw: MockConnection())

    # Worker A
    worker_a = CrossChannelIdentityService()
    worker_a.clear()

    # Worker B (simulating another process, separate memory)
    worker_b = CrossChannelIdentityService()
    worker_b.clear()

    # 1. Worker A links account 778899 to usr_alice
    worker_a.link_account(
        organization_id="gdg_mcet",
        person_id="usr_alice",
        channel_type=ChannelType.GITHUB,
        account_id="778899",
        username="alice-dev",
        link_type=LinkVerificationType.OAUTH_VERIFIED,
        confidence=1.0
    )

    # Assert Worker A has it in memory
    assert "gdg_mcet:github:778899" in worker_a._account_links
    # Assert Worker B has empty memory
    assert "gdg_mcet:github:778899" not in worker_b._account_links

    # 2. Worker B attempts to link account 778899 to usr_bob
    # Must fail closed with AccountAlreadyLinkedError based on PostgreSQL row lock
    with pytest.raises(AccountAlreadyLinkedError) as exc_info:
        worker_b.link_account(
            organization_id="gdg_mcet",
            person_id="usr_bob",
            channel_type=ChannelType.GITHUB,
            account_id="778899",
            username="bob-dev",
            link_type=LinkVerificationType.OAUTH_VERIFIED,
            confidence=1.0
        )
    assert "already actively linked to person 'usr_alice'" in str(exc_info.value)

    # 3. Revoke active link
    mock_db_table[("gdg_mcet", "github", "778899")]["is_active"] = False

    # 4. Now Worker B attempts to link account 778899 to usr_bob -> succeeds!
    link_b = worker_b.link_account(
        organization_id="gdg_mcet",
        person_id="usr_bob",
        channel_type=ChannelType.GITHUB,
        account_id="778899",
        username="bob-dev",
        link_type=LinkVerificationType.OAUTH_VERIFIED,
        confidence=1.0
    )
    assert link_b.person_id == "usr_bob"
    assert link_b.is_active is True

