import logging
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime, timezone

from app.core.config import settings
from app.core.canonical import (
    MemoryChunk,
    SourceRecord,
    SourceType,
    PermissionLevel
)

logger = logging.getLogger(__name__)

class SupabaseMemoryStore:
    """
    Supabase pgvector & PostgreSQL full-text search store for Thread Memory Core.
    Implements Reciprocal Rank Fusion (RRF) hybrid retrieval with pre-retrieval ACL filtering,
    transactional persistence via PostgreSQL RPC, and complete provenance preservation.
    """
    def __init__(self, supabase_url: Optional[str] = None, supabase_key: Optional[str] = None):
        self.url = supabase_url or settings.SUPABASE_URL
        self.key = supabase_key or settings.SUPABASE_SERVICE_ROLE_KEY
        self._client = None

    @property
    def is_configured(self) -> bool:
        return bool(self.url and self.key)

    @property
    def client(self):
        if not self.is_configured:
            return None
        if self._client is None:
            try:
                from supabase import create_client
                self._client = create_client(self.url, self.key)
            except Exception as e:
                logger.error(f"Failed to initialize Supabase client: {e}")
                self._client = None
        return self._client

    def _format_record_for_db(self, record: SourceRecord) -> Dict[str, Any]:
        if not getattr(record, "timestamp", None):
            raise ValueError(f"Provenance violation: SourceRecord '{record.id}' missing valid timestamp.")
        rec_ts = record.timestamp.isoformat()
        created_ts = record.created_at.isoformat() if hasattr(record, "created_at") and record.created_at else rec_ts

        return {
            "id": record.id,
            "organization_id": record.organization_id,
            "source_type": record.source_type.value,
            "source_uri": record.source_uri,
            "external_id": record.external_id,
            "author_id": record.author_id,
            "author_name": record.author_name,
            "author_role": record.author_role,
            "timestamp": rec_ts,
            "raw_content": record.raw_content,
            "permission": record.permission.value,
            "metadata": record.metadata or {},
            "hash": record.hash or "",
            "created_at": created_ts
        }

    def _format_chunk_for_db(self, chunk: MemoryChunk) -> Dict[str, Any]:
        if chunk.embedding is not None and len(chunk.embedding) != settings.EMBEDDING_DIMENSION:
            raise ValueError(
                f"Embedding dimension mismatch: expected {settings.EMBEDDING_DIMENSION}, got {len(chunk.embedding)}"
            )

        prov = chunk.provenance or {}
        # Deterministic timestamp preservation: Never fabricate datetime.now()
        if hasattr(chunk, "timestamp") and chunk.timestamp:
            src_ts_iso = chunk.timestamp.isoformat()
        elif prov.get("timestamp"):
            raw_ts = prov["timestamp"]
            src_ts_iso = raw_ts.isoformat() if isinstance(raw_ts, datetime) else str(raw_ts)
        else:
            raise ValueError(f"Provenance violation: Chunk '{chunk.id}' missing source timestamp.")

        created_ts = chunk.created_at.isoformat() if hasattr(chunk, "created_at") and chunk.created_at else src_ts_iso

        return {
            "id": chunk.id,
            "source_record_id": chunk.source_record_id,
            "organization_id": chunk.organization_id,
            "source_type": chunk.source_type.value,
            "source_uri": chunk.source_uri or prov.get("source_uri"),
            "source_timestamp": src_ts_iso,
            "source_hash": prov.get("source_hash") or prov.get("hash") or "",
            "ingestion_version": prov.get("ingestion_version", "v0"),
            "policy_version": prov.get("policy_version", "v0"),
            "author": chunk.author,
            "author_role": chunk.author_role,
            "title": chunk.title,
            "content": chunk.content,
            "permission": chunk.permission.value,
            "tags": chunk.tags or [],
            "entities": chunk.entities or {},
            "embedding": chunk.embedding,
            "embedding_status": getattr(chunk, "embedding_status", "ready"),
            "embedding_model": prov.get("embedding_model", settings.DEFAULT_EMBEDDING_MODEL),
            "embedding_dimension": prov.get("embedding_dimension", settings.EMBEDDING_DIMENSION),
            "provenance": prov,
            "created_at": created_ts
        }

    def persist_record_and_chunks(self, record: SourceRecord, chunks: List[MemoryChunk]) -> bool:
        """
        Transactional Persistence RPC: Atomically persists a SourceRecord and its derived MemoryChunks.
        If any chunk insertion fails (e.g. dimension mismatch, constraint error), the transaction rolls back.
        """
        if not self.client:
            return False

        record_data = self._format_record_for_db(record)
        chunks_data = [self._format_chunk_for_db(c) for c in chunks]

        try:
            rpc_res = self.client.rpc("persist_record_and_chunks", {
                "record_data": record_data,
                "chunks_data": chunks_data
            }).execute()

            if rpc_res.data and rpc_res.data.get("success"):
                return True
            return False
        except Exception as e:
            logger.error(f"Transactional persistence failed in Supabase RPC: {e}")
            raise

    def add_record(self, record: SourceRecord) -> bool:
        """Upsert SourceRecord into Supabase source_records table."""
        if not self.client:
            return False
        try:
            data = self._format_record_for_db(record)
            self.client.table("source_records").upsert(data).execute()
            return True
        except Exception as e:
            logger.error(f"Failed to upsert source record {record.id} to Supabase: {e}")
            return False

    def add_chunk(self, chunk: MemoryChunk) -> bool:
        """Upsert MemoryChunk into Supabase memory_chunks table with full provenance."""
        if not self.client:
            return False
        try:
            data = self._format_chunk_for_db(chunk)
            self.client.table("memory_chunks").upsert(data).execute()
            return True
        except Exception as e:
            logger.error(f"Failed to upsert memory chunk {chunk.id} to Supabase: {e}")
            return False

    def add_chunks(self, chunks: List[MemoryChunk]) -> int:
        count = 0
        for c in chunks:
            if self.add_chunk(c):
                count += 1
        return count

    def get_chunk(self, chunk_id: str) -> Optional[MemoryChunk]:
        """Fetch a single MemoryChunk by ID from Supabase."""
        if not self.client:
            return None
        try:
            res = self.client.table("memory_chunks").select("*").eq("id", chunk_id).execute()
            rows = res.data or []
            if not rows:
                return None
            return self._row_to_chunk(rows[0])
        except Exception as e:
            logger.warning(f"Error fetching chunk {chunk_id} from Supabase: {e}")
            return None

    def get_record(self, record_id: str) -> Optional[SourceRecord]:
        """Fetch a single SourceRecord by ID from Supabase."""
        if not self.client:
            return None
        try:
            res = self.client.table("source_records").select("*").eq("id", record_id).execute()
            rows = res.data or []
            if not rows:
                return None
            row = rows[0]
            return SourceRecord(
                id=row["id"],
                organization_id=row["organization_id"],
                source_type=SourceType(row["source_type"]),
                source_uri=row.get("source_uri"),
                external_id=row.get("external_id"),
                author_id=row.get("author_id"),
                author_name=row["author_name"],
                author_role=row.get("author_role"),
                timestamp=datetime.fromisoformat(row["timestamp"].replace("Z", "+00:00")),
                raw_content=row["raw_content"],
                permission=PermissionLevel(row["permission"]),
                metadata=row.get("metadata") or {},
                hash=row.get("hash") or ""
            )
        except Exception as e:
            logger.warning(f"Error fetching record {record_id} from Supabase: {e}")
            return None

    def get_chunks_for_organization(
        self,
        organization_id: str,
        permission: Optional[PermissionLevel] = None
    ) -> List[MemoryChunk]:
        """Fetch chunks for an organization from persistent Supabase database."""
        if not self.client:
            return []
        try:
            query = self.client.table("memory_chunks").select("*").eq("organization_id", organization_id)
            if permission:
                query = query.eq("permission", permission.value)
            res = query.execute()
            rows = res.data or []
            return [self._row_to_chunk(r) for r in rows]
        except Exception as e:
            logger.warning(f"Error fetching chunks for org {organization_id} from Supabase: {e}")
            return []

    def promote_quarantined_chunks(
        self,
        organization_id: str,
        import_hash: str,
        approved_by_user_id: str,
        approval_id: str
    ) -> List[str]:
        """
        Durable Promotion RPC: Atomically promotes quarantined PENDING_REVIEW chunks to INTERNAL_CORE.
        Persists promotion audit trail in import_approvals table.
        """
        if not self.client:
            return []

        try:
            res = self.client.rpc("promote_quarantined_chunks", {
                "p_organization_id": organization_id,
                "p_import_hash": import_hash,
                "p_approved_by_user_id": approved_by_user_id,
                "p_approval_id": approval_id
            }).execute()

            if res.data and res.data.get("success"):
                return res.data.get("promoted_chunk_ids") or []
            return []
        except Exception as e:
            logger.error(f"Durable promotion RPC failed in Supabase: {e}")
            return []

    def get_candidate_counts(
        self,
        organization_id: str,
        allowed_scopes: List[PermissionLevel]
    ) -> Tuple[int, int]:
        """
        Calculates pre-retrieval candidate counts before and after ACL enforcement.
        Returns: (candidates_before_acl, candidates_after_acl)
        """
        if not self.client:
            return 0, 0
        try:
            scope_vals = [s.value for s in allowed_scopes]
            res_total = self.client.table("memory_chunks") \
                .select("id", count="exact") \
                .eq("organization_id", organization_id) \
                .execute()
            total_before = res_total.count or 0

            res_authorized = self.client.table("memory_chunks") \
                .select("id", count="exact") \
                .eq("organization_id", organization_id) \
                .in_("permission", scope_vals) \
                .execute()
            total_after = res_authorized.count or 0

            return total_before, total_after
        except Exception as e:
            logger.warning(f"Error getting candidate counts from Supabase: {e}")
            return 0, 0

    def hybrid_search(
        self,
        query: str,
        query_embedding: List[float],
        organization_id: str,
        allowed_scopes: List[PermissionLevel],
        match_count: int = 10,
        rrf_k: int = 60
    ) -> List[Tuple[float, MemoryChunk, float, float, int, int]]:
        """
        Execute pre-retrieval ACL filtered hybrid search via Supabase RPC.
        Combines pgvector cosine similarity with tsvector FTS using Reciprocal Rank Fusion (RRF).
        Returns: List of (combined_score, chunk, similarity, fts_rank, dense_rank, lexical_rank)
        """
        if not self.client:
            return []

        if len(query_embedding) != settings.EMBEDDING_DIMENSION:
            raise ValueError(
                f"Query embedding dimension mismatch: expected {settings.EMBEDDING_DIMENSION}, got {len(query_embedding)}"
            )

        try:
            scope_values = [s.value for s in allowed_scopes]
            rpc_params = {
                "query_text": query,
                "query_embedding": query_embedding,
                "match_count": match_count,
                "filter_organization_id": organization_id,
                "filter_permissions": scope_values,
                "rrf_k": rrf_k
            }
            res = self.client.rpc("hybrid_search", rpc_params).execute()
            rows = res.data or []

            results = []
            for row in rows:
                chunk = self._row_to_chunk(row)
                combined_score = float(row.get("combined_score") or 0.0)
                sim = float(row.get("similarity") or 0.0)
                fts_rank = float(row.get("fts_rank") or 0.0)
                d_rank = int(row.get("dense_rank") or 0)
                l_rank = int(row.get("lexical_rank") or 0)
                results.append((combined_score, chunk, sim, fts_rank, d_rank, l_rank))

            return results
        except Exception as e:
            logger.error(f"Supabase hybrid search failed: {e}")
            return []

    def _row_to_chunk(self, row: Dict[str, Any]) -> MemoryChunk:
        """Helper to reconstruct MemoryChunk preserving full provenance and original timestamps."""
        prov = row.get("provenance") or {}
        source_uri = row.get("source_uri") or prov.get("source_uri")
        prov["source_uri"] = source_uri

        # Deterministic timestamp reconstruction: Preserve original source_timestamp
        raw_ts = row.get("source_timestamp") or prov.get("timestamp")
        ts = None
        if raw_ts:
            if isinstance(raw_ts, datetime):
                ts = raw_ts
            else:
                try:
                    ts = datetime.fromisoformat(str(raw_ts).replace("Z", "+00:00"))
                except Exception:
                    ts = None

        if not ts:
            raise ValueError(
                f"Provenance violation: MemoryChunk row '{row.get('id')}' is missing a valid, uncorrupted source_timestamp."
            )

        raw_created = row.get("created_at")
        created_at = None
        if raw_created:
            if isinstance(raw_created, datetime):
                created_at = raw_created
            else:
                try:
                    created_at = datetime.fromisoformat(str(raw_created).replace("Z", "+00:00"))
                except Exception:
                    created_at = None

        # Fall back strictly to the verified source timestamp; never fabricate datetime.now()
        created_at = created_at or ts

        if "source_hash" in row:
            prov["source_hash"] = row.get("source_hash")
        if "ingestion_version" in row:
            prov["ingestion_version"] = row.get("ingestion_version")
        if "policy_version" in row:
            prov["policy_version"] = row.get("policy_version")
        if "embedding_model" in row:
            prov["embedding_model"] = row.get("embedding_model")
        if "embedding_dimension" in row:
            prov["embedding_dimension"] = row.get("embedding_dimension")

        raw_embedding = row.get("embedding")
        embedding = None
        if isinstance(raw_embedding, str):
            import json
            try:
                embedding = json.loads(raw_embedding)
            except Exception:
                cleaned = raw_embedding.strip().lstrip("[").rstrip("]")
                if cleaned:
                    embedding = [float(x.strip()) for x in cleaned.split(",") if x.strip()]
                else:
                    embedding = []
        elif isinstance(raw_embedding, list):
            embedding = [float(x) for x in raw_embedding]

        return MemoryChunk(
            id=row["id"],
            source_record_id=row["source_record_id"],
            organization_id=row["organization_id"],
            source_type=SourceType(row["source_type"]),
            source_uri=source_uri,
            author=row["author"],
            author_role=row.get("author_role"),
            title=row.get("title"),
            content=row["content"],
            timestamp=ts,
            created_at=created_at,
            permission=PermissionLevel(row["permission"]),
            tags=row.get("tags") or [],
            entities=row.get("entities") or {},
            embedding=embedding,
            embedding_status=row.get("embedding_status") or "ready",
            provenance=prov
        )

# Global singleton
supabase_memory_store = SupabaseMemoryStore()
