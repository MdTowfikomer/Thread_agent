import os
import json
import time
import inspect
import pytest
from datetime import datetime, timezone
from typing import Optional
from pathlib import Path
from pydantic import ValidationError
from fastapi.testclient import TestClient
from cryptography.hazmat.primitives.asymmetric import ed25519

# FORCE OFFLINE DETERMINISTIC EMBEDDINGS & SYNTHESIS FOR FAST, LOCAL, DETERMINISTIC TESTS
os.environ["THREAD_FORCE_DETERMINISTIC_EMBEDDINGS"] = "1"
os.environ["THREAD_FORCE_DETERMINISTIC_SYNTHESIS"] = "1"
os.environ["APP_ENV"] = "production"
os.environ["THREAD_DEMO_AUTH_ENABLED"] = "false"
os.environ["THREAD_ALLOW_GUEST_MODE"] = "false"
os.environ["THREAD_JWT_SECRET"] = "test-secret-cryptographically-secure-32-chars-long-abc12345"

# Cryptographic Ed25519 keypair for authenticated Discord webhook testing
TEST_PRIVATE_KEY = ed25519.Ed25519PrivateKey.generate()
TEST_PUBLIC_KEY_HEX = TEST_PRIVATE_KEY.public_key().public_bytes_raw().hex()
os.environ["THREAD_DISCORD_PUBLIC_KEY"] = TEST_PUBLIC_KEY_HEX

from app.core.config import settings
from app.core.canonical import (
    ChannelType,
    ChannelMessage,
    IdentityMapping,
    PermissionLevel,
    SourceType,
    ChannelPolicy,
    IngestionTrustMode,
    ImportApprovalRecord
)
from app.channels.base import ChannelAdapter
from app.core.membership import membership_store
from app.core.auth import create_access_token
from app.memory.store import memory_store
from app.channels.discord import (
    DiscordExportAdapter,
    trusted_discord_connector_service,
    parse_iso_datetime
)
from app.channels.policy import channel_policy_store
from app.channels.approval import ApprovalStore, approval_store
from app.channels.installation import guild_installation_store
from app.channels.gateway import discord_gateway_bot
from app.api.webhooks import clear_processed_interactions
from app.data.seeds import get_seed_data
from app.main import app

client = TestClient(app)

def send_signed_discord_webhook(
    payload: dict,
    timestamp: Optional[str] = None,
    signature_override: Optional[str] = None,
    omit_signature: bool = False,
    omit_timestamp: bool = False
):
    """Helper to dispatch authenticated Discord webhooks signed with Ed25519."""
    if timestamp is None:
        timestamp = str(int(time.time()))

    body_bytes = json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if not omit_timestamp:
        headers["X-Signature-Timestamp"] = timestamp
    if not omit_signature:
        if signature_override is not None:
            headers["X-Signature-Ed25519"] = signature_override
        else:
            headers["X-Signature-Ed25519"] = TEST_PRIVATE_KEY.sign(timestamp.encode("utf-8") + body_bytes).hex()
    return client.post("/api/webhooks/discord", content=body_bytes, headers=headers)

@pytest.fixture(autouse=True)
def setup_channel_test_env():
    """Ensure clean store, membership, approvals, and policies populated with verified seed data."""
    memory_store.clear()
    memory_store.force_deterministic = True
    channel_policy_store.clear()
    approval_store.clear()
    guild_installation_store.clear()
    clear_processed_interactions()
    membership_store.reset()

    records, chunks, receipts = get_seed_data(organization_id="gdg_mcet")
    for r in records:
        memory_store.add_record(r)
    memory_store.add_chunks(chunks)
    return records, chunks, receipts

# =====================================================================
# CHANNEL ADAPTER CORE v0 TESTS
# =====================================================================

# 1. Discord messages enter the same core memory store, not a separate store
def test_discord_messages_enter_same_core_memory_store():
    initial_chunks = len(memory_store.get_chunks_for_organization("gdg_mcet"))

    adapter = DiscordExportAdapter()
    export_data = {
        "guild": {"id": "11223344", "name": "GDG MCET Discord"},
        "channel": {"id": "55667788", "name": "general"},
        "messages": [
            {
                "id": "msg_discord_core_01",
                "content": "Welcome to the GDG MCET Discord server! Feel free to ask questions.",
                "author": {"id": "discord_random_user_1", "name": "new_student"},
                "timestamp": "2026-03-01T10:00:00Z"
            }
        ]
    }
    records, chunks, receipt = adapter.ingest_export(export_data, organization_id="gdg_mcet")
    for r in records:
        memory_store.add_record(r)
    memory_store.add_chunks(chunks)

    # Must be in the exact same memory_store instance
    updated_chunks = memory_store.get_chunks_for_organization("gdg_mcet")
    assert len(updated_chunks) == initial_chunks + 1

    stored_chunk = memory_store.get_chunk("chk_discord_gdg_mcet_msg_discord_core_01")
    assert stored_chunk is not None
    assert stored_chunk.content == "Welcome to the GDG MCET Discord server! Feel free to ask questions."
    assert stored_chunk.source_type == SourceType.DISCORD
    assert stored_chunk.source_uri == "https://discord.com/channels/11223344/55667788/msg_discord_core_01"
    assert stored_chunk.provenance["guild_id"] == "11223344"
    assert stored_chunk.provenance["guild_name"] == "GDG MCET Discord"
    assert stored_chunk.provenance["channel_id"] == "55667788"
    assert stored_chunk.provenance["channel_name"] == "general"
    assert stored_chunk.provenance["message_id"] == "msg_discord_core_01"
    assert stored_chunk.provenance["author_external_id"] == "discord_random_user_1"

