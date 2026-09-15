import os
import uuid
import pytest
from datetime import datetime, timezone
from dotenv import load_dotenv

from app.core.config import settings
from app.core.canonical import (
    SourceRecord,
    MemoryChunk,
    SourceType,
    PermissionLevel
)
from app.memory.supabase_store import SupabaseMemoryStore
from app.data.reembedder import ReembeddingJob

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "..", ".env"))

def check_live_prerequisites(store: SupabaseMemoryStore):
    if os.getenv("THREAD_RUN_LIVE_SUPABASE_TESTS") != "1":
        pytest.skip("Set THREAD_RUN_LIVE_SUPABASE_TESTS=1 to run live remote Supabase integration tests.")

    if not settings.has_supabase:
        pytest.skip("Supabase credentials not configured in environment.")

    client = store.client
    if not client:
        pytest.skip("Unable to create live Supabase client.")

    try:
        client.table("memory_chunks").select("id").limit(1).execute()
    except Exception as e:
        err_msg = str(e)
        if "PGRST205" in err_msg or "Could not find the table" in err_msg:
            pytest.skip(
                "Supabase tables not migrated on remote project yet. "
                "Apply migrations via 'python -m app.data.migrator --up' to enable live integration."
            )
        raise

def test_live_supabase_transactional_persistence_and_hybrid_retrieval():
    """
    1. Tests production transactional persistence RPC (persist_record_and_chunks).
    2. Tests hybrid_search RPC with pre-retrieval ACL and RRF ranking.
    3. P0 check: Proves anon client cannot access INTERNAL_CORE records via RLS.
    """
    store = SupabaseMemoryStore()
    check_live_prerequisites(store)
    client = store.client

    run_id = f"test_{uuid.uuid4().hex[:8]}"
    rec_id = f"rec_tx_{run_id}"
    chk_id = f"chk_tx_{run_id}"
    org_id = f"org_{run_id}"

    record = SourceRecord(
        id=rec_id,
        organization_id=org_id,
        source_type=SourceType.DISCORD,
        source_uri=f"https://discord.com/channels/live/{run_id}",
        author_name="LiveTxRunner",
        raw_content="Disposable transactional persistence test content for Supabase",
        permission=PermissionLevel.INTERNAL_CORE,
        metadata={"disposable_test_run": run_id}
    )

    chunk = MemoryChunk(
        id=chk_id,
        source_record_id=rec_id,
        organization_id=org_id,
        source_type=SourceType.DISCORD,
        source_uri=f"https://discord.com/channels/live/{run_id}",
        author="LiveTxRunner",
        title="Live Transactional Chunk",
        content="Disposable transactional test chunk for Supabase hybrid search",
        permission=PermissionLevel.INTERNAL_CORE,
        tags=["live_tx_test"],
        embedding=[0.02] * settings.EMBEDDING_DIMENSION,
        embedding_status="ready",
        provenance={"test_run": run_id}
    )

    try:
        # 1. Transactional persistence RPC
        persisted = store.persist_record_and_chunks(record, [chunk])
        assert persisted is True, "persist_record_and_chunks must atomically commit record and chunks"

        # Round-trip fetch
        fetched_chunk = store.get_chunk(chk_id)
        assert fetched_chunk is not None
        assert fetched_chunk.id == chk_id
        assert fetched_chunk.permission == PermissionLevel.INTERNAL_CORE
        assert fetched_chunk.embedding_status == "ready"

        fetched_rec = store.get_record(rec_id)
        assert fetched_rec is not None
        assert fetched_rec.id == rec_id

        # 2. P0: Anon Client RLS / Privilege Enforcement
        anon_key = os.getenv("SUPABASE_PUBLISHABLE_KEY")
        if anon_key:
            from supabase import create_client
            anon_client = create_client(settings.SUPABASE_URL, anon_key)
            try:
                anon_res = anon_client.table("memory_chunks").select("*").eq("id", chk_id).execute()
                assert len(anon_res.data or []) == 0, "P0 Violation: Anon client must NOT be able to read INTERNAL_CORE chunk"
            except Exception as e:
                assert "permission denied" in str(e).lower() or "42501" in str(e), f"Unexpected anon error: {e}"

        # 3. Hybrid Search RPC Execution
        results = store.hybrid_search(
            query="Disposable transactional test",
            query_embedding=[0.02] * settings.EMBEDDING_DIMENSION,
            organization_id=org_id,
            allowed_scopes=[PermissionLevel.INTERNAL_CORE],
            match_count=5
        )
        assert len(results) >= 1
        assert results[0][1].id == chk_id

    finally:
        try:
            client.table("memory_chunks").delete().eq("organization_id", org_id).execute()
            client.table("source_records").delete().eq("organization_id", org_id).execute()
        except Exception:
            pass

