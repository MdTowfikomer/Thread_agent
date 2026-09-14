import os
import sys
import logging
import argparse
from typing import Optional, Callable, List, Tuple, Union, Any
import psycopg2
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv

from app.core.config import settings
from app.memory.store import memory_store

logger = logging.getLogger("thread.reembedder")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

load_dotenv()

def get_production_embedder(
    allow_deterministic: bool = False
) -> Callable[[str], Tuple[List[float], str, int]]:
    """
    Constructs a strict, fail-closed embedding provider for re-embedding.
    - If Gemini is configured, produces text-embedding-004 vectors and returns ("models/text-embedding-004", 768).
    - If OpenAI is configured, produces text-embedding-3-small vectors and returns ("text-embedding-3-small", 768).
    - If neither is configured, FAILS CLOSED in production (raises RuntimeError).
    - Only falls back to deterministic-v1 when allow_deterministic=True is explicitly passed (e.g. offline tests),
      and strictly records 'deterministic-v1' as the model label rather than claiming Gemini.
    """
    if settings.has_gemini:
        try:
            from langchain_google_genai import GoogleGenerativeAIEmbeddings
            embedder = GoogleGenerativeAIEmbeddings(
                model="models/text-embedding-004",
                google_api_key=settings.GEMINI_API_KEY
            )
            def _embed_gemini(text: str) -> Tuple[List[float], str, int]:
                try:
                    vec = embedder.embed_query(text)
                except Exception as e:
                    raise RuntimeError(f"Gemini embedding API call failed: {e}") from e
                if len(vec) != settings.EMBEDDING_DIMENSION:
                    raise ValueError(f"Gemini returned dimension {len(vec)}, expected {settings.EMBEDDING_DIMENSION}")
                return vec, "models/text-embedding-004", settings.EMBEDDING_DIMENSION
            return _embed_gemini
        except ImportError:
            pass

    if settings.has_openai:
        try:
            from langchain_openai import OpenAIEmbeddings
            embedder = OpenAIEmbeddings(
                model="text-embedding-3-small",
                dimensions=settings.EMBEDDING_DIMENSION,
                openai_api_key=settings.OPENAI_API_KEY
            )
            def _embed_openai(text: str) -> Tuple[List[float], str, int]:
                try:
                    vec = embedder.embed_query(text)
                except Exception as e:
                    raise RuntimeError(f"OpenAI embedding API call failed: {e}") from e
                if len(vec) != settings.EMBEDDING_DIMENSION:
                    raise ValueError(f"OpenAI returned dimension {len(vec)}, expected {settings.EMBEDDING_DIMENSION}")
                return vec, "text-embedding-3-small", settings.EMBEDDING_DIMENSION
            return _embed_openai
        except ImportError:
            pass

    if not allow_deterministic:
        raise RuntimeError(
            "Fail-Closed: No production neural embedding provider configured (GEMINI_API_KEY or OPENAI_API_KEY required). "
            "Refusing to generate degraded or fabricated embeddings in production. "
            "Pass allow_deterministic=True only for offline tests."
        )

    def _embed_deterministic(text: str) -> Tuple[List[float], str, int]:
        vec = memory_store._deterministic_vector(text)
        return vec, "deterministic-v1", settings.EMBEDDING_DIMENSION

    return _embed_deterministic

