"""Public API security checks; SQLite is an explicit offline repository seam.

Set THREAD_TEST_SERVICE_DB_URL to a disposable PostgreSQL database to run the
same suite against real transactions and the complete migration in a fresh schema.
"""
import os
from pathlib import Path
import sqlite3
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.tenancy.auth import COOKIE
from app.tenancy.repository import tenant_repository, digest

MIGRATION = Path(__file__).parents[1] / "app/data/migrations/020_v2_identity_and_tenants.sql"
MIGRATIONS = [MIGRATION, MIGRATION.with_name("021_v2_model_credentials.sql"), MIGRATION.with_name("022_v2_execution_traces.sql")]
PASSWORD = "a-long-test-password-123"


@pytest.fixture(params=["sqlite", pytest.param("postgres", marks=pytest.mark.skipif(
    not os.getenv("THREAD_TEST_SERVICE_DB_URL"), reason="Requires disposable THREAD_TEST_SERVICE_DB_URL"))])
def service(request, tmp_path, monkeypatch):
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("THREAD_FORCE_DETERMINISTIC_SYNTHESIS", "1")
    monkeypatch.setenv("THREAD_FORCE_DETERMINISTIC_EMBEDDINGS", "1")
    monkeypatch.setenv("THREAD_DEMO_AUTH_ENABLED", "false")
    monkeypatch.setenv("THREAD_ALLOW_GUEST_MODE", "false")
    if request.param == "sqlite":
        path = tmp_path / "service.sqlite"
        def connect():
            conn = sqlite3.connect(path, timeout=10)
            conn.execute("PRAGMA foreign_keys=ON")
            return conn
        conn = connect()
        for migration in MIGRATIONS:
            conn.executescript(migration.read_text().split("-- PostgreSQL access boundary")[0])
        conn.close()
    else:
        import psycopg2
        url = os.environ["THREAD_TEST_SERVICE_DB_URL"]
        schema = "test_v2_" + uuid.uuid4().hex
        with psycopg2.connect(url) as conn:
            with conn.cursor() as cur:
                cur.execute(f'CREATE SCHEMA "{schema}"')
        def connect():
            return psycopg2.connect(url, options=f"-c search_path={schema} -c lock_timeout=5000")
        conn = connect()
        with conn.cursor() as cur:
            for migration in MIGRATIONS:
                cur.execute(migration.read_text())
        conn.commit()
        conn.close()
    monkeypatch.setattr(tenant_repository, "connection_factory", connect)
    monkeypatch.setattr(tenant_repository, "dialect", request.param)
    from app.tracing.repository import trace_repository
    monkeypatch.setattr(trace_repository, "connection_factory", connect)
    monkeypatch.setattr(trace_repository, "dialect", request.param)
    yield connect
    if request.param == "postgres":
        with psycopg2.connect(url) as conn:
            with conn.cursor() as cur:
                # Generated schema is isolated to this test and validated by construction.
                cur.execute(f'DROP SCHEMA "{schema}" CASCADE')


def account(email="owner@example.com"):
    client = TestClient(app)
    result = client.post("/api/v2/auth/signup", json={"email": email, "name": email.split("@")[0], "password": PASSWORD})
    assert result.status_code == 201, result.text
    return client, result.json()["id"]


def workspace(client, name="Synthetic Team"):
    result = client.post("/api/v2/organizations", json={"name": name, "description": "A separate team"})
    assert result.status_code == 201, result.text
    return result.json()["id"]


def join(owner, org_id, email, role="member"):
    client, user_id = account(email)
    result = owner.post(f"/api/v2/organizations/{org_id}/invitations", json={"email": email, "role": role})
    assert result.status_code == 201, result.text
    token = result.json()["invitation_path"].split("/")[-1]
    result = client.post(f"/api/v2/invitations/{token}/accept")
    assert result.status_code == 200, result.text
    return client, user_id, token


def test_account_login_logout_and_hashed_storage(service):
    client, user_id = account()
    cookie = client.cookies.get(COOKIE)
    assert client.get("/api/v2/auth/me").json()["user"]["id"] == user_id
    with tenant_repository.transaction() as cur:
        row = tenant_repository.one(cur, "SELECT password_hash FROM thread_users WHERE id=%s", (user_id,))
        session = tenant_repository.one(cur, "SELECT token_hash FROM user_sessions WHERE user_id=%s", (user_id,))
    assert row["password_hash"].startswith("$argon2id$")
    assert PASSWORD not in row["password_hash"]
    assert session["token_hash"] == digest(cookie)
    assert client.post("/api/v2/auth/logout").status_code == 200
    replay = TestClient(app)
    replay.cookies.set(COOKIE, cookie)
    assert replay.get("/api/v2/auth/me").status_code == 401
    assert client.post("/api/v2/auth/login", json={"email": "owner@example.com", "password": "wrong"}).status_code == 401
    assert client.post("/api/v2/auth/login", json={"email": "OWNER@example.com", "password": PASSWORD}).status_code == 200