def test_live_supabase_atomic_transaction_rollback():
    """
    P1 Test: Proves atomic rollback in persist_record_and_chunks.
    When a batch contains an invalid chunk (e.g. invalid embedding dimension 128 instead of 768),
    the entire transaction must abort and roll back.
    Neither the SourceRecord nor any preceding valid MemoryChunk may exist in the database.
    """
    store = SupabaseMemoryStore()
    check_live_prerequisites(store)
    client = store.client

    run_id = f"test_{uuid.uuid4().hex[:8]}"
    rec_id = f"rec_rb_{run_id}"
    valid_chk_id = f"chk_valid_{run_id}"
    invalid_chk_id = f"chk_invalid_{run_id}"
    org_id = f"org_{run_id}"

    record = SourceRecord(
        id=rec_id,
        organization_id=org_id,
        source_type=SourceType.DISCORD,
        source_uri=f"https://discord.com/channels/rollback/{run_id}",
        author_name="RollbackRunner",
        raw_content="This record must NOT persist after chunk failure",
        permission=PermissionLevel.INTERNAL_CORE
    )

    valid_chunk = MemoryChunk(
        id=valid_chk_id,
        source_record_id=rec_id,
        organization_id=org_id,
        source_type=SourceType.DISCORD,
        author="RollbackRunner",
        content="Valid chunk that precedes invalid chunk",
        permission=PermissionLevel.INTERNAL_CORE,
        embedding=[0.01] * settings.EMBEDDING_DIMENSION,
        embedding_status="ready"
    )

    # Invalid chunk with incompatible 128-dim vector (causes Postgres cast ::vector(768) to fail)
    invalid_chunk = MemoryChunk(
        id=invalid_chk_id,
        source_record_id=rec_id,
        organization_id=org_id,
        source_type=SourceType.DISCORD,
        author="RollbackRunner",
        content="Invalid chunk with incompatible vector dimension",
        permission=PermissionLevel.INTERNAL_CORE,
        embedding=[0.01] * 128,  # Intentionally 128 instead of 768
        embedding_status="ready"
    )

    try:
        # Must fail and raise error due to pgvector dimension mismatch in SQL
        with pytest.raises(Exception) as exc_info:
            store.persist_record_and_chunks(record, [valid_chunk, invalid_chunk])

        err_text = str(exc_info.value)
        assert any(term in err_text.lower() for term in ["dimension", "vector", "invalid", "22000", "pgrst"]), (
            f"Expected dimension mismatch or RPC error, got: {err_text}"
        )

        # Atomic Rollback Verification:
        # Neither the record nor the valid chunk must be present in the database
        fetched_rec = store.get_record(rec_id)
        assert fetched_rec is None, "Atomic Rollback Violation: SourceRecord was committed despite chunk failure!"

        fetched_chunk = store.get_chunk(valid_chk_id)
        assert fetched_chunk is None, "Atomic Rollback Violation: valid chunk was committed despite batch failure!"

    finally:
        try:
            client.table("memory_chunks").delete().eq("organization_id", org_id).execute()
            client.table("source_records").delete().eq("organization_id", org_id).execute()
        except Exception:
            pass

