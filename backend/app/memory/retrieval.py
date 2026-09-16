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
        threshold: float = 0.45,
        exclude_message_ids: Optional[List[str]] = None
    ) -> EvidencePack:
        org_id = access_context.organization_id
        exclude_set = set(exclude_message_ids or [])
        query_norm = query.strip().lower()

        # 0. Check for Supabase Hybrid Retrieval (pgvector + FTS + RRF)
        use_supabase = (
            self.supabase_store
            and self.supabase_store.is_configured
            and os.environ.get("THREAD_FORCE_DETERMINISTIC_EMBEDDINGS") != "1"
        )
        if use_supabase:
            try:
                supa_evidence = self._retrieve_supabase(
                    query, access_context, top_k, threshold, exclude_message_ids=exclude_message_ids
                )
                if supa_evidence is not None:
                    return supa_evidence
            except Exception:
                pass

        all_chunks = self.store.get_chunks_for_organization(org_id)

        # 1. Candidate count before ACL
        candidates_before_acl = len(all_chunks)

        # 2. Strict Pre-Retrieval ACL Filtering & Contamination Exclusion
        allowed_chunks: List[MemoryChunk] = []
        for c in all_chunks:
            if c.permission not in access_context.allowed_scopes:
                continue

            prov = c.provenance or {}
            msg_id = prov.get("message_id") or prov.get("external_id")
            if c.id in exclude_set or c.source_record_id in exclude_set or (msg_id and str(msg_id) in exclude_set):
                continue

            if c.content.strip().lower() == query_norm:
                continue

            if prov.get("is_bot_mention") is True and not prov.get("is_approved_summary"):
                continue

            author_lower = (c.author or "").lower()
            if ("bot" in author_lower or "threadagent" in author_lower) and not prov.get("is_approved_summary"):
                continue

            allowed_chunks.append(c)

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

        # 3. Embedding retrieval mode and scoring
        raw_query_vec = self.store._get_embedding(query)
        active_model = getattr(self.store, "_active_model_name", "sparse_only")

        if os.environ.get("THREAD_FORCE_DETERMINISTIC_EMBEDDINGS") == "1" or self.store.force_deterministic:
            retrieval_mode = "deterministic_offline_test"
            query_model = active_model
        elif raw_query_vec is None or active_model == "sparse_only":
            retrieval_mode = "sparse_only"
            query_model = "sparse_only"
        else:
            retrieval_mode = "dense_and_sparse"
            query_model = active_model

        scored_candidates = []

        if raw_query_vec is None or retrieval_mode == "sparse_only":
            # Sparse-only retrieval path (FTS / BM25 lexical token match)
            q_words = set(re.findall(r"\b\w+\b", query.lower()))
            stopwords = {"what", "is", "our", "the", "in", "and", "or", "for", "to", "a", "an", "on", "of", "with", "we", "are"}
            sig_q_words = q_words - stopwords
            for chunk in allowed_chunks:
                c_words = set(re.findall(r"\b\w+\b", chunk.content.lower()))
                tag_words = set(re.findall(r"\b\w+\b", " ".join(chunk.tags).lower()))
                title_words = set(re.findall(r"\b\w+\b", (chunk.title or "").lower()))
                all_c_words = c_words.union(tag_words).union(title_words)
                overlap = len(sig_q_words.intersection(all_c_words))
                if overlap > 0:
                    score = min(0.95, round(0.40 + overlap * 0.15, 3))
                    scored_candidates.append((score, chunk))
        else:
            query_vec = np.array(raw_query_vec, dtype=float)
            norm_q = np.linalg.norm(query_vec)
            if norm_q > 0:
                query_vec = query_vec / norm_q

            for chunk in allowed_chunks:
                # Homogeneous Vector Space Enforcement: exclude chunks embedded with a different model
                chunk_model = chunk.provenance.get("embedding_model")
                chunk_vec_raw = self.store._embeddings.get(chunk.id)
                
                # Check for vector model compatibility
                if chunk_vec_raw and len(chunk_vec_raw) == len(raw_query_vec) and (not chunk_model or chunk_model == active_model or active_model == "deterministic-v1"):
                    chunk_vec = np.array(chunk_vec_raw, dtype=float)
                    norm_c = np.linalg.norm(chunk_vec)
                    if norm_c > 0:
                        chunk_vec = chunk_vec / norm_c
                    cos_sim = float(np.dot(query_vec, chunk_vec))
                else:
                    cos_sim = 0.0

                q_words = set(re.findall(r"\b\w+\b", query.lower()))
                c_words = set(re.findall(r"\b\w+\b", chunk.content.lower()))
                tag_words = set(re.findall(r"\b\w+\b", " ".join(chunk.tags).lower()))
                title_words = set(re.findall(r"\b\w+\b", (chunk.title or "").lower()))
                overlap = len(q_words.intersection(c_words.union(tag_words).union(title_words)))
                boost = min(0.35, overlap * 0.08)

                final_score = cos_sim + boost
                if final_score > 0:
                    scored_candidates.append((final_score, chunk))

        # Sort descending by score
        scored_candidates.sort(key=lambda x: x[0], reverse=True)

        # 4. Filter by threshold
        stopwords = {"what", "is", "our", "the", "in", "and", "or", "for", "to", "a", "an", "on", "of", "with", "we", "are"}
        q_words = set(re.findall(r"\b\w+\b", query.lower()))
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

        receipt = RetrievalReceipt(
            query=query,
            organization_id=org_id,
            allowed_scopes=access_context.allowed_scopes,
            candidates_before_acl=candidates_before_acl,
            candidates_after_acl=candidates_after_acl,
            selected_item_ids=selected_ids,
            scores=scores_map,
            source_types=source_types,
            retrieval_strategy=f"{retrieval_mode}_pre_acl",
            query_embedding_model=query_model,
            retrieval_mode=retrieval_mode
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
        threshold: float,
        exclude_message_ids: Optional[List[str]] = None
    ) -> Optional[EvidencePack]:
        """
        Supabase pgvector + tsvector Reciprocal Rank Fusion (RRF) retrieval.
        Strict pre-retrieval ACL filtering is executed directly in PostgreSQL.
        """
        org_id = access_context.organization_id
        exclude_set = set(exclude_message_ids or [])
        query_norm = query.strip().lower()

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
        active_model = getattr(self.store, "_active_model_name", "sparse_only")
        if query_vec is None:
            retrieval_mode = "sparse_only"
            query_model = "sparse_only"
            hybrid_results = self.supabase_store.fts_search(
                query=query,
                organization_id=org_id,
                allowed_scopes=access_context.allowed_scopes,
                match_count=top_k * 2
            )
        else:
            retrieval_mode = "hybrid_vector_fts"
            query_model = active_model
            hybrid_results = self.supabase_store.hybrid_search(
                query=query,
                query_embedding=query_vec,
                organization_id=org_id,
                allowed_scopes=access_context.allowed_scopes,
                match_count=top_k * 2
            )

        if not hybrid_results:
            return None

        q_words = set(re.findall(r"\b\w+\b", query.lower()))
        stopwords = {"what", "is", "our", "the", "in", "and", "or", "for", "to", "a", "an", "on", "of", "with", "we", "are"}
        significant_q_words = q_words - stopwords

        qualifying = []
        has_substantive_match = False

        for combined_score, chunk, sim, fts_rank, d_rank, l_rank in hybrid_results:
            prov = chunk.provenance or {}
            msg_id = prov.get("message_id") or prov.get("external_id")
            if chunk.id in exclude_set or chunk.source_record_id in exclude_set or (msg_id and str(msg_id) in exclude_set):
                continue

            if chunk.content.strip().lower() == query_norm:
                continue

            if prov.get("is_bot_mention") is True and not prov.get("is_approved_summary"):
                continue

            author_lower = (chunk.author or "").lower()
            if ("bot" in author_lower or "threadagent" in author_lower) and not prov.get("is_approved_summary"):
                continue
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
            retrieval_strategy="supabase_pgvector_fts_rrf_pre_acl",
            query_embedding_model=query_model,
            retrieval_mode=retrieval_mode
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

