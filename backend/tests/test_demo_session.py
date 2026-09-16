from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_demo_session_is_unavailable_without_explicit_flag(monkeypatch):
    client.cookies.clear()
    monkeypatch.delenv("THREAD_DEMO_WORKSPACE_ENABLED", raising=False)

    response = client.post("/api/session/demo")

    assert response.status_code == 404


def test_demo_session_is_fixed_to_public_demo_viewer(monkeypatch):
    client.cookies.clear()
    monkeypatch.setenv("THREAD_DEMO_WORKSPACE_ENABLED", "true")

    response = client.post(
        "/api/session/demo",
        json={"user_id": "demo_organizer", "organization_id": "another_org", "role": "organizer"},
    )

    assert response.status_code == 200
    assert response.json()["user_id"] == "demo_judge"
    assert response.json()["organization_id"] == "gdg_mcet"
    assert "thread_session" in response.cookies

    session = client.get(
        "/api/session",
        headers={"Cookie": f"thread_session={response.cookies.get('thread_session')}"},
    )
    assert session.status_code == 200
    assert session.json()["user_id"] == "demo_judge"
    assert session.json()["organization_id"] == "gdg_mcet"
    assert session.json()["allowed_scopes"] == ["PUBLIC_COMMUNITY"]


def test_legacy_arbitrary_session_login_is_not_available():
    client.cookies.clear()

    response = client.post("/api/session/login", json={"user_id": "usr_arjun", "organization_id": "gdg_mcet"})

    assert response.status_code == 404