def test_live_supabase_durable_quarantine_promotion():
    """
    P1 Test: Proves durable quarantine promotion (promote_quarantined_chunks).
    1. Ingests record and chunks with permission PENDING_REVIEW and quarantine flags.
    2. Calls promote_quarantined_chunks() via Supabase RPC.
    3. Verifies permission promoted to INTERNAL_CORE and provenance review_status updated.
    4. Verifies durable audit entry in import_approvals table.
    """
    store = SupabaseMemoryStore()
    check_live_prerequisites(store)
    client = store.client

    run_id = f"test_{uuid.uuid4().hex[:8]}"
    import_hash = f"hash_quarantine_{run_id}"
    rec_id = f"rec_q_{run_id}"
    chk_id = f"chk_q_{run_id}"
    org_id = f"org_{run_id}"
    approval_id = f"appr_{run_id}"
    admin_user = f"admin_{run_id}"

    record = SourceRecord(
        id=rec_id,
        organization_id=org_id,
        source_type=SourceType.DISCORD,
        source_uri=f"https://discord.com/channels/quarantine/{run_id}",
        author_name="QuarantineRunner",
        raw_content="Quarantined import content pending promotion",
        permission=PermissionLevel.PENDING_REVIEW,
        hash=import_hash,
        metadata={"import_hash": import_hash, "quarantined_from_internal": True}
    )

    chunk = MemoryChunk(
        id=chk_id,
        source_record_id=rec_id,
        organization_id=org_id,
        source_type=SourceType.DISCORD,
        author="QuarantineRunner",
        title="Quarantined Chunk",
        content="Quarantined content to be promoted to INTERNAL_CORE",
        permission=PermissionLevel.PENDING_REVIEW,
        tags=["quarantined"],
        embedding=[0.03] * settings.EMBEDDING_DIMENSION,
        embedding_status="ready",
        provenance={
            "import_hash": import_hash,
            "source_hash": import_hash,
            "quarantined_from_internal": True,
            "review_status": "pending_review"
        }
    )

    try:
        persisted = store.persist_record_and_chunks(record, [chunk])
        assert persisted is True

        # Pre-promotion check
        pre_chunk = store.get_chunk(chk_id)
        assert pre_chunk is not None
        assert pre_chunk.permission == PermissionLevel.PENDING_REVIEW

        # Execute durable promotion RPC
        promoted_ids = store.promote_quarantined_chunks(
            organization_id=org_id,
            import_hash=import_hash,
            approved_by_user_id=admin_user,
            approval_id=approval_id
        )

        assert chk_id in promoted_ids, f"Expected {chk_id} in promoted_ids, got {promoted_ids}"

        # Post-promotion check on memory_chunk
        post_chunk = store.get_chunk(chk_id)
        assert post_chunk is not None
        assert post_chunk.permission == PermissionLevel.INTERNAL_CORE, "Chunk must be promoted to INTERNAL_CORE"
        assert post_chunk.provenance.get("review_status") == "approved_internal"
        assert post_chunk.provenance.get("approved_by_user_id") == admin_user
        assert post_chunk.provenance.get("quarantined_from_internal") is False

        # Post-promotion check on source_record
        post_rec = store.get_record(rec_id)
        assert post_rec is not None
        assert post_rec.permission == PermissionLevel.INTERNAL_CORE
        assert post_rec.metadata.get("review_status") == "approved_internal"

        # Verify audit trail in import_approvals
        appr_res = client.table("import_approvals").select("*").eq("id", approval_id).execute()
        assert len(appr_res.data or []) == 1, "Audit row must exist in import_approvals"
        appr_row = appr_res.data[0]
        assert appr_row["approved_by_user_id"] == admin_user
        assert appr_row["import_hash"] == import_hash
        assert chk_id in (appr_row.get("promoted_chunk_ids") or [])

    finally:
        try:
            client.table("import_approvals").delete().eq("id", approval_id).execute()
            client.table("memory_chunks").delete().eq("organization_id", org_id).execute()
            client.table("source_records").delete().eq("organization_id", org_id).execute()
        except Exception:
            pass

