import os
import pytest
from unittest.mock import MagicMock, patch
from pathlib import Path
from datetime import datetime, timezone
from fastapi.testclient import TestClient

os.environ["THREAD_FORCE_DETERMINISTIC_EMBEDDINGS"] = "1"
os.environ["APP_ENV"] = "production"
os.environ["THREAD_DEMO_AUTH_ENABLED"] = "false"
os.environ["THREAD_ALLOW_GUEST_MODE"] = "false"
os.environ["THREAD_JWT_SECRET"] = "test-secret-cryptographically-secure-32-chars-long-abc12345"

from app.core.config import settings
from app.core.canonical import (
    MemoryChunk,
    SourceRecord,
    SourceType,
    PermissionLevel,
    AccessContext
)
from app.core.auth import create_access_token
from app.memory.supabase_store import SupabaseMemoryStore
from app.memory.repository import MemoryRepository, memory_repository
from app.memory.retrieval import RetrievalService
from app.memory.store import MemoryStore
from app.channels.approval import ApprovalStore
from app.main import app

client = TestClient(app)

# 1. P0 & P1: Verify Schema RLS, Transactional RPCs, SECURITY INVOKER, and Provenance Columns
def test_supabase_schema_rls_and_security_hardening():
    schema_path = Path(__file__).resolve().parent.parent / "app" / "data" / "supabase_schema.sql"
    assert schema_path.exists(), "supabase_schema.sql must exist"
    
    sql = schema_path.read_text(encoding="utf-8")

    # Extension & vector dimension
    assert "CREATE EXTENSION IF NOT EXISTS vector;" in sql
    assert "embedding VECTOR(768) NOT NULL" in sql

    # Provenance columns on memory_chunks
    assert "source_uri TEXT" in sql
    assert "source_timestamp TIMESTAMPTZ NOT NULL" in sql
    assert "source_hash TEXT" in sql
    assert "ingestion_version TEXT" in sql
    assert "policy_version TEXT" in sql
    assert "embedding_model TEXT" in sql
    assert "embedding_dimension INT" in sql

    # P0: Row Level Security enabled and forced on all tables
    assert "ALTER TABLE source_records ENABLE ROW LEVEL SECURITY;" in sql
    assert "ALTER TABLE source_records FORCE ROW LEVEL SECURITY;" in sql
    assert "ALTER TABLE memory_chunks ENABLE ROW LEVEL SECURITY;" in sql
    assert "ALTER TABLE memory_chunks FORCE ROW LEVEL SECURITY;" in sql
    assert "ALTER TABLE guild_installations FORCE ROW LEVEL SECURITY;" in sql
    assert "ALTER TABLE import_approvals FORCE ROW LEVEL SECURITY;" in sql

    # P0: Zero-direct-access: All privileges revoked from public, anon, and authenticated
    assert "REVOKE ALL ON ALL TABLES IN SCHEMA public FROM PUBLIC, anon, authenticated;" in sql
    assert "GRANT ALL ON ALL TABLES IN SCHEMA public TO service_role;" in sql
    assert "REVOKE EXECUTE ON FUNCTION hybrid_search(TEXT, VECTOR(768), INT, TEXT, TEXT[], INT) FROM PUBLIC, anon, authenticated;" in sql
    assert "GRANT EXECUTE ON FUNCTION hybrid_search(TEXT, VECTOR(768), INT, TEXT, TEXT[], INT) TO service_role;" in sql
    assert "SECURITY INVOKER" in sql

    # P1: Transactional RPCs defined and restricted
    assert "CREATE OR REPLACE FUNCTION persist_record_and_chunks" in sql
    assert "REVOKE EXECUTE ON FUNCTION persist_record_and_chunks(JSONB, JSONB) FROM PUBLIC, anon, authenticated;" in sql
    assert "CREATE OR REPLACE FUNCTION promote_quarantined_chunks" in sql
    assert "REVOKE EXECUTE ON FUNCTION promote_quarantined_chunks(TEXT, TEXT, TEXT, TEXT) FROM PUBLIC, anon, authenticated;" in sql

    # P1: Explicitly ordered CTEs before LIMIT
    assert "ORDER BY pfc.embedding <=> query_embedding ASC" in sql
    assert "LIMIT match_count * 3" in sql
    assert "ORDER BY ts_rank_cd(pfc.fts, plainto_tsquery('english', query_text)) DESC" in sql