def test_workspace_persistence_switch_and_unknown_id(service):
    client, _ = account()
    first = workspace(client)
    second = workspace(client, "Other Team")
    assert client.get("/api/workspace").json()["id"] == second
    assert client.post(f"/api/v2/organizations/{first}/switch").status_code == 200
    assert client.get("/api/workspace").json()["id"] == first
    # Recreate the HTTP client and repository wrapper: no in-process registry state.
    restarted = TestClient(app)
    restarted.cookies.set(COOKIE, client.cookies.get(COOKIE))
    assert len(restarted.get("/api/v2/organizations").json()) == 2
    assert restarted.get("/api/workspace").json()["roles"][0]["id"] == "general_assistant"
    assert restarted.get("/api/v2/organizations/unknown").status_code == 404
    assert restarted.post("/api/v2/organizations/unknown/switch").status_code == 404


def test_invite_email_binding_single_use_and_expiration(service):
    owner, _ = account()
    org_id = workspace(owner)
    invited, _ = account("invitee@example.com")
    wrong, _ = account("other@example.com")
    path = owner.post(f"/api/v2/organizations/{org_id}/invitations", json={"email": "invitee@example.com"}).json()["invitation_path"]
    token = path.split("/")[-1]
    assert wrong.post(f"/api/v2/invitations/{token}/accept").status_code == 403
    assert invited.post(f"/api/v2/invitations/{token}/accept").status_code == 200
    assert invited.post(f"/api/v2/invitations/{token}/accept").status_code == 410
    token2 = owner.post(f"/api/v2/organizations/{org_id}/invitations", json={"email": "other@example.com"}).json()["invitation_path"].split("/")[-1]
    with tenant_repository.transaction() as cur:
        tenant_repository.execute(cur, "UPDATE invitations SET expires_at=%s WHERE token_hash=%s", (int(time.time()) - 1, digest(token2)))
    assert wrong.post(f"/api/v2/invitations/{token2}/accept").status_code == 410


def test_revocation_blocks_existing_api_and_chat_sessions(service):
    owner, _ = account()
    org_id = workspace(owner)
    member, member_id, _ = join(owner, org_id, "member@example.com")
    assert member.get("/api/session").status_code == 200
    assert owner.delete(f"/api/v2/organizations/{org_id}/members/{member_id}").status_code == 200
    assert member.get(f"/api/v2/organizations/{org_id}").status_code == 403
    assert member.get("/api/workspace").status_code == 403
    assert member.post("/api/chat", json={"query": "What did our team decide?"}).status_code == 403
    assert member.get("/api/v2/auth/me").json()["active_organization_id"] is None


def test_expired_session_and_legacy_bearer_membership_revocation(service, monkeypatch):
    from app.core.auth import create_access_token
    monkeypatch.setenv("THREAD_JWT_SECRET", "v2-isolated-test-signing-secret-at-least-32-characters")
    owner, _ = account()
    org_id = workspace(owner)
    member, member_id, _ = join(owner, org_id, "bearer@example.com")
    token = create_access_token(member_id, org_id)
    bearer = TestClient(app)
    assert bearer.get("/api/workspace", headers={"Authorization": f"Bearer {token}"}).status_code == 200
    owner.delete(f"/api/v2/organizations/{org_id}/members/{member_id}")
    assert bearer.get("/api/workspace", headers={"Authorization": f"Bearer {token}"}).status_code == 403
    with tenant_repository.transaction() as cur:
        tenant_repository.execute(cur, "UPDATE user_sessions SET expires_at=%s WHERE token_hash=%s", (int(time.time()) - 1, digest(owner.cookies.get(COOKIE))))
    assert owner.get("/api/v2/auth/me").status_code == 401


def test_member_and_admin_cannot_escalate_privileges(service):
    owner, owner_id = account()
    org_id = workspace(owner)
    member, member_id, _ = join(owner, org_id, "member@example.com")
    admin, admin_id, _ = join(owner, org_id, "admin@example.com", "admin")
    prefix = f"/api/v2/organizations/{org_id}"
    assert member.post(prefix + "/invitations", json={"email": "new@example.com"}).status_code == 403
    assert member.patch(prefix + f"/members/{member_id}", json={"role": "admin"}).status_code == 403
    assert admin.patch(prefix + f"/members/{member_id}", json={"role": "owner"}).status_code == 403
    assert admin.delete(prefix + f"/members/{owner_id}").status_code in (403, 409)
    assert admin.post(prefix + "/invitations", json={"email": "new@example.com", "role": "admin"}).status_code == 403
    assert owner.patch(prefix + f"/members/{admin_id}", json={"role": "member"}).status_code == 200
    assert admin.post(prefix + "/invitations", json={"email": "new@example.com"}).status_code == 403


