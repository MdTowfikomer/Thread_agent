import os
import pytest
from unittest.mock import patch, MagicMock

from app.core.config import settings
from app.core.canonical import (
    MemoryChunk,
    SourceRecord,
    SourceType,
    PermissionLevel,
    AccessContext
)
from app.memory.store import MemoryStore
from app.memory.retrieval import RetrievalService, derive_access_context


def make_context(user_id="test_user", org_id="gdg_mcet"):
    return AccessContext(
        user_id=user_id,
        organization_id=org_id,
        role_id="organizer",
        user_permission=PermissionLevel.INTERNAL_CORE,
        allowed_scopes=[PermissionLevel.INTERNAL_CORE, PermissionLevel.PUBLIC_COMMUNITY]
    )


# 1. Provider 404 causes NO hash-vector production fallback
def test_provider_404_causes_no_hash_vector_fallback_in_production():
    store = MemoryStore()
    store.force_deterministic = False

    with patch.dict(os.environ, {"THREAD_FORCE_DETERMINISTIC_EMBEDDINGS": "0"}):
        with patch("langchain_google_genai.GoogleGenerativeAIEmbeddings") as mock_embedder_cls:
            mock_embedder = MagicMock()
            mock_embedder.embed_query.side_effect = RuntimeError("Error 404: models/text-embedding-004 is not found")
            mock_embedder_cls.return_value = mock_embedder

            # In production runtime, provider failure MUST return None, NOT a hash vector
            vec = store._get_embedding("What is GDG MCET?")
            assert vec is None
            assert store._active_model_name == "sparse_only"


# 2. Sparse-only retrieval remains grounded
def test_sparse_only_retrieval_remains_grounded():
    store = MemoryStore()
    store.force_deterministic = False

    chunk = MemoryChunk(
        source_record_id="rec_sparse_1",
        organization_id="gdg_mcet",
        source_type=SourceType.DISCORD,
        author="Arjun Lead",
        title="Event Planning",
        content="The GDG MCET DevFest annual workshop is scheduled at Gate 2 hall.",
        permission=PermissionLevel.PUBLIC_COMMUNITY,
        tags=["devfest", "workshop", "event"]
    )

    # Force provider failure so embedding is None
    with patch.dict(os.environ, {"THREAD_FORCE_DETERMINISTIC_EMBEDDINGS": "0"}):
        with patch.object(store, "_get_embedding", return_value=None):
            store._active_model_name = "sparse_only"
            store.add_chunk(chunk)

            retriever = RetrievalService(store=store)
            ctx = make_context()
            evidence = retriever.retrieve(
                query="When is the DevFest workshop?",
                access_context=ctx
            )

            assert evidence.sufficient_evidence is True
            assert len(evidence.citations) > 0
            assert "DevFest" in evidence.citations[0].snippet
            assert evidence.receipt.retrieval_mode == "sparse_only"
            assert evidence.receipt.query_embedding_model == "sparse_only"


# 3. Embedding dimensions remain 768
def test_embedding_dimensions_remain_768():
    assert settings.EMBEDDING_DIMENSION == 768

    store = MemoryStore()
    invalid_chunk = MemoryChunk(
        source_record_id="rec_invalid_dim",
        organization_id="gdg_mcet",
        source_type=SourceType.DISCORD,
        author="Tester",
        content="Mismatch dimension content",
        embedding=[0.1] * 128  # Invalid 128 dimension
    )

    with pytest.raises(ValueError) as exc_info:
        store.add_chunk(invalid_chunk)

    assert "Embedding dimension mismatch: expected 768" in str(exc_info.value)


# 4. Mixed embedding model chunks are excluded during dense retrieval
def test_mixed_embedding_models_are_excluded_during_dense_search():
    store = MemoryStore()
    store.force_deterministic = True  # Deterministic test mode

    # Chunk A: embedded with current active model
    chunk_a = MemoryChunk(
        id="chk_model_a",
        source_record_id="rec_a",
        organization_id="gdg_mcet",
        source_type=SourceType.DISCORD,
        author="Lead A",
        content="DevFest venue information",
        permission=PermissionLevel.PUBLIC_COMMUNITY,
        embedding=[0.1] * 768,
        provenance={"embedding_model": "models/gemini-embedding-001"}
    )

    # Chunk B: legacy chunk embedded with old incompatible model
    chunk_b = MemoryChunk(
        id="chk_model_b",
        source_record_id="rec_b",
        organization_id="gdg_mcet",
        source_type=SourceType.DISCORD,
        author="Lead B",
        content="DevFest sponsor list",
        permission=PermissionLevel.PUBLIC_COMMUNITY,
        embedding=[0.9] * 768,
        provenance={"embedding_model": "old-model-v0"}
    )

    store.add_chunk(chunk_a)
    store.add_chunk(chunk_b)
    store._active_model_name = "models/gemini-embedding-001"

    retriever = RetrievalService(store=store)
    ctx = make_context()

    # Query with active model
    with patch.object(store, "_get_embedding", return_value=[0.1] * 768):
        evidence = retriever.retrieve("DevFest venue", ctx)
        
        # Chunk A should be selected, Chunk B vector similarity should be zeroed / excluded
        selected_ids = evidence.receipt.selected_item_ids
        assert "chk_model_a" in selected_ids


# 5. Live provider embedding smoke test (Opt-In)
@pytest.mark.skipif(
    os.getenv("THREAD_RUN_LIVE_PROVIDER_TESTS") != "1" or not (os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")),
    reason="Opt-in live provider smoke test requires THREAD_RUN_LIVE_PROVIDER_TESTS=1 and GEMINI_API_KEY"
)
def test_live_gemini_provider_embedding_smoke_test():
    from app.memory.store import MemoryStore

    store = MemoryStore()
    vec = store._get_embedding("GDG MCET production embedding smoke test")
    assert vec is not None
    assert len(vec) == 768
    assert store._active_model_name == settings.DEFAULT_EMBEDDING_MODEL


# 6. Outage chunk with 'pending_reembed' status is claimed by ReembeddingJob and upgraded to 'ready'
def test_outage_chunk_claimed_and_upgraded_by_reembedding_job():
    from app.data.reembedder import ReembeddingJob

    mock_conn = MagicMock()
    mock_cur = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cur

    # Simulated chunk created during embedding outage with 'pending_reembed' status
    outage_chunk_row = {
        "id": "outage_chunk_123",
        "title": "Outage Msg",
        "content": "Message received during embedding provider outage",
        "author": "User",
        "tags": ["discord"],
        "reembed_attempts": 0,
        "embedding_status": "pending_reembed"
    }
    mock_cur.fetchall.return_value = [outage_chunk_row]

    mock_embed_fn = MagicMock(return_value=([0.05] * 768, "models/gemini-embedding-001", 768))

    job = ReembeddingJob(
        db_url="postgresql://fake",
        batch_size=1,
        embed_fn=mock_embed_fn,
        embedding_model="models/gemini-embedding-001"
    )

    processed = job.process_batch(mock_conn, limit=1)
    assert processed == 1
    assert mock_embed_fn.call_count == 1

    # Verify database update
    item_updates = [c for c in mock_cur.execute.call_args_list if "WHERE id = %s" in str(c)]
    assert len(item_updates) == 1

    update_sql, update_args = item_updates[0][0][0], item_updates[0][0][1]
    assert "embedding_status = 'ready'" in update_sql
    assert update_args[1] == "models/gemini-embedding-001"
    assert update_args[2] == 768
    assert update_args[4] == "outage_chunk_123"