# 2. P0: Cross-organization public data denial
def test_cross_organization_public_data_denial():
    # Token for Acme Corp user
    acme_token = create_access_token(
        user_id="usr_acme_alice",
        organization_id="acme_corp"
    )

    # Attempt to access GDG MCET memories (even public chunks) using Acme token
    res = client.get(
        f"{settings.API_PREFIX}/memories?organization_id=gdg_mcet",
        headers={"Authorization": f"Bearer {acme_token}"}
    )
    # Cross-tenant access is strictly denied with 403 Forbidden
    assert res.status_code == 403
    assert "Cross-organization memory access is denied" in res.json()["detail"]

    # Repository tenant isolation
    repo = MemoryRepository(in_memory=MemoryStore(), supabase=None)
    chunk_gdg = MemoryChunk(
        id="chk_gdg_pub",
        source_record_id="rec_gdg",
        organization_id="gdg_mcet",
        source_type=SourceType.DISCORD,
        author="Arjun",
        title="GDG Public Event",
        content="Welcome to GDG event",
        permission=PermissionLevel.PUBLIC_COMMUNITY,
        embedding=[0.01] * 768
    )
    chunk_acme = MemoryChunk(
        id="chk_acme_pub",
        source_record_id="rec_acme",
        organization_id="acme_corp",
        source_type=SourceType.DISCORD,
        author="Alice",
        title="Acme Public Event",
        content="Welcome to Acme event",
        permission=PermissionLevel.PUBLIC_COMMUNITY,
        embedding=[0.01] * 768
    )
    repo.save_chunk(chunk_gdg)
    repo.save_chunk(chunk_acme)

    acme_chunks = repo.get_chunks_for_organization("acme_corp")
    assert len(acme_chunks) == 1
    assert acme_chunks[0].id == "chk_acme_pub"
    assert "chk_gdg_pub" not in [c.id for c in acme_chunks]

# 3. P0: RPC denial with publishable key
def test_rpc_denial_with_publishable_key():
    anon_client = MagicMock()
    # Simulates PostgREST permission denial for anon role on RPC functions
    anon_client.rpc.side_effect = Exception("PGRST301: permission denied for function")

    store = SupabaseMemoryStore(supabase_url="https://test.supabase.co", supabase_key="anon-publishable-key")
    store._client = anon_client

    # 1. hybrid_search denied
    results = store.hybrid_search(
        query="What is the internal budget?",
        query_embedding=[0.1] * 768,
        organization_id="gdg_mcet",
        allowed_scopes=[PermissionLevel.INTERNAL_CORE]
    )
    assert results == []

    # 2. persist_record_and_chunks denied
    rec = SourceRecord(
        id="rec_attack",
        organization_id="gdg_mcet",
        source_type=SourceType.DISCORD,
        author_name="Attacker",
        raw_content="Injected text",
        permission=PermissionLevel.INTERNAL_CORE
    )
    with pytest.raises(Exception) as exc_persist:
        store.persist_record_and_chunks(rec, [])
    assert "permission denied" in str(exc_persist.value)

    # 3. promote_quarantined_chunks denied
    promoted = store.promote_quarantined_chunks("gdg_mcet", "hash123", "usr_attacker", "appr123")
    assert promoted == []

# 4. P1: Rollback on failed chunk write (transactional persistence)
def test_rollback_on_failed_chunk_write():
    mock_supabase = MagicMock(spec=SupabaseMemoryStore)
    mock_supabase.is_configured = True
    # Simulate RPC failure during transaction (e.g. database constraint error or connection error)
    mock_supabase.persist_record_and_chunks.side_effect = RuntimeError("PostgreSQL RPC transaction aborted: constraint error")

    local_store = MemoryStore()
    repo = MemoryRepository(in_memory=local_store, supabase=mock_supabase)

    record = SourceRecord(
        id="rec_fail_tx",
        organization_id="gdg_mcet",
        source_type=SourceType.DISCORD,
        author_name="Arjun",
        raw_content="Venue details",
        permission=PermissionLevel.PUBLIC_COMMUNITY
    )
    chunk = MemoryChunk(
        id="chk_fail_tx",
        source_record_id="rec_fail_tx",
        organization_id="gdg_mcet",
        source_type=SourceType.DISCORD,
        author="Arjun",
        title="Venue",
        content="Auditorium 3",
        permission=PermissionLevel.PUBLIC_COMMUNITY,
        embedding=[0.05] * 768
    )

    # Transactional persistence must raise exception on DB failure
    with pytest.raises(RuntimeError) as exc_info:
        repo.save_record_and_chunks(record, [chunk])
    assert "PostgreSQL RPC transaction aborted" in str(exc_info.value)

    # ATOMIC GUARANTEE: In-memory cache is NOT updated / remains completely clean
    assert local_store.get_record("rec_fail_tx") is None, "Cache must not contain aborted record"
    assert local_store.get_chunk("chk_fail_tx") is None, "Cache must not contain aborted chunk"

