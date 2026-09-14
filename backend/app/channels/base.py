from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional, Tuple, Union
from app.core.canonical import (
    ChannelType,
    ChannelMessage,
    IdentityMapping,
    SourceRecord,
    MemoryChunk,
    IngestionReceipt,
    IngestionTrustMode
)

class ChannelAdapter(ABC):
    """
    Shared interface for channel adapters (Discord, Slack, Telegram, etc.).
    Normalizes platform exports/messages into ChannelMessage, resolves identity mappings,
    and ingests via the canonical SourceRecord -> MemoryChunk pipeline.
    """
    channel_type: ChannelType

    @abstractmethod
    def parse_export(
        self,
        raw_export: Union[Dict[str, Any], List[Dict[str, Any]], ChannelMessage, List[ChannelMessage]],
        organization_id: str = "gdg_mcet"
    ) -> List[ChannelMessage]:
        """
        Parse raw exported data (e.g., JSON export dump, raw message list)
        into normalized ChannelMessage instances.
        """
        pass

    @abstractmethod
    def ingest_message(
        self,
        message: ChannelMessage,
        organization_id: str
    ) -> Tuple[SourceRecord, List[MemoryChunk], IngestionReceipt]:
        """
        Ingest a single ChannelMessage through the SourceRecord -> MemoryChunk pipeline.
        Must preserve guild, channel, message ID, author external ID, timestamp, source URI, and provenance.
        """
        pass

    @abstractmethod
    def ingest_export(
        self,
        raw_export: Union[Dict[str, Any], List[Dict[str, Any]], ChannelMessage, List[ChannelMessage]],
        organization_id: str
    ) -> Tuple[List[SourceRecord], List[MemoryChunk], IngestionReceipt]:
        """
        Ingest a complete channel export through the SourceRecord -> MemoryChunk pipeline.
        """
        pass