# 2. An identity mapping resolves an external Discord user to the correct internal member via Gateway
def test_identity_mapping_resolves_external_discord_user_to_internal_member():
    # Register an identity mapping for Priya: discord_priya_789 -> usr_priya
    membership_store.register_identity_mapping(
        organization_id="gdg_mcet",
        channel_type=ChannelType.DISCORD,
        external_user_id="discord_priya_789",
        internal_user_id="usr_priya",
        external_username="priya_codes"
    )

    # Live MESSAGE_CREATE event dispatched via Discord Gateway bot
    event_data = {
        "id": "msg_discord_priya_01",
        "guild_id": "11223344",
        "guild_name": "GDG MCET Discord",
        "channel_id": "99001122",
        "channel_name": "core-team",
        "content": "Updated the GenAI codelab repository link and Docker deployment configuration.",
        "author": {"id": "discord_priya_789", "username": "priya_codes", "bot": False},
        "timestamp": "2026-03-02T11:00:00Z"
    }
    result = discord_gateway_bot.handle_gateway_event("MESSAGE_CREATE", event_data)
    assert result is not None
    record, chunks, receipt = result

    assert receipt.provenance_summary["trust_mode"] == IngestionTrustMode.VERIFIED_CONNECTOR.value
    assert len(chunks) == 1
    chunk = chunks[0]

    # Verified internal resolution
    assert chunk.author == "Priya Ramesh"
    assert chunk.author_role == "Tech Lead"
    assert chunk.provenance["is_mapped"] is True
    assert chunk.provenance["internal_user_id"] == "usr_priya"
    assert chunk.provenance["author_external_id"] == "discord_priya_789"
    # Bound internal channel + mapped active lead on verified Gateway connector -> INTERNAL_CORE
    assert chunk.permission == PermissionLevel.INTERNAL_CORE

# 3. Unmapped users are public-only via Gateway
def test_unmapped_users_are_public_only():
    event_data = {
        "id": "msg_stranger_confidential",
        "guild_id": "11223344",
        "guild_name": "GDG MCET Discord",
        "channel_id": "99001122",
        "channel_name": "core-team",
        "content": "Leaked confidential sponsor tier numbers from unmapped visitor.",
        "author": {"id": "discord_stranger_9999", "username": "anonymous_guest", "bot": False},
        "timestamp": "2026-03-02T12:00:00Z",
        "metadata": {"is_internal": True, "permission": "INTERNAL_CORE"}
    }
    result = discord_gateway_bot.handle_gateway_event("MESSAGE_CREATE", event_data)
    assert result is not None
    record, chunks, receipt = result

    chunk = chunks[0]
    # Even on verified Gateway connector in a bound internal channel, unmapped user MUST be PUBLIC_COMMUNITY
    assert chunk.permission == PermissionLevel.PUBLIC_COMMUNITY
    assert chunk.provenance["is_mapped"] is False
    assert chunk.provenance["internal_user_id"] is None
    assert chunk.author_role == "Discord Contributor"