# 5. P1: Restart-safe approval across workers
def test_restart_safe_approval_across_workers():
    mock_supabase = MagicMock(spec=SupabaseMemoryStore)
    mock_supabase.is_configured = True

    # Supabase has the quarantined chunk and executes durable promotion
    mock_supabase.promote_quarantined_chunks.return_value = ["chk_quarantined_01"]

    local_store = MemoryStore()
    # Cache is empty (simulating process restart or second worker)
    local_store.clear()
    assert local_store.get_chunk("chk_quarantined_01") is None

    repo = MemoryRepository(in_memory=local_store, supabase=mock_supabase)
    local_audit_file = Path(__file__).resolve().parent / ".test_restart_approval.jsonl"
    if local_audit_file.exists():
        local_audit_file.unlink()

    try:
        approval_store = ApprovalStore(audit_file_path=local_audit_file)

        # Worker calls approve_import
        with patch("app.channels.approval.memory_repository", repo):
            appr = approval_store.approve_import(
                organization_id="gdg_mcet",
                import_hash="hash_quarantined_abc",
                approved_by_user_id="usr_arjun"
            )

        assert appr is not None
        assert "chk_quarantined_01" in appr.promoted_chunk_ids
        mock_supabase.promote_quarantined_chunks.assert_called_once_with(
            organization_id="gdg_mcet",
            import_hash="hash_quarantined_abc",
            approved_by_user_id="usr_arjun",
            approval_id=appr.id
        )
    finally:
        if local_audit_file.exists():
            local_audit_file.unlink()

# 6. P2: Original timestamp round-trips without fabrication
def test_original_timestamp_round_trips_without_fabrication():
    store = SupabaseMemoryStore(supabase_url="https://test.supabase.co", supabase_key="test-key")

    historical_timestamp = datetime(2023, 11, 20, 9, 15, 30, tzinfo=timezone.utc)
    historical_created_at = datetime(2023, 11, 20, 9, 16, 0, tzinfo=timezone.utc)

    chunk = MemoryChunk(
        id="chk_historical_01",
        source_record_id="rec_hist_01",
        organization_id="gdg_mcet",
        source_type=SourceType.DISCORD,
        source_uri="https://discord.com/channels/1122/5566/msg_hist_99",
        author="Arjun",
        title="Historical Budget Post",
        content="Original 2023 budget allocation",
        timestamp=historical_timestamp,
        created_at=historical_created_at,
        permission=PermissionLevel.INTERNAL_CORE,
        tags=["archive"],
        embedding=[0.05] * 768,
        provenance={"original_event_id": "evt_2023"}
    )

    # 1. Format for DB
    db_dict = store._format_chunk_for_db(chunk)
    assert db_dict["source_timestamp"] == historical_timestamp.isoformat()
    assert db_dict["created_at"] == historical_created_at.isoformat()
    assert db_dict["source_uri"] == "https://discord.com/channels/1122/5566/msg_hist_99"

    # 2. Reconstruct from DB row
    db_row = {
        **db_dict,
        "source_timestamp": db_dict["source_timestamp"],
        "created_at": db_dict["created_at"]
    }
    reconstructed = store._row_to_chunk(db_row)

    # Provenance guarantees: Exact timestamp and URI match, no datetime.now() fabrication
    assert reconstructed.timestamp == historical_timestamp
    assert reconstructed.created_at == historical_created_at
    assert reconstructed.source_uri == "https://discord.com/channels/1122/5566/msg_hist_99"
    assert reconstructed.provenance["source_uri"] == "https://discord.com/channels/1122/5566/msg_hist_99"

# 7. P2: Reject malformed or missing persisted timestamps instead of substituting now()
def test_malformed_persisted_timestamp_rejection():
    store = SupabaseMemoryStore(supabase_url="https://test.supabase.co", supabase_key="test-key")

    base_row = {
        "id": "chk_corrupted_ts",
        "source_record_id": "rec_001",
        "organization_id": "gdg_mcet",
        "source_type": "discord",
        "source_uri": "https://discord.com/channels/1/2/3",
        "author": "Alice",
        "title": "Title",
        "content": "Content",
        "permission": "PUBLIC_COMMUNITY",
        "provenance": {}
    }

    # Case 1: missing source_timestamp entirely
    row_missing = dict(base_row)
    with pytest.raises(ValueError) as exc_missing:
        store._row_to_chunk(row_missing)
    assert "missing a valid, uncorrupted source_timestamp" in str(exc_missing.value)

    # Case 2: malformed/unparseable source_timestamp
    row_corrupt = dict(base_row)
    row_corrupt["source_timestamp"] = "corrupted-unparseable-timestamp-string"
    with pytest.raises(ValueError) as exc_corrupt:
        store._row_to_chunk(row_corrupt)
    assert "missing a valid, uncorrupted source_timestamp" in str(exc_corrupt.value)

    # Case 3: chunk missing timestamp when formatting for DB
    chunk_no_ts = MemoryChunk(
        id="chk_no_ts",
        source_record_id="rec_001",
        organization_id="gdg_mcet",
        source_type=SourceType.DISCORD,
        author="Alice",
        content="Content",
        permission=PermissionLevel.PUBLIC_COMMUNITY,
        embedding=[0.01] * 768
    )
    chunk_no_ts.timestamp = None
    chunk_no_ts.provenance = {}
    with pytest.raises(ValueError) as exc_format:
        store._format_chunk_for_db(chunk_no_ts)
    assert "missing source timestamp" in str(exc_format.value)

