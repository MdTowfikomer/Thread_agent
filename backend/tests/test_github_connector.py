import json
import hmac
import hashlib
import uuid
import pytest
from datetime import datetime, timezone
from fastapi.testclient import TestClient

from app.main import app
from app.core.config import settings
from app.core.canonical import ChannelType, PermissionLevel, SourceType
from app.channels.github import (
    GitHubConnector,
    GitHubEvent,
    verify_github_signature,
    parse_iso_datetime
)
from app.channels.delivery import webhook_delivery_store
from app.channels.installation import github_binding_store
from app.memory.repository import memory_repository
from app.identity.service import identity_service

client = TestClient(app)

def test_github_signature_verification():
    secret = "my_webhook_secret_key_123"
    body = b'{"action": "opened", "number": 1}'
    
    # Valid HMAC-SHA256
    mac = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    valid_header = f"sha256={mac}"
    assert verify_github_signature(body, valid_header, secret) is True

    # Tampered body
    tampered_body = b'{"action": "opened", "number": 2}'
    assert verify_github_signature(tampered_body, valid_header, secret) is False

    # Invalid header format
    assert verify_github_signature(body, "invalid_format", secret) is False
    assert verify_github_signature(body, None, secret) is False

def test_github_pull_request_ingestion_with_verified_author():
    connector = GitHubConnector()
    
    # Payload from Arjun (GitHub ID: 583231)
    raw_payload = {
        "action": "opened",
        "repository": {
            "id": 1029384,
            "full_name": "gdgmcet/core-platform",
            "private": False
        },
        "pull_request": {
            "number": 42,
            "title": "feat: distributed identity and access control",
            "body": "Implements cross-channel identity mapping and provenance tracking.",
            "user": {
                "id": 583231,
                "login": "arjun-dev"
            },
            "created_at": "2026-09-14T18:00:00Z",
            "updated_at": "2026-09-14T18:00:00Z",
            "html_url": "https://github.com/gdgmcet/core-platform/pull/42",
            "additions": 150,
            "deletions": 10,
            "changed_files": 4,
            "base": {"ref": "main"},
            "head": {"ref": "feat/identity"}
        }
    }

    events = connector.parse_webhook_payload("pull_request", raw_payload, "gdg_mcet")
    assert len(events) == 1
    ev = events[0]
    assert ev.item_number == 42
    assert ev.author_id == "583231"
    assert ev.author_username == "arjun-dev"

    record, chunks, receipt = connector.ingest_event(ev)
    assert record.source_type == SourceType.GITHUB
    assert record.author == "usr_arjun"
    assert record.author_role == "organizer"
    assert len(chunks) == 1
    
    chunk = chunks[0]
    assert chunk.author == "usr_arjun"
    assert "PR #42" in chunk.title
    assert "Diff Summary: +150 -10 (4 files)" in chunk.content
    assert chunk.provenance["identity_resolution"]["is_verified"] is True
    assert chunk.provenance["identity_resolution"]["person_id"] == "usr_arjun"

def test_github_pr_review_and_comment_ingestion():
    connector = GitHubConnector()

    # Review by Priya (GitHub ID: 791245)
    review_payload = {
        "action": "submitted",
        "repository": {
            "id": 1029384,
            "full_name": "gdgmcet/core-platform",
            "private": False
        },
        "pull_request": {
            "number": 42,
            "title": "feat: distributed identity and access control"
        },
        "review": {
            "id": 998877,
            "user": {
                "id": 791245,
                "login": "priya-tech"
            },
            "body": "LGTM! The tenant boundary enforcement is mathematically sound.",
            "state": "APPROVED",
            "submitted_at": "2026-09-14T19:30:00Z",
            "html_url": "https://github.com/gdgmcet/core-platform/pull/42#pullrequestreview-998877"
        }
    }

    events = connector.parse_webhook_payload("pull_request_review", review_payload, "gdg_mcet")
    assert len(events) == 1
    ev = events[0]
    assert ev.event_type == "pull_request_review"
    assert ev.author_id == "791245"

    record, chunks, receipt = connector.ingest_event(ev)
    assert record.author == "usr_priya"
    assert "Review on PR #42 (APPROVED)" in chunks[0].title
    assert "LGTM!" in chunks[0].content