# 4. Channel-ingested records obey the same ACL retrieval rules as web queries
def test_channel_ingested_records_obey_same_acl_rules():
    export_adapter = DiscordExportAdapter()

    # 1. Ingest an INTERNAL_CORE message from mapped organizer (Arjun) via Discord Gateway bot
    event_internal = {
        "id": "msg_arjun_budget_secret",
        "guild_id": "11223344",
        "guild_name": "GDG MCET Discord",
        "channel_id": "77889900",
        "channel_name": "organizers-budget",
        "content": "Discord internal budget review: Allocated Rs. 20,000 for speaker travel grants.",
        "author": {"id": "discord_arjun_101", "username": "arjun_gdg", "bot": False},
        "timestamp": "2026-03-03T14:00:00Z"
    }
    result1 = discord_gateway_bot.handle_gateway_event("MESSAGE_CREATE", event_internal)
    assert result1 is not None
    _, chunks1, _ = result1
    assert chunks1[0].permission == PermissionLevel.INTERNAL_CORE

    # 2. Ingest a PUBLIC_COMMUNITY message from unmapped attendee via file export
    public_export = {
        "guild": {"id": "11223344", "name": "GDG MCET Discord"},
        "channel": {"id": "11112222", "name": "general-help"},
        "messages": [
            {
                "id": "msg_public_rsvp_guide",
                "content": "Discord announcement: RSVP check-in booth will open at 8:30 AM at Gate 2.",
                "author": {"id": "discord_attendee_42", "name": "mcet_student_sam"},
                "timestamp": "2026-03-03T15:00:00Z"
            }
        ]
    }
    recs2, chks2, _ = export_adapter.ingest_export(public_export, organization_id="gdg_mcet")
    for r in recs2:
        memory_store.add_record(r)
    memory_store.add_chunks(chks2)

    # Verification A: Community Member query via /api/chat
    student_token = create_access_token(user_id="usr_student_rohan", organization_id="gdg_mcet")

    # Community member queries public announcement
    res_public = client.post(
        "/api/chat",
        json={"query": "When does the RSVP check-in booth open at Gate 2?"},
        headers={"Authorization": f"Bearer {student_token}"}
    )
    assert res_public.status_code == 200
    student_citations = res_public.json()["citations"]
    assert any("Gate 2" in c["snippet"] for c in student_citations)

    # Community member queries confidential budget
    res_secret = client.post(
        "/api/chat",
        json={"query": "What is the allocated speaker travel grant budget?"},
        headers={"Authorization": f"Bearer {student_token}"}
    )
    assert res_secret.status_code == 200
    student_secret_citations = res_secret.json()["citations"]
    # Pre-retrieval ACL MUST completely exclude internal core Discord message from community member
    assert not any("Rs. 20,000" in c["snippet"] for c in student_secret_citations)
    assert not any("travel grant" in c["snippet"] for c in student_secret_citations)

    # Verification B: Lead Organizer query via /api/chat
    organizer_token = create_access_token(user_id="usr_arjun", organization_id="gdg_mcet")

    res_org = client.post(
        "/api/chat",
        json={"query": "What is the allocated speaker travel grant budget?"},
        headers={"Authorization": f"Bearer {organizer_token}"}
    )
    assert res_org.status_code == 200
    org_citations = res_org.json()["citations"]
    assert any("Rs. 20,000" in c["snippet"] for c in org_citations)

# 5. Duplicate external message IDs are idempotent
def test_duplicate_external_message_ids_are_idempotent():
    adapter = DiscordExportAdapter()

    msg_payload = {
        "guild": {"id": "11223344", "name": "GDG MCET Discord"},
        "channel": {"id": "55667788", "name": "general"},
        "messages": [
            {
                "id": "msg_discord_idempotent_01",
                "content": "Join the Discord study group channel #web-dev for study materials.",
                "author": {"id": "discord_arjun_101", "name": "arjun_gdg"},
                "timestamp": "2026-03-04T09:00:00Z"
            }
        ]
    }

    # First ingestion
    recs1, chks1, receipt1 = adapter.ingest_export(msg_payload, organization_id="gdg_mcet")
    for r in recs1:
        memory_store.add_record(r)
    memory_store.add_chunks(chks1)
    first_count = len(memory_store.get_chunks_for_organization("gdg_mcet"))

    # Second ingestion of duplicate message
    recs2, chks2, receipt2 = adapter.ingest_export(msg_payload, organization_id="gdg_mcet")
    for r in recs2:
        memory_store.add_record(r)
    memory_store.add_chunks(chks2)
    second_count = len(memory_store.get_chunks_for_organization("gdg_mcet"))

    # Store size must NOT increase; IDs are deterministic
    assert first_count == second_count
    assert chks1[0].id == chks2[0].id
    assert recs1[0].id == recs2[0].id
    assert chks1[0].id == "chk_discord_gdg_mcet_msg_discord_idempotent_01"

    # Batch with internal duplicates
    batch_with_duplicates = {
        "guild": {"id": "11223344", "name": "GDG MCET Discord"},
        "channel": {"id": "55667788", "name": "general"},
        "messages": [
            {
                "id": "msg_discord_intra_dup",
                "content": "Workshop registration deadline is Friday 11:59 PM.",
                "author": {"id": "discord_arjun_101", "name": "arjun_gdg"},
                "timestamp": "2026-03-04T10:00:00Z"
            },
            {
                "id": "msg_discord_intra_dup",  # DUPLICATE ID IN SAME BATCH
                "content": "Workshop registration deadline is Friday 11:59 PM.",
                "author": {"id": "discord_arjun_101", "name": "arjun_gdg"},
                "timestamp": "2026-03-04T10:00:00Z"
            }
        ]
    }
    recs_dup, chks_dup, receipt = adapter.ingest_export(batch_with_duplicates, organization_id="gdg_mcet")
    assert len(recs_dup) == 1
    assert len(chks_dup) == 1

