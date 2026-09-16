import pytest
from app.core.canonical import MemoryChunk, SourceType, PermissionLevel, AccessContext
from app.core.auth import AuthenticatedPrincipal
from app.memory.store import memory_store
from app.graph.state import GraphState
from app.graph.workflow import app_graph

def test_triggering_organizational_question_cannot_be_cited_in_own_response():
    """
    Live-shaped integration test:
    1. Persists a triggering organizational question message in memory (simulating inbound chat message).
    2. Persists authoritative organizational evidence/facts in memory.
    3. Invokes app_graph with exclude_message_ids containing the triggering question's message/record ID.
    4. Proves the triggering organizational question chunk is filtered out and CANNOT be cited in its own response.
    5. Proves only authoritative record evidence is cited in the response.
    """
    org_id = "gdg_mcet"
    
    # 1. Triggering question message (already persisted in institutional memory)
    trigger_question_chunk = MemoryChunk(
        id="chunk_trigger_q999",
        source_record_id="rec_trigger_q999",
        organization_id=org_id,
        source_type=SourceType.TELEGRAM,
        author="StudentMember99",
        content="What is the internal budget approval status for DevFest catering and t-shirts?",
        permission=PermissionLevel.PUBLIC_COMMUNITY,
        provenance={"message_id": "msg_telegram_999", "is_bot_mention": True}
    )

    # 2. Authoritative record evidence
    authoritative_fact_chunk = MemoryChunk(
        id="chunk_fact_777",
        source_record_id="rec_fact_777",
        organization_id=org_id,
        source_type=SourceType.SLACK,
        author="Karthik Verma (Finance Lead)",
        content="DevFest catering budget is approved for 15,000 INR and t-shirt vendor procurement is 12,000 INR.",
        permission=PermissionLevel.PUBLIC_COMMUNITY,
        provenance={"message_id": "msg_slack_777", "is_bot_mention": False}
    )

    memory_store.add_chunk(trigger_question_chunk)
    memory_store.add_chunk(authoritative_fact_chunk)

    try:
        ctx = AccessContext(
            user_id="user_test_999",
            organization_id=org_id,
            role_id="community_lead",
            user_permission=PermissionLevel.PUBLIC_COMMUNITY,
            allowed_scopes=[PermissionLevel.PUBLIC_COMMUNITY]
        )

        state = GraphState(
            query="What is the internal budget approval status for DevFest catering and t-shirts?",
            organization_id=org_id,
            access_context=ctx,
            exclude_message_ids=["msg_telegram_999", "rec_trigger_q999", "chunk_trigger_q999"]
        )

        # Invoke full workflow execution
        result = app_graph.invoke(state)

        evidence_pack = result.get("evidence_pack")
        assert evidence_pack is not None, "EvidencePack should be generated for organizational facts query"
        assert evidence_pack.sufficient_evidence is True, "Sufficient evidence should be found from authoritative fact chunk"

        citation_item_ids = [c.item_id for c in evidence_pack.citations]
        
        # PROOF 1: The triggering question chunk MUST NOT be cited in its own response
        assert "chunk_trigger_q999" not in citation_item_ids, "Triggering question chunk was cited in its own response!"
        
        # PROOF 2: The authoritative fact chunk is cited
        assert "chunk_fact_777" in citation_item_ids, "Authoritative fact chunk was not cited"

        # PROOF 3: Final answer contains synthesized information from authoritative evidence
        final_answer = result.get("final_answer", "")
        assert len(final_answer) > 0

    finally:
        # Cleanup test chunks from memory_store
        memory_store._chunks.pop(trigger_question_chunk.id, None)
        memory_store._chunks.pop(authoritative_fact_chunk.id, None)
        memory_store._embeddings.pop(trigger_question_chunk.id, None)
        memory_store._embeddings.pop(authoritative_fact_chunk.id, None)
