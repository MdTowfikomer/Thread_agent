import hashlib
import hmac
import json
import os
import time

import pytest
from fastapi.testclient import TestClient

os.environ["APP_ENV"] = "production"
os.environ["THREAD_JWT_SECRET"] = "test-secret-cryptographically-secure-32-chars-long-abc12345"
os.environ["THREAD_ALLOW_OFFLINE_LEDGER"] = "1"
os.environ["THREAD_ALLOW_OFFLINE_BINDINGS"] = "1"
os.environ["THREAD_FORCE_DETERMINISTIC_EMBEDDINGS"] = "1"
os.environ["SLACK_SIGNING_SECRET"] = "test-slack-signing-secret"

from app.main import app
from app.channels.delivery import webhook_delivery_store
from app.channels.installation import slack_binding_store
from app.channels.policy import channel_policy_store
from app.core.canonical import ChannelType, PermissionLevel
from app.memory.repository import memory_repository
from app.memory.store import memory_store


client = TestClient(app)
SECRET = "test-slack-signing-secret"
TEAM = "T_TEST"
CHANNEL = "C_TEST"


def signed(payload, timestamp=None):
    body = json.dumps(payload, separators=(",", ":")).encode()
    ts = str(timestamp or int(time.time()))
    base = f"v0:{ts}:{body.decode()}".encode()
    signature = "v0=" + hmac.new(SECRET.encode(), base, hashlib.sha256).hexdigest()
    return body, {"X-Slack-Request-Timestamp": ts, "X-Slack-Signature": signature}


def message_payload(event_id="Ev_test", **event_overrides):
    event = {
        "type": "message",
        "channel": CHANNEL,
        "user": "U_UNMAPPED",
        "ts": "1726435200.000100",
        "text": "Slack connector test",
    }
    event.update(event_overrides)
    return {"type": "event_callback", "event_id": event_id, "team_id": TEAM, "event": event}


@pytest.fixture(autouse=True)
def clean_stores():
    memory_store.clear()
    memory_store.force_deterministic = True
    webhook_delivery_store.clear()
    slack_binding_store.clear()
    slack_binding_store.register_binding(TEAM, "gdg_mcet", metadata={"channel_ids": [CHANNEL]})
    channel_policy_store.clear()


def post(payload, timestamp=None):
    body, headers = signed(payload, timestamp)
    return client.post("/api/webhooks/slack", content=body, headers=headers)


def test_signature_freshness_is_required():
    response = post(message_payload(), timestamp=int(time.time()) - 301)
    assert response.status_code == 401


def test_url_verification_returns_challenge():
    response = post({"type": "url_verification", "challenge": "challenge-value"})
    assert response.status_code == 200
    assert response.json() == {"challenge": "challenge-value"}


def test_unbound_workspace_or_channel_is_rejected():
    payload = message_payload()
    payload["team_id"] = "T_FOREIGN"
    response = post(payload)
    assert response.status_code == 403

    slack_binding_store.register_binding("T_OTHER", "gdg_mcet", metadata={"channel_ids": ["C_OTHER"]})
    payload = message_payload(event_id="Ev_other")
    payload["team_id"] = "T_OTHER"
    response = post(payload)
    assert response.status_code == 403


def test_replay_is_deduplicated():
    payload = message_payload()
    assert post(payload).json()["status"] == "ingested"
    assert post(payload).json()["status"] == "duplicate"


def test_bot_message_is_ignored():
    response = post(message_payload(event_id="Ev_bot", bot_id="B123"))
    assert response.status_code == 200
    assert response.json()["status"] == "ignored"
    assert not memory_store.get_chunks_for_organization("gdg_mcet")


def test_unmapped_author_in_internal_channel_is_quarantined():
    channel_policy_store.register_policy(
        organization_id="gdg_mcet",
        channel_type=ChannelType.SLACK,
        channel_id=CHANNEL,
        permission_scope=PermissionLevel.INTERNAL_CORE,
    )
    response = post(message_payload(event_id="Ev_internal"))
    assert response.status_code == 200
    chunk = memory_store.get_chunks_for_organization("gdg_mcet")[0]
    assert chunk.permission == PermissionLevel.PENDING_REVIEW