# 6. P0 & P1: Quarantined internal import is assigned PENDING_REVIEW and is STRICTLY ABSENT from community retrieval
def test_quarantined_internal_import_is_pending_review_and_absent_from_community_retrieval():
    adapter = DiscordExportAdapter()

    # Manual unverified file export claiming to be from real internal channel and mapped organizer
    forged_export = {
        "guild": {"id": "11223344", "name": "GDG MCET Discord"},
        "channel": {"id": "99001122", "name": "core-team"},
        "messages": [
            {
                "id": "msg_quarantined_secret_roadmap",
                "content": "Top-secret internal roadmap: Project Titan launch date confirmed for November 17th.",
                "author": {"id": "discord_arjun_101", "name": "arjun_gdg"},
                "timestamp": "2026-03-05T09:00:00Z"
            }
        ]
    }

    recs, chks, receipt = adapter.ingest_export(forged_export, organization_id="gdg_mcet")
    for r in recs:
        memory_store.add_record(r)
    memory_store.add_chunks(chks)

    chunk = chks[0]
    import_hash = recs[0].hash

    # 1. Verify chunk was assigned non-retrievable PENDING_REVIEW (NOT PUBLIC_COMMUNITY!)
    assert chunk.permission == PermissionLevel.PENDING_REVIEW
    assert chunk.provenance["quarantined_from_internal"] is True
    assert chunk.provenance["review_status"] == "quarantined_pending_organizer_approval"

    # 2. PROVE COMMUNITY RETRIEVAL EXCLUSION:
    # A community user queries specifically for the quarantined secret roadmap
    student_token = create_access_token(user_id="usr_student_rohan", organization_id="gdg_mcet")
    res_student = client.post(
        "/api/chat",
        json={"query": "When is the launch date for Project Titan?"},
        headers={"Authorization": f"Bearer {student_token}"}
    )
    assert res_student.status_code == 200
    student_citations = res_student.json()["citations"]
    # Quarantined chunk MUST be 100% absent from community retrieval!
    assert not any("Project Titan" in c["snippet"] for c in student_citations)
    assert not any("November 17th" in c["snippet"] for c in student_citations)

    # 3. PROVE ORGANIZER RETRIEVAL EXCLUSION PRIOR TO APPROVAL:
    # Even an organizer cannot retrieve unpromoted PENDING_REVIEW records in regular chat
    organizer_token = create_access_token(user_id="usr_arjun", organization_id="gdg_mcet")
    res_org_pre = client.post(
        "/api/chat",
        json={"query": "When is the launch date for Project Titan?"},
        headers={"Authorization": f"Bearer {organizer_token}"}
    )
    assert res_org_pre.status_code == 200
    org_pre_citations = res_org_pre.json()["citations"]
    assert not any("Project Titan" in c["snippet"] for c in org_pre_citations)

    # 4. UNAUTHENTICATED OR COMMUNITY ATTEMPT TO APPROVE IS REJECTED:
    # Community member attempting to approve gets 403 Forbidden
    res_unauth_approve = client.post(
        "/api/imports/approve",
        json={"import_hash": import_hash},
        headers={"Authorization": f"Bearer {student_token}"}
    )
    assert res_unauth_approve.status_code == 403

    # 5. AUTHENTICATED PROMOTION BY ORGANIZER VIA SERVER ENDPOINT:
    res_approve = client.post(
        "/api/imports/approve",
        json={"import_hash": import_hash},
        headers={"Authorization": f"Bearer {organizer_token}"}
    )
    assert res_approve.status_code == 200
    approve_data = res_approve.json()
    assert approve_data["status"] == "success"
    assert approve_data["approved_by"] == "usr_arjun"
    assert approve_data["promoted_count"] == 1

    # 6. VERIFY POST-PROMOTION ACCESS:
    # Community member STILL CANNOT see it (it is promoted to INTERNAL_CORE)
    res_student_post = client.post(
        "/api/chat",
        json={"query": "When is the launch date for Project Titan?"},
        headers={"Authorization": f"Bearer {student_token}"}
    )
    assert not any("Project Titan" in c["snippet"] for c in res_student_post.json()["citations"])
    assert not any("November 17th" in c["snippet"] for c in res_student_post.json()["citations"])

    # Lead organizer CAN NOW RETRIEVE it as INTERNAL_CORE
    res_org_post = client.post(
        "/api/chat",
        json={"query": "When is the launch date for Project Titan?"},
        headers={"Authorization": f"Bearer {organizer_token}"}
    )
    assert res_org_post.status_code == 200
    org_post_citations = res_org_post.json()["citations"]
    assert any("Project Titan" in c["snippet"] or "November 17th" in c["snippet"] for c in org_post_citations)

# 7. P1: Wildcard policy rejection - Discord requires exact guild match
def test_wildcard_policy_rejection():
    # Direct policy store lookup: missing guild_id returns None for Discord
    policy_no_guild = channel_policy_store.get_policy(
        organization_id="gdg_mcet",
        channel_type=ChannelType.DISCORD,
        channel_id="99001122",
        guild_id=None
    )
    assert policy_no_guild is None

    # Foreign guild not bound in GuildInstallationStore is dropped
    event_foreign = {
        "id": "msg_foreign_guild_attack",
        "guild_id": "malicious_foreign_guild_666",
        "guild_name": "Attacker Guild",
        "channel_id": "99001122",
        "channel_name": "core-team",
        "content": "Attacking via channel ID collisions across guilds.",
        "author": {"id": "discord_arjun_101", "username": "arjun_gdg", "bot": False},
        "timestamp": "2026-03-05T09:30:00Z"
    }
    result = discord_gateway_bot.handle_gateway_event("MESSAGE_CREATE", event_foreign)
    assert result is None  # Dropped because guild is unknown to installation store
    assert memory_store.get_chunk("chk_discord_gdg_mcet_msg_foreign_guild_attack") is None

