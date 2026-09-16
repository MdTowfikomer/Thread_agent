from app.graph.state import GraphState
from app.graph.workflow import app_graph
from app.tools.github_helper import github_helper


def test_github_tool_returns_live_tool_evidence(monkeypatch):
    repo = {
        "repository_name": "MdTowfikomer/Thread_agent",
        "url": "https://github.com/MdTowfikomer/Thread_agent",
        "is_active": True,
    }
    commits = [{
        "sha": "b50aa97",
        "message": "feat(frontend): show query progress",
        "author": "Md Towfik Omer",
        "date": "2026-09-16T00:00:00Z",
        "url": "https://github.com/MdTowfikomer/Thread_agent/commit/b50aa97",
    }]
    monkeypatch.setattr(github_helper, "get_bound_repository", lambda _org: repo)
    monkeypatch.setattr(github_helper, "get_recent_commits", lambda **_kwargs: commits)

    result = app_graph.invoke(GraphState(
        query="What is the latest activity in the connected repository?",
        organization_id="gdg_mcet",
    ))

    evidence = result["evidence_pack"]
    assert evidence is not None
    assert evidence.sufficient_evidence is True
    assert evidence.receipt.retrieval_strategy == "authoritative_github_tool"
    assert evidence.citations[0].source_uri == commits[0]["url"]
    assert evidence.citations[0].snippet == commits[0]["message"]