def test_failed_persistence_can_retry(monkeypatch):
    original = memory_repository.persist_record_and_chunks
    calls = {"count": 0}

    def fail_once(record, chunks):
        calls["count"] += 1
        if calls["count"] == 1:
            raise RuntimeError("temporary failure")
        return original(record, chunks)

    monkeypatch.setattr(memory_repository, "persist_record_and_chunks", fail_once)
    payload = message_payload(event_id="Ev_retry")
    assert post(payload).status_code == 500
    assert post(payload).json()["status"] == "ingested"


def test_app_mention_response_and_bot_stripping(monkeypatch):
    from app.channels.outbound import channel_message_delivery_service

    send_calls = []

    def mock_send_message(principal, platform, destination_id, query, idempotency_key=None, **kwargs):
        send_calls.append({
            "principal": principal,
            "platform": platform,
            "destination_id": destination_id,
            "query": query,
            "idempotency_key": idempotency_key,
        })
        return {
            "status": "sent",
            "delivery_id": idempotency_key,
            "provider_response_id": "1726435201.999999",
            "retrieval_receipt_id": "rcpt_mock",
            "citations": [],
            "destination": {"team_id": TEAM, "channel_id": CHANNEL},
        }

    monkeypatch.setattr(channel_message_delivery_service, "send_message", mock_send_message)

    payload = {
        "type": "event_callback",
        "event_id": "Ev_mention_1",
        "team_id": TEAM,
        "authorizations": [{"user_id": "U_BOT_123"}],
        "event": {
            "type": "app_mention",
            "channel": CHANNEL,
            "user": "U_STUDENT",
            "user_name": "student_user",
            "ts": "1726435200.000200",
            "text": "<@U_BOT_123> what are the community hackathon dates?",
        }
    }

    res = post(payload)
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "responded"
    assert len(send_calls) == 1
    # Check that bot mention was cleanly stripped from query
    assert send_calls[0]["query"] == "what are the community hackathon dates?"
    assert send_calls[0]["destination_id"] == CHANNEL

    # Verify message was also ingested
    chunks = memory_store.get_chunks_for_organization("gdg_mcet")
    assert len(chunks) == 1

    # Retry of the same app_mention event should return duplicate without re-sending
    retry_res = post(payload)
    assert retry_res.status_code == 200
    assert retry_res.json()["status"] == "duplicate"
    assert len(send_calls) == 1


def test_canonical_deduplication_between_message_and_app_mention(monkeypatch):
    from app.channels.outbound import channel_message_delivery_service

    monkeypatch.setattr(
        channel_message_delivery_service,
        "send_message",
        lambda *args, **kwargs: {"status": "sent", "provider_response_id": "ts_mock"}
    )

    same_ts = "1726435200.000300"

    # Step 1: message.channels event arrives first
    msg_payload = {
        "type": "event_callback",
        "event_id": "Ev_msg_300",
        "team_id": TEAM,
        "event": {
            "type": "message",
            "channel": CHANNEL,
            "user": "U_STUDENT",
            "ts": same_ts,
            "text": "<@U_BOT_123> what is the schedule?",
        }
    }
    r1 = post(msg_payload)
    assert r1.status_code == 200
    assert r1.json()["status"] == "ingested"
    assert len(memory_store.get_chunks_for_organization("gdg_mcet")) == 1

    # Step 2: app_mention event arrives for the SAME message (same workspace + channel + ts)
    mention_payload = {
        "type": "event_callback",
        "event_id": "Ev_mention_300",  # Different Slack event ID!
        "team_id": TEAM,
        "authorizations": [{"user_id": "U_BOT_123"}],
        "event": {
            "type": "app_mention",
            "channel": CHANNEL,
            "user": "U_STUDENT",
            "ts": same_ts,  # Canonical ts
            "text": "<@U_BOT_123> what is the schedule?",
        }
    }
    r2 = post(mention_payload)
    assert r2.status_code == 200
    assert r2.json()["status"] == "responded"

    # Chunk count must still be 1 (NOT duplicated)!
    assert len(memory_store.get_chunks_for_organization("gdg_mcet")) == 1


def test_bot_app_mention_is_ignored():
    payload = {
        "type": "event_callback",
        "event_id": "Ev_bot_mention",
        "team_id": TEAM,
        "event": {
            "type": "app_mention",
            "channel": CHANNEL,
            "user": "U_BOT_123",
            "bot_id": "B_SOME_BOT",
            "ts": "1726435200.000400",
            "text": "<@U_BOT_123> self mention",
        }
    }
    res = post(payload)
    assert res.status_code == 200
    assert res.json()["status"] == "ignored"
    assert len(memory_store.get_chunks_for_organization("gdg_mcet")) == 0