# 8. P2: Direct ChannelMessage construction without timestamp is rejected
def test_direct_channel_message_without_timestamp_rejected():
    with pytest.raises(ValidationError):
        ChannelMessage(
            message_id="msg_no_ts",
            channel_type=ChannelType.DISCORD,
            organization_id="gdg_mcet",
            channel_id="55667788",
            author_external_id="discord_arjun_101",
            author_name="arjun",
            content="Direct construction without timestamp"
            # timestamp missing!
        )

# 9. P1: Channel rename invariance: channel name changes cannot alter authoritative policy
def test_channel_rename_invariance():
    # Case A: Public channel 55667788 renamed to 'core-organizer-secret-leads'
    result_a = discord_gateway_bot.handle_gateway_event("MESSAGE_CREATE", {
        "id": "msg_rename_public_01",
        "guild_id": "11223344",
        "guild_name": "GDG MCET Discord",
        "channel_id": "55667788",
        "channel_name": "core-organizer-secret-leads",
        "content": "ChatMessage in renamed public channel.",
        "author": {"id": "discord_arjun_101", "username": "arjun_gdg", "bot": False},
        "timestamp": "2026-03-05T11:00:00Z"
    })
    assert result_a is not None
    assert result_a[1][0].permission == PermissionLevel.PUBLIC_COMMUNITY

    # Case B: Bound internal channel 99001122 renamed to 'general-random-memes'
    result_b = discord_gateway_bot.handle_gateway_event("MESSAGE_CREATE", {
        "id": "msg_rename_internal_01",
        "guild_id": "11223344",
        "guild_name": "GDG MCET Discord",
        "channel_id": "99001122",
        "channel_name": "general-random-memes",
        "content": "ChatMessage in renamed internal channel.",
        "author": {"id": "discord_arjun_101", "username": "arjun_gdg", "bot": False},
        "timestamp": "2026-03-05T11:30:00Z"
    })
    assert result_b is not None
    assert result_b[1][0].permission == PermissionLevel.INTERNAL_CORE

# 10. P1: Unknown / unbound channel falls back to PUBLIC_COMMUNITY
def test_unknown_or_unbound_channel_fallback_to_public():
    result_unbound = discord_gateway_bot.handle_gateway_event("MESSAGE_CREATE", {
        "id": "msg_unbound_01",
        "guild_id": "11223344",
        "guild_name": "GDG MCET Discord",
        "channel_id": "unknown_unbound_9988",
        "channel_name": "mystery-channel",
        "content": "Discussion in an unconfigured channel.",
        "author": {"id": "discord_arjun_101", "username": "arjun_gdg", "bot": False},
        "timestamp": "2026-03-05T12:00:00Z"
    })
    assert result_unbound is not None
    assert result_unbound[1][0].permission == PermissionLevel.PUBLIC_COMMUNITY

# 11. P2: Source metadata cannot overwrite authoritative provenance fields
def test_source_metadata_cannot_overwrite_authoritative_provenance():
    adapter = DiscordExportAdapter()
    malicious_payload = {
        "guild": {"id": "11223344", "name": "GDG MCET Discord"},
        "channel": {"id": "99001122", "name": "core-team"},
        "messages": [
            {
                "id": "msg_authoritative_tamper_attempt",
                "content": "Attempting to overwrite internal provenance fields via incoming metadata.",
                "author": {"id": "discord_arjun_101", "name": "arjun_gdg"},
                "timestamp": "2026-03-05T13:00:00Z",
                "metadata": {
                    "guild_id": "forged_guild_999",
                    "channel_id": "forged_channel_999",
                    "message_id": "forged_message_999",
                    "author_external_id": "forged_author_999",
                    "is_mapped": False,
                    "internal_user_id": "attacker_usr",
                    "custom_audit_note": "legitimate payload note"
                }
            }
        ]
    }
    records, chunks, _ = adapter.ingest_export(malicious_payload, organization_id="gdg_mcet")
    record = records[0]
    chunk = chunks[0]

    # Authoritative fields must NOT be overwritten
    assert record.metadata["guild_id"] == "11223344"
    assert record.metadata["channel_id"] == "99001122"
    assert record.metadata["message_id"] == "msg_authoritative_tamper_attempt"
    assert record.metadata["author_external_id"] == "discord_arjun_101"
    assert record.metadata["is_mapped"] is True
    assert record.metadata["internal_user_id"] == "usr_arjun"

    # Untrusted raw payload metadata is quarantined under payload_metadata
    assert record.metadata["payload_metadata"]["guild_id"] == "forged_guild_999"
    assert record.metadata["payload_metadata"]["custom_audit_note"] == "legitimate payload note"

    # Chunk provenance is similarly protected
    assert chunk.provenance["guild_id"] == "11223344"
    assert chunk.provenance["channel_id"] == "99001122"
    assert chunk.provenance["internal_user_id"] == "usr_arjun"

