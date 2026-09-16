import os
import pytest
from app.core.canonical import ChannelType, AccessContext, PermissionLevel
from app.core.auth import AuthenticatedPrincipal
from app.channels.inbound_service import inbound_agent_query_service, validate_output, is_substantially_echoing
from app.memory.conversation import conversation_store
from app.memory.repository import memory_repository

def setup_module():
    os.environ["THREAD_FORCE_DETERMINISTIC_SYNTHESIS"] = "1"
    os.environ["THREAD_ALLOW_OFFLINE_BINDINGS"] = "1"

def make_principal(user_id="test_user", org_id="gdg_mcet"):
    ctx = AccessContext(
        user_id=user_id,
        organization_id=org_id,
        role_id="organizer",
        user_permission=PermissionLevel.INTERNAL_CORE,
        allowed_scopes=[PermissionLevel.INTERNAL_CORE, PermissionLevel.PUBLIC_COMMUNITY]
    )
    return AuthenticatedPrincipal(
        user_id=user_id,
        organization_id=org_id,
        access_context=ctx
    )


def test_output_validator_anti_echo():
    """Verify pre-send output validator blocks prompt echoes and recent turn echoes."""
    # Direct echo
    query = "can you see this?"
    assert is_substantially_echoing("can you see this?", query) is True
    validated = validate_output("can you see this?", query)
    assert validated != "can you see this?"
    assert "online" in validated.lower() or "active" in validated.lower() or "see your message" in validated.lower()

    # Capability echo
    query2 = "what can you do?"
    assert is_substantially_echoing("what can you do?", query2) is True
    val2 = validate_output("what can you do?", query2)
    assert val2 != "what can you do?"
    assert "threadagent" in val2.lower() or "assistant" in val2.lower() or "events" in val2.lower()

    # Empty response fallback
    val_empty = validate_output("", "some query")
    assert "can't reach the language model" in val_empty.lower()


def test_inbound_query_service_conversational_queries():
    """
    Contract test:
    1. 'can you see this?' -> direct synthesis, NO retrieval, NO echo.
    2. 'what can you do?' -> direct synthesis, NO retrieval, NO echo.
    3. 'what tools do you have?' -> direct synthesis, NO retrieval, NO echo.
    4. 'what is the state space in RL?' -> general knowledge, NO retrieval, NO echo.
    """
    principal = make_principal()

    test_queries = [
        "can you see this?",
        "what can you do?",
        "what tools do you have?",
        "what is the state space in RL?"
    ]

    for q in test_queries:
        res = inbound_agent_query_service.process_query(
            query=q,
            organization_id="gdg_mcet",
            principal=principal,
            platform=ChannelType.WEB_CHAT,
            destination_id="web_chat"
        )
        assert res["query"] == q
        assert res["answer"] is not None and len(res["answer"]) > 0
        assert not is_substantially_echoing(res["answer"], q)
        assert res["citations"] == []
        assert res["sufficient_evidence"] is False or res["intent_category"] == "GENERAL_KNOWLEDGE"

        # Verify turn was recorded in conversation_turns
        session_key = conversation_store.format_session_key("web_chat", "web_chat", principal.user_id)
        turns = conversation_store.get_recent_turns(session_key=session_key, organization_id="gdg_mcet", limit=10)
        assert len(turns) >= 2


def test_inbound_query_service_organizational_query():
    """
    Contract test:
    'what is GDG MCET's sponsorship budget for DevFest?' -> organizational facts query -> ACL-protected retrieval triggered.
    """
    principal = make_principal()
    query = "what is GDG MCET's sponsorship budget for DevFest?"

    res = inbound_agent_query_service.process_query(
        query=query,
        organization_id="gdg_mcet",
        principal=principal,
        platform=ChannelType.WEB_CHAT,
        destination_id="web_chat"
    )

    assert res["query"] == query
    assert res["intent_category"] == "ORGANIZATIONAL_FACTS"
    assert res["answer"] is not None
    assert not is_substantially_echoing(res["answer"], query)


def test_agent_directed_messages_never_stored_in_source_records():
    """
    Verify agent-directed queries are saved exclusively in conversation_turns, NEVER in source_records / memory_chunks.
    """
    principal = make_principal("agent_turn_user")
    query = "what tools do you have?"

    records_before = len(memory_repository.in_memory._records)

    inbound_agent_query_service.process_query(
        query=query,
        organization_id="gdg_mcet",
        principal=principal,
        platform=ChannelType.WEB_CHAT,
        destination_id="web_chat"
    )

    records_after = len(memory_repository.in_memory._records)
    assert records_after == records_before, "Agent-directed query must NEVER create a source_record in Core Memory."
