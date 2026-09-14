import json
import pytest
from unittest.mock import MagicMock, call
from app.data.reembedder import ReembeddingJob

def test_reembedder_process_batch_resumable():
    mock_conn = MagicMock()
    mock_cur = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cur

    # Simulate 2 pending chunks
    mock_cur.fetchall.return_value = [
        {"id": "c1", "title": "T1", "content": "C1", "author": "A1", "tags": ["tag1"], "reembed_attempts": 0},
        {"id": "c2", "title": "T2", "content": "C2", "author": "A2", "tags": [], "reembed_attempts": 0}
    ]

    mock_embed_fn = MagicMock(return_value=[0.1] * 768)

    job = ReembeddingJob(
        db_url="postgresql://fake",
        batch_size=2,
        embed_fn=mock_embed_fn,
        embedding_model="test-embed-model"
    )

    processed = job.process_batch(mock_conn, limit=2)
    assert processed == 2

    # Verify embed_fn called for each chunk
    assert mock_embed_fn.call_count == 2

    # Verify UPDATE statements set embedding_status = 'ready' and write provenance JSONB
    item_updates = [c for c in mock_cur.execute.call_args_list if "WHERE id = %s" in str(c)]
    assert len(item_updates) == 2

    first_update_sql = item_updates[0][0][0]
    first_update_args = item_updates[0][0][1]

    assert "embedding_status = 'ready'" in first_update_sql
    assert "provenance = COALESCE(provenance, '{}'::jsonb) || %s::jsonb" in first_update_sql

    # Verify provenance JSON content
    prov_arg = [arg for arg in first_update_args if isinstance(arg, str) and "reembedding" in arg][0]
    prov_data = json.loads(prov_arg)
    assert prov_data["reembedding"]["status"] == "completed"
    assert prov_data["reembedding"]["model"] == "test-embed-model"
    assert prov_data["reembedding"]["dimension"] == 768
    assert "reembedded_at" in prov_data["reembedding"]
    assert prov_data["reembedding"]["job_version"] == "1.1"

def test_reembedder_single_row_failure_does_not_stall_batch_and_deadletters_after_max_retries():
    mock_conn = MagicMock()
    mock_cur = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cur

    # Chunk 1 has reached max retries (3 attempts), Chunk 2 is fresh (0 attempts)
    mock_cur.fetchall.return_value = [
        {"id": "failing_chunk", "title": "Bad", "content": "Bad Content", "author": "A", "tags": [], "reembed_attempts": 3},
        {"id": "good_chunk", "title": "Good", "content": "Good Content", "author": "B", "tags": [], "reembed_attempts": 0}
    ]

    def mock_embed_fn(text: str):
        if "Bad" in text:
            raise RuntimeError("Gemini API 500: Internal transient error on toxic content")
        return [0.5] * 768

    job = ReembeddingJob(
        db_url="postgresql://fake",
        batch_size=2,
        max_retries=3,
        embed_fn=mock_embed_fn,
        embedding_model="test-embed-model"
    )

    # Must process both rows without crashing out or aborting the batch!
    processed = job.process_batch(mock_conn, limit=2)
    assert processed == 2

    # Check updates
    item_updates = [c for c in mock_cur.execute.call_args_list if "WHERE id = %s" in str(c)]
    assert len(item_updates) == 2

    # 1. Failing chunk reached max_retries (3) -> Dead-lettered to 'failed_reembed'
    fail_update = [c for c in item_updates if "failing_chunk" in str(c)][0]
    fail_sql = fail_update[0][0]
    fail_args = fail_update[0][1]
    assert "embedding_status = %s" in fail_sql
    assert fail_args[0] == "failed_reembed"
    assert "Gemini API 500" in fail_args[1]
    fail_prov = json.loads(fail_args[2])
    assert fail_prov["reembedding"]["status"] == "failed"
    assert "Gemini API 500" in fail_prov["reembedding"]["error"]

    # 2. Good chunk succeeded -> 'ready'
    good_update = [c for c in item_updates if "good_chunk" in str(c)][0]
    good_sql = good_update[0][0]
    good_args = good_update[0][1]
    assert "embedding_status = 'ready'" in good_sql
    good_prov = json.loads(good_args[3])
    assert good_prov["reembedding"]["status"] == "completed"

def test_reembedder_finalize_schema_restores_not_null_and_index():
    mock_conn = MagicMock()
    mock_cur = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cur

    # 0 failed chunks
    mock_cur.fetchone.return_value = (0,)

    job = ReembeddingJob(db_url="postgresql://fake")
    job.finalize_schema(mock_conn)

    sql_executed = " ".join(str(c) for c in mock_cur.execute.call_args_list)
    assert "ALTER TABLE memory_chunks ALTER COLUMN embedding SET NOT NULL;" in sql_executed
    assert "CREATE INDEX IF NOT EXISTS idx_memory_chunks_embedding" in sql_executed

def test_reembedder_run_all_orchestration():
    mock_conn = MagicMock()
    mock_cur = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cur

    # Sequence of get_pending_count: first returns 2, then 0
    # Also finalize_schema checks failed count -> returns 0
    mock_cur.fetchone.side_effect = [(2,), (0,), (0,)]
    # First batch returns 2 rows, next batch returns 0
    mock_cur.fetchall.side_effect = [
        [
            {"id": "c1", "title": "T1", "content": "C1", "author": "A1", "tags": [], "reembed_attempts": 0},
            {"id": "c2", "title": "T2", "content": "C2", "author": "A2", "tags": [], "reembed_attempts": 0}
        ],
        []
    ]

    job = ReembeddingJob(
        db_url="postgresql://fake",
        batch_size=10,
        embed_fn=lambda text: [0.2] * 768
    )

    total = job.run_all(mock_conn)
    assert total == 2

    sql_executed = " ".join(str(c) for c in mock_cur.execute.call_args_list)
    assert "ALTER TABLE memory_chunks ALTER COLUMN embedding SET NOT NULL;" in sql_executed
