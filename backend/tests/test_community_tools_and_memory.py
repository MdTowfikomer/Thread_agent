import os
os.environ["THREAD_FORCE_DETERMINISTIC_SYNTHESIS"] = "1"

import pytest
from datetime import datetime, timezone
from types import SimpleNamespace

from app.core.canonical import ChannelType, PermissionLevel, AccessContext
from app.core.auth import AuthenticatedPrincipal
from app.graph.state import GraphState
from app.graph.workflow import app_graph, classify_intent_and_routing
from app.core.organizations import get_workspace
from app.memory.conversation import conversation_store, ConversationTurnStore
from app.tools.events import event_assistant
from app.tools.resources import resource_assistant
from app.tools.summarizer import summarizer_assistant
from app.tools.github_helper import github_helper
from app.tools.account_link import account_link_tool
from app.channels.outbound import ChannelMessageDeliveryService, OutboundAuditStore


def principal(user_id="usr_tester", org_id="gdg_mcet"):
    return AuthenticatedPrincipal(
        user_id=user_id,
        organization_id=org_id,
        access_context=AccessContext(
            user_id=user_id,
            organization_id=org_id,
            role_id="community",
            user_permission=PermissionLevel.PUBLIC_COMMUNITY,
            allowed_scopes=[PermissionLevel.PUBLIC_COMMUNITY],
        ),
    )


# --- 1. Multi-Turn Conversation Memory Tests ---
def test_conversation_store_records_and_retrieves_turns():
    store = ConversationTurnStore(max_cached_turns=10)
    session_key = "test_plat:chan_1:user_1"

    store.record_turn(session_key, "discord", "gdg_mcet", "user_1", "user", "What is GDG MCET?")
    store.record_turn(session_key, "discord", "gdg_mcet", "user_1", "assistant", "GDG MCET is the Google Developer Group at MCET.")
    store.record_turn(session_key, "discord", "gdg_mcet", "user_1", "user", "When is the next hackathon?")

    recent = store.get_recent_turns(session_key, limit=2)
    assert len(recent) == 2
    assert recent[0]["role"] == "assistant"
    assert recent[1]["role"] == "user"
    assert recent[1]["content"] == "When is the next hackathon?"


def test_session_key_formatting():
    k1 = ConversationTurnStore.format_session_key("discord", "98765", "12345")
    assert k1 == "discord:98765:12345"

    k2 = ConversationTurnStore.format_session_key(ChannelType.TELEGRAM.value, "-10019283", "554433")
    assert k2 == "telegram:-10019283:554433"


# --- 2. Event Assistant Tests ---
def test_event_assistant_lists_and_formats_events():
    events = event_assistant.list_upcoming_events(org_id="gdg_mcet", limit=5)
    assert len(events) > 0
    first = events[0]
    assert "title" in first
    assert "start_time" in first

    formatted = event_assistant.format_events_response(events)
    assert "Upcoming Community Events" in formatted
    assert first["title"] in formatted


# --- 3. Resource & FAQ Assistant Tests ---
def test_resource_assistant_search_and_faq():
    all_res = resource_assistant.search_resources()
    assert len(all_res) > 0

    gh_res = resource_assistant.search_resources(query="github")
    assert any("github" in r["title"].lower() or "github" in r.get("tags", []) for r in gh_res)

    faq_res = resource_assistant.search_resources(category="FAQ")
    assert len(faq_res) > 0
    assert any("link" in r["title"].lower() for r in faq_res)

    formatted = resource_assistant.format_resources_response(faq_res)
    assert "Community Resources" in formatted


# --- 4. GitHub Helper Tests ---
def test_github_helper_returns_repo_and_guide():
    repo_info = github_helper.get_bound_repository("gdg_mcet")
    assert "repository_name" in repo_info
    assert "Thread_agent" in repo_info["repository_name"]

    guide = github_helper.format_github_response(repo_info)
    assert "How to Contribute" in guide
    assert "pytest" in guide
    assert repo_info["url"] in guide


