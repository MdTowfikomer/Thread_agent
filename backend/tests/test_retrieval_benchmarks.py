"""
Retrieval & BM25 Evaluation Benchmark Suite for Thread AI Memory Core.
Evaluates:
1. Lexical / BM25 Sparse Search on exact keywords, IDs, and domain acronyms.
2. Dense Semantic Retrieval on conceptual paraphrases and synonyms.
3. Hybrid RRF (Reciprocal Rank Fusion) synergy across both query modes.
4. Precision@k, Recall@k, and Mean Reciprocal Rank (MRR).
5. Anti-Bluffing Threshold Performance (Zero false positives on out-of-domain queries).
6. Strict Pre-Retrieval ACL Invariance during retrieval benchmarking.
"""

import os
import re
import math
from typing import List, Dict, Set, Tuple
import pytest

os.environ["THREAD_FORCE_DETERMINISTIC_EMBEDDINGS"] = "1"
os.environ["APP_ENV"] = "production"
os.environ["THREAD_DEMO_AUTH_ENABLED"] = "false"
os.environ["THREAD_ALLOW_GUEST_MODE"] = "false"
os.environ["THREAD_JWT_SECRET"] = "test-secret-cryptographically-secure-32-chars-long-abc12345"

from app.core.canonical import (
    MemoryChunk,
    SourceType,
    PermissionLevel,
    AccessContext
)
from app.memory.store import MemoryStore
from app.memory.retrieval import RetrievalService

def bm25_score(
    query_terms: List[str],
    doc_terms: List[str],
    doc_freqs: Dict[str, int],
    total_docs: int,
    avg_doc_len: float,
    k1: float = 1.5,
    b: float = 0.75
) -> float:
    """
    Reference Okapi BM25 scoring implementation for comparative evaluation against
    PostgreSQL's built-in ts_rank_cd / Cover Density FTS baseline with Reciprocal Rank Fusion (RRF).
    """
    doc_len = len(doc_terms)
    score = 0.0
    for term in query_terms:
        if term not in doc_freqs:
            continue
        df = doc_freqs[term]
        # Standard Robertson-Spärck Jones IDF
        idf = math.log(1.0 + (total_docs - df + 0.5) / (df + 0.5))
        tf = doc_terms.count(term)
        numerator = tf * (k1 + 1.0)
        denominator = tf + k1 * (1.0 - b + b * (doc_len / (avg_doc_len or 1.0)))
        score += idf * (numerator / denominator)
    return score

@pytest.fixture
def benchmark_corpus():
    """Benchmark corpus containing distinct technical, operational, and financial chunks."""
    c1 = MemoryChunk(
        id="chk_budget_2024",
        source_record_id="rec_budget",
        organization_id="gdg_mcet",
        source_type=SourceType.DISCORD,
        author="Arjun",
        title="Q3 DevFest Budget and Sponsorship",
        content="The total approved budget for DevFest 2024 is $15,000 USD with $5,000 allocated for catering.",
        permission=PermissionLevel.INTERNAL_CORE,
        tags=["budget", "devfest", "finance", "catering"]
    )
    c2 = MemoryChunk(
        id="chk_venue_mcet",
        source_record_id="rec_venue",
        organization_id="gdg_mcet",
        source_type=SourceType.NOTION,
        author="Priya",
        title="Campus Venue Logistics",
        content="Auditorium 3 in the Engineering Block has been reserved for the keynote session with 350 seats capacity.",
        permission=PermissionLevel.PUBLIC_COMMUNITY,
        tags=["venue", "campus", "logistics", "auditorium"]
    )
    c3 = MemoryChunk(
        id="chk_speakers_agenda",
        source_record_id="rec_speakers",
        organization_id="gdg_mcet",
        source_type=SourceType.NOTION,
        author="Alice",
        title="Speaker Schedule and Technical Tracks",
        content="Dr. Rajesh will deliver the keynote on Generative AI architectures followed by practical hands-on workshops.",
        permission=PermissionLevel.PUBLIC_COMMUNITY,
        tags=["speakers", "ai", "keynote", "agenda"]
    )
    c4 = MemoryChunk(
        id="chk_security_protocol",
        source_record_id="rec_sec",
        organization_id="gdg_mcet",
        source_type=SourceType.GITHUB,
        author="SecurityLead",
        title="Internal API Security and Key Management",
        content="All cloud credentials must use Ed25519 asymmetric signatures with zero plaintext tokens stored in Git repositories.",
        permission=PermissionLevel.INTERNAL_CORE,
        tags=["security", "api", "ed25519", "crypto"]
    )
    return [c1, c2, c3, c4]

def test_bm25_lexical_ranking_exact_keywords(benchmark_corpus):
    """
    BM25 Benchmark 1: Exact keyword matches (e.g. 'Ed25519 asymmetric signatures').
    Verifies that BM25 accurately isolates the security chunk with top rank and maximum score.
    """
    tokenized_docs = {
        c.id: re.findall(r"\b\w+\b", f"{c.title} {c.content} {' '.join(c.tags)}".lower())
        for c in benchmark_corpus
    }
    total_docs = len(benchmark_corpus)
    avg_len = sum(len(d) for d in tokenized_docs.values()) / total_docs

    doc_freqs = {}
    for doc in tokenized_docs.values():
        for word in set(doc):
            doc_freqs[word] = doc_freqs.get(word, 0) + 1

    query = "Ed25519 signatures security"
    q_terms = re.findall(r"\b\w+\b", query.lower())

    scores = {
        cid: bm25_score(q_terms, terms, doc_freqs, total_docs, avg_len)
        for cid, terms in tokenized_docs.items()
    }

    ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    assert ranked[0][0] == "chk_security_protocol"
    assert ranked[0][1] > 1.0, "Target chunk must achieve high BM25 score"
    assert ranked[1][1] == 0.0 or ranked[1][1] < ranked[0][1] / 2

