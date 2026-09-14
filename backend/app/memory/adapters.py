import hashlib
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Dict, Any, List, Tuple
from app.core.canonical import (
    SourceType,
    PermissionLevel,
    SourceRecord,
    MemoryChunk,
    IngestionReceipt
)

def compute_hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()

class BaseSourceAdapter(ABC):
    source_type: SourceType

    @abstractmethod
    def ingest(
        self,
        raw_source: Dict[str, Any],
        organization_id: str
    ) -> Tuple[SourceRecord, List[MemoryChunk], IngestionReceipt]:
        """
        Takes raw source payload and normalizes into a SourceRecord, MemoryChunks, and IngestionReceipt.
        Must preserve: source_type, source_uri, author, timestamp, permission, organization_id, metadata, provenance.
        """
        pass

class GenericSourceAdapter(BaseSourceAdapter):
    """
    Standard adapter supporting Discord, Slack, GitHub, GDrive, Notion, and File docs.
    Ensures strict provenance preservation and immutable chunk lineage.
    """
    def __init__(self, source_type: SourceType):
        self.source_type = source_type

    def ingest(
        self,
        raw_source: Dict[str, Any],
        organization_id: str
    ) -> Tuple[SourceRecord, List[MemoryChunk], IngestionReceipt]:
        content = raw_source.get("content", "")
        author = raw_source.get("author", "Unknown Author")
        author_role = raw_source.get("author_role")
        source_uri = raw_source.get("source_uri")
        title = raw_source.get("title")
        timestamp = raw_source.get("timestamp") or datetime.now(timezone.utc)
        if isinstance(timestamp, str):
            try:
                timestamp = datetime.fromisoformat(timestamp)
            except Exception:
                timestamp = datetime.now(timezone.utc)

        permission_raw = raw_source.get("permission", PermissionLevel.INTERNAL_CORE)
        if isinstance(permission_raw, str):
            permission = PermissionLevel(permission_raw)
        else:
            permission = permission_raw

        metadata = raw_source.get("metadata", {})
        tags = raw_source.get("tags", [])
        entities = raw_source.get("entities", {})
        external_id = raw_source.get("external_id")

        # 1. Create Immutable SourceRecord
        record_hash = compute_hash(f"{self.source_type}:{source_uri}:{content}")
        source_record = SourceRecord(
            organization_id=organization_id,
            source_type=self.source_type,
            source_uri=source_uri,
            external_id=external_id,
            author_id=raw_source.get("author_id"),
            author_name=author,
            author_role=author_role,
            timestamp=timestamp,
            raw_content=content,
            permission=permission,
            metadata=metadata,
            hash=record_hash
        )

        # 2. Generate MemoryChunk(s) with provenance lineage
        chunks: List[MemoryChunk] = []
        # For simplicity and granularity in Memory Core v0, chunking cleanly into single or segmented chunks
        chunk_provenance = {
            "source_record_id": source_record.id,
            "source_type": self.source_type.value,
            "source_uri": source_uri,
            "record_hash": record_hash,
            "ingested_at": datetime.now(timezone.utc).isoformat(),
            "author": author,
            "author_role": author_role,
            "permission": permission.value,
            "adapter": self.__class__.__name__
        }

        chunk = MemoryChunk(
            source_record_id=source_record.id,
            organization_id=organization_id,
            source_type=self.source_type,
            source_uri=source_uri,
            author=author,
            author_role=author_role,
            title=title,
            content=content,
            timestamp=timestamp,
            permission=permission,
            tags=tags,
            entities=entities,
            provenance=chunk_provenance
        )
        chunks.append(chunk)

        # 3. Create IngestionReceipt
        receipt = IngestionReceipt(
            organization_id=organization_id,
            source_type=self.source_type,
            source_uri=source_uri,
            records_ingested=1,
            chunks_created=len(chunks),
            status="success",
            provenance_summary={
                "record_id": source_record.id,
                "record_hash": record_hash,
                "author": author,
                "permission": permission.value,
                "chunk_ids": [c.id for c in chunks]
            }
        )

        return source_record, chunks, receipt

ADAPTER_REGISTRY: Dict[SourceType, BaseSourceAdapter] = {
    SourceType.DISCORD: GenericSourceAdapter(SourceType.DISCORD),
    SourceType.SLACK: GenericSourceAdapter(SourceType.SLACK),
    SourceType.GITHUB: GenericSourceAdapter(SourceType.GITHUB),
    SourceType.GDRIVE: GenericSourceAdapter(SourceType.GDRIVE),
    SourceType.NOTION: GenericSourceAdapter(SourceType.NOTION),
    SourceType.PDF: GenericSourceAdapter(SourceType.PDF),
    SourceType.JIRA: GenericSourceAdapter(SourceType.JIRA),
    SourceType.MANUAL: GenericSourceAdapter(SourceType.MANUAL),
}

def get_source_adapter(source_type: SourceType) -> BaseSourceAdapter:
    return ADAPTER_REGISTRY.get(source_type, GenericSourceAdapter(source_type))
