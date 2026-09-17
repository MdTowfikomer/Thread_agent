import os
os.environ["THREAD_FORCE_DETERMINISTIC_SYNTHESIS"] = "1"

import hashlib
import pytest
from datetime import datetime, timezone, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.core.canonical import ChannelType, PermissionLevel, AccessContext
from app.core.auth import AuthenticatedPrincipal
from app.graph.state import GraphState
from app.graph.workflow import app_graph, classify_intent_and_routing
from app.core.organizations import get_workspace
from app.memory.conversation import conversation_store, ConversationTurnStore
from app.tools.events import event_assistant, EventAssistant
from app.tools.resources import resource_assistant, ResourceAssistant
from app.tools.summarizer import summarizer_assistant, SummarizerAssistant
from app.tools.github_helper import github_helper
from app.tools.account_link import account_link_tool, AccountLinkTool, MAX_FAILED_ATTEMPTS
from app.channels.outbound import ChannelMessageDeliveryService, OutboundAuditStore


def principal(user_id="usr_tester", org_id="gdg_mcet", permission=PermissionLevel.PUBLIC_COMMUNITY):
    allowed = [permission]
    if permission == PermissionLevel.INTERNAL_CORE:
        allowed = [PermissionLevel.PUBLIC_COMMUNITY, PermissionLevel.INTERNAL_CORE]
    return AuthenticatedPrincipal(
        user_id=user_id,
        organization_id=org_id,
        access_context=AccessContext(
            user_id=user_id,
            organization_id=org_id,
            role_id="community" if permission == PermissionLevel.PUBLIC_COMMUNITY else "organizer_lead",
            user_permission=permission,
            allowed_scopes=allowed,
        ),
    )


# ==============================================================================
# 1. P0 FINDING 1: EVENTS ASSISTANT — ZERO FABRICATION & FAIL-CLOSED
# ==============================================================================
def test_events_fails_closed_when_database_unavailable():
    """Verify event tool returns empty list and clean fail-closed message when DB offline."""
    assistant = EventAssistant()
    with patch.object(assistant, "_get_db_conn", return_value=None):
        events = assistant.list_upcoming_events(org_id="gdg_mcet")
        assert events == [], "Must return empty list when DB is unreachable"

        formatted = assistant.format_events_response(events)
        assert "no published events scheduled" in formatted.lower()
        # Must NEVER contain fabricated workshops or fake dates
        assert "2026" not in formatted
        assert "Next.js" not in formatted


def test_events_returns_real_events_from_database():
    """Verify event tool correctly parses and formats real events returned by PostgreSQL."""
    assistant = EventAssistant()
    mock_conn = MagicMock()
    mock_cur = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cur
    mock_conn.__enter__.return_value = mock_conn

    now = datetime.now(timezone.utc)
    future_event = now + timedelta(days=5)

    # Database query columns: id, title, description, start_time, end_time, location_or_url, rsvp_url, speakers, status
    mock_cur.fetchall.return_value = [
        (
            "evt_real_101",
            "Real GDG MCET AI Workshop",
            "Hands-on workshop on generative agents.",
            future_event,
            future_event + timedelta(hours=3),
            "Auditorium 2",
            "https://gdg.community.dev/events/101",
            ["Speaker A"],
            "upcoming"
        )
    ]

    with patch.object(assistant, "_get_db_conn", return_value=mock_conn):
        events = assistant.list_upcoming_events(org_id="gdg_mcet")
        assert len(events) == 1
        assert events[0]["title"] == "Real GDG MCET AI Workshop"
        assert events[0]["location_or_url"] == "Auditorium 2"

        formatted = assistant.format_events_response(events)
        assert "Upcoming Community Events" in formatted
        assert "Real GDG MCET AI Workshop" in formatted
        assert "Auditorium 2" in formatted


def test_events_organizer_can_create_event():
    """Verify event creation persists to PostgreSQL community_events table."""
    assistant = EventAssistant()
    mock_conn = MagicMock()
    mock_cur = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cur
    mock_conn.__enter__.return_value = mock_conn

    start = datetime.now(timezone.utc) + timedelta(days=7)
    mock_cur.fetchone.return_value = ("evt_101", "Spring Hackathon 2026", start)

    with patch.object(assistant, "_get_db_conn", return_value=mock_conn):
        res = assistant.create_event(
            org_id="gdg_mcet",
            title="Spring Hackathon 2026",
            start_time=start,
            description="Official hackathon",
            location_or_url="Lab 3"
        )
        assert res is not None
        assert res["id"] == "evt_101"
        assert mock_cur.execute.called
        sql = mock_cur.execute.call_args[0][0]
        assert "INSERT INTO community_events" in sql


