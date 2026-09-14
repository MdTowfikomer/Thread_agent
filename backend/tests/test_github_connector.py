import json
import hmac
import hashlib
import pytest
from datetime import datetime, timezone
from fastapi.testclient import TestClient

from app.main import app
from app.core.canonical import ChannelType, PermissionLevel, SourceType
from app.channels.github import (
    GitHubConnector,
    GitHubEvent,
    verify_github_signature,
    parse_iso_datetime
)
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

def test_github_webhook_endpoint_live():
    """
    End-to-end FastAPI test of POST /api/webhooks/github.
    """
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

    resp = client.post(
        "/api/webhooks/github?organization_id=gdg_mcet",
        json=payload,
        headers={
            "X-GitHub-Event": "pull_request",
            "Content-Type": "application/json"
        }
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ingested"
    assert data["event_type"] == "pull_request"
    assert data["records_count"] == 1
    assert data["chunks_count"] == 1
