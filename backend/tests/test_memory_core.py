import os
import pytest
from fastapi.testclient import TestClient

# FORCE OFFLINE DETERMINISTIC EMBEDDINGS & SYNTHESIS FOR FAST, LOCAL, DETERMINISTIC TESTS
os.environ["THREAD_FORCE_DETERMINISTIC_EMBEDDINGS"] = "1"
os.environ["THREAD_FORCE_DETERMINISTIC_SYNTHESIS"] = "1"
os.environ["APP_ENV"] = "production"
os.environ["THREAD_DEMO_AUTH_ENABLED"] = "false"
os.environ["THREAD_ALLOW_GUEST_MODE"] = "false"
os.environ["THREAD_JWT_SECRET"] = "test-secret-cryptographically-secure-32-chars-long-abc12345"

from app.core.config import settings
from app.core.canonical import PermissionLevel, SourceType
from app.core.membership import membership_store
from app.core.auth import create_access_token
from app.memory.store import memory_store
from app.memory.adapters import get_source_adapter
from app.memory.retrieval import retrieval_service, derive_access_context
from app.data.seeds import get_seed_data
from app.graph.state import GraphState
from app.graph.workflow import app_graph
from app.main import app

client = TestClient(app)

@pytest.fixture(autouse=True)
def setup_memory_and_env():
    """Ensure clean store populated with verified seed data and deterministic mode enabled."""
    memory_store.clear()
    memory_store.force_deterministic = True
    records, chunks, receipts = get_seed_data(organization_id="gdg_mcet")
    for r in records:
        memory_store.add_record(r)
    memory_store.add_chunks(chunks)
    return records, chunks, receipts

# =====================================================================
# AUTHENTICATION BOUNDARY v0 TESTS
# =====================================================================

# 1. Unauthenticated requests must return 401 Unauthorized
def test_unauthenticated_chat_returns_401():
    response = client.post("/api/chat", json={"query": "Where is DevFest?"})
    assert response.status_code == 401
    assert "credentials were not provided" in response.json()["detail"].lower()
    assert "Bearer" in response.headers.get("WWW-Authenticate", "")

def test_unauthenticated_memories_returns_401():
    response = client.get("/api/memories?organization_id=gdg_mcet")
    assert response.status_code == 401
    assert "credentials were not provided" in response.json()["detail"].lower()

# 2. Forged body user_id="usr_arjun" without token is rejected as 401
def test_forged_body_user_id_rejected_as_401():
    response = client.post("/api/chat", json={
        "query": "What is our internal budget for t-shirts?",
        "user_id": "usr_arjun",
        "user_role": "organizer"
    })
    assert response.status_code == 401

# 3. Forged X-User-Id: usr_arjun header without token is rejected as 401
def test_forged_x_user_id_header_rejected_as_401():
    response = client.post(
        "/api/chat",
        json={"query": "What is our internal budget for t-shirts?"},
        headers={"X-User-Id": "usr_arjun"}
    )
    assert response.status_code == 401

# 4. Forged body user_id="usr_arjun" alongside valid student token cannot elevate privileges
def test_forged_body_user_id_with_student_token_cannot_elevate():
    student_token = create_access_token(user_id="usr_student_rohan", organization_id="gdg_mcet")
    payload = {
        "query": "What is our internal budget for attendee t-shirts and swag?",
        "organization_id": "gdg_mcet",
        "user_id": "usr_arjun",    # ATTEMPT TO FORGE ARJUN IN BODY
        "user_role": "organizer"   # ATTEMPT TO CLAIM ORGANIZER IN BODY
    }

    response = client.post(
        "/api/chat",
        json=payload,
        headers={"Authorization": f"Bearer {student_token}"}
    )
    assert response.status_code == 200
    data = response.json()

    # Identity must be derived exclusively from the token (usr_student_rohan -> PUBLIC_COMMUNITY)
    receipt = data.get("receipt")
    assert receipt is not None
    assert receipt["allowed_scopes"] == [PermissionLevel.PUBLIC_COMMUNITY.value]
    assert receipt["candidates_after_acl"] == 3

    # Zero confidential budget data leaked
    for cit in data.get("citations", []):
        assert cit["permission"] == PermissionLevel.PUBLIC_COMMUNITY.value
        assert "PrintWear Co" not in cit["snippet"]
        assert "55,000" not in cit["snippet"]

