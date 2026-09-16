import pytest
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app, base_url="https://testserver")

def test_browser_cookie_auth_end_to_end():
    """
    End-to-End Browser Cookie Authentication Test:
    1. Proves initial request without cookie or Authorization header receives 401.
    2. Invokes POST /api/session/login which issues secure HttpOnly 'thread_session' cookie.
    3. Proves subsequent GET /api/session succeeds with 200 OK using ONLY the cookie (NO Authorization header).
    4. Proves subsequent POST /api/chat succeeds with 200 OK using ONLY the cookie (NO Authorization header).
    5. Invokes POST /api/session/logout which clears cookie.
    6. Proves subsequent GET /api/session returns 401 Unauthorized.
    """
    # 1. Unauthenticated request without header or cookie -> 401
    res_unauth = client.get("/api/session")
    assert res_unauth.status_code == 401

    # 2. Login via POST /api/session/login (sets thread_session cookie in TestClient jar)
    res_login = client.post("/api/session/login", json={"user_id": "demo_organizer", "organization_id": "gdg_mcet"})
    assert res_login.status_code == 200
    assert "thread_session" in client.cookies

    # 3. GET /api/session using ONLY cookie (explicitly NO Authorization header)
    res_session = client.get("/api/session")
    assert res_session.status_code == 200
    data_session = res_session.json()
    assert data_session["authenticated"] is True
    assert data_session["user_id"] == "demo_organizer"
    assert data_session["organization_id"] == "gdg_mcet"

    # 4. POST /api/chat using ONLY cookie (explicitly NO Authorization header)
    res_chat = client.post("/api/chat", json={"query": "what is the venue for DevFest?", "organization_id": "gdg_mcet"})
    assert res_chat.status_code == 200
    data_chat = res_chat.json()
    assert "answer" in data_chat
    assert data_chat["organization_id"] == "gdg_mcet"

    # 5. Logout via POST /api/session/logout
    res_logout = client.post("/api/session/logout")
    assert res_logout.status_code == 200

    # 6. Subsequent request without cookie -> 401
    res_after_logout = client.get("/api/session")
    assert res_after_logout.status_code == 401