# --- 5. Cross-Platform Account Link Tool Tests ---
def test_account_link_tool_lifecycle():
    tool = account_link_tool
    # Step 1: Generate link token on Discord
    token = tool.generate_link_token(
        initiating_platform="discord",
        initiating_account_id="discord_snowflake_111",
        initiating_username="discord_alice",
        person_id="person_alice_uuid",
        org_id="gdg_mcet"
    )
    assert token.startswith("LINK-")

    # Step 2: Attempt same-platform redemption should fail
    same_ok, same_msg = tool.redeem_link_token(
        token=token,
        target_platform="discord",
        target_account_id="discord_snowflake_222",
        target_username="discord_bob",
        org_id="gdg_mcet"
    )
    assert same_ok is False
    assert "already generated on Discord" in same_msg

    # Step 3: Redeem on Telegram should succeed
    ok, msg = tool.redeem_link_token(
        token=token,
        target_platform="telegram",
        target_account_id="telegram_user_999",
        target_username="telegram_alice",
        org_id="gdg_mcet"
    )
    assert ok is True
    assert "Account Successfully Linked" in msg
    assert "Telegram" in msg

    # Step 4: Re-redeem used token should fail
    re_ok, re_msg = tool.redeem_link_token(
        token=token,
        target_platform="slack",
        target_account_id="slack_user_888",
        target_username="slack_alice",
        org_id="gdg_mcet"
    )
    assert re_ok is False
    assert "already been redeemed" in re_msg


# --- 6. Hybrid Intent Router Tests ---
def test_intent_classification():
    ws = get_workspace("gdg_mcet")

    # Command triggers
    c1, t1, _, _ = classify_intent_and_routing("!events", ws)
    assert c1 == "TOOL_EXECUTION" and t1 == "events"

    c2, t2, _, _ = classify_intent_and_routing("!github", ws)
    assert c2 == "TOOL_EXECUTION" and t2 == "github"

    c3, t3, _, _ = classify_intent_and_routing("!summary", ws)
    assert c3 == "TOOL_EXECUTION" and t3 == "summary"

    c4, t4, a4, _ = classify_intent_and_routing("!link LINK-12345", ws)
    assert c4 == "TOOL_EXECUTION" and t4 == "link" and a4 == "LINK-12345"

    # Conversational greetings
    c5, _, _, _ = classify_intent_and_routing("Hello! How are you doing today?", ws)
    assert c5 == "GENERAL_KNOWLEDGE"

    c6, _, _, _ = classify_intent_and_routing("hi", ws)
    assert c6 == "GENERAL_KNOWLEDGE"

    # Natural language tool requests
    c7, t7, _, _ = classify_intent_and_routing("When is the next upcoming workshop?", ws)
    assert c7 == "TOOL_EXECUTION" and t7 == "events"

    # Organizational queries
    c8, _, _, _ = classify_intent_and_routing("What was the approved budget for DevFest?", ws)
    assert c8 == "ORGANIZATIONAL_FACTS"


# --- 7. Full Graph Execution with Tools and General Knowledge ---
def test_graph_executes_events_tool():
    state = GraphState(query="!events", organization_id="gdg_mcet")
    res = app_graph.invoke(state)
    assert res["intent_category"] == "TOOL_EXECUTION"
    assert res["tool_name"] == "events"
    assert "Upcoming Community Events" in res["final_answer"]


def test_graph_executes_github_tool():
    state = GraphState(query="!github", organization_id="gdg_mcet")
    res = app_graph.invoke(state)
    assert res["intent_category"] == "TOOL_EXECUTION"
    assert "Thread_agent" in res["final_answer"]
    assert "How to Contribute" in res["final_answer"]


def test_graph_executes_conversational_greeting_without_error():
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

    p = principal()
    result = service.send_message(p, ChannelType.SLACK, "C_TEST", "Hello! Can you help me?", "general-key-1")

    assert result["status"] == "sent"
    assert len(calls) == 1
    assert "insufficient evidence" not in calls[0].lower()

    session_key = conversation_store.format_session_key(ChannelType.SLACK.value, "C_TEST", p.user_id)
    history = conversation_store.get_recent_turns(session_key, limit=5)
    assert any(h["content"] == "Hello! Can you help me?" for h in history)