def test_owner_transfer_is_atomic_and_prevents_orphaning(service):
    owner, owner_id = account()
    org_id = workspace(owner)
    member, member_id, _ = join(owner, org_id, "next-owner@example.com")
    prefix = f"/api/v2/organizations/{org_id}/members"
    assert owner.delete(prefix + f"/{owner_id}").status_code == 409
    assert owner.patch(prefix + f"/{owner_id}", json={"role": "member"}).status_code == 409
    assert owner.patch(prefix + f"/{member_id}", json={"role": "owner"}).status_code == 200
    roles = {row["id"]: row["role"] for row in member.get(prefix).json()}
    assert roles[member_id] == "owner" and roles[owner_id] == "admin"
    assert owner.patch(prefix + f"/{owner_id}", json={"role": "owner"}).status_code == 403


def test_concurrent_transfers_preserve_single_owner(service):
    owner, _ = account()
    org_id = workspace(owner)
    _, first, _ = join(owner, org_id, "first@example.com")
    _, second, _ = join(owner, org_id, "second@example.com")
    cookie = owner.cookies.get(COOKIE)
    def transfer(target):
        client = TestClient(app)
        client.cookies.set(COOKIE, cookie)
        return client.patch(f"/api/v2/organizations/{org_id}/members/{target}", json={"role": "owner"}).status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        statuses = list(pool.map(transfer, [first, second]))
    assert sorted(statuses) == [200, 403]
    assert sum(row["role"] == "owner" for row in owner.get(f"/api/v2/organizations/{org_id}/members").json()) == 1


def test_cross_tenant_access_and_forged_org_are_denied(service):
    first, _ = account()
    org_a = workspace(first)
    second, _ = account("second@example.com")
    org_b = workspace(second)
    assert first.post(f"/api/v2/organizations/{org_b}/switch").status_code == 403
    assert first.get(f"/api/v2/organizations/{org_b}").status_code == 403
    assert first.get(f"/api/workspace?organization_id={org_b}").status_code == 403
    assert first.post("/api/chat", json={"query": "Hello", "organization_id": org_b}).status_code == 403
    assert first.get("/api/workspace").json()["id"] == org_a


def test_generic_routing_and_persistent_configuration(service):
    from app.core.organizations import get_workspace
    from app.graph.workflow import classify_intent_and_routing
    owner, _ = account()
    org_id = workspace(owner)
    ws = get_workspace(org_id)
    assert ws.roles[0].name == "Thread"
    assert classify_intent_and_routing("What is Project Aurora?", ws)[0] == "ORGANIZATIONAL_FACTS"
    assert classify_intent_and_routing("Hello", ws)[0] == "GENERAL_KNOWLEDGE"
    assert classify_intent_and_routing("What can you do?", ws)[0] == "GENERAL_KNOWLEDGE"
    assert classify_intent_and_routing("Hi, what did our team decide?", ws)[0] == "ORGANIZATIONAL_FACTS"
    assert classify_intent_and_routing("Explain reinforcement learning", ws)[0] == "GENERAL_KNOWLEDGE"
    answer = owner.post("/api/chat", json={"query": "What did our team decide about Aurora?"})
    # Phase 2 requires explicit BYOK before executing any tenant query.
    assert answer.status_code == 409, answer.text
    assert "GDG MCET" not in answer.text
    specialist = {"id": "support", "name": "Support", "role": "Support lead", "department": "Service", "style": "Concise", "avatar": "", "expertise": ["refund"]}
    result = owner.patch(f"/api/v2/organizations/{org_id}", json={"name": "Changed", "default_agent_name": "Atlas", "configured_roles": [specialist]})
    assert result.status_code == 200, result.text
    ws = get_workspace(org_id)
    assert ws.name == "Changed" and ws.roles[0].name == "Atlas"
    assert classify_intent_and_routing("Our refund policy", ws)[3].id == "support"


def test_cross_site_mutations_invalid_cookie_and_validation(service):
    owner, _ = account()
    assert owner.post("/api/v2/organizations", json={"name": "Bad"}, headers={"Origin": "https://attacker.example"}).status_code == 403
    assert owner.post("/api/v2/auth/logout", headers={"Sec-Fetch-Site": "cross-site"}).status_code == 403
    assert owner.post("/api/v2/organizations", json={"name": "  "}).status_code == 422
    invalid = TestClient(app)
    invalid.cookies.set(COOKIE, "invalid")
    assert invalid.get("/api/session").status_code == 401


def test_database_unavailable_never_uses_demo(service, monkeypatch):
    client, _ = account()
    workspace(client)
    def unavailable():
        raise OSError("postgresql://user:private-password@host/database")
    monkeypatch.setattr(tenant_repository, "connection_factory", unavailable)
    result = client.get("/api/workspace")
    assert result.status_code == 503
    assert "private-password" not in result.text and "gdg_mcet" not in result.text
