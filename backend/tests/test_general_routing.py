import os
import pytest
from app.graph.workflow import classify_intent_and_routing, app_graph, get_llm
from app.core.organizations import get_workspace
from app.graph.state import GraphState

def test_routing_deterministic_general_knowledge():
    ws = get_workspace("gdg_mcet")
    
    # 1. "what is the state space in RL?" -> GENERAL_KNOWLEDGE
    cat1, tool1, arg1, role1 = classify_intent_and_routing("what is the state space in RL?", ws)
    assert cat1 == "GENERAL_KNOWLEDGE"
    assert tool1 is None

    # 2. "can you explain reinforcement learning?" -> GENERAL_KNOWLEDGE
    cat2, tool2, arg2, role2 = classify_intent_and_routing("can you explain reinforcement learning?", ws)
    assert cat2 == "GENERAL_KNOWLEDGE"
    assert tool2 is None

    # 3. "what is GDG MCET's next workshop?" -> ORGANIZATIONAL_FACTS or TOOL_EXECUTION
    cat3, tool3, arg3, role3 = classify_intent_and_routing("what is GDG MCET's next workshop?", ws)
    assert cat3 in ("ORGANIZATIONAL_FACTS", "TOOL_EXECUTION")


def test_event_details_with_a_named_topic_use_organizational_retrieval():
    ws = get_workspace("gdg_mcet")
    category, tool, _, _ = classify_intent_and_routing(
        "What are the details and registration deadline for the RAG workshop?",
        ws,
    )

    assert category == "ORGANIZATIONAL_FACTS"
    assert tool is None


def test_general_knowledge_bypasses_retrieval():
    state = GraphState(
        query="what is the state space in RL?",
        organization_id="gdg_mcet"
    )
    res = app_graph.invoke(state)
    
    assert res["intent_category"] == "GENERAL_KNOWLEDGE"
    # evidence_pack should be None because vector retrieval is bypassed
    assert res.get("evidence_pack") is None


@pytest.mark.skipif(
    os.environ.get("THREAD_RUN_LIVE_PROVIDER_TESTS") != "1",
    reason="Requires THREAD_RUN_LIVE_PROVIDER_TESTS=1 environment variable"
)
def test_live_gemini_provider_smoke():
    llm = get_llm()
    assert llm is not None, "get_llm() returned None despite THREAD_RUN_LIVE_PROVIDER_TESTS=1"
    response = llm.invoke("Say 'ThreadAgent live test success' and nothing else.")
    text = response.content if hasattr(response, "content") else str(response)
    assert "ThreadAgent live test success" in text