def test_github_push_commits_ingestion():
    connector = GitHubConnector()

    push_payload = {
        "ref": "refs/heads/main",
        "repository": {
            "id": 1029384,
            "full_name": "gdgmcet/core-platform",
            "private": False
        },
        "commits": [
            {
                "id": "a1b2c3d4e5f67890",
                "message": "fix: normalize sha256 migration checksums across platforms",
                "timestamp": "2026-09-14T20:00:00Z",
                "url": "https://github.com/gdgmcet/core-platform/commit/a1b2c3d4e5f67890",
                "author": {
                    "name": "Arjun Sharma",
                    "email": "arjun@gdgmcet.org",
                    "username": "arjun-dev",
                    "id": 583231
                },
                "added": ["manifest.json"],
                "removed": [],
                "modified": ["migrator.py"]
            }
        ]
    }

    events = connector.parse_webhook_payload("push", push_payload, "gdg_mcet")
    assert len(events) == 1
    ev = events[0]
    assert ev.commit_sha == "a1b2c3d4e5f67890"

    record, chunks, receipt = connector.ingest_event(ev)
    assert record.author == "usr_arjun"
    assert "Commit in gdgmcet/core-platform" in chunks[0].title
    assert "fix: normalize sha256 migration checksums" in chunks[0].content

def test_github_unmapped_user_prohibits_automatic_merge():
    """
    Even if an external user's login is 'arjun' or 'priya', if their GitHub ID is unlinked,
    they are treated as an isolated public contributor.
    """
    connector = GitHubConnector()

    unmapped_issue = {
        "action": "opened",
        "repository": {
            "id": 1029384,
            "full_name": "gdgmcet/core-platform",
            "private": False
        },
        "issue": {
            "number": 88,
            "title": "Discussion: Open source contribution guidelines",
            "body": "Here are some ideas for contributors.",
            "user": {
                "id": 9991234,  # UNMAPPED ID
                "login": "arjun_gdg"  # Spoofed / colliding handle
            },
            "created_at": "2026-09-14T21:00:00Z",
            "html_url": "https://github.com/gdgmcet/core-platform/issues/88"
        }
    }

    events = connector.parse_webhook_payload("issues", unmapped_issue, "gdg_mcet")
    record, chunks, receipt = connector.ingest_event(events[0])

    # Must NOT map to usr_arjun
    assert record.author != "usr_arjun"
    assert record.author == "ext_github_9991234"
    assert record.author_role == "contributor"
    assert chunks[0].author == "ext_github_9991234"
    assert chunks[0].provenance["identity_resolution"]["is_verified"] is False
    assert chunks[0].provenance["identity_resolution"]["is_synthetic_public"] is True

def make_github_signature(payload_bytes: bytes, secret: str) -> str:
    mac = hmac.new(secret.encode("utf-8"), payload_bytes, hashlib.sha256).hexdigest()
    return f"sha256={mac}"

def test_github_webhook_missing_secret_fails_closed(monkeypatch):
    """If GITHUB_WEBHOOK_SECRET is not configured on the server, endpoint returns 500 fail-closed."""
    monkeypatch.delenv("GITHUB_WEBHOOK_SECRET", raising=False)
    resp = client.post(
        "/api/webhooks/github",
        json={"action": "opened"},
        headers={"X-GitHub-Event": "pull_request", "X-GitHub-Delivery": "del_000"}
    )
    assert resp.status_code == 500
    assert "not configured" in resp.json()["detail"]

def test_github_webhook_missing_signature_rejected(monkeypatch):
    """With secret configured, missing X-Hub-Signature-256 returns 401."""
    monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", "test_webhook_secret_key_32_bytes_long!")
    resp = client.post(
        "/api/webhooks/github",
        json={"action": "opened"},
        headers={"X-GitHub-Event": "pull_request", "X-GitHub-Delivery": "del_001"}
    )
    assert resp.status_code == 401
    assert "Missing or invalid" in resp.json()["detail"]