class ReembeddingJob:
    """
    Resumable, Fault-Tolerant Re-embedding Job for 128-to-768 Vector Migration.
    - Claims batches using short-lived non-blocking leases (embedding_status = 'processing')
      via FOR UPDATE SKIP LOCKED.
    - Commits the lease immediately so database row locks are NOT held during external HTTP embedding calls.
    - Generates 768-dimensional embeddings using the configured neural provider.
    - Persists actual model name, dimension, timestamp, version, and attempts directly to JSONB `provenance`.
    - Handles single-row embedding failures without aborting the batch:
        - Increments attempt count and releases lease for retry if attempts < max_retries.
        - Moves permanently failing rows to 'failed_reembed' dead-letter queue with operator-visible error
          records once attempts >= max_retries.
    - Commits per-row so progress is never lost on interruption or single-item failure.
    - Once all pending chunks are re-embedded, enforces NOT NULL and full HNSW index.
    """
    def __init__(
        self,
        db_url: Optional[str] = None,
        batch_size: int = 50,
        lease_seconds: int = 300,
        max_retries: int = 3,
        embed_fn: Optional[Callable[[str], Any]] = None,
        embedding_model: Optional[str] = None,
        allow_deterministic: bool = False
    ):
        self.db_url = db_url or os.getenv("SUPABASE_DB_URL") or os.getenv("DATABASE_URL")
        self.batch_size = batch_size
        self.lease_seconds = lease_seconds
        self.max_retries = max_retries
        self.allow_deterministic = allow_deterministic
        self.embedding_model = embedding_model
        self.embed_fn = embed_fn or get_production_embedder(allow_deterministic=allow_deterministic)

    def get_pending_count(self, conn) -> int:
        """Returns total number of chunks still pending re-embedding or with expired leases."""
        with conn.cursor() as cur:
            cur.execute("""
                SELECT count(*) 
                FROM memory_chunks 
                WHERE embedding_status = 'pending_reembed'
                   OR (embedding_status = 'processing' AND (reembed_lease_until IS NULL OR reembed_lease_until < NOW()));
            """)
            row = cur.fetchone()
            return row[0] if row else 0

    def get_failed_count(self, conn) -> int:
        """Returns total number of chunks in dead-letter state ('failed_reembed')."""
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM memory_chunks WHERE embedding_status = 'failed_reembed';")
            row = cur.fetchone()
            return row[0] if row else 0

    def process_batch(self, conn, limit: Optional[int] = None) -> int:
        """
        Processes a batch of chunks with non-blocking lease acquisition and isolated error handling.
        Returns the number of claimed chunks processed.
        """
        import json
        from datetime import datetime, timezone

        batch_limit = limit or self.batch_size
        rows = []

        # 1. Lease Acquisition (Fast transaction with FOR UPDATE SKIP LOCKED)
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            try:
                cur.execute("""
                    WITH claimable AS (
                        SELECT id
                        FROM memory_chunks
                        WHERE embedding_status = 'pending_reembed'
                           OR (embedding_status = 'processing' AND (reembed_lease_until IS NULL OR reembed_lease_until < NOW()))
                        ORDER BY id ASC
                        LIMIT %s
                        FOR UPDATE SKIP LOCKED
                    )
                    UPDATE memory_chunks
                    SET embedding_status = 'processing',
                        reembed_lease_until = NOW() + (%s || ' seconds')::interval,
                        reembed_attempts = COALESCE(reembed_attempts, 0) + 1
                    FROM claimable
                    WHERE memory_chunks.id = claimable.id
                    RETURNING memory_chunks.id, memory_chunks.title, memory_chunks.content, 
                              memory_chunks.author, memory_chunks.tags, memory_chunks.reembed_attempts;
                """, (batch_limit, str(self.lease_seconds)))
                rows = cur.fetchall()
                conn.commit()
            except Exception as e:
                conn.rollback()
                logger.warning(f"Lease acquisition query failed, attempting basic select: {e}")
                cur.execute("""
                    SELECT id, title, content, author, tags
                    FROM memory_chunks
                    WHERE embedding_status = 'pending_reembed'
                    ORDER BY id ASC
                    LIMIT %s
                    FOR UPDATE SKIP LOCKED;
                """, (batch_limit,))
                rows = cur.fetchall()

        if not rows:
            return 0

        # 2. Remote Embedding & Per-Item Isolated Persistence
        for row in rows:
            chunk_id = row["id"]
            attempts = row.get("reembed_attempts", 1) or 1
            title = row.get("title") or ""
            content = row.get("content") or ""
            author = row.get("author") or ""
            tags = row.get("tags") or []
            tag_str = " ".join(tags) if isinstance(tags, list) else ""

            text_to_embed = f"{title} {author} {tag_str}: {content}".strip()

            try:
                result = self.embed_fn(text_to_embed)

                if isinstance(result, tuple) and len(result) >= 3:
                    vector, model_name, dim = result[0], result[1], result[2]
                elif isinstance(result, tuple) and len(result) == 2:
                    vector, model_name = result[0], result[1]
                    dim = len(vector)
                else:
                    vector = result
                    model_name = self.embedding_model or ("deterministic-v1" if self.allow_deterministic else settings.DEFAULT_EMBEDDING_MODEL)
                    dim = len(vector)

                if len(vector) != settings.EMBEDDING_DIMENSION:
                    raise ValueError(
                        f"Generated vector dimension {len(vector)} does not match target {settings.EMBEDDING_DIMENSION}"
                    )

                vec_literal = "[" + ",".join(str(float(x)) for x in vector) + "]"
                prov_meta = json.dumps({
                    "reembedding": {
                        "status": "completed",
                        "model": model_name,
                        "dimension": dim,
                        "reembedded_at": datetime.now(timezone.utc).isoformat(),
                        "job_version": "1.1",
                        "attempts": attempts
                    }
                })

                with conn.cursor() as cur:
                    cur.execute("""
                        UPDATE memory_chunks
                        SET embedding = %s::vector,
                            embedding_model = %s,
                            embedding_dimension = %s,
                            embedding_status = 'ready',
                            reembed_lease_until = NULL,
                            reembed_error = NULL,
                            provenance = COALESCE(provenance, '{}'::jsonb) || %s::jsonb
                        WHERE id = %s;
                    """, (vec_literal, model_name, dim, prov_meta, chunk_id))
                conn.commit()

            except Exception as e:
                conn.rollback()
                logger.warning(f"Error re-embedding chunk {chunk_id} (attempt {attempts}): {e}")

                is_dead_letter = attempts >= self.max_retries
                status = "failed_reembed" if is_dead_letter else "pending_reembed"
                prov_meta = json.dumps({
                    "reembedding": {
                        "status": "failed" if is_dead_letter else "retry_scheduled",
                        "error": str(e),
                        "failed_at": datetime.now(timezone.utc).isoformat(),
                        "job_version": "1.1",
                        "attempts": attempts
                    }
                })

                with conn.cursor() as cur:
                    cur.execute("""
                        UPDATE memory_chunks
                        SET embedding_status = %s,
                            reembed_lease_until = NULL,
                            reembed_error = %s,
                            provenance = COALESCE(provenance, '{}'::jsonb) || %s::jsonb
                        WHERE id = %s;
                    """, (status, str(e), prov_meta, chunk_id))
                conn.commit()

        return len(rows)

    def finalize_schema(self, conn):
        """
        Enforces NOT NULL constraint on embedding and builds the full 768 HNSW index
        once all pending chunks are re-embedded.
        """
        logger.info("Checking for failed or null embeddings before finalizing schema...")
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM memory_chunks WHERE embedding_status = 'failed_reembed';")
            failed_count = cur.fetchone()[0]
            if failed_count > 0:
                logger.warning(
                    f"Operator Attention: {failed_count} chunks are in 'failed_reembed' status. "
                    "Leaving NOT NULL unconstrained and preserving partial HNSW index."
                )
                return

            cur.execute("ALTER TABLE memory_chunks ALTER COLUMN embedding SET NOT NULL;")
            cur.execute("DROP INDEX IF EXISTS idx_memory_chunks_embedding;")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_memory_chunks_embedding ON memory_chunks USING hnsw (embedding vector_cosine_ops);")
        conn.commit()
        logger.info("HNSW 768-dim index successfully active.")

    def run_all(self, conn) -> int:
        """
        Runs batch loop until 0 pending chunks remain, then finalizes schema.
        Returns total number of chunks re-embedded.
        """
        pending = self.get_pending_count(conn)
        if pending == 0:
            logger.info("No chunks pending re-embedding.")
            self.finalize_schema(conn)
            return 0

        logger.info(f"Starting resumable re-embedding job for {pending} chunks (batch size: {self.batch_size})...")
        total_processed = 0

        while True:
            processed = self.process_batch(conn)
            if processed == 0:
                break
            total_processed += processed
            logger.info(f"Re-embedded {processed} chunks (cumulative: {total_processed})...")

        remaining = self.get_pending_count(conn)
        if remaining == 0:
            self.finalize_schema(conn)

        logger.info(f"Re-embedding job complete. Processed {total_processed} chunks.")
        return total_processed

def main():
    parser = argparse.ArgumentParser(description="Resumable Re-embedding Job for Thread Vector Migration")
    parser.add_argument("--batch-size", type=int, default=50, help="Batch size for re-embedding (default: 50)")
    parser.add_argument("--status", action="store_true", help="Check pending re-embedding count and exit")
    parser.add_argument("--allow-deterministic", action="store_true", help="Allow deterministic vectors (testing only)")
    args = parser.parse_args()

    db_url = os.getenv("SUPABASE_DB_URL") or os.getenv("DATABASE_URL")
    if not db_url:
        logger.error("No SUPABASE_DB_URL or DATABASE_URL found.")
        sys.exit(1)

    conn = psycopg2.connect(db_url)
    try:
        job = ReembeddingJob(db_url=db_url, batch_size=args.batch_size, allow_deterministic=args.allow_deterministic)
        if args.status:
            pending = job.get_pending_count(conn)
            print(f"Chunks pending re-embedding: {pending}")
            return

        job.run_all(conn)
    finally:
        conn.close()

if __name__ == "__main__":
    main()