def test_live_supabase_reembedding_migration_and_dense_exclusion():
    """
    P1 Test: Proves 128-to-768 re-embedding migration state and dense retrieval exclusion.
    1. Chunks with embedding_status = 'pending_reembed' are strictly excluded from dense vector search.
    2. Chunks remain searchable via full-text search (lexical match preserves access).
    3. ReembeddingJob processes pending chunks in resumable batches, sets embedding_status = 'ready'.
    4. Once re-embedded, chunk actively participates in dense vector similarity search.
    """
    store = SupabaseMemoryStore()
    check_live_prerequisites(store)
    client = store.client

    run_id = f"test_{uuid.uuid4().hex[:8]}"
    rec_id = f"rec_reembed_{run_id}"
    chk_id = f"chk_reembed_{run_id}"
    org_id = f"org_{run_id}"

    record = SourceRecord(
        id=rec_id,
        organization_id=org_id,
        source_type=SourceType.MANUAL,
        author_name="ReembedRunner",
        raw_content="Documentation for Quantum Encryption Architecture",
        permission=PermissionLevel.INTERNAL_CORE
    )

    # Chunk with embedding_status = 'pending_reembed'
    chunk = MemoryChunk(
        id=chk_id,
        source_record_id=rec_id,
        organization_id=org_id,
        source_type=SourceType.MANUAL,
        author="ReembedRunner",
        title="Quantum Encryption Protocol",
        content="Quantum Encryption Protocol specifies secure key distribution over organizational channels",
        permission=PermissionLevel.INTERNAL_CORE,
        tags=["quantum", "encryption", "security"],
        embedding=None,  # Or legacy pending
        embedding_status="pending_reembed"
    )

    # Persist via direct SQL / client to simulate legacy row marked pending_reembed
    db_url = os.getenv("SUPABASE_DB_URL")
    import psycopg2
    conn = psycopg2.connect(db_url)

    try:
        with conn.cursor() as cur:
            # Drop NOT NULL to simulate legacy 128-to-768 transition state before re-embedding completes
            cur.execute("ALTER TABLE memory_chunks ALTER COLUMN embedding DROP NOT NULL;")
            
            # Insert parent record
            cur.execute("""
                INSERT INTO source_records (id, organization_id, source_type, author_name, timestamp, raw_content, permission)
                VALUES (%s, %s, %s, %s, NOW(), %s, %s);
            """, (rec_id, org_id, "manual", "ReembedRunner", record.raw_content, "INTERNAL_CORE"))

            # Insert chunk with embedding_status = 'pending_reembed' and legacy 128 embedding
            cur.execute("""
                INSERT INTO memory_chunks (
                    id, source_record_id, organization_id, source_type, source_timestamp,
                    author, title, content, permission, tags, embedding, legacy_embedding_128, embedding_status
                ) VALUES (
                    %s, %s, %s, %s, NOW(),
                    %s, %s, %s, %s, %s, NULL, %s::vector(128), 'pending_reembed'
                );
            """, (
                chk_id, rec_id, org_id, "manual",
                chunk.author, chunk.title, chunk.content, "INTERNAL_CORE",
                chunk.tags, "[" + ",".join(["0.05"] * 128) + "]"
            ))
        conn.commit()

        # 1. Dense retrieval exclusion check:
        # A query matching the chunk lexically must find it via FTS, but dense similarity MUST be 0.0
        query_vec = [0.05] * settings.EMBEDDING_DIMENSION
        results_before = store.hybrid_search(
            query="Quantum Encryption Protocol",
            query_embedding=query_vec,
            organization_id=org_id,
            allowed_scopes=[PermissionLevel.INTERNAL_CORE],
            match_count=5
        )

        assert len(results_before) >= 1
        found_before = [r for r in results_before if r[1].id == chk_id][0]
        sim_before = found_before[2]  # similarity score
        dense_rank_before = found_before[4]  # dense rank
        fts_rank_before = found_before[3]  # fts rank

        assert sim_before == 0.0, f"Dense exclusion violation: pending_reembed chunk had similarity {sim_before}"
        assert dense_rank_before == 0, "Dense rank must be 0 for pending_reembed chunk"
        assert fts_rank_before > 0.0, "Chunk must still be found via FTS while pending re-embedding"

        # 2. Run resumable re-embedding job
        job = ReembeddingJob(
            db_url=db_url,
            batch_size=10,
            embed_fn=lambda text: [0.05] * settings.EMBEDDING_DIMENSION
        )
        assert job.get_pending_count(conn) >= 1

        processed = job.process_batch(conn, limit=50)
        assert processed >= 1, "ReembeddingJob must process the pending chunk"
        assert job.get_pending_count(conn) == 0

        # Finalize schema: restores NOT NULL and creates full 768 HNSW index
        job.finalize_schema(conn)

        # Verify chunk updated to 'ready'
        updated_chunk = store.get_chunk(chk_id)
        assert updated_chunk is not None
        assert updated_chunk.embedding_status == "ready"
        assert updated_chunk.embedding is not None
        assert len(updated_chunk.embedding) == settings.EMBEDDING_DIMENSION

        # 3. Post-reembedding check:
        # Chunk must now actively participate in dense vector search
        results_after = store.hybrid_search(
            query="Quantum Encryption Protocol",
            query_embedding=query_vec,
            organization_id=org_id,
            allowed_scopes=[PermissionLevel.INTERNAL_CORE],
            match_count=5
        )

        assert len(results_after) >= 1
        found_after = [r for r in results_after if r[1].id == chk_id][0]
        sim_after = found_after[2]
        dense_rank_after = found_after[4]

        assert sim_after > 0.9, f"After re-embedding, dense vector similarity must be active; got {sim_after}"
        assert dense_rank_after >= 1, "Dense rank must be >= 1 after re-embedding"

    finally:
        try:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM memory_chunks WHERE organization_id = %s;", (org_id,))
                cur.execute("DELETE FROM source_records WHERE organization_id = %s;", (org_id,))
            conn.commit()
            conn.close()
        except Exception:
            pass


