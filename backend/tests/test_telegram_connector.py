import os
import json
import pytest
from datetime import datetime, timezone
from fastapi.testclient import TestClient

# FORCE OFFLINE DETERMINISTIC EMBEDDINGS & SYNTHESIS FOR FAST, DETERMINISTIC TESTS
os.environ["THREAD_FORCE_DETERMINISTIC_EMBEDDINGS"] = "1"
os.environ["THREAD_FORCE_DETERMINISTIC_SYNTHESIS"] = "1"
os.environ["APP_ENV"] = "production"
os.environ["THREAD_DEMO_AUTH_ENABLED"] = "false"
os.environ["THREAD_ALLOW_GUEST_MODE"] = "false"
os.environ["THREAD_JWT_SECRET"] = "test-secret-cryptographically-secure-32-chars-long-abc12345"
os.environ["THREAD_TELEGRAM_WEBHOOK_SECRET"] = "test-tg-secret-xyz-987"
os.environ["THREAD_ALLOW_OFFLINE_LEDGER"] = "1"
os.environ["THREAD_ALLOW_OFFLINE_BINDINGS"] = "1"

from app.main import app
from app.core.config import settings
from app.core.canonical import ChannelType, PermissionLevel, SourceType, LinkVerificationType
from app.channels.installation import telegram_binding_store
from app.channels.delivery import webhook_delivery_store
from app.channels.policy import channel_policy_store
from app.memory.store import memory_store
from app.identity.service import identity_service

client = TestClient(app)

TEST_SECRET = "test-tg-secret-xyz-987"
BOUND_CHAT_ID = "-1001234567890"  # Pre-registered in telegram_binding_store for gdg_mcet


@pytest.fixture(autouse=True)
def clean_test_stores():
    """Reset stores before each test."""
    memory_store.clear()
    memory_store.force_deterministic = True
    webhook_delivery_store._deliveries.clear()
    telegram_binding_store.clear()
    channel_policy_store.clear()
    # Re-register test chat
    telegram_binding_store.register_binding(
        chat_id=BOUND_CHAT_ID,
        organization_id="gdg_mcet",
        chat_title="GDG MCET Core Team Telegram",
        chat_type="supergroup"
    )
    channel_policy_store.register_policy(
        organization_id="gdg_mcet",
        channel_type=ChannelType.TELEGRAM,
        channel_id=BOUND_CHAT_ID,
        permission_scope=PermissionLevel.INTERNAL_CORE,
    )


def test_telegram_webhook_rejects_missing_or_invalid_secret_token():
    payload = {
        "update_id": 10001,
        "message": {
            "message_id": 1,
            "chat": {"id": int(BOUND_CHAT_ID), "title": "GDG MCET Core Team Telegram"},
            "from": {"id": 998877, "username": "towfik", "first_name": "Towfik"},
            "text": "Hello Telegram!"
        }
    }

    # Case A: Missing header
    res_no_header = client.post("/api/webhooks/telegram", json=payload)
    assert res_no_header.status_code == 401
    assert "Invalid or missing Telegram webhook secret token" in res_no_header.json()["detail"]

    # Case B: Wrong secret
    res_bad_secret = client.post(
        "/api/webhooks/telegram",
        json=payload,
        headers={"X-Telegram-Bot-Api-Secret-Token": "wrong-secret"}
    )
    assert res_bad_secret.status_code == 401


def test_telegram_webhook_rejects_unbound_foreign_chat():
    payload = {
        "update_id": 10002,
        "message": {
            "message_id": 2,
            "chat": {"id": -999888777, "title": "Rogue Group"},
            "from": {"id": 12345, "username": "attacker"},
            "text": "Attempted injection"
        }
    }
    res = client.post(
        "/api/webhooks/telegram",
        json=payload,
        headers={"X-Telegram-Bot-Api-Secret-Token": TEST_SECRET}
    )
    assert res.status_code == 403
    assert "not bound to any organization" in res.json()["detail"]


def test_telegram_webhook_ignores_non_message_or_non_text_updates():
    # Case A: Update without message (e.g. callback_query)
    callback_payload = {
        "update_id": 10003,
        "callback_query": {"id": "cb_01", "data": "btn_click"}
    }
    res_cb = client.post(
        "/api/webhooks/telegram",
        json=callback_payload,
        headers={"X-Telegram-Bot-Api-Secret-Token": TEST_SECRET}
    )
    assert res_cb.status_code == 200
    assert res_cb.json()["status"] == "ignored"

    # Case B: Message without text (e.g. photo / sticker)
    photo_payload = {
        "update_id": 10004,
        "message": {
            "message_id": 3,
            "chat": {"id": int(BOUND_CHAT_ID), "title": "GDG MCET Core Team Telegram"},
            "from": {"id": 998877, "username": "towfik"},
            "photo": [{"file_id": "file_123"}]
        }
    }
    res_photo = client.post(
        "/api/webhooks/telegram",
        json=photo_payload,
        headers={"X-Telegram-Bot-Api-Secret-Token": TEST_SECRET}
    )
    assert res_photo.status_code == 200
    assert res_photo.json()["status"] == "ignored"
    assert "Only text messages are supported" in res_photo.json()["message"]