# 5. Forged X-User-Id alongside valid student token cannot elevate privileges
def test_forged_x_user_id_with_student_token_cannot_elevate():
    student_token = create_access_token(user_id="usr_student_rohan", organization_id="gdg_mcet")
    response = client.post(
        "/api/chat",
        json={"query": "What is our internal budget for attendee t-shirts and swag?"},
        headers={
            "Authorization": f"Bearer {student_token}",
            "X-User-Id": "usr_arjun"  # ATTEMPT TO FORGE ARJUN IN HEADER
        }
    )
    assert response.status_code == 200
    data = response.json()

    receipt = data.get("receipt")
    assert receipt is not None
    assert receipt["allowed_scopes"] == [PermissionLevel.PUBLIC_COMMUNITY.value]
    for cit in data.get("citations", []):
        assert "PrintWear Co" not in cit["snippet"]

# 6. Default demo-disabled behavior: THREAD_DEMO_AUTH_ENABLED defaults to false
def test_default_demo_auth_disabled_behavior():
    assert settings.demo_auth_enabled is False

    response = client.post("/api/chat", json={
        "query": "Where is DevFest?",
        "user_role": "organizer"
    })
    assert response.status_code == 401

# 7. Dev demo identity requires BOTH APP_ENV=development AND THREAD_DEMO_AUTH_ENABLED=true
def test_dev_demo_requires_both_app_env_and_demo_flag(monkeypatch):
    # Case A: APP_ENV=production, THREAD_DEMO_AUTH_ENABLED=true -> must return 401
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("THREAD_DEMO_AUTH_ENABLED", "true")
    res_a = client.post("/api/chat", json={"query": "Where is DevFest?"})
    assert res_a.status_code == 401

    # Case B: APP_ENV=development, THREAD_DEMO_AUTH_ENABLED=false -> must return 401
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("THREAD_DEMO_AUTH_ENABLED", "false")
    res_b = client.post("/api/chat", json={"query": "Where is DevFest?"})
    assert res_b.status_code == 401

    # Case C: BOTH enabled -> succeeds with dev demo identity
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("THREAD_DEMO_AUTH_ENABLED", "true")
    res_c = client.post("/api/chat", json={"query": "Where is DevFest?"})
    assert res_c.status_code == 200
    assert res_c.json()["organization_id"] == "gdg_mcet"

# 8. Explicit public guest mode may only receive public scope
def test_guest_mode_may_only_receive_public_scope(monkeypatch):
    monkeypatch.setenv("THREAD_ALLOW_GUEST_MODE", "true")

    response = client.post("/api/chat", json={
        "query": "What is our internal budget for t-shirts and swag?"
    })
    assert response.status_code == 200
    data = response.json()

    receipt = data.get("receipt")
    assert receipt["allowed_scopes"] == [PermissionLevel.PUBLIC_COMMUNITY.value]
    assert receipt["candidates_after_acl"] == 3
    for cit in data.get("citations", []):
        assert cit["permission"] == PermissionLevel.PUBLIC_COMMUNITY.value
        assert "PrintWear" not in cit["snippet"]

# 9. Verified Bearer token for active organizer retrieves INTERNAL_CORE
def test_verified_bearer_organizer_can_retrieve_internal_core():
    organizer_token = create_access_token(user_id="usr_arjun", organization_id="gdg_mcet")
    response = client.post(
        "/api/chat",
        json={"query": "What is our internal budget for attendee t-shirts and swag?"},
        headers={"Authorization": f"Bearer {organizer_token}"}
    )
    assert response.status_code == 200
    data = response.json()

    assert data["sufficient_evidence"] is True
    matched_budget = any("55,000" in c["snippet"] or "PrintWear" in c["snippet"] for c in data["citations"])
    assert matched_budget is True

