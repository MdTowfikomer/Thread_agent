import logging
from typing import List, Optional, Dict, Any, Tuple
from app.core.config import settings
from app.core.canonical import (
    SourceRecord,
    MemoryChunk,
    SourceType,
    PermissionLevel
)
from app.memory.store import memory_store, MemoryStore
from app.memory.supabase_store import supabase_memory_store, SupabaseMemoryStore

logger = logging.getLogger(__name__)

class MemoryRepository:
    """
    Unified Persistence Repository for Thread Memory Core.
    Acts as the single authoritative persistence facade:
    - Transactionally writes source records and memory chunks to Supabase via single PostgreSQL RPC.
    - Synchronizes in-memory cache strictly AFTER database commit, preventing cache pollution on failure.
    - Durable multi-worker querying and promotion support for /api/memories and quarantine approvals.
    - Enforces 768-dim embeddings and deterministic timestamps across all persistence paths.
    """
    def __init__(
        self,
        in_memory: Optional[MemoryStore] = None,
        supabase: Optional[SupabaseMemoryStore] = None
    ):
        self.in_memory = in_memory or memory_store
        self.supabase = supabase or supabase_memory_store

    def _prepare_chunk(self, chunk: MemoryChunk) -> MemoryChunk:
        """Validate embedding dimensions and stamp provenance."""
        if chunk.embedding is None:
            text_to_embed = f"{chunk.title or ''} {chunk.author} {' '.join(chunk.tags)}: {chunk.content}"
            chunk.embedding = self.in_memory._get_embedding(text_to_embed)

        if len(chunk.embedding) != settings.EMBEDDING_DIMENSION:
            raise ValueError(
                f"Embedding dimension mismatch: expected {settings.EMBEDDING_DIMENSION}, got {len(chunk.embedding)}"
            )

        chunk.provenance.setdefault("embedding_model", getattr(self.in_memory, "_active_model_name", settings.DEFAULT_EMBEDDING_MODEL))
        chunk.provenance.setdefault("embedding_dimension", settings.EMBEDDING_DIMENSION)
        return chunk

    def save_record(self, record: SourceRecord) -> bool:
        """Save a single SourceRecord. Writes to Supabase first if configured."""
        if self.supabase and self.supabase.is_configured:
            ok = self.supabase.add_record(record)
            if not ok:
                return False
        self.in_memory.add_record(record)
        return True

    def save_chunk(self, chunk: MemoryChunk) -> bool:
        """Save a single MemoryChunk. Writes to Supabase first if configured."""
        chunk = self._prepare_chunk(chunk)
        if self.supabase and self.supabase.is_configured:
            ok = self.supabase.add_chunk(chunk)
            if not ok:
                return False
        self.in_memory.add_chunk(chunk)
        return True

    def save_record_and_chunks(
        self,
        record: SourceRecord,
        chunks: List[MemoryChunk]
    ) -> Tuple[bool, int]:
        """
        Transactional Persistence:
        Atomically persists a SourceRecord and its derived MemoryChunks via single PostgreSQL transaction.
        If the database write fails or rolls back, in-memory cache is NOT updated (zero cache pollution).
        Updates in-memory cache ONLY after successful commit.
        """
        # Validate all chunks first
        prepared_chunks = [self._prepare_chunk(c) for c in chunks]

        # 1. Supabase Transactional RPC write first
        if self.supabase and self.supabase.is_configured:
            try:
                success = self.supabase.persist_record_and_chunks(record, prepared_chunks)
                if not success:
                    logger.error("Supabase transactional persistence returned false.")
                    return False, 0
            except Exception as e:
                logger.error(f"Supabase transactional persistence failed; aborting cache update: {e}")
                raise

        # 2. Only after database commit, update in-memory cache
        self.in_memory.add_record(record)
        self.in_memory.add_chunks(prepared_chunks)
        return True, len(prepared_chunks)

    def save_records_and_chunks(
        self,
        records: List[SourceRecord],
        chunks: List[MemoryChunk]
    ) -> Tuple[int, int]:
        """Batch transactional persistence."""
        # For simplicity and isolation, pair each record with its chunks or batch
        rec_count = 0
        chunk_count = 0
        chunks_by_record: Dict[str, List[MemoryChunk]] = {}
        for c in chunks:
            chunks_by_record.setdefault(c.source_record_id, []).append(c)

        for r in records:
            r_chunks = chunks_by_record.get(r.id, [])
            ok, cnt = self.save_record_and_chunks(r, r_chunks)
            if ok:
                rec_count += 1
                chunk_count += cnt

        return rec_count, chunk_count

    def get_chunk(self, chunk_id: str) -> Optional[MemoryChunk]:
        """Retrieve chunk from persistent Supabase database, falling back to cache."""
        if self.supabase and self.supabase.is_configured:
            chunk = self.supabase.get_chunk(chunk_id)
            if chunk:
                self.in_memory.add_chunk(chunk)
                return chunk
        return self.in_memory.get_chunk(chunk_id)

    def get_record(self, record_id: str) -> Optional[SourceRecord]:
        """Retrieve record from persistent Supabase database, falling back to cache."""
        if self.supabase and self.supabase.is_configured:
            rec = self.supabase.get_record(record_id)
            if rec:
                self.in_memory.add_record(rec)
                return rec
        return self.in_memory.get_record(record_id)

    def get_chunks_for_organization(
        self,
        organization_id: str,
        permission: Optional[PermissionLevel] = None
    ) -> List[MemoryChunk]:
        """
        Multi-Worker Safe: Queries persistent Supabase database for tenant's chunks,
        falling back to in-memory store in offline mode.
        """
        if self.supabase and self.supabase.is_configured:
            db_chunks = self.supabase.get_chunks_for_organization(organization_id, permission=permission)
            if db_chunks:
                # Sync into local cache
                for c in db_chunks:
                    self.in_memory.add_chunk(c)
                return db_chunks

        # Offline / local cache fallback
        local_chunks = self.in_memory.get_chunks_for_organization(organization_id)
        if permission:
            local_chunks = [c for c in local_chunks if c.permission == permission]
        return local_chunks

    def promote_import(
        self,
        organization_id: str,
        import_hash: str,
        approved_by_user_id: str,
        approval_id: str
    ) -> List[str]:
        """
        Durable Multi-Worker Promotion:
        Promotes quarantined PENDING_REVIEW chunks in Supabase database.
        Synchronizes local cache so all workers reflect the promotion.
        """
        promoted_ids: List[str] = []

        if self.supabase and self.supabase.is_configured:
            promoted_ids = self.supabase.promote_quarantined_chunks(
                organization_id=organization_id,
                import_hash=import_hash,
                approved_by_user_id=approved_by_user_id,
                approval_id=approval_id
            )

        # Also promote in local cache
        for chunk in self.in_memory.get_chunks_for_organization(organization_id):
            chunk_hash = chunk.provenance.get("import_hash") or chunk.provenance.get("source_hash")
            if chunk.permission == PermissionLevel.PENDING_REVIEW and chunk_hash == import_hash:
                chunk.permission = PermissionLevel.INTERNAL_CORE
                chunk.provenance["quarantined_from_internal"] = False
                chunk.provenance["review_status"] = "approved_internal"
                chunk.provenance["approved_by_user_id"] = approved_by_user_id
                if chunk.id not in promoted_ids:
                    promoted_ids.append(chunk.id)

        return promoted_ids

    def has_external_record(self, organization_id: str, source_type: SourceType, external_id: str) -> bool:
        return self.in_memory.has_external_record(organization_id, source_type, external_id)

    def clear(self):
        """Clear memory cache (for testing)."""
        self.in_memory.clear()

# Global singleton
memory_repository = MemoryRepository()
