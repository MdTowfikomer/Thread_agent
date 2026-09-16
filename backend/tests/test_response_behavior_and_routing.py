import os
import pytest
from unittest.mock import patch, MagicMock

from app.core.auth import AuthenticatedPrincipal
from app.core.canonical import ChannelType, PermissionLevel
from app.channels.inbound_service import inbound_agent_query_service
from app.graph.workflow import app_graph, classify_intent_and_routing
from app.core.organizations import get_workspace
from app.tools.github_helper import github_helper
from app.tools.events import event_assistant
from app.memory.conversation import conversation_store


from app.core.canonical import AccessContext

@pytest.fixture
def test_principal():
    ctx = AccessContext(
        user_id="user_test_123",
        organization_id="gdg_mcet",
        role_id="community_member",
        user_permission=PermissionLevel.PUBLIC_COMMUNITY,
        allowed_scopes=[PermissionLevel.PUBLIC_COMMUNITY]
    )
    return AuthenticatedPrincipal(
        user_id="user_test_123",
        organization_id="gdg_mcet",
        access_context=ctx
    )


# 1. First-turn versus second-turn tone
def test_first_turn_vs_second_turn_tone(test_principal):
    session_key = conversation_store.format_session_key("web_chat", "dest_tone_test", test_principal.user_id)
    
    # First turn
    res_1 = inbound_agent_query_service.process_query(
        query="Hello",
        organization_id=test_principal.organization_id,
        principal=test_principal,
        platform=ChannelType.WEB_CHAT,
        destination_id="dest_tone_test"
    )
    ans_1 = res_1.get("answer", "")
    assert "ThreadAgent" in ans_1 or "community assistant" in ans_1.lower()

    # Second turn
    res_2 = inbound_agent_query_service.process_query(
        query="Hello again",
        organization_id=test_principal.organization_id,
        principal=test_principal,
        platform=ChannelType.WEB_CHAT,
        destination_id="dest_tone_test"
    )
    ans_2 = res_2.get("answer", "")
    assert "I am ThreadAgent, your community assistant" not in ans_2
    assert "Based on verified organizational records" not in ans_2


# 2. Empty events result
def test_empty_events_result():
    with patch.object(event_assistant, "list_upcoming_events", return_value=[]):
        formatted = event_assistant.format_events_response([])
        assert "no published events" in formatted.lower() or "no published events scheduled" in formatted.lower()


# 3. Latest commit (exactly 1 commit)
def test_latest_commit(test_principal):
    mock_commits = [
        {"sha": "abc1234", "message": "feat: initial commit", "author": "Alice", "date": "2026-09-17T00:00:00Z"},
        {"sha": "def5678", "message": "fix: bug fix", "author": "Bob", "date": "2026-09-16T00:00:00Z"},
        {"sha": "789ghi0", "message": "docs: update readme", "author": "Charlie", "date": "2026-09-15T00:00:00Z"},
    ]
    with patch.object(github_helper, "get_recent_commits", return_value=mock_commits):
        res = inbound_agent_query_service.process_query(
            query="what is the latest commit?",
            organization_id=test_principal.organization_id,
            principal=test_principal,
            platform=ChannelType.WEB_CHAT,
            destination_id="dest_commit_1"
        )
        ans = res.get("answer", "")
        assert "`abc1234`" in ans
        assert "`def5678`" not in ans
        assert "showing 1" in ans.lower() or "(showing 1)" in ans


# 4. Last five commits (exactly 5 commits)
def test_last_five_commits(test_principal):
    mock_commits = [
        {"sha": f"sha{i}", "message": f"commit msg {i}", "author": "Dev", "date": "2026-09-17T00:00:00Z"}
        for i in range(1, 10)
    ]
    with patch.object(github_helper, "get_recent_commits", return_value=mock_commits):
        res = inbound_agent_query_service.process_query(
            query="show me the last 5 commits",
            organization_id=test_principal.organization_id,
            principal=test_principal,
            platform=ChannelType.WEB_CHAT,
            destination_id="dest_commit_5"
        )
        ans = res.get("answer", "")
        assert "`sha1`" in ans
        assert "`sha5`" in ans
        assert "`sha6`" not in ans
        assert "showing 5" in ans.lower() or "(showing 5)" in ans


# 5. Unavailable GitHub connection
def test_unavailable_github_connection(test_principal):
    with patch.object(github_helper, "get_recent_commits", return_value=None):
        res = inbound_agent_query_service.process_query(
            query="show recent commits",
            organization_id=test_principal.organization_id,
            principal=test_principal,
            platform=ChannelType.WEB_CHAT,
            destination_id="dest_github_down"
        )
        ans = res.get("answer", "")
        assert "GitHub connection is currently unavailable" in ans


# 6. No unrelated GitHub context in an event response
def test_no_unrelated_github_context_in_event_response(test_principal):
    mock_events = [
        {
            "id": "ev1",
            "title": "Flutter & AI Workshop",
            "description": "Learn to build cross-platform apps with Gemini",
            "start_time": "2026-10-01 10:00:00",
            "end_time": None,
            "location_or_url": "Hall A",
            "rsvp_url": "https://gdg.community.dev/events/1",
            "speakers": ["Jane Doe"],
            "status": "upcoming"
        }
    ]
    with patch.object(event_assistant, "list_upcoming_events", return_value=mock_events):
        res = inbound_agent_query_service.process_query(
            query="when is the next workshop?",
            organization_id=test_principal.organization_id,
            principal=test_principal,
            platform=ChannelType.WEB_CHAT,
            destination_id="dest_events_clean"
        )
        ans = res.get("answer", "")
        assert "Flutter & AI Workshop" in ans
        assert "github" not in ans.lower()
        assert "git clone" not in ans.lower()
        assert "repository" not in ans.lower()