# ==============================================================================
# 2. P0 FINDING 2: RESOURCE ASSISTANT — STRICT SQL PRE-RETRIEVAL ACL
# ==============================================================================
def test_resources_fails_closed_when_database_unavailable():
    """Verify resource tool fails closed when DB is unreachable."""
    assistant = ResourceAssistant()
    with patch.object(assistant, "_get_db_conn", return_value=None):
        res = assistant.search_resources("github", org_id="gdg_mcet")
        assert res == []
        formatted = assistant.format_resources_response(res)
        assert "No published resources or FAQs found" in formatted


def test_resources_strictly_enforces_acl_scopes():
    """
    CRITICAL ACL TEST:
    Verifies that SQL query filters by allowed_scopes in SQL (WHERE permission_scope = ANY(%s)).
    A public community user must ONLY query public_community scope.
    An internal member can query internal_core and public_community.
    """
    assistant = ResourceAssistant()
    mock_conn = MagicMock()
    mock_cur = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cur
    mock_conn.__enter__.return_value = mock_conn

    # 1. Public user query
    public_ctx = AccessContext(
        user_id="usr_public",
        organization_id="gdg_mcet",
        role_id="community",
        user_permission=PermissionLevel.PUBLIC_COMMUNITY,
        allowed_scopes=[PermissionLevel.PUBLIC_COMMUNITY]
    )

    mock_cur.fetchall.return_value = []
    with patch.object(assistant, "_get_db_conn", return_value=mock_conn):
        assistant.search_resources(query="docs", org_id="gdg_mcet", access_context=public_ctx)
        call_args = mock_cur.execute.call_args
        sql, params = call_args[0][0], call_args[0][1]
        assert "permission_scope = ANY(%s)" in sql
        assert params[1] == ["PUBLIC_COMMUNITY"], "Public user must strictly be restricted to PUBLIC_COMMUNITY scope"

    # 2. Internal core member query
    internal_ctx = AccessContext(
        user_id="usr_core",
        organization_id="gdg_mcet",
        role_id="organizer_lead",
        user_permission=PermissionLevel.INTERNAL_CORE,
        allowed_scopes=[PermissionLevel.PUBLIC_COMMUNITY, PermissionLevel.INTERNAL_CORE]
    )

    with patch.object(assistant, "_get_db_conn", return_value=mock_conn):
        assistant.search_resources(query="budget", org_id="gdg_mcet", access_context=internal_ctx)
        call_args = mock_cur.execute.call_args
        params = call_args[0][1]
        assert "INTERNAL_CORE" in params[1]
        assert "PUBLIC_COMMUNITY" in params[1]


# ==============================================================================
# 3. P0 FINDING 3: CRYPTOGRAPHIC ACCOUNT LINKING & ATOMIC CONSUMPTION
# ==============================================================================
def test_account_link_generates_256bit_token_and_stores_only_sha256_hash():
    """
    CRITICAL SECURITY TEST:
    Verify token has 256 bits of entropy and only the SHA-256 digest is stored in SQL.
    """
    tool = AccountLinkTool()
    mock_conn = MagicMock()
    mock_cur = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cur
    mock_conn.__enter__.return_value = mock_conn

    with patch.object(tool, "_get_db_conn", return_value=mock_conn):
        raw_token = tool.generate_link_token(
            initiating_platform="discord",
            initiating_account_id="snowflake_12345",
            initiating_username="alice_discord",
            person_id="person_alice_uuid",
            org_id="gdg_mcet"
        )
        assert raw_token.startswith("LINK_")
        assert len(raw_token) >= 40, "Token must have at least 256 bits of entropy"

        # Check SQL insert parameters
        assert mock_cur.execute.called
        sql, params = mock_cur.execute.call_args[0][0], mock_cur.execute.call_args[0][1]
        assert "INSERT INTO account_link_tokens" in sql
        token_hash = params[0]
        assert token_hash == hashlib.sha256(raw_token.strip().encode("utf-8")).hexdigest()
        assert raw_token not in params, "Raw token must NEVER be written to the database"