# 12. P2: Malformed or missing timestamps fail deterministically with structured error
def test_malformed_or_missing_timestamps_fail_with_structured_error():
    adapter = DiscordExportAdapter()

    # Case A: Malformed string timestamp
    with pytest.raises(ValueError, match="Malformed timestamp"):
        adapter.parse_export({
            "guild": {"id": "11223344"},
            "channel": {"id": "55667788"},
            "messages": [
                {
                    "id": "msg_bad_ts_01",
                    "content": "Message with bad date.",
                    "author": {"id": "discord_arjun_101"},
                    "timestamp": "not-a-valid-iso-date"
                }
            ]
        })

    # Case B: Missing/empty timestamp
    with pytest.raises(ValueError, match="Missing or invalid timestamp"):
        adapter.parse_export({
            "guild": {"id": "11223344"},
            "channel": {"id": "55667788"},
            "messages": [
                {
                    "id": "msg_bad_ts_02",
                    "content": "Message without timestamp.",
                    "author": {"id": "discord_arjun_101"},
                    "timestamp": ""
                }
            ]
        })

# 13. P2: Identity mappings reject unknown, cross-org, and inactive members
def test_identity_mappings_reject_invalid_members():
    # Case A: Unknown member ID
    with pytest.raises(ValueError, match="not a registered member"):
        membership_store.register_identity_mapping(
            organization_id="gdg_mcet",
            channel_type=ChannelType.DISCORD,
            external_user_id="discord_ghost_user",
            internal_user_id="usr_ghost_nonexistent"
        )

    # Case B: Cross-organization mapping attempt
    membership_store.register_member(
        user_id="usr_other_org_member",
        name="Other Org Member",
        organization_id="other_org",
        role_id="lead",
        role_name="Lead",
        permission=PermissionLevel.INTERNAL_CORE
    )
    with pytest.raises(ValueError, match="cross-organization mapping rejected|does not belong to organization"):
        membership_store.register_identity_mapping(
            organization_id="gdg_mcet",
            channel_type=ChannelType.DISCORD,
            external_user_id="discord_cross_org_user",
            internal_user_id="usr_other_org_member"
        )

    # Case C: Inactive member (usr_inactive_lead)
    with pytest.raises(ValueError, match="inactive"):
        membership_store.register_identity_mapping(
            organization_id="gdg_mcet",
            channel_type=ChannelType.DISCORD,
            external_user_id="discord_inactive_user",
            internal_user_id="usr_inactive_lead"
        )

# =====================================================================
# P1 & P2 CRYPTOGRAPHIC INTERACTIONS, REPLAY, & GATEWAY TESTS
# =====================================================================

# 14. P1: Discord webhook rejects missing, tampered, or unauthenticated Ed25519 signatures
def test_discord_webhook_ed25519_verification_rejects_missing_or_invalid_signature():
    payload = {
        "id": "inter_forged_attempt_01",
        "type": 1
    }

    # Case A: Missing signature header
    res_no_sig = send_signed_discord_webhook(payload, omit_signature=True)
    assert res_no_sig.status_code == 401
    assert "Missing Discord signature" in res_no_sig.json()["detail"]

    # Case B: Missing timestamp header
    res_no_ts = send_signed_discord_webhook(payload, omit_timestamp=True)
    assert res_no_ts.status_code == 401
    assert "Missing Discord signature" in res_no_ts.json()["detail"]

    # Case C: Tampered / forged signature
    res_bad_sig = send_signed_discord_webhook(payload, signature_override="00" * 64)
    assert res_bad_sig.status_code == 401
    assert "Invalid Discord Ed25519" in res_bad_sig.json()["detail"]

# 15. P1: Discord interaction PING handling (type == 1)
def test_discord_webhook_ping_interaction():
    res_ping = send_signed_discord_webhook({"id": "inter_ping_01", "type": 1})
    assert res_ping.status_code == 200
    assert res_ping.json() == {"type": 1}

