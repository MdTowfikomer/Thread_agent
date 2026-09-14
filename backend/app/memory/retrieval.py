import os
import re
import numpy as np
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional, Tuple
from app.core.canonical import (
    AccessContext,
    RetrievalReceipt,
    EvidencePack,
    Citation,
    PermissionLevel,
    SourceType,
    MemoryChunk
)
from app.memory.store import memory_store, MemoryStore
from app.memory.supabase_store import supabase_memory_store, SupabaseMemoryStore
from app.core.membership import membership_store

def derive_access_context(
    user_id: str = "anon",
    organization_id: str = "gdg_mcet",
    role_id: Optional[str] = None
) -> AccessContext:
    """
    Derives deterministic AccessContext exclusively from authoritative MembershipStore.
    Raw client role_id strings are ignored for privilege elevation.
    """
    return membership_store.derive_access_context(user_id=user_id, organization_id=organization_id)

class RetrievalService:
    """
    Hybrid retrieval pipeline for Thread Memory Core.
    Supports Supabase pgvector + PostgreSQL full-text search with Reciprocal Rank Fusion (RRF),
    with deterministic in-memory vector + lexical fallback.
    Enforces ACL strictly before candidate scoring at the SQL or memory boundary.
    Emits an EvidencePack with an immutable RetrievalReceipt.
    """
    def __init__(
        self,
        store: Optional[MemoryStore] = None,
        supabase_store: Optional[SupabaseMemoryStore] = None
    ):
        self.store = store or memory_store
        self.supabase_store = supabase_store or supabase_memory_store

    def retrieve(
        self,
        query: str,
        access_context: AccessContext,
        top_k: int = 4,
        threshold: float = 0.45
    ) -> EvidencePack:
        org_id = access_context.organization_id

        # 0. Check for Supabase Hybrid Retrieval (pgvector + FTS + RRF)
        use_supabase = (
            self.supabase_store
            and self.supabase_store.is_configured
            and os.environ.get("THREAD_FORCE_DETERMINISTIC_EMBEDDINGS") != "1"
        )
        if use_supabase:
            try:
                supa_evidence = self._retrieve_supabase(query, access_context, top_k, threshold)
                if supa_evidence is not None:
                    return supa_evidence
            except Exception:
                pass

        all_chunks = self.store.get_chunks_for_organization(org_id)

        
        # 1. Candidate count before ACL
        candidates_before_acl = len(all_chunks)

        # 2. Strict Pre-Retrieval ACL Filtering:
        # Items outside allowed_scopes NEVER enter the scoring pool
        allowed_chunks: List[MemoryChunk] = [
            c for c in all_chunks if c.permission in access_context.allowed_scopes
        ]
        candidates_after_acl = len(allowed_chunks)

        # Handle empty authorized candidate space
        if candidates_after_acl == 0:
            receipt = RetrievalReceipt(
                query=query,
                organization_id=org_id,
                allowed_scopes=access_context.allowed_scopes,
                candidates_before_acl=candidates_before_acl,
                candidates_after_acl=0,
                selected_item_ids=[],
                scores={},
                source_types=[],
                retrieval_strategy="deterministic_hybrid_cosine_lexical_pre_acl"
            )
            return EvidencePack(
                query=query,
                organization_id=org_id,
                citations=[],
                receipt=receipt,
                sufficient_evidence=False,
                confidence_score=0.0
            )

        # 3. Deterministic Scoring on Authorized Candidates
        query_vec = np.array(self.store._get_embedding(query), dtype=float)
        norm_q = np.linalg.norm(query_vec)
        if norm_q > 0:
            query_vec = query_vec / norm_q

        scored_candidates = []
        for chunk in allowed_chunks:
            chunk_vec = np.array(self.store._embeddings.get(chunk.id, []), dtype=float)
            if len(chunk_vec) == 0:
                continue

            norm_c = np.linalg.norm(chunk_vec)
            if norm_c > 0:
                chunk_vec = chunk_vec / norm_c

            cos_sim = float(np.dot(query_vec, chunk_vec))

            # Lexical keyword overlap bonus with clean punctuation-agnostic tokenization
            q_words = set(re.findall(r"\b\w+\b", query.lower()))
            c_words = set(re.findall(r"\b\w+\b", chunk.content.lower()))
            tag_words = set(re.findall(r"\b\w+\b", " ".join(chunk.tags).lower()))
            title_words = set(re.findall(r"\b\w+\b", (chunk.title or "").lower()))
            overlap = len(q_words.intersection(c_words.union(tag_words).union(title_words)))
            boost = min(0.35, overlap * 0.08)

            final_score = cos_sim + boost
            scored_candidates.append((final_score, chunk))

        # Sort descending by score
        scored_candidates.sort(key=lambda x: x[0], reverse=True)

        # 4. Filter by threshold
        # For an item to qualify as sufficient evidence, it must either:
        # a) Have meaningful lexical/tag overlap with query terms, OR
        # b) Have very high semantic confidence (> 0.65)
        stopwords = {"what", "is", "our", "the", "in", "and", "or", "for", "to", "a", "an", "on", "of", "with", "we", "are"}
        significant_q_words = q_words - stopwords

        qualifying = []
        has_substantive_match = False

        for score, chunk in scored_candidates:
            c_words = set(re.findall(r"\b\w+\b", chunk.content.lower()))
            tag_words = set(re.findall(r"\b\w+\b", " ".join(chunk.tags).lower()))
            title_words = set(re.findall(r"\b\w+\b", (chunk.title or "").lower()))
            overlap = len(significant_q_words.intersection(c_words.union(tag_words).union(title_words)))

            # If there's overlap or very high semantic score, it qualifies
            if overlap > 0 and score >= threshold:
                qualifying.append((score, chunk))
                has_substantive_match = True
            elif score >= 0.70:
                qualifying.append((score, chunk))
                has_substantive_match = True

        selected_items = qualifying[:top_k]
        selected_ids = [chunk.id for _, chunk in selected_items]
        scores_map = {chunk.id: round(score, 3) for score, chunk in selected_items}
        source_types = list({chunk.source_type for _, chunk in selected_items})

        # 5. Build Citations
        citations: List[Citation] = []
        for score, chunk in selected_items:
            snippet = chunk.content if len(chunk.content) <= 240 else chunk.content[:237] + "..."
            citations.append(
                Citation(
                    item_id=chunk.id,
                    source=chunk.source_type,
                    author=f"{chunk.author} ({chunk.author_role or 'Lead'})",
                    title=chunk.title,
                    snippet=snippet,
                    permission=chunk.permission,
                    source_uri=chunk.source_uri,
                    relevance_score=round(score, 3)
                )
            )

        confidence = round(selected_items[0][0], 2) if selected_items else 0.0
        sufficient = len(selected_items) > 0 and has_substantive_match

        # 6. Generate RetrievalReceipt
        # CRITICAL GUARANTEE: RetrievalReceipt contains ONLY query, allowed_scopes, counts, IDs, scores, and types.
        # NEVER unauthorized or raw chunk content!
        receipt = RetrievalReceipt(
            query=query,
            organization_id=org_id,
            allowed_scopes=access_context.allowed_scopes,
            candidates_before_acl=candidates_before_acl,
            candidates_after_acl=candidates_after_acl,
            selected_item_ids=selected_ids,
            scores=scores_map,
            source_types=source_types,
            retrieval_strategy="deterministic_hybrid_cosine_lexical_pre_acl"
        )

        return EvidencePack(
            query=query,
            organization_id=org_id,
            citations=citations,
            receipt=receipt,
            sufficient_evidence=sufficient,
            confidence_score=confidence
        )

    def _retrieve_supabase(
        self,
        query: str,
        access_context: AccessContext,
        top_k: int,
        threshold: float
    ) -> Optional[EvidencePack]:
        """
        Supabase pgvector + tsvector Reciprocal Rank Fusion (RRF) retrieval.
        Strict pre-retrieval ACL filtering is executed directly in PostgreSQL.
        """
        org_id = access_context.organization_id
        candidates_before, candidates_after = self.supabase_store.get_candidate_counts(
            org_id, access_context.allowed_scopes
        )

        if candidates_after == 0:
            receipt = RetrievalReceipt(
                query=query,
                organization_id=org_id,
                allowed_scopes=access_context.allowed_scopes,
                candidates_before_acl=candidates_before,
                candidates_after_acl=0,
                selected_item_ids=[],
                scores={},
                source_types=[],
                retrieval_strategy="supabase_pgvector_fts_rrf_pre_acl"
            )
            return EvidencePack(
                query=query,
                organization_id=org_id,
                citations=[],
                receipt=receipt,
                sufficient_evidence=False,
                confidence_score=0.0
            )

        query_vec = self.store._get_embedding(query)
        hybrid_results = self.supabase_store.hybrid_search(
            query=query,
            query_embedding=query_vec,
            organization_id=org_id,
            allowed_scopes=access_context.allowed_scopes,
            match_count=top_k * 2
        )

        if not hybrid_results:
            return None

        # Filter candidates using the same substantive evidence criteria as deterministic pipeline
        # (preventing bluffing on low-confidence random vector matches)
        q_words = set(re.findall(r"\b\w+\b", query.lower()))
        stopwords = {"what", "is", "our", "the", "in", "and", "or", "for", "to", "a", "an", "on", "of", "with", "we", "are"}
        significant_q_words = q_words - stopwords

        qualifying = []
        has_substantive_match = False

        for combined_score, chunk, sim, fts_rank, d_rank, l_rank in hybrid_results:
            c_words = set(re.findall(r"\b\w+\b", chunk.content.lower()))
            tag_words = set(re.findall(r"\b\w+\b", " ".join(chunk.tags).lower()))
            title_words = set(re.findall(r"\b\w+\b", (chunk.title or "").lower()))
            overlap = len(significant_q_words.intersection(c_words.union(tag_words).union(title_words)))

            # An item qualifies as sufficient evidence only if:
            # 1. It has meaningful keyword overlap with substantive query words and score >= threshold, OR
            # 2. It has very high semantic similarity (sim >= 0.70)
            if overlap > 0 and combined_score >= 0.015:
                qualifying.append((combined_score, chunk, sim, fts_rank, d_rank, l_rank))
                has_substantive_match = True
            elif sim >= 0.70 or fts_rank >= 0.5:
                qualifying.append((combined_score, chunk, sim, fts_rank, d_rank, l_rank))
                has_substantive_match = True

        selected_items = qualifying[:top_k]
        selected_ids = [chunk.id for _, chunk, _, _, _, _ in selected_items]
        # Preserve dense rank, lexical rank, and combined score in receipt
        scores_map = {
            chunk.id: round(combined_score, 4)
            for combined_score, chunk, _, _, _, _ in selected_items
        }
        source_types = list({chunk.source_type for _, chunk, _, _, _, _ in selected_items})

        citations: List[Citation] = []
        for combined_score, chunk, sim, fts_rank, d_rank, l_rank in selected_items:
            snippet = chunk.content if len(chunk.content) <= 240 else chunk.content[:237] + "..."
            citations.append(
                Citation(
                    item_id=chunk.id,
                    source=chunk.source_type,
                    author=f"{chunk.author} ({chunk.author_role or 'Lead'})",
                    title=chunk.title,
                    snippet=snippet,
                    permission=chunk.permission,
                    source_uri=chunk.source_uri,
                    relevance_score=round(combined_score, 4)
                )
            )

        confidence = round(selected_items[0][0], 4) if selected_items else 0.0
        sufficient = len(selected_items) > 0 and has_substantive_match

        receipt = RetrievalReceipt(
            query=query,
            organization_id=org_id,
            allowed_scopes=access_context.allowed_scopes,
            candidates_before_acl=candidates_before,
            candidates_after_acl=candidates_after,
            selected_item_ids=selected_ids,
            scores=scores_map,
            source_types=source_types,
            retrieval_strategy="supabase_pgvector_fts_rrf_pre_acl"
        )

        return EvidencePack(
            query=query,
            organization_id=org_id,
            citations=citations,
            receipt=receipt,
            sufficient_evidence=sufficient,
            confidence_score=confidence
        )

# Global singleton
retrieval_service = RetrievalService()