# 8. P1: RRF candidate selection and anti-bluffing threshold
def test_rrf_scoring_and_anti_bluffing_threshold():
    store = SupabaseMemoryStore(supabase_url="https://test.supabase.co", supabase_key="test-key")
    mock_client = MagicMock()
    store._client = mock_client

    mock_client.table.return_value.select.return_value.eq.return_value.execute.return_value.count = 10
    mock_client.table.return_value.select.return_value.eq.return_value.in_.return_value.execute.return_value.count = 5

    # Low similarity, no query term overlap -> Must NOT be marked as sufficient evidence
    mock_client.rpc.return_value.execute.return_value.data = [
        {
            "id": "chk_irrelevant_01",
            "source_record_id": "rec_01",
            "organization_id": "gdg_mcet",
            "source_type": "discord",
            "source_uri": "https://discord.com/channels/test",
            "source_timestamp": "2026-01-01T00:00:00+00:00",
            "author": "Anon",
            "title": "Random Lunch Topic",
            "content": "Let us grab some pizza after the meeting",
            "permission": "PUBLIC_COMMUNITY",
            "tags": ["social"],
            "similarity": 0.25,
            "fts_rank": 0.0,
            "combined_score": 0.010,
            "dense_rank": 10,
            "lexical_rank": 0
        }
    ]

    local_store = MemoryStore()
    service = RetrievalService(store=local_store, supabase_store=store)

    access_context = AccessContext(
        user_id="usr_rohit",
        organization_id="gdg_mcet",
        role_id="community_member",
        user_permission=PermissionLevel.PUBLIC_COMMUNITY,
        allowed_scopes=[PermissionLevel.PUBLIC_COMMUNITY]
    )

    evidence_irrelevant = service._retrieve_supabase(
        query="What is the venue for the workshop?",
        access_context=access_context,
        top_k=3,
        threshold=0.45
    )

    # Anti-bluffing: Irrelevant match rejected
    assert evidence_irrelevant.sufficient_evidence is False
    assert len(evidence_irrelevant.citations) == 0

    # Substantive match with keyword overlap
    mock_client.rpc.return_value.execute.return_value.data = [
        {
            "id": "chk_substantive_01",
            "source_record_id": "rec_02",
            "organization_id": "gdg_mcet",
            "source_type": "discord",
            "source_uri": "https://discord.com/channels/test",
            "source_timestamp": "2026-03-01T10:00:00+00:00",
            "author": "Arjun",
            "title": "Workshop Venue Announcement",
            "content": "The workshop venue is Auditorium 3, Main Campus",
            "permission": "PUBLIC_COMMUNITY",
            "tags": ["workshop", "venue"],
            "similarity": 0.88,
            "fts_rank": 0.75,
            "combined_score": 0.033,
            "dense_rank": 1,
            "lexical_rank": 1
        }
    ]

    evidence_substantive = service._retrieve_supabase(
        query="What is the venue for the workshop?",
        access_context=access_context,
        top_k=3,
        threshold=0.45
    )

    assert evidence_substantive.sufficient_evidence is True
    assert len(evidence_substantive.citations) == 1
    assert evidence_substantive.citations[0].source_uri == "https://discord.com/channels/test"
    assert evidence_substantive.receipt.retrieval_strategy == "supabase_pgvector_fts_rrf_pre_acl"

# 8. Fallback to In-Memory Deterministic Store
def test_retrieval_service_offline_fallback():
    from app.data.seeds import get_seed_data
    local_store = MemoryStore()
    records, chunks, receipts = get_seed_data()
    for r in records:
        local_store.add_record(r)
    local_store.add_chunks(chunks)

    unconfigured_store = SupabaseMemoryStore(supabase_url="", supabase_key="")
    service = RetrievalService(store=local_store, supabase_store=unconfigured_store)

    access_context = AccessContext(
        user_id="usr_arjun",
        organization_id="gdg_mcet",
        role_id="lead_organizer",
        user_permission=PermissionLevel.INTERNAL_CORE,
        allowed_scopes=[PermissionLevel.INTERNAL_CORE, PermissionLevel.PUBLIC_COMMUNITY]
    )

    evidence = service.retrieve("What is the venue for the workshop?", access_context)
    assert evidence is not None
    assert evidence.receipt.retrieval_strategy == "deterministic_hybrid_cosine_lexical_pre_acl"
    assert len(evidence.citations) > 0