def test_account_link_atomic_redemption_and_same_platform_rejection():
    """
    CRITICAL SECURITY TEST:
    Verify atomic UPDATE ... WHERE used=false RETURNING statement and rejection of same-platform linking.
    """
    tool = AccountLinkTool()
    mock_conn = MagicMock()
    mock_cur = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cur
    mock_conn.__enter__.return_value = mock_conn

    raw_token = "LINK_testtoken1234567890abcdefghijklmnopqrstuvwxyz"

    # Simulate same-platform redemption attempt (Discord -> Discord)
    mock_cur.fetchone.return_value = (
        "person_alice_uuid", "gdg_mcet", "discord", "snowflake_12345", "alice_discord"
    )

    with patch.object(tool, "_get_db_conn", return_value=mock_conn):
        ok, msg = tool.redeem_link_token(
            raw_token=raw_token,
            target_platform="discord",
            target_account_id="snowflake_99999",
            target_username="alice_clone",
            org_id="gdg_mcet"
        )
        assert ok is False
        assert "generated on Discord" in msg

    # Simulate cross-platform redemption attempt (Discord -> Telegram)
    with patch.object(tool, "_get_db_conn", return_value=mock_conn), \
         patch("app.identity.service.identity_service.link_account") as mock_link:
        ok, msg = tool.redeem_link_token(
            raw_token=raw_token,
            target_platform="telegram",
            target_account_id="tg_12345",
            target_username="alice_tg",
            org_id="gdg_mcet"
        )
        assert ok is True
        assert "Account Successfully Linked" in msg
        assert "Telegram" in msg
        assert mock_link.called


def test_account_link_brute_force_rate_limiting():
    """
    CRITICAL RATE LIMIT TEST:
    Exceeding MAX_FAILED_ATTEMPTS (5) within 15 minutes blocks the caller.
    """
    tool = AccountLinkTool()
    mock_conn = MagicMock()
    mock_cur = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cur
    mock_conn.__enter__.return_value = mock_conn

    # Simulate token not found in database (invalid or already used)
    mock_cur.fetchone.return_value = None

    with patch.object(tool, "_get_db_conn", return_value=mock_conn):
        for i in range(MAX_FAILED_ATTEMPTS):
            ok, msg = tool.redeem_link_token(
                raw_token=f"LINK_bad_guess_{i}",
                target_platform="telegram",
                target_account_id="attacker_101",
                target_username="attacker"
            )
            assert ok is False
            assert "Invalid, expired, or already redeemed" in msg

        # 6th attempt must be rate-limited without even querying DB
        ok_blocked, blocked_msg = tool.redeem_link_token(
            raw_token="LINK_bad_guess_final",
            target_platform="telegram",
            target_account_id="attacker_101",
            target_username="attacker"
        )
        assert ok_blocked is False
        assert "Too many failed redemption attempts" in blocked_msg


# ==============================================================================
# 4. P1 FINDING 4: SCOPED MULTI-TURN MEMORY & RETENTION CLEANUP
# ==============================================================================
def test_conversation_store_scopes_by_org_and_enforces_sliding_window():
    """
    CRITICAL MEMORY SCOPING TEST:
    Verifies that get_recent_turns queries strictly filter by organization_id,
    session_key, and 24-hour sliding window.
    """
    store = ConversationTurnStore()
    mock_conn = MagicMock()
    mock_cur = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cur
    mock_conn.__enter__.return_value = mock_conn

    mock_cur.fetchall.return_value = [
        ("user", "Hello!"),
        ("assistant", "Hi there! How can I help?")
    ]

    with patch.object(store, "_get_db_conn", return_value=mock_conn):
        turns = store.get_recent_turns(
            session_key="discord:channel_1:user_1",
            organization_id="gdg_mcet",
            limit=5,
            max_age_hours=24
        )
        assert len(turns) == 2
        assert turns[0]["role"] == "user"

        assert mock_cur.execute.called
        sql, params = mock_cur.execute.call_args[0][0], mock_cur.execute.call_args[0][1]
        assert "organization_id = %s" in sql
        assert "session_key = %s" in sql
        assert "created_at >= NOW() - (%s * INTERVAL '1 hour')" in sql
        assert params[0] == "gdg_mcet"
        assert params[1] == "discord:channel_1:user_1"
        assert params[2] == 24