def test_github_webhook_invalid_signature_rejected(monkeypatch):
    """With secret configured, tampered/invalid signature returns 401."""
    secret = "test_webhook_secret_key_32_bytes_long!"
    monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", secret)
    body = json.dumps({"action": "opened"}).encode("utf-8")
    tampered_header = "sha256=baddeadbeef000111222333444555666777888999aaabbbcccdddeeefff0001"

    resp = client.post(
        "/api/webhooks/github",
        content=body,
        headers={
            "X-GitHub-Event": "pull_request",
            "X-GitHub-Delivery": "del_002",
            "X-Hub-Signature-256": tampered_header,
            "Content-Type": "application/json"
        }
    )
    assert resp.status_code == 401

def test_github_webhook_missing_delivery_header(monkeypatch):
    """With valid signature, missing X-GitHub-Delivery returns 400."""
    secret = "test_webhook_secret_key_32_bytes_long!"
    monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", secret)
    body = json.dumps({"action": "opened"}).encode("utf-8")
    sig = make_github_signature(body, secret)

    resp = client.post(
        "/api/webhooks/github",
        content=body,
        headers={
            "X-GitHub-Event": "pull_request",
            "X-Hub-Signature-256": sig,
            "Content-Type": "application/json"
        }
    )
    assert resp.status_code == 400
    assert "Missing X-GitHub-Delivery" in resp.json()["detail"]

def test_github_webhook_unbound_repository_rejected(monkeypatch):
    """Valid signature and delivery, but repository is unbound -> 403 Forbidden."""
    secret = "test_webhook_secret_key_32_bytes_long!"
    monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", secret)
    payload = {
        "action": "opened",
        "repository": {
            "id": 9999999,
            "full_name": "malicious-org/unbound-repo",
            "private": False
        },
        "pull_request": {
            "number": 1,
            "title": "unbound pr",
            "body": "attempted injection",
            "user": {"id": 12345, "login": "external-user"},
            "created_at": "2026-09-14T22:00:00Z"
        }
    }
    body = json.dumps(payload).encode("utf-8")
    sig = make_github_signature(body, secret)

    resp = client.post(
        "/api/webhooks/github",
        content=body,
        headers={
            "X-GitHub-Event": "pull_request",
            "X-GitHub-Delivery": "del_unbound_1",
            "X-Hub-Signature-256": sig,
            "Content-Type": "application/json"
        }
    )
    assert resp.status_code == 403
    assert "not bound to any organization" in resp.json()["detail"]