def test_telegram_webhook_successful_text_ingestion_and_provenance():
    payload = {
        "update_id": 20001,
        "message": {
            "message_id": 42,
            "chat": {
                "id": int(BOUND_CHAT_ID),
                "title": "GDG MCET Core Team Telegram",
                "type": "supergroup"
            },
            "from": {
                "id": 554433,
                "username": "towfik_telegram",
                "first_name": "Towfik",
                "last_name": "Omer"
            },
            "date": 1726435200,
            "text": "The Telegram connector is live with full provenance tracking!"
        }
    }

    res = client.post(
        "/api/webhooks/telegram",
        json=payload,
        headers={"X-Telegram-Bot-Api-Secret-Token": TEST_SECRET}
    )
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "ingested"
    assert body["channel"] == "telegram"
    assert body["organization_id"] == "gdg_mcet"
    assert body["chat_id"] == BOUND_CHAT_ID
    assert body["message_id"] == 42

    # Verify memory store records
    rec = memory_store._records.get(body["record_id"])
    assert rec is not None
    assert rec.source_type == SourceType.TELEGRAM
    assert rec.external_id == f"{BOUND_CHAT_ID}:42"
    assert "https://t.me/c/1234567890/42" in rec.source_uri

    # Verify chunk
    chunks = memory_store.get_chunks_for_organization("gdg_mcet")
    matching_chunks = [c for c in chunks if c.id in body["chunk_ids"]]
    assert len(matching_chunks) == 1
    chk = matching_chunks[0]
    assert chk.source_type == SourceType.TELEGRAM
    assert chk.content == "The Telegram connector is live with full provenance tracking!"
    assert chk.author == "Towfik Omer"
    assert "telegram" in chk.tags
    assert chk.provenance["chat_id"] == BOUND_CHAT_ID
    assert chk.provenance["message_id"] == 42
    assert chk.provenance["source_uri"] == rec.source_uri


def test_telegram_webhook_replay_protection_deduplicates_updates():
    payload = {
        "update_id": 30001,
        "message": {
            "message_id": 99,
            "date": 1726435200,
            "chat": {"id": int(BOUND_CHAT_ID), "title": "GDG MCET Core Team Telegram"},
            "from": {"id": 112233, "username": "alice"},
            "text": "Replay protection test message"
        }
    }

    # First delivery: ingested
    res1 = client.post(
        "/api/webhooks/telegram",
        json=payload,
        headers={"X-Telegram-Bot-Api-Secret-Token": TEST_SECRET}
    )
    assert res1.status_code == 200
    assert res1.json()["status"] == "ingested"

    # Second delivery (exact same update_id): returns duplicate
    res2 = client.post(
        "/api/webhooks/telegram",
        json=payload,
        headers={"X-Telegram-Bot-Api-Secret-Token": TEST_SECRET}
    )
    assert res2.status_code == 200
    assert res2.json()["status"] == "duplicate"
    assert "already processed" in res2.json()["message"]


def test_telegram_author_identity_link_and_acl_enforcement():
    # Link Telegram ID 776655 to usr_arjun (INTERNAL_CORE)
    identity_service.link_account(
        organization_id="gdg_mcet",
        person_id="usr_arjun",
        channel_type=ChannelType.TELEGRAM,
        account_id="776655",
        username="arjun_tg",
        display_name="Arjun Sharma",
        link_type=LinkVerificationType.ORGANIZER_MANUAL,
        confidence=1.0,
        evidence={"verified_by": "bootstrap"}
    )

    payload_arjun = {
        "update_id": 40001,
        "message": {
            "message_id": 101,
            "date": 1726435200,
            "chat": {"id": int(BOUND_CHAT_ID), "title": "GDG MCET Core Team Telegram"},
            "from": {"id": 776655, "username": "arjun_tg", "first_name": "Arjun"},
            "text": "Organizer confidential note: Budget details for workshop."
        }
    }

    res = client.post(
        "/api/webhooks/telegram",
        json=payload_arjun,
        headers={"X-Telegram-Bot-Api-Secret-Token": TEST_SECRET}
    )
    assert res.status_code == 200
    chunk_id = res.json()["chunk_ids"][0]

    chunks = memory_store.get_chunks_for_organization("gdg_mcet")
    chunk = next(c for c in chunks if c.id == chunk_id)
    assert chunk.permission == PermissionLevel.INTERNAL_CORE
    assert chunk.author == "Arjun Sharma"
    assert chunk.provenance["internal_person_id"] == "usr_arjun"
    assert chunk.provenance["is_verified"] is True