def test_conversation_store_fails_closed_when_disconnected():
    """Verify conversation memory fails closed (returns []) if DB is disconnected."""
    store = ConversationTurnStore()
    with patch.object(store, "_get_db_conn", return_value=None):
        turns = store.get_recent_turns(
            session_key="discord:channel_1:user_1",
            organization_id="gdg_mcet"
        )
        assert turns == [], "Must return empty list when DB is unreachable"

        recorded = store.record_turn(
            session_key="discord:channel_1:user_1",
            platform="discord",
            organization_id="gdg_mcet",
            initiating_user_id="user_1",
            role="user",
            content="Hello"
        )
        assert recorded is False, "Must fail closed if DB cannot persist turn"


def test_conversation_store_cleanup_expired_turns():
    """Verify retention cleanup issues DELETE statement with retention parameter."""
    store = ConversationTurnStore()
    mock_conn = MagicMock()
    mock_cur = MagicMock()
    mock_cur.rowcount = 42
    mock_conn.cursor.return_value.__enter__.return_value = mock_cur
    mock_conn.__enter__.return_value = mock_conn

    with patch.object(store, "_get_db_conn", return_value=mock_conn):
        deleted = store.cleanup_expired_turns(retention_days=7)
        assert deleted == 42
        sql = mock_cur.execute.call_args[0][0]
        assert "DELETE FROM conversation_turns" in sql
        assert "INTERVAL '1 day'" in sql


def test_session_key_formatting():
    k1 = ConversationTurnStore.format_session_key("discord", "98765", "12345")
    assert k1 == "discord:98765:12345"

    k2 = ConversationTurnStore.format_session_key(ChannelType.TELEGRAM.value, "-10019283", "554433")
    assert k2 == "telegram:-10019283:554433"


# ==============================================================================
# 5. FINDING 5: CHANNEL SUMMARIZER — ACTUAL DISCUSSION & ACL GATING
# ==============================================================================
def test_summarizer_queries_source_records_with_acl_and_fails_closed():
    """
    CRITICAL SUMMARIZER TEST:
    Verifies that !summary inspects actual human messages from 'source_records'
    scoped by AccessContext allowed_scopes, and fails closed if empty.
    """
    assistant = SummarizerAssistant()
    mock_conn = MagicMock()
    mock_cur = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cur
    mock_conn.__enter__.return_value = mock_conn

    public_ctx = AccessContext(
        user_id="usr_public",
        organization_id="gdg_mcet",
        role_id="community",
        user_permission=PermissionLevel.PUBLIC_COMMUNITY,
        allowed_scopes=[PermissionLevel.PUBLIC_COMMUNITY]
    )

    # 1. Verify fail-closed when no messages found
    mock_cur.fetchall.return_value = []
    with patch.object(assistant, "_get_db_conn", return_value=mock_conn):
        summary = assistant.summarize_channel_discussion(
            organization_id="gdg_mcet",
            channel_id="chan_general",
            platform="discord",
            access_context=public_ctx,
            window_hours=48
        )
        assert "No authorized channel discussion was found" in summary
        sql, params = mock_cur.execute.call_args[0][0], mock_cur.execute.call_args[0][1]
        assert "FROM source_records" in sql
        assert "permission = ANY(%s)" in sql
        assert params[1] == ["PUBLIC_COMMUNITY"]

    # 2. Verify summary when human channel messages exist
    now = datetime.now(timezone.utc)
    mock_cur.fetchall.return_value = [
        ("Alice", "Let's organize the next workshop on Saturday.", now - timedelta(hours=2), "PUBLIC_COMMUNITY", "discord_message"),
        ("Bob", "Agreed, I will prepare the presentation slides.", now - timedelta(hours=1), "PUBLIC_COMMUNITY", "discord_message"),
    ]

    with patch.object(assistant, "_get_db_conn", return_value=mock_conn):
        summary = assistant.summarize_channel_discussion(
            organization_id="gdg_mcet",
            channel_id="chan_general",
            platform="discord",
            access_context=public_ctx,
            window_hours=48
        )
        assert "Channel Discussion Summary" in summary
        assert "Alice" in summary or "Bob" in summary


# ==============================================================================
# 6. GITHUB HELPER & INTENT ROUTING
# ==============================================================================
def test_github_helper_returns_repo_and_guide():
    repo_info = github_helper.get_bound_repository("gdg_mcet")
    assert "repository_name" in repo_info
    assert "Thread_agent" in repo_info["repository_name"]

    guide = github_helper.format_github_response(repo_info)
    assert "How to Contribute" in guide
    assert "pytest" in guide
    assert repo_info["url"] in guide


