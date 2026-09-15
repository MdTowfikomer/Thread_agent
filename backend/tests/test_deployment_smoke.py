import os
import pytest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.channels.gateway import (
    try_acquire_gateway_advisory_lock,
    release_gateway_advisory_lock,
    DISCORD_GATEWAY_ADVISORY_LOCK_ID
)


# ==============================================================================
# 1. NORMAL PRODUCTION SECURITY & DEDICATED WORKER ENFORCEMENT
# ==============================================================================
def test_production_strict_rule_forbids_in_process_gateway(monkeypatch):
    """
    CRITICAL PRODUCTION SAFETY TEST:
    In standard production (APP_ENV=production without render_free_demo),
    THREAD_START_GATEWAY_BOT=true MUST abort startup with a RuntimeError.
    Dedicated worker process (run_gateway.py) is strictly required.
    """
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.delenv("THREAD_DEPLOYMENT_MODE", raising=False)
    monkeypatch.setenv("THREAD_JWT_SECRET", "cryptographically-secure-32-character-secret-abc123")
    monkeypatch.setenv("THREAD_START_GATEWAY_BOT", "true")

    s = Settings()
    assert s.is_render_free_demo is False
    with pytest.raises(RuntimeError) as exc_info:
        s.validate_production_security()
    assert "THREAD_START_GATEWAY_BOT is strictly development-only" in str(exc_info.value)
    assert "run_gateway" in str(exc_info.value)


def test_production_rejects_weak_or_missing_jwt_secret(monkeypatch):
    """Verify production requires at least 32-char secure JWT secret."""
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.delenv("THREAD_DEPLOYMENT_MODE", raising=False)
    monkeypatch.setenv("THREAD_START_GATEWAY_BOT", "false")

    # 1. Missing secret
    monkeypatch.setenv("THREAD_JWT_SECRET", "")
    s1 = Settings()
    with pytest.raises(RuntimeError) as exc1:
        s1.validate_production_security()
    assert "THREAD_JWT_SECRET is absent" in str(exc1.value)

    # 2. Too short secret (<32 chars)
    monkeypatch.setenv("THREAD_JWT_SECRET", "short-secret-12345")
    s2 = Settings()
    with pytest.raises(RuntimeError) as exc2:
        s2.validate_production_security()
    assert "THREAD_JWT_SECRET is too weak" in str(exc2.value)


# ==============================================================================
# 2. RENDER FREE DEMO MODE CONFIGURATION & ADVISORY LOCK
# ==============================================================================
def test_render_free_demo_allows_gateway_with_production_secrets(monkeypatch):
    """
    RENDER FREE MODE TEST:
    When THREAD_DEPLOYMENT_MODE=render_free_demo, the single web service is permitted
    to start the Gateway bot in the background provided production secrets are valid.
    """
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("THREAD_DEPLOYMENT_MODE", "render_free_demo")
    monkeypatch.setenv("THREAD_JWT_SECRET", "cryptographically-secure-32-character-secret-abc123")
    monkeypatch.setenv("THREAD_START_GATEWAY_BOT", "true")

    s = Settings()
    assert s.is_render_free_demo is True
    # Must NOT raise RuntimeError about THREAD_START_GATEWAY_BOT
    s.validate_production_security()


def test_render_free_demo_advisory_lock_leader_election():
    """
    CRITICAL MULTI-INSTANCE LOCK TEST:
    Verifies that try_acquire_gateway_advisory_lock uses pg_try_advisory_lock.
    - Leader acquires lock (returns connection).
    - Peer/standby fails to acquire (returns None) without crashing.
    """
    mock_conn = MagicMock()
    mock_cur = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cur
    mock_conn.__enter__.return_value = mock_conn

    # 1. Leader acquires lock
    mock_cur.fetchone.return_value = (True,)
    with patch("psycopg2.connect", return_value=mock_conn), \
         patch.dict(os.environ, {"SUPABASE_DB_URL": "postgresql://test:test@localhost:5432/test"}):
        conn = try_acquire_gateway_advisory_lock()
        assert conn is not None
        mock_cur.execute.assert_called_with("SELECT pg_try_advisory_lock(%s);", (DISCORD_GATEWAY_ADVISORY_LOCK_ID,))

        # Release lock on shutdown
        release_gateway_advisory_lock(conn)
        mock_cur.execute.assert_called_with("SELECT pg_advisory_unlock(%s);", (DISCORD_GATEWAY_ADVISORY_LOCK_ID,))

    # 2. Peer fails to acquire lock (another instance holds it)
    mock_cur.fetchone.return_value = (False,)
    with patch("psycopg2.connect", return_value=mock_conn), \
         patch.dict(os.environ, {"SUPABASE_DB_URL": "postgresql://test:test@localhost:5432/test"}):
        conn_peer = try_acquire_gateway_advisory_lock()
        assert conn_peer is None, "Peer must receive None and enter standby mode"


# ==============================================================================
# 3. ZERO SYNTHETIC STARTUP SEEDS IN PRODUCTION
# ==============================================================================
def test_production_startup_never_injects_seed_data(monkeypatch):
    """
    CRITICAL REAL-DATA RULE TEST:
    In production or render_free_demo mode, lifespan startup MUST NEVER call get_seed_data
    or save fixture chunks into memory repository.
    """
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("THREAD_DEPLOYMENT_MODE", "render_free_demo")
    monkeypatch.setenv("THREAD_JWT_SECRET", "cryptographically-secure-32-character-secret-abc123")
    monkeypatch.setenv("THREAD_START_GATEWAY_BOT", "false")

    with patch("app.main.get_seed_data") as mock_seeds, \
         patch("app.main.memory_repository.save_records_and_chunks") as mock_save:
        from app.main import app
        with TestClient(app) as client:
            resp = client.get("/health")
            assert resp.status_code == 200

        assert not mock_seeds.called, "Must NEVER call get_seed_data() on production startup"
        assert not mock_save.called, "Must NEVER save synthetic seeds on production startup"


# ==============================================================================
# 4. MINIMAL /health LIVENESS PROBE (ZERO INFORMATION DISCLOSURE)
# ==============================================================================
def test_health_check_minimal_liveness(monkeypatch):
    """
    CRITICAL INFORMATION DISCLOSURE TEST:
    /health must return strictly minimal status ('healthy') and NEVER leak
    environment name, CORS allowed origins, demo auth flags, or provider presence.
    """
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("THREAD_JWT_SECRET", "cryptographically-secure-32-character-secret-abc123")

    from app.main import app
    client = TestClient(app)
    resp = client.get("/health")

    assert resp.status_code == 200
    data = resp.json()
    assert data == {"status": "healthy"}
    assert "app_env" not in data
    assert "cors_origins" not in data
    assert "providers" not in data
    assert "demo_auth_enabled" not in data
