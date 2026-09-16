import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.core.auth import create_access_token

client = TestClient(app)

def test_session_endpoint_signed_out_state():
    """Verify GET /api/session without authorization returns HTTP 401 signed-out state."""
    response = client.get("/api/session")
    assert response.status_code == 401
    assert "detail" in response.json()


def test_session_endpoint_invalid_or_expired_session():
    """Verify GET /api/session with malformed or invalid token returns HTTP 401."""
    # 1. Malformed token
    res1 = client.get("/api/session", headers={"Authorization": "Bearer invalid_token_xyz"})
    assert res1.status_code == 401

    # 2. Expired token
    expired_token = create_access_token(user_id="demo_organizer", expires_in_seconds=-3600)
    res2 = client.get("/api/session", headers={"Authorization": "Bearer " + expired_token})
    assert res2.status_code == 401
    assert "expired" in res2.json()["detail"].lower()


def test_session_endpoint_valid_session():
    """Verify GET /api/session with valid token returns authenticated session context."""
    valid_token = create_access_token(user_id="demo_organizer", expires_in_seconds=3600)
    res = client.get("/api/session", headers={"Authorization": "Bearer " + valid_token})
    assert res.status_code == 200
    data = res.json()
    assert data["authenticated"] is True
    assert data["user_id"] == "demo_organizer"
    assert data["organization_id"] == "gdg_mcet"


def test_chat_endpoint_unchanged_query_text():
    """Verify POST /api/chat processes unchanged raw query text without prefix mutation."""
    valid_token = create_access_token(user_id="demo_organizer", expires_in_seconds=3600)
    query_text = "What is the venue for DevFest?"

    res = client.post(
        "/api/chat",
        headers={"Authorization": "Bearer " + valid_token},
        json={"query": query_text, "organization_id": "gdg_mcet"}
    )
    assert res.status_code == 200
    data = res.json()
    assert data["query"] == query_text, "Query returned in response must match unchanged input query"