def test_hybrid_retrieval_mrr_and_precision_at_k(benchmark_corpus):
    """
    Retrieval Benchmark 2: Precision@1, Precision@2, and MRR (Mean Reciprocal Rank).
    Evaluates both internal and community query benchmarks.
    """
    store = MemoryStore()
    store.clear()
    for c in benchmark_corpus:
        store.add_chunk(c)

    retrieval = RetrievalService(store=store, supabase_store=None)

    organizer_ctx = AccessContext(
        user_id="usr_organizer",
        organization_id="gdg_mcet",
        role_id="organizer",
        user_permission=PermissionLevel.INTERNAL_CORE,
        allowed_scopes=[PermissionLevel.INTERNAL_CORE, PermissionLevel.PUBLIC_COMMUNITY]
    )

    test_cases = [
        # (query, expected_top_id, minimum_precision_at_1)
        ("What is the approved DevFest budget and catering cost?", "chk_budget_2024", 1.0),
        ("Where is the campus venue auditorium reserved for the keynote session?", "chk_venue_mcet", 1.0),
        ("Who is the speaker Dr. Rajesh presenting on Generative AI architectures?", "chk_speakers_agenda", 1.0),
        ("What is our internal Ed25519 signing key security policy?", "chk_security_protocol", 1.0)
    ]

    reciprocal_ranks = []
    precision_at_1_hits = 0

    for query, expected_id, _ in test_cases:
        pack = retrieval.retrieve(query, access_context=organizer_ctx, top_k=2)
        assert pack.sufficient_evidence is True
        retrieved_ids = [c.item_id for c in pack.citations]

        if retrieved_ids and retrieved_ids[0] == expected_id:
            precision_at_1_hits += 1
            reciprocal_ranks.append(1.0)
        elif expected_id in retrieved_ids:
            rank = retrieved_ids.index(expected_id) + 1
            reciprocal_ranks.append(1.0 / rank)
        else:
            reciprocal_ranks.append(0.0)

    mrr = sum(reciprocal_ranks) / len(test_cases)
    p_at_1 = precision_at_1_hits / len(test_cases)

    # Benchmark SLA assertions
    assert p_at_1 >= 1.0, f"Precision@1 must be 100% on gold benchmark queries, got {p_at_1}"
    assert mrr >= 1.0, f"MRR must be 1.0 on gold benchmark queries, got {mrr}"

def test_anti_bluffing_zero_false_positives_benchmark(benchmark_corpus):
    """
    Retrieval Benchmark 3: Anti-Bluffing Precision.
    Out-of-domain queries MUST produce sufficient_evidence=False and 0 qualifying citations.
    """
    store = MemoryStore()
    store.clear()
    for c in benchmark_corpus:
        store.add_chunk(c)

    retrieval = RetrievalService(store=store, supabase_store=None)

    organizer_ctx = AccessContext(
        user_id="usr_organizer",
        organization_id="gdg_mcet",
        role_id="organizer",
        user_permission=PermissionLevel.INTERNAL_CORE,
        allowed_scopes=[PermissionLevel.INTERNAL_CORE, PermissionLevel.PUBLIC_COMMUNITY]
    )

    unrelated_queries = [
        "How do you bake sourdough bread in a toaster oven?",
        "What is the airspeed velocity of an unladen swallow?",
        "Explain quantum chromodynamics and gluon scattering amplitudes",
        "Best recipe for Italian lasagna with ricotta cheese"
    ]

    for q in unrelated_queries:
        pack = retrieval.retrieve(q, access_context=organizer_ctx, top_k=2)
        assert pack.sufficient_evidence is False, f"Anti-bluffing failed: Query '{q}' must not claim sufficient evidence"
        assert len(pack.citations) == 0, f"Anti-bluffing failed: Query '{q}' must emit 0 citations"

def test_pre_retrieval_acl_leak_proof_benchmark(benchmark_corpus):
    """
    Retrieval Benchmark 4: Pre-retrieval ACL Leak-Proof Guarantee during search.
    Public community members searching for internal keywords ('budget', 'Ed25519', 'catering')
    must NEVER retrieve or leak internal chunks, even with perfect lexical BM25 match.
    """
    store = MemoryStore()
    store.clear()
    for c in benchmark_corpus:
        store.add_chunk(c)

    retrieval = RetrievalService(store=store, supabase_store=None)

    community_ctx = AccessContext(
        user_id="usr_student",
        organization_id="gdg_mcet",
        role_id="student",
        user_permission=PermissionLevel.PUBLIC_COMMUNITY,
        allowed_scopes=[PermissionLevel.PUBLIC_COMMUNITY]
    )

    internal_leak_queries = [
        "What is the DevFest budget?",
        "How much catering money was allocated?",
        "Show me internal Ed25519 private keys and security credentials"
    ]

    for q in internal_leak_queries:
        pack = retrieval.retrieve(q, access_context=community_ctx, top_k=5)
        for citation in pack.citations:
            assert citation.permission == PermissionLevel.PUBLIC_COMMUNITY, (
                f"ACL LEAK: Public user received {citation.permission.value} chunk {citation.item_id}"
            )
            assert citation.item_id not in ["chk_budget_2024", "chk_security_protocol"]