def test_live_supabase_two_independent_workers_prevent_account_reassignment():
    """
    P0 Live Verification:
    Tests two independent CrossChannelIdentityService instances against remote Supabase PostgreSQL.
    Instance 1 links a GitHub account to person_1.
    Instance 2 (with empty local memory) attempts to link the same GitHub account to person_2.
    Must fail closed with AccountAlreadyLinkedError via the PostgreSQL row lock.
    When Instance 1 revokes the link, Instance 2 can now link the account to person_2.
    """
    store = SupabaseMemoryStore()
    check_live_prerequisites(store)

    from app.identity.service import CrossChannelIdentityService, AccountAlreadyLinkedError
    from app.core.canonical import ChannelType, LinkVerificationType
    import psycopg2

    db_url = os.getenv("SUPABASE_DB_URL") or os.getenv("DATABASE_URL")
    if not db_url:
        pytest.skip("SUPABASE_DB_URL not configured for live integration test.")

    run_id = f"live_{uuid.uuid4().hex[:8]}"
    org_id = f"org_{run_id}"
    test_account_id = f"998877{run_id[:4]}"

    worker_1 = CrossChannelIdentityService()
    worker_1.clear()

    worker_2 = CrossChannelIdentityService()
    worker_2.clear()

    try:
        # 1. Worker 1 links account to usr_alice
        worker_1.link_account(
            organization_id=org_id,
            person_id="usr_alice",
            channel_type=ChannelType.GITHUB,
            account_id=test_account_id,
            username="alice-dev",
            link_type=LinkVerificationType.OAUTH_VERIFIED,
            confidence=1.0
        )

        # 2. Worker 2 (separate memory) attempts to link same account to usr_bob
        with pytest.raises(AccountAlreadyLinkedError) as exc_info:
            worker_2.link_account(
                organization_id=org_id,
                person_id="usr_bob",
                channel_type=ChannelType.GITHUB,
                account_id=test_account_id,
                username="bob-dev",
                link_type=LinkVerificationType.OAUTH_VERIFIED,
                confidence=1.0
            )
        assert "already actively linked to person 'usr_alice'" in str(exc_info.value)

        # 3. Worker 1 revokes the link
        worker_1.revoke_account_link(
            organization_id=org_id,
            channel_type=ChannelType.GITHUB,
            account_id=test_account_id,
            actor_person_id="usr_alice"
        )

        # 4. Worker 2 now succeeds in linking to usr_bob
        link_2 = worker_2.link_account(
            organization_id=org_id,
            person_id="usr_bob",
            channel_type=ChannelType.GITHUB,
            account_id=test_account_id,
            username="bob-dev",
            link_type=LinkVerificationType.OAUTH_VERIFIED,
            confidence=1.0
        )
        assert link_2.person_id == "usr_bob"
        assert link_2.is_active is True

    finally:
        try:
            with psycopg2.connect(db_url) as cleanup_conn:
                with cleanup_conn.cursor() as cur:
                    cur.execute("DELETE FROM channel_account_links WHERE organization_id = %s;", (org_id,))
                    cur.execute("DELETE FROM identity_audit_log WHERE organization_id = %s;", (org_id,))
                cleanup_conn.commit()
        except Exception:
            pass