# 10. /api/memories ACL is enforced via Bearer token
def test_api_memories_acl_enforced_via_bearer():
    student_token = create_access_token(user_id="usr_student_rohan", organization_id="gdg_mcet")
    res_student = client.get("/api/memories", headers={"Authorization": f"Bearer {student_token}"})
    assert res_student.status_code == 200
    data_student = res_student.json()
    assert data_student["count"] == 3
    assert all(m["permission"] == PermissionLevel.PUBLIC_COMMUNITY.value for m in data_student["memories"])

    organizer_token = create_access_token(user_id="usr_arjun", organization_id="gdg_mcet")
    res_organizer = client.get("/api/memories", headers={"Authorization": f"Bearer {organizer_token}"})
    assert res_organizer.status_code == 200
    data_organizer = res_organizer.json()
    assert data_organizer["count"] == 5

# 11. Inactive members with signed token get no internal access
def test_inactive_members_get_no_internal_access():
    inactive_token = create_access_token(user_id="usr_inactive_lead", organization_id="gdg_mcet")
    response = client.post(
        "/api/chat",
        json={"query": "What is our internal budget for attendee t-shirts and swag?"},
        headers={"Authorization": f"Bearer {inactive_token}"}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["receipt"]["candidates_after_acl"] == 3
    assert all(c["permission"] == PermissionLevel.PUBLIC_COMMUNITY.value for c in data["citations"])

# 12. Retrieval receipt never includes unauthorized item contents
def test_retrieval_receipt_never_includes_unauthorized_contents():
    student_token = create_access_token(user_id="usr_student_rohan", organization_id="gdg_mcet")
    response = client.post(
        "/api/chat",
        json={"query": "Show me confidential sponsor allocations and speaker rolodex"},
        headers={"Authorization": f"Bearer {student_token}"}
    )
    assert response.status_code == 200
    receipt_str = str(response.json()["receipt"])
    assert "PrintWear" not in receipt_str
    assert "55,000" not in receipt_str
    assert "Dr. S. Raman" not in receipt_str

# 13. Role routing is deterministic for known queries
def test_role_routing_is_deterministic_for_known_queries():
    test_cases = [
        ("What are the prerequisites for the GenAI workshop and github repository?", "tech_lead"),
        ("Has the Main Mechanical Auditorium venue date been approved for DevFest?", "organizer_lead"),
        ("How do students get attendance certificates and where is the registration RSVP?", "community_lead"),
    ]

    for q, expected_role_id in test_cases:
        state = GraphState(
            query=q,
            organization_id="gdg_mcet",
            access_context=derive_access_context(user_id="usr_arjun", organization_id="gdg_mcet")
        )
        res = app_graph.invoke(state)
        assert res["target_role_id"] == expected_role_id

# 14. No-evidence query returns insufficient-evidence state (No Bluffing)
def test_no_evidence_query_returns_insufficient_evidence_state():
    organizer_token = create_access_token(user_id="usr_arjun", organization_id="gdg_mcet")
    response = client.post(
        "/api/chat",
        json={"query": "What is our submarine propulsion protocol in the Mariana Trench?"},
        headers={"Authorization": f"Bearer {organizer_token}"}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["sufficient_evidence"] is False
    assert "insufficient evidence" in data["answer"].lower()

# 15. Ingestion preserves source provenance
def test_ingestion_preserves_source_provenance():
    adapter = get_source_adapter(SourceType.GITHUB)
    raw_payload = {
        "source_uri": "https://github.com/gdg-mcet/cloud-codelab",
        "author": "Priya Ramesh",
        "author_role": "Tech Lead",
        "title": "Cloud Run Deployment Guide",
        "content": "Step 1: Ensure gcloud CLI is authenticated. Step 2: Deploy service via gcloud run deploy.",
        "permission": PermissionLevel.PUBLIC_COMMUNITY,
        "tags": ["gcp", "cloudrun", "guide"],
        "metadata": {"commit_sha": "abc12345", "branch": "main"}
    }

    record, chunks, receipt = adapter.ingest(raw_payload, organization_id="gdg_mcet")
    assert record.organization_id == "gdg_mcet"
    assert record.source_type == SourceType.GITHUB
    assert len(record.hash) == 64
    assert chunks[0].provenance["record_hash"] == record.hash
    assert receipt.status == "success"

# 16. Forged token signed with old committed secret is rejected with 401
def test_forged_token_signed_with_old_committed_secret_rejected_as_401():
    old_secret = "thread-sec-boundary-key-9f8a2b3c4d5e"
    forged_token = create_access_token(
        user_id="usr_arjun",
        organization_id="gdg_mcet",
        secret=old_secret
    )
    # Test on /api/chat
    response_chat = client.post(
        "/api/chat",
        json={"query": "What is our budget?"},
        headers={"Authorization": f"Bearer {forged_token}"}
    )
    assert response_chat.status_code == 401
    assert "invalid authentication token" in response_chat.json()["detail"].lower()

    # Test on /api/memories
    response_mem = client.get(
        "/api/memories",
        headers={"Authorization": f"Bearer {forged_token}"}
    )
    assert response_mem.status_code == 401
    assert "invalid authentication token" in response_mem.json()["detail"].lower()

# 17. Missing, weak, or known insecure production secrets cause startup failure
def test_production_startup_fails_on_insecure_secrets(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")

    # A. Absent secret
    monkeypatch.setenv("THREAD_JWT_SECRET", "")
    with pytest.raises(RuntimeError, match="THREAD_JWT_SECRET is absent in production"):
        settings.validate_production_security()

    # B. Weak secret (< 32 chars)
    monkeypatch.setenv("THREAD_JWT_SECRET", "too-short-secret-12345")
    with pytest.raises(RuntimeError, match="too weak"):
        settings.validate_production_security()

    # C. Known insecure / old development secret
    monkeypatch.setenv("THREAD_JWT_SECRET", "thread-sec-boundary-key-9f8a2b3c4d5e")
    with pytest.raises(RuntimeError, match="known development or default value"):
        settings.validate_production_security()

# 18. Cross-organization access is rejected with 403 Forbidden
def test_cross_organization_access_rejected_as_403():
    # User token is valid exclusively for gdg_mcet
    token = create_access_token(user_id="usr_arjun", organization_id="gdg_mcet")

    # A. /api/memories with mismatched requested organization
    res_mem = client.get(
        "/api/memories?organization_id=other_unauthorized_org",
        headers={"Authorization": f"Bearer {token}"}
    )
    assert res_mem.status_code == 403
    assert "Cross-organization memory access is denied" in res_mem.json()["detail"]

    # B. /api/chat with mismatched requested organization
    res_chat = client.post(
        "/api/chat",
        json={"query": "Where is DevFest?", "organization_id": "other_unauthorized_org"},
        headers={"Authorization": f"Bearer {token}"}
    )
    assert res_chat.status_code == 403
    assert "Cross-organization access is denied" in res_chat.json()["detail"]

    # C. /api/memories without organization_id defaults to principal's organization
    res_default = client.get(
        "/api/memories",
        headers={"Authorization": f"Bearer {token}"}
    )
    assert res_default.status_code == 200
    data = res_default.json()
    assert data["organization_id"] == "gdg_mcet"
    assert data["count"] == 5

# 19. Arbitrary development header impersonation is rejected with 403 Forbidden
def test_arbitrary_dev_demo_user_impersonation_rejected_as_403(monkeypatch):
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("THREAD_DEMO_AUTH_ENABLED", "true")

    # A. Arbitrary user_id impersonation rejected
    res_arjun = client.post(
        "/api/chat",
        json={"query": "What is our internal budget?"},
        headers={"X-Dev-Demo-User": "usr_arjun"}
    )
    assert res_arjun.status_code == 403
    assert "not an authorized demo identity" in res_arjun.json()["detail"]

    # B. Admin / root impersonation rejected
    res_admin = client.get(
        "/api/memories",
        headers={"X-Dev-Demo-User": "admin"}
    )
    assert res_admin.status_code == 403
    assert "not an authorized demo identity" in res_admin.json()["detail"]

    # C. Explicit allowed demo identities succeed in development mode
    res_demo_comm = client.get(
        "/api/memories",
        headers={"X-Dev-Demo-User": "demo_community"}
    )
    assert res_demo_comm.status_code == 200
    assert res_demo_comm.json()["count"] == 3

    res_demo_org = client.get(
        "/api/memories",
        headers={"X-Dev-Demo-User": "demo_organizer"}
    )
    assert res_demo_org.status_code == 200
    assert res_demo_org.json()["count"] == 5
