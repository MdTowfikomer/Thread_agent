import pytest
from app.memory.retrieval import retrieval_service, derive_access_context
from app.memory.store import memory_store
from app.core.canonical import MemoryChunk, SourceType, PermissionLevel

def test_retrieval_contamination_exclusion():
    org_id = "gdg_mcet"
    ctx = derive_access_context(user_id="anon", organization_id=org_id, role_id="community")

    # Ingest test chunk representing a user query / bot mention
    test_chunk_1 = MemoryChunk(
        source_record_id="rec_msg_100",
        organization_id=org_id,
        source_type=SourceType.TELEGRAM,
        author="GDGCThreadBot",
        content="what is GDG MCET's upcoming event announced?",
        permission=PermissionLevel.PUBLIC_COMMUNITY,
        provenance={"is_bot_mention": True, "message_id": "msg_100"}
    )

    test_chunk_2 = MemoryChunk(
        source_record_id="rec_msg_101",
        organization_id=org_id,
        source_type=SourceType.TELEGRAM,
        author="Student123",
        content="The upcoming GDG MCET workshop is on October 15th at 10 AM in Hall B.",
        permission=PermissionLevel.PUBLIC_COMMUNITY,
        provenance={"is_bot_mention": False, "message_id": "msg_101"}
    )

    memory_store.add_chunk(test_chunk_1)
    memory_store.add_chunk(test_chunk_2)

    try:
        # Query matching exact content of test_chunk_1
        query = "what is GDG MCET's upcoming event announced?"

        # 1. Test excluding message_id "msg_100"
        evidence_pack = retrieval_service.retrieve(
            query=query,
            access_context=ctx,
            top_k=5,
            exclude_message_ids=["msg_100", "rec_msg_100"]
        )

        selected_ids = evidence_pack.receipt.selected_item_ids
        assert test_chunk_1.id not in selected_ids, "Message msg_100 was retrieved despite being in exclude_message_ids"

        # 2. Test bot mention exclusion
        assert test_chunk_1.id not in selected_ids, "Unapproved bot mention was retrieved as evidence"

    finally:
        # Cleanup
        memory_store._chunks.pop(test_chunk_1.id, None)
        memory_store._chunks.pop(test_chunk_2.id, None)
        memory_store._embeddings.pop(test_chunk_1.id, None)
        memory_store._embeddings.pop(test_chunk_2.id, None)