def test_intent_classification():
    ws = get_workspace("gdg_mcet")

    # Command triggers
    c1, t1, _, _ = classify_intent_and_routing("!events", ws)
    assert c1 == "TOOL_EXECUTION" and t1 == "events"

    c2, t2, _, _ = classify_intent_and_routing("!github", ws)
    assert c2 == "TOOL_EXECUTION" and t2 == "github"

    c3, t3, _, _ = classify_intent_and_routing("!summary", ws)
    assert c3 == "TOOL_EXECUTION" and t3 == "summary"

    c4, t4, a4, _ = classify_intent_and_routing("!link LINK_12345", ws)
    assert c4 == "TOOL_EXECUTION" and t4 == "link" and a4 == "LINK_12345"

    # Conversational greetings
    c5, _, _, _ = classify_intent_and_routing("Hello! How are you doing today?", ws)
    assert c5 == "GENERAL_KNOWLEDGE"

    c6, _, _, _ = classify_intent_and_routing("hi", ws)
    assert c6 == "GENERAL_KNOWLEDGE"

    # Freeform event questions search ingested, permission-aware announcements.
    # !events remains the explicit structured-calendar command.
    c7, t7, _, _ = classify_intent_and_routing("When is the next upcoming workshop?", ws)
    assert c7 == "ORGANIZATIONAL_FACTS" and t7 is None

    # Organizational queries
    c8, _, _, _ = classify_intent_and_routing("What was the approved budget for DevFest?", ws)
    assert c8 == "ORGANIZATIONAL_FACTS"


# ==============================================================================
# 7. FULL GRAPH EXECUTION & OUTBOUND DELIVERY
# ==============================================================================
def test_graph_executes_events_tool_fail_closed():
    state = GraphState(query="!events", organization_id="gdg_mcet")
    res = app_graph.invoke(state)
    assert res["intent_category"] == "TOOL_EXECUTION"
    assert res["tool_name"] == "events"
    assert "Community Events" in res["final_answer"]
    assert "no published events" in res["final_answer"].lower()


def test_graph_executes_github_tool():
    state = GraphState(query="!github", organization_id="gdg_mcet")
    res = app_graph.invoke(state)
    assert res["intent_category"] == "TOOL_EXECUTION"
    assert "Thread_agent" in res["final_answer"]
    assert "How to Contribute" in res["final_answer"]


def test_graph_executes_conversational_greeting():
    state = GraphState(
        query="Hello! Who are you?",
        organization_id="gdg_mcet",
        chat_history=[
            {"role": "user", "content": "Hi"},
            {"role": "assistant", "content": "Hello! I am Thread Agent."}
        ]
    )
    res = app_graph.invoke(state)
    assert res["intent_category"] == "GENERAL_KNOWLEDGE"
    assert "insufficient evidence" not in res["final_answer"].lower()
    assert len(res["final_answer"]) > 10


def test_outbound_delivery_general_knowledge_delivers_and_records_turn(monkeypatch):
    store = OutboundAuditStore()
    service = ChannelMessageDeliveryService(store)
    calls = []
    service.adapters[ChannelType.SLACK] = SimpleNamespace(send=lambda dest, text, key: calls.append(text) or "ts-slack-1")
    monkeypatch.setattr(service, "_resolve_destination", lambda *args: {"channel_id": "C_TEST", "team_id": "T_TEST"})

    # In-memory turn collector for test
    mock_turns = []
    monkeypatch.setattr(
        conversation_store,
        "record_turn",
        lambda session_key, plat, org, uid, role, content: mock_turns.append({"role": role, "content": content}) or True
    )
    monkeypatch.setattr(
        conversation_store,
        "get_recent_turns",
        lambda session_key, organization_id=None, limit=10, max_age_hours=24: mock_turns[-limit:]
    )

    p = principal()
    result = service.send_message(p, ChannelType.SLACK, "C_TEST", "Hello! Can you help me?", "general-key-1")

    assert result["status"] == "sent"
    assert len(calls) == 1
    assert "insufficient evidence" not in calls[0].lower()

    session_key = conversation_store.format_session_key(ChannelType.SLACK.value, "C_TEST", p.user_id)
    history = conversation_store.get_recent_turns(session_key=session_key, organization_id=p.organization_id, limit=5)
    assert any(h["content"] == "Hello! Can you help me?" for h in history)
