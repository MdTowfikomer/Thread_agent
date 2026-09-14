import pytest
from unittest.mock import MagicMock, call
from app.data.reembedder import ReembeddingJob

def test_reembedder_process_batch_resumable():
    mock_conn = MagicMock()
    mock_cur = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cur

    # Simulate 2 pending chunks
    mock_cur.fetchall.return_value = [
        {"id": "c1", "title": "T1", "content": "C1", "author": "A1", "tags": ["tag1"]},
        {"id": "c2", "title": "T2", "content": "C2", "author": "A2", "tags": []}
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

    # Verify per-batch commit (resumability)
    mock_conn.commit.assert_called_once()

    # Verify UPDATE statements set embedding_status = 'ready'
    update_calls = [c for c in mock_cur.execute.call_args_list if "UPDATE memory_chunks" in str(c)]
    assert len(update_calls) == 2
    assert "embedding_status = 'ready'" in str(update_calls[0])

def test_reembedder_finalize_schema_restores_not_null_and_index():
    mock_conn = MagicMock()
    mock_cur = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cur

    job = ReembeddingJob(db_url="postgresql://fake")
    job.finalize_schema(mock_conn)

    sql_executed = " ".join(str(c) for c in mock_cur.execute.call_args_list)
    assert "ALTER TABLE memory_chunks ALTER COLUMN embedding SET NOT NULL;" in sql_executed
    assert "CREATE INDEX IF NOT EXISTS idx_memory_chunks_embedding" in sql_executed
    mock_conn.commit.assert_called_once()

def test_reembedder_run_all_orchestration():
    mock_conn = MagicMock()
    mock_cur = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cur

    # Sequence of get_pending_count: first returns 2, then 0
    mock_cur.fetchone.side_effect = [(2,), (0,)]
    # First batch returns 2 rows, next batch returns 0
    mock_cur.fetchall.side_effect = [
        [
            {"id": "c1", "title": "T1", "content": "C1", "author": "A1", "tags": []},
            {"id": "c2", "title": "T2", "content": "C2", "author": "A2", "tags": []}
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