def test_github_webhook_valid_ingestion_and_durable_persistence(monkeypatch):
    """
    Valid signed delivery for bound repository:
    1. Ingests PR into memory_repository transactionally.
    2. Enforces organization boundary strictly from server-owned binding.
    3. Persists record and chunks to repository.
    """
    secret = "test_webhook_secret_key_32_bytes_long!"
    monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", secret)
    webhook_delivery_store.clear()

    payload = {
        "action": "opened",
        "repository": {
            "id": 1029384,
            "full_name": "gdgmcet/core-platform",
            "private": False
        },
        "pull_request": {
            "number": 55,
            "title": "feat: production webhook connector",
            "body": "End-to-end integration verified.",
            "user": {
                "id": 583231,
                "login": "arjun-dev"
            },
            "created_at": "2026-09-14T22:00:00Z",
            "html_url": "https://github.com/gdgmcet/core-platform/pull/55"
        }
    }
    body = json.dumps(payload).encode("utf-8")
    sig = make_github_signature(body, secret)
    delivery_id = f"del_valid_{uuid.uuid4().hex[:12]}"

    resp = client.post(
        "/api/webhooks/github",
        content=body,
        headers={
            "X-GitHub-Event": "pull_request",
            "X-GitHub-Delivery": delivery_id,
            "X-Hub-Signature-256": sig,
            "Content-Type": "application/json"
        }
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ingested"
    assert data["event_type"] == "pull_request"
    assert data["organization_id"] == "gdg_mcet"
    assert data["delivery_id"] == delivery_id
    assert data["records_count"] == 1
    assert data["chunks_count"] == 1

    # Verify durable persistence in memory_repository
    record_id = data["record_ids"][0]
    rec = memory_repository.get_record(record_id)
    assert rec is not None
    assert rec.organization_id == "gdg_mcet"
    assert rec.author == "usr_arjun"

    chunks = memory_repository.get_chunks_for_organization("gdg_mcet")
    matching_chunk = next((c for c in chunks if c.id in data["chunk_ids"]), None)
    assert matching_chunk is not None
    assert matching_chunk.source_record_id == record_id
    assert matching_chunk.author == "usr_arjun"

def test_github_webhook_replay_protection_deduplication(monkeypatch):
    """
    Re-submitting the exact same X-GitHub-Delivery must be detected as a duplicate.
    Returns 200 with status="duplicate" and 0 records/chunks created.
    """
    secret = "test_webhook_secret_key_32_bytes_long!"
    monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", secret)
    webhook_delivery_store.clear()

    payload = {
        "action": "opened",
        "repository": {
            "id": 1029384,
            "full_name": "gdgmcet/core-platform",
            "private": False
        },
        "pull_request": {
            "number": 56,
            "title": "feat: replay check",
            "body": "Checking deduplication.",
            "user": {"id": 583231, "login": "arjun-dev"},
            "created_at": "2026-09-14T22:30:00Z",
            "html_url": "https://github.com/gdgmcet/core-platform/pull/56"
        }
    }
    body = json.dumps(payload).encode("utf-8")
    sig = make_github_signature(body, secret)
    delivery_id = f"del_replay_{uuid.uuid4().hex[:12]}"

    # First delivery: ingested
    resp1 = client.post(
        "/api/webhooks/github",
        content=body,
        headers={
            "X-GitHub-Event": "pull_request",
            "X-GitHub-Delivery": delivery_id,
            "X-Hub-Signature-256": sig,
            "Content-Type": "application/json"
        }
    )
    assert resp1.status_code == 200
    assert resp1.json()["status"] == "ingested"
    assert resp1.json()["records_count"] == 1

    # Second delivery (replay): duplicate
    resp2 = client.post(
        "/api/webhooks/github",
        content=body,
        headers={
            "X-GitHub-Event": "pull_request",
            "X-GitHub-Delivery": delivery_id,
            "X-Hub-Signature-256": sig,
            "Content-Type": "application/json"
        }
    )
    assert resp2.status_code == 200
    data2 = resp2.json()
    assert data2["status"] == "duplicate"
    assert data2["records_count"] == 0
    assert data2["chunks_count"] == 0
    assert "already processed" in data2["message"]

def test_github_webhook_caller_cannot_override_organization(monkeypatch):
    """
    Even if caller passes ?organization_id=foreign_tenant in URL,
    the server-owned repository binding strictly dictates the organization (gdg_mcet).
    """
    secret = "test_webhook_secret_key_32_bytes_long!"
    monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", secret)
    webhook_delivery_store.clear()

    payload = {
        "action": "opened",
        "repository": {
            "id": 1029384,
            "full_name": "gdgmcet/core-platform",
            "private": False
        },
        "pull_request": {
            "number": 57,
            "title": "feat: tenant isolation test",
            "body": "Checking URL query param override is ignored.",
            "user": {"id": 583231, "login": "arjun-dev"},
            "created_at": "2026-09-14T23:00:00Z",
            "html_url": "https://github.com/gdgmcet/core-platform/pull/57"
        }
    }
    body = json.dumps(payload).encode("utf-8")
    sig = make_github_signature(body, secret)
    delivery_id = f"del_tenant_override_{uuid.uuid4().hex[:12]}"

    resp = client.post(
        "/api/webhooks/github?organization_id=foreign_tenant_hack",
        content=body,
        headers={
            "X-GitHub-Event": "pull_request",
            "X-GitHub-Delivery": delivery_id,
            "X-Hub-Signature-256": sig,
            "Content-Type": "application/json"
        }
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ingested"
    assert data["organization_id"] == "gdg_mcet"  # NOT foreign_tenant_hack
    rec = memory_repository.get_record(data["record_ids"][0])
    assert rec.organization_id == "gdg_mcet"

def test_github_webhook_transient_failure_allows_retry_without_event_loss(monkeypatch):
    """
    P0 Verification:
    If parsing or memory persistence fails, delivery status is marked as 'failed',
    and GitHub retries with the SAME delivery ID are allowed and succeed without being dropped as 'duplicate'.
    """
    secret = "test_webhook_secret_key_32_bytes_long!"
    monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", secret)
    webhook_delivery_store.clear()

    payload = {
        "action": "opened",
        "repository": {
            "id": 1029384,
            "full_name": "gdgmcet/core-platform",
            "private": False
        },
        "pull_request": {
            "number": 99,
            "title": "feat: transient failure recovery",
            "body": "Checking retry behavior.",
            "user": {"id": 583231, "login": "arjun-dev"},
            "created_at": "2026-09-14T23:30:00Z",
            "html_url": "https://github.com/gdgmcet/core-platform/pull/99"
        }
    }
    body = json.dumps(payload).encode("utf-8")
    sig = make_github_signature(body, secret)
    delivery_id = f"del_retry_test_{uuid.uuid4().hex[:12]}"

    # Attempt 1: Simulate persistence failure
    def failing_persist(record, chunks):
        return False, 0

    monkeypatch.setattr(memory_repository, "persist_record_and_chunks", failing_persist)

    resp1 = client.post(
        "/api/webhooks/github",
        content=body,
        headers={
            "X-GitHub-Event": "pull_request",
            "X-GitHub-Delivery": delivery_id,
            "X-Hub-Signature-256": sig,
            "Content-Type": "application/json"
        }
    )
    assert resp1.status_code == 500
    assert webhook_delivery_store.get_delivery_status(delivery_id) == "failed"

    # Attempt 2: GitHub retries with the exact same delivery ID and normal persistence
    monkeypatch.undo()
    monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", secret)

    resp2 = client.post(
        "/api/webhooks/github",
        content=body,
        headers={
            "X-GitHub-Event": "pull_request",
            "X-GitHub-Delivery": delivery_id,
            "X-Hub-Signature-256": sig,
            "Content-Type": "application/json"
        }
    )
    assert resp2.status_code == 200
    data2 = resp2.json()
    assert data2["status"] == "ingested"  # NOT duplicate!
    assert data2["records_count"] == 1
    assert webhook_delivery_store.get_delivery_status(delivery_id) == "completed"

def test_github_webhook_malformed_supported_event_returns_500_and_succeeds_on_retry(monkeypatch):
    """
    P1 Verification:
    A malformed payload for a supported event must return 500 (non-2xx) so GitHub retries.
    When the fault is corrected, retrying with the SAME delivery ID must succeed.
    """
    secret = "test_webhook_secret_key_32_bytes_long!"
    monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", secret)
    webhook_delivery_store.clear()

    # Malformed payload: invalid timestamp triggers ValueError in parse_iso_datetime
    bad_payload = {
        "action": "opened",
        "repository": {
            "id": 1029384,
            "full_name": "gdgmcet/core-platform",
            "private": False
        },
        "pull_request": {
            "number": 101,
            "title": "feat: malformed parse check",
            "body": "Checking retry on parse error.",
            "user": {"id": 583231, "login": "arjun-dev"},
            "created_at": "this-is-not-a-valid-timestamp"  # Corrupted!
        }
    }
    bad_body = json.dumps(bad_payload).encode("utf-8")
    delivery_id = f"del_parse_err_{uuid.uuid4().hex[:12]}"

    # Attempt 1: Malformed payload must return non-2xx (500)
    resp1 = client.post(
        "/api/webhooks/github",
        content=bad_body,
        headers={
            "X-GitHub-Event": "pull_request",
            "X-GitHub-Delivery": delivery_id,
            "X-Hub-Signature-256": make_github_signature(bad_body, secret),
            "Content-Type": "application/json"
        }
    )
    assert resp1.status_code == 500
    assert "Malformed or unparseable payload" in resp1.json()["detail"]
    assert webhook_delivery_store.get_delivery_status(delivery_id) == "failed"

    # Attempt 2: Fault removed, GitHub retries with the SAME delivery ID
    fixed_payload = dict(bad_payload)
    fixed_payload["pull_request"] = dict(bad_payload["pull_request"])
    fixed_payload["pull_request"]["created_at"] = "2026-09-15T00:00:00Z"
    fixed_body = json.dumps(fixed_payload).encode("utf-8")

    resp2 = client.post(
        "/api/webhooks/github",
        content=fixed_body,
        headers={
            "X-GitHub-Event": "pull_request",
            "X-GitHub-Delivery": delivery_id,
            "X-Hub-Signature-256": make_github_signature(fixed_body, secret),
            "Content-Type": "application/json"
        }
    )
    assert resp2.status_code == 200
    data2 = resp2.json()
    assert data2["status"] == "ingested"
    assert data2["records_count"] == 1
    assert webhook_delivery_store.get_delivery_status(delivery_id) == "completed"

def test_github_webhook_unsupported_event_returns_200_ignored_and_completed(monkeypatch):
    """
    Intentionally unsupported events (e.g. 'ping', 'watch', 'star') must be marked
    'completed' and return 200 ignored so GitHub does not retry.
    """
    secret = "test_webhook_secret_key_32_bytes_long!"
    monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", secret)
    webhook_delivery_store.clear()

    payload = {
        "zen": "Non-blocking is better than blocking.",
        "hook_id": 123456,
        "repository": {
            "id": 1029384,
            "full_name": "gdgmcet/core-platform",
            "private": False
        }
    }
    body = json.dumps(payload).encode("utf-8")
    delivery_id = f"del_unsupported_{uuid.uuid4().hex[:12]}"

    resp = client.post(
        "/api/webhooks/github",
        content=body,
        headers={
            "X-GitHub-Event": "ping",  # Unsupported event
            "X-GitHub-Delivery": delivery_id,
            "X-Hub-Signature-256": make_github_signature(body, secret),
            "Content-Type": "application/json"
        }
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ignored"
    assert "intentionally ignored" in data["message"]
    assert webhook_delivery_store.get_delivery_status(delivery_id) == "completed"

def test_github_webhook_delivery_ledger_database_failure_fails_closed(monkeypatch):
    """
    P1 Verification:
    If the delivery ledger database operation fails, the request fails closed with 500
    so GitHub retries later; deliveries are never accepted without durable recording.
    """
    secret = "test_webhook_secret_key_32_bytes_long!"
    monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", secret)

    from app.channels.delivery import DeliveryLedgerError
    def failing_claim(*args, **kwargs):
        raise DeliveryLedgerError("Database connection dropped.")

    monkeypatch.setattr(webhook_delivery_store, "claim_delivery", failing_claim)

    payload = {
        "action": "opened",
        "repository": {"id": 1029384, "full_name": "gdgmcet/core-platform"}
    }
    body = json.dumps(payload).encode("utf-8")

    resp = client.post(
        "/api/webhooks/github",
        content=body,
        headers={
            "X-GitHub-Event": "pull_request",
            "X-GitHub-Delivery": "del_db_fail",
            "X-Hub-Signature-256": make_github_signature(body, secret),
            "Content-Type": "application/json"
        }
    )
    assert resp.status_code == 500
    assert "Delivery ledger unavailable" in resp.json()["detail"]

def test_privileged_identity_link_creation_fails_closed_on_db_error(monkeypatch):
    """
    P2 Verification:
    If durable database persistence fails, privileged link creation must fail closed.
    In-memory cache must not grant permissions without durable recording.
    """
    from app.identity.service import CrossChannelIdentityService, IdentityPersistenceError, LinkVerificationType
    service = CrossChannelIdentityService()

    def failing_db_persist(link, *args, **kwargs):
        raise RuntimeError("Postgres connection lost during link insert.")

    monkeypatch.setattr(service, "_persist_link_to_db", failing_db_persist)

    with pytest.raises(IdentityPersistenceError):
        service.link_account(
            organization_id="gdg_mcet",
            person_id="usr_arjun",
            channel_type=ChannelType.GITHUB,
            account_id="999888777",
            username="arjun-new-account",
            link_type=LinkVerificationType.ORGANIZER_MANUAL,
            confidence=1.0,
            evidence={"verifier": "admin"}
        )

    # In-memory mapping must NOT have been updated
    key = "gdg_mcet:github:999888777"
    assert key not in service._account_links
