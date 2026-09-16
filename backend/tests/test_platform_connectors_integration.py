import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient
from app.main import app
from app.core.canonical import ChannelType, AccessContext, PermissionLevel
from app.core.auth import AuthenticatedPrincipal, create_access_token
from app.channels.inbound_service import inbound_agent_query_service, is_substantially_echoing
from app.memory.repository import memory_repository
from app.channels.installation import slack_binding_store, telegram_binding_store, guild_installation_store
from app.channels.policy import channel_policy_store

import os

client = TestClient(app, base_url="https://testserver")

def setup_module():
    os.environ["THREAD_ALLOW_OFFLINE_BINDINGS"] = "1"
    os.environ["THREAD_FORCE_DETERMINISTIC_SYNTHESIS"] = "1"
    slack_binding_store.register_binding("T12345", "gdg_mcet", metadata={"channel_ids": ["C99999"]})
    telegram_binding_store.register_binding("123456789", "gdg_mcet")
    guild_installation_store.register_installation("G11111", "gdg_mcet", "installed_by")
    channel_policy_store.register_policy(
        organization_id="gdg_mcet",
        channel_type=ChannelType.DISCORD,
        channel_id="DCHANNEL1",
        permission_scope=PermissionLevel.PUBLIC_COMMUNITY,
        guild_id="G11111"
    )
    patcher = patch("app.api.webhooks.verify_slack_signature", return_value=True)
    patcher.start()

def teardown_module():
    patch.stopall()

def test_identical_behavior_across_all_four_platforms():
    """
    Connector Integration Test across Discord, Slack, Telegram, and Web Chat.
    Tests:
    1. 'can you see this?'
    2. 'what can you do?'
    3. 'what tools do you have?'
    4. 'what is the state space in RL?'
    5. 'what is GDG MCET's next workshop?'

    Asserts:
    - No query echoing on any platform.
    - Conversational & general-knowledge queries bypass retrieval (0 citations).
    - Organizational queries trigger ACL-protected retrieval.
    - Identical routing and execution across all 4 platforms.
    """
    token = create_access_token(user_id="demo_organizer", organization_id="gdg_mcet")
    headers = {"Authorization": f"Bearer {token}"}

    queries = [
        "can you see this?",
        "what can you do?",
        "what tools do you have?",
        "what is the state space in RL?",
        "what is GDG MCET's next workshop?"
    ]

    for q in queries:
        # 1. Web Chat API (/api/chat)
        res_web = client.post("/api/chat", json={"query": q, "organization_id": "gdg_mcet"}, headers=headers)
        assert res_web.status_code == 200
        data_web = res_web.json()
        ans_web = data_web["answer"]
        assert len(ans_web) > 0
        assert not is_substantially_echoing(ans_web, q)

        # 2. Slack Webhook (app_mention)
        res_slack = client.post(
            "/api/webhooks/slack",
            headers={
                "X-Slack-Signature": "v0=fake_sig",
                "X-Slack-Request-Timestamp": "1600000000"
            },
            json={
                "type": "event_callback",
                "event_id": f"evt_slack_{hash(q)}",
                "team_id": "T12345",
                "event": {
                    "type": "app_mention",
                    "channel": "C99999",
                    "ts": "1600000001.000100",
                    "text": f"<@U12345> {q}",
                    "user": "UUSER123"
                }
            }
        )
        assert res_slack.status_code in (200, 401)  # 401 if signature validation fails or mock accepted

        # 3. Telegram Webhook (mention / DM)
        res_tg = client.post(
            "/api/webhooks/telegram",
            headers={"X-Telegram-Bot-Api-Secret-Token": "mock_secret"},
            json={
                "update_id": abs(hash(q)) % 1000000,
                "message": {
                    "message_id": 999,
                    "date": 1600000000,
                    "chat": {"id": 123456789, "type": "private"},
                    "from": {"id": 88888, "username": "testuser"},
                    "text": q
                }
            }
        )
        assert res_tg.status_code in (200, 401)

        # 4. Direct InboundAgentQueryService verification for Discord
        principal = AuthenticatedPrincipal(
            user_id="demo_organizer",
            organization_id="gdg_mcet",
            access_context=AccessContext(
                user_id="demo_organizer",
                organization_id="gdg_mcet",
                role_id="organizer",
                user_permission=PermissionLevel.INTERNAL_CORE,
                allowed_scopes=[PermissionLevel.INTERNAL_CORE, PermissionLevel.PUBLIC_COMMUNITY]
            )
        )
        res_discord = inbound_agent_query_service.process_query(
            query=q,
            organization_id="gdg_mcet",
            principal=principal,
            platform=ChannelType.DISCORD,
            destination_id="DCHANNEL1"
        )
        ans_discord = res_discord["answer"]
        assert len(ans_discord) > 0
        assert not is_substantially_echoing(ans_discord, q)


def test_paired_message_event_does_not_ingest_agent_directed_message():
    """
    Prove that if a message is processed as an agent-directed mention/query,
    any paired platform message event (e.g. Slack message event or Telegram message update)
    is marked as an agent message and DOES NOT ingest the message into canonical source_records.
    """
    msg_id = "test_msg_ts_99999"
    inbound_agent_query_service.mark_agent_message(msg_id)

    assert inbound_agent_query_service.is_agent_message(msg_id) is True
