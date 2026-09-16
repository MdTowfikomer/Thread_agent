import math
import numpy as np
from typing import List, Dict, Any, Optional
from app.core.config import settings
from app.core.canonical import (
    MemoryChunk,
    SourceRecord,
    SourceType,
    PermissionLevel
)

class MemoryStore:
    """
    In-memory vector & chunk store with provenance tracking for Thread Memory Core v0.
    """
    def __init__(self):
        self._records: Dict[str, SourceRecord] = {}
        self._chunks: Dict[str, MemoryChunk] = {}
        self._embeddings: Dict[str, List[float]] = {}
        self._external_record_ids: Dict[str, str] = {}
        self._external_chunk_ids: Dict[str, str] = {}
        self.force_deterministic: bool = False

    def _get_embedding(self, text: str) -> Optional[List[float]]:
        text = text.replace("\n", " ").strip()
        
        # 0. Force deterministic offline vector for explicit local tests ONLY
        import os
        if self.force_deterministic or os.environ.get("THREAD_FORCE_DETERMINISTIC_EMBEDDINGS") == "1":
            self._active_model_name = "deterministic-v1"
            return self._deterministic_vector(text)

        # 1. Try Gemini (768 dimensions requested directly from provider)
        if settings.has_gemini:
            try:
                from langchain_google_genai import GoogleGenerativeAIEmbeddings
                try:
                    embedder = GoogleGenerativeAIEmbeddings(
                        model=settings.DEFAULT_EMBEDDING_MODEL,
                        google_api_key=settings.gemini_api_key,
                        output_dimensionality=settings.EMBEDDING_DIMENSION
                    )
                except Exception:
                    embedder = GoogleGenerativeAIEmbeddings(
                        model=settings.DEFAULT_EMBEDDING_MODEL,
                        google_api_key=settings.gemini_api_key
                    )
                vec = embedder.embed_query(text)
                if len(vec) >= settings.EMBEDDING_DIMENSION:
                    if len(vec) > settings.EMBEDDING_DIMENSION:
                        vec = vec[:settings.EMBEDDING_DIMENSION]
                        norm = math.sqrt(sum(x * x for x in vec)) or 1.0
                        vec = [x / norm for x in vec]
                    self._active_model_name = settings.DEFAULT_EMBEDDING_MODEL
                    return vec
            except Exception:
                pass

        # 2. Try OpenAI (explicit 768 dimensions)
        if settings.has_openai:
            try:
                from langchain_openai import OpenAIEmbeddings
                embedder = OpenAIEmbeddings(
                    model="text-embedding-3-small",
                    dimensions=settings.EMBEDDING_DIMENSION,
                    openai_api_key=settings.OPENAI_API_KEY
                )
                vec = embedder.embed_query(text)
                if len(vec) == settings.EMBEDDING_DIMENSION:
                    self._active_model_name = "text-embedding-3-small"
                    return vec
            except Exception:
                pass

        # Production Runtime: NO silent hash-vector fallback! Return None to trigger sparse_only retrieval.
        self._active_model_name = "sparse_only"
        return None

    def _deterministic_vector(self, text: str) -> List[float]:
        dim = settings.EMBEDDING_DIMENSION  # Enforce exact 768 dimensions
        vec = [0.0] * dim
        for i, word in enumerate(text.lower().split()):
            idx = sum(ord(c) for c in word) % dim
            vec[idx] += 1.0 / (1.0 + i * 0.1)
        norm = math.sqrt(sum(x * x for x in vec)) or 1.0
        return [x / norm for x in vec]

    def add_record(self, record: SourceRecord):
        if record.external_id:
            ext_key = f"{record.organization_id}:{record.source_type.value}:{record.external_id}"
            if ext_key in self._external_record_ids:
                existing_id = self._external_record_ids[ext_key]
                self._records[existing_id] = record
                return
            self._external_record_ids[ext_key] = record.id
        self._records[record.id] = record

    def add_chunk(self, chunk: MemoryChunk):
        # Validate embedding dimensions and reject mismatches
        if chunk.embedding is not None:
            if len(chunk.embedding) != settings.EMBEDDING_DIMENSION:
                raise ValueError(
                    f"Embedding dimension mismatch: expected {settings.EMBEDDING_DIMENSION}, got {len(chunk.embedding)}"
                )
        else:
            text_to_embed = f"{chunk.title or ''} {chunk.author} {' '.join(chunk.tags)}: {chunk.content}"
            chunk.embedding = self._get_embedding(text_to_embed)

        active_model = getattr(self, "_active_model_name", "sparse_only")
        chunk.provenance.setdefault("embedding_model", active_model if chunk.embedding is not None else "sparse_only")
        chunk.provenance.setdefault("embedding_dimension", settings.EMBEDDING_DIMENSION if chunk.embedding is not None else 0)

        ext_id = chunk.provenance.get("message_id") or chunk.provenance.get("external_id")
        if ext_id:
            ext_key = f"{chunk.organization_id}:{chunk.source_type.value}:{ext_id}"
            if ext_key in self._external_chunk_ids:
                existing_id = self._external_chunk_ids[ext_key]
                self._chunks[existing_id] = chunk
                self._embeddings[existing_id] = chunk.embedding
                return
            self._external_chunk_ids[ext_key] = chunk.id
            
        self._chunks[chunk.id] = chunk
        self._embeddings[chunk.id] = chunk.embedding

    def add_chunks(self, chunks: List[MemoryChunk]):
        for chunk in chunks:
            self.add_chunk(chunk)

    def get_chunks_for_organization(self, organization_id: str) -> List[MemoryChunk]:
        return [c for c in self._chunks.values() if c.organization_id == organization_id]

    def get_chunk(self, chunk_id: str) -> Optional[MemoryChunk]:
        return self._chunks.get(chunk_id)

    def get_record(self, record_id: str) -> Optional[SourceRecord]:
        return self._records.get(record_id)

    def has_external_record(self, organization_id: str, source_type: SourceType, external_id: str) -> bool:
        ext_key = f"{organization_id}:{source_type.value}:{external_id}"
        return ext_key in self._external_record_ids

    def clear(self):
        self._records.clear()
        self._chunks.clear()
        self._embeddings.clear()
        self._external_record_ids.clear()
        self._external_chunk_ids.clear()

# Global singleton
memory_store = MemoryStore()