# 16. P1 & P2: Discord slash command /ask-thread returns deferred response (Type 5) within 3s deadline
def test_discord_webhook_slash_command_ask_thread():
    # 1. Standard production mode: Immediate Type 5 Deferred Response (satisfies Discord 3s timeout)
    interaction_payload = {
        "id": "inter_slash_ask_01",
        "type": 2,  # APPLICATION_COMMAND
        "guild_id": "11223344",
        "channel_id": "99001122",
        "data": {
            "name": "ask-thread",
            "options": [
                {"name": "query", "value": "What are the prerequisites for the GenAI workshop?"}
            ]
        },
        "member": {
            "user": {
                "id": "discord_arjun_101",
                "username": "arjun_gdg"
            }
        }
    }
    res_deferred = send_signed_discord_webhook(interaction_payload)
    assert res_deferred.status_code == 200
    data = res_deferred.json()
    assert data["type"] == 5  # DEFERRED_CHANNEL_MESSAGE_WITH_SOURCE
    assert data["data"]["flags"] == 64  # EPHEMERAL: Never channel-visible
    assert data["thread_meta"]["status"] == "deferred"
    assert data["thread_meta"]["organization_id"] == "gdg_mcet"
    assert data["thread_meta"]["user_id"] == "usr_arjun"

    # 2. Test execution mode: Immediate Type 4 Response
    interaction_payload_imm = dict(interaction_payload)
    interaction_payload_imm["id"] = "inter_slash_ask_02_imm"
    interaction_payload_imm["immediate"] = True
    res_imm = send_signed_discord_webhook(interaction_payload_imm)
    assert res_imm.status_code == 200
    data_imm = res_imm.json()
    assert data_imm["type"] == 4  # CHANNEL_MESSAGE_WITH_SOURCE
    assert data_imm["data"]["flags"] == 64  # EPHEMERAL: Never channel-visible
    assert "content" in data_imm["data"]
    assert data_imm["thread_meta"]["organization_id"] == "gdg_mcet"
    assert data_imm["thread_meta"]["user_id"] == "usr_arjun"
    assert data_imm["thread_meta"]["citations_count"] > 0

# 17. P1: Organization is strictly server-resolved from guild installation, rejecting unknown guilds
def test_discord_webhook_rejects_uninstalled_guild_or_tampered_org():
    # Attacker crafts signed interaction with uninstalled foreign guild
    foreign_interaction = {
        "id": "inter_foreign_guild_01",
        "type": 2,
        "guild_id": "rogue_guild_9999",
        "data": {"name": "ask-thread", "options": [{"name": "query", "value": "secret info"}]},
        "member": {"user": {"id": "attacker", "username": "attacker"}}
    }
    res = send_signed_discord_webhook(foreign_interaction)
    # Server-owned GuildInstallationStore rejects unknown guild with 403 Forbidden
    assert res.status_code == 403
    assert "not installed or bound" in res.json()["detail"]

# 18. P2: Timestamp freshness window and interaction replay protection
def test_discord_webhook_freshness_window_and_replay_rejection():
    # Case A: Stale timestamp (1 hour in the past)
    stale_timestamp = str(int(time.time()) - 3600)
    res_stale = send_signed_discord_webhook(
        {"id": "inter_stale_01", "type": 1},
        timestamp=stale_timestamp
    )
    assert res_stale.status_code == 401
    assert "freshness window" in res_stale.json()["detail"]

    # Case B: Replay attack (sending the exact same interaction ID twice)
    fresh_payload = {"id": "inter_replay_target_01", "type": 1}
    res_first = send_signed_discord_webhook(fresh_payload)
    assert res_first.status_code == 200

    # Second send with same interaction ID
    res_replay = send_signed_discord_webhook(fresh_payload)
    assert res_replay.status_code == 409
    assert "Replay detected" in res_replay.json()["detail"]

# 19. P2: Shared ChannelAdapter base interface has NO spoofable trust parameters
def test_channel_adapter_base_has_no_spoofable_trust_parameters():
    ingest_msg_sig = inspect.signature(ChannelAdapter.ingest_message)
    ingest_export_sig = inspect.signature(ChannelAdapter.ingest_export)

    # Proving trust_mode and approved_by_organizer_id are completely absent from base contract
    assert "trust_mode" not in ingest_msg_sig.parameters
    assert "approved_by_organizer_id" not in ingest_msg_sig.parameters

    assert "trust_mode" not in ingest_export_sig.parameters
    assert "approved_by_organizer_id" not in ingest_export_sig.parameters

# 20. P2: ApprovalStore local demo persistence operates with durable flush/sync
def test_approval_store_durable_persistence():
    # Use workspace-local file to avoid OS temp permission issues on Windows
    local_audit_file = Path(__file__).resolve().parent / ".test_audit_store.jsonl"
    if local_audit_file.exists():
        local_audit_file.unlink()

    try:
        store1 = ApprovalStore(audit_file_path=local_audit_file)
        appr = store1.approve_import(
            organization_id="gdg_mcet",
            import_hash="testhash123abc",
            approved_by_user_id="usr_arjun",
            store=memory_store
        )
        assert local_audit_file.exists()

        # Create second instance pointing to the same audit file (simulating service restart)
        store2 = ApprovalStore(audit_file_path=local_audit_file)
        restored = store2.get_approval(appr.id)
        assert restored is not None
        assert restored.import_hash == "testhash123abc"
        assert restored.approved_by_user_id == "usr_arjun"
        assert len(store2.get_approvals_for_hash("testhash123abc")) == 1
    finally:
        if local_audit_file.exists():
            local_audit_file.unlink()

# 21. P1: Gateway Bot ignores bot messages to prevent echo loops
def test_gateway_bot_ignores_bot_messages_and_unbound_guilds():
    # Bot message event
    bot_event = {
        "id": "msg_bot_echo",
        "guild_id": "11223344",
        "channel_id": "55667788",
        "content": "Echoing bot content",
        "author": {"id": "bot_999", "username": "ThreadBot", "bot": True},
        "timestamp": "2026-03-05T15:00:00Z"
    }
    result = discord_gateway_bot.handle_gateway_event("MESSAGE_CREATE", bot_event)
    assert result is None
    assert memory_store.get_chunk("chk_discord_gdg_mcet_msg_bot_echo") is None

# 22. Lifespan startup and shutdown execution in development
def test_fastapi_lifespan_execution_in_dev(monkeypatch):
    started = []
    stopped = []

    monkeypatch.setattr(discord_gateway_bot, "start_background", lambda: started.append(True))
    async def mock_stop():
        stopped.append(True)
    monkeypatch.setattr(discord_gateway_bot, "stop", mock_stop)
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "test_bot_token")
    monkeypatch.setenv("THREAD_START_GATEWAY_BOT", "true")
    discord_gateway_bot._running = True

    with TestClient(app) as test_client:
        assert len(started) == 1
        resp = test_client.get("/health")
        assert resp.status_code == 200

    assert len(stopped) == 1
    discord_gateway_bot._running = False

# 23. P2: Lifespan Gateway Bot is strictly rejected in production to prevent multi-worker Gateway duplications
def test_fastapi_lifespan_rejected_in_production(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("THREAD_JWT_SECRET", "cryptographically-secure-production-secret-32-chars-long")
    monkeypatch.setenv("THREAD_START_GATEWAY_BOT", "true")

    # In production, validate_production_security fails startup when THREAD_START_GATEWAY_BOT is set
    with pytest.raises(RuntimeError) as exc_info:
        settings.validate_production_security()
    assert "THREAD_START_GATEWAY_BOT is strictly development-only" in str(exc_info.value)
    assert "run_gateway" in str(exc_info.value)

# 24. P0: End-to-end test proving organizer's internal answer cannot become channel-visible (EPHEMERAL flags == 64)
def test_discord_webhook_organizer_internal_answer_cannot_become_channel_visible():
    # 1. Organizer asks for sensitive internal budget data in a Discord channel
    organizer_query_payload = {
        "id": "inter_slash_confidential_budget_01",
        "type": 2,  # APPLICATION_COMMAND
        "guild_id": "11223344",
        "channel_id": "99001122",
        "data": {
            "name": "ask-thread",
            "options": [
                {"name": "query", "value": "What is the internal organizer budget and allocation for GDG MCET?"}
            ]
        },
        "member": {
            "user": {
                "id": "discord_arjun_101",  # Maps to usr_arjun (INTERNAL_CORE)
                "username": "arjun_gdg"
            }
        },
        "immediate": True
    }

    res_org = send_signed_discord_webhook(organizer_query_payload)
    assert res_org.status_code == 200
    data_org = res_org.json()

    # CONFIDENTIALITY GUARANTEE 1: The response type and flags MUST be ephemeral (64)
    assert data_org["type"] == 4
    assert data_org["data"]["flags"] == 64, "P0 Violation: flags must be 64 (EPHEMERAL) so message is never channel-visible"
    assert (data_org["data"]["flags"] & 64) == 64

    # CONFIDENTIALITY GUARANTEE 2: Arjun retrieves INTERNAL_CORE information
    allowed_scopes = data_org["thread_meta"]["allowed_scopes"]
    assert "INTERNAL_CORE" in allowed_scopes
    assert "budget" in data_org["data"]["content"].lower() or "credits" in data_org["data"]["content"].lower()

    # CONFIDENTIALITY GUARANTEE 3: Deferred response path also strictly enforces flags == 64
    deferred_payload = dict(organizer_query_payload)
    deferred_payload["id"] = "inter_slash_confidential_budget_02_def"
    deferred_payload.pop("immediate", None)
    res_def = send_signed_discord_webhook(deferred_payload)
    assert res_def.status_code == 200
    data_def = res_def.json()
    assert data_def["type"] == 5
    assert data_def["data"]["flags"] == 64, "P0 Violation: Deferred response must have flags: 64 to prevent public display"

    # CONFIDENTIALITY GUARANTEE 4: Non-organizer community member asking the same question never gets internal data
    community_query_payload = {
        "id": "inter_slash_confidential_budget_03_comm",
        "type": 2,
        "guild_id": "11223344",
        "channel_id": "99001122",
        "data": {
            "name": "ask-thread",
            "options": [
                {"name": "query", "value": "What is the internal organizer budget and allocation for GDG MCET?"}
            ]
        },
        "member": {
            "user": {
                "id": "discord_unknown_comm_999",  # Unmapped/community user -> public only
                "username": "random_guest"
            }
        },
        "immediate": True
    }
    res_comm = send_signed_discord_webhook(community_query_payload)
    assert res_comm.status_code == 200
    data_comm = res_comm.json()
    # Response is also ephemeral
    assert data_comm["data"]["flags"] == 64
    # Allowed scopes does NOT contain INTERNAL_CORE
    assert "INTERNAL_CORE" not in data_comm["thread_meta"]["allowed_scopes"]
    # Evidence must NOT expose internal budget figures
    assert "$500" not in data_comm["data"]["content"]


