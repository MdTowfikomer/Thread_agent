import hashlib
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional, Tuple, Union
from app.core.canonical import (
    ChannelType,
    ChannelMessage,
    SourceType,
    PermissionLevel,
    SourceRecord,
    MemoryChunk,
    IngestionReceipt,
    ChannelPolicy,
    IngestionTrustMode
)
from app.core.membership import membership_store, MembershipStore
from app.channels.base import ChannelAdapter
from app.channels.policy import channel_policy_store, ChannelPolicyStore

def parse_iso_datetime(val: Any) -> datetime:
    """
    Strict ISO-8601 parser.
    Fails deterministically on missing or malformed timestamps rather than falling back to 'now'.
    """
    if isinstance(val, datetime):
        return val if val.tzinfo else val.replace(tzinfo=timezone.utc)
    if isinstance(val, str) and val.strip():
        cleaned = val.strip().replace("Z", "+00:00")
        try:
            dt = datetime.fromisoformat(cleaned)
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except Exception as e:
            raise ValueError(f"Malformed timestamp '{val}': must be a valid ISO-8601 format.") from e
    raise ValueError(f"Missing or invalid timestamp '{val}': timestamps must not be null or empty.")

class DiscordExportAdapter(ChannelAdapter):
    """
    Channel Adapter for unverified Discord message file exports (e.g. DiscordChatExporter JSON, raw exports).
    Ingests messages through the canonical SourceRecord -> MemoryChunk pipeline.

    Security & Boundary Guarantees:
      - Manual file imports are by definition UNVERIFIED_FILE_IMPORT.
      - Any message targeting a bound internal channel from a mapped active organizer is
        strictly placed into PENDING_REVIEW (quarantined and excluded from retrieval).
        It NEVER defaults or downgrades to PUBLIC_COMMUNITY.
      - Public channels and unmapped users ingest as PUBLIC_COMMUNITY.
      - No caller-supplied trust or approval parameters exist on the public interface.
      - Exact guild matching is enforced (no wildcard guild fallback).
      - Timestamps are strictly required and validated.
    """
    channel_type = ChannelType.DISCORD

    def __init__(
        self,
        membership: Optional[MembershipStore] = None,
        policy_store: Optional[ChannelPolicyStore] = None
    ):
        self.membership_store = membership or membership_store
        self.policy_store = policy_store or channel_policy_store

    def parse_export(
        self,
        raw_export: Union[Dict[str, Any], List[Dict[str, Any]], ChannelMessage, List[ChannelMessage]],
        organization_id: str = "gdg_mcet"
    ) -> List[ChannelMessage]:
        """Parse raw export data into a normalized list of ChannelMessage instances."""
        # 1. Already a list of ChannelMessage: strictly revalidate timestamps
        if isinstance(raw_export, list) and all(isinstance(x, ChannelMessage) for x in raw_export):
            for msg in raw_export:
                if not isinstance(msg.timestamp, datetime) or msg.timestamp is None:
                    raise ValueError(f"ChannelMessage '{msg.message_id}' missing or invalid timestamp: datetime required.")
            return raw_export

        # 2. Single ChannelMessage instance: strictly revalidate timestamp
        if isinstance(raw_export, ChannelMessage):
            if not isinstance(raw_export.timestamp, datetime) or raw_export.timestamp is None:
                raise ValueError(f"ChannelMessage '{raw_export.message_id}' missing or invalid timestamp: datetime required.")
            return [raw_export]

        messages: List[ChannelMessage] = []

        # 3. DiscordChatExporter standard JSON format
        if isinstance(raw_export, dict) and "messages" in raw_export:
            guild_info = raw_export.get("guild", {})
            channel_info = raw_export.get("channel", {})

            guild_id = str(guild_info.get("id") or raw_export.get("guild_id") or "")
            guild_name = guild_info.get("name") or raw_export.get("guild_name")
            channel_id = str(channel_info.get("id") or raw_export.get("channel_id") or "general")
            channel_name = channel_info.get("name") or raw_export.get("channel_name")

            for m in raw_export.get("messages", []):
                msg_id = str(m.get("id") or m.get("message_id") or "")
                if not msg_id:
                    continue

                author_obj = m.get("author", {})
                if isinstance(author_obj, dict):
                    author_ext_id = str(author_obj.get("id") or "unknown")
                    author_name = author_obj.get("nickname") or author_obj.get("name") or "Unknown"
                else:
                    author_ext_id = str(m.get("author_id") or m.get("author_external_id") or "unknown")
                    author_name = str(m.get("author_name") or author_obj or "Unknown")

                ts = parse_iso_datetime(m.get("timestamp"))
                content = m.get("content", "")

                source_uri = m.get("source_uri") or (
                    f"https://discord.com/channels/{guild_id or '@me'}/{channel_id}/{msg_id}"
                )

                messages.append(ChannelMessage(
                    message_id=msg_id,
                    channel_type=ChannelType.DISCORD,
                    organization_id=organization_id,
                    guild_id=guild_id or None,
                    guild_name=guild_name,
                    channel_id=channel_id,
                    channel_name=channel_name,
                    author_external_id=author_ext_id,
                    author_name=author_name,
                    content=content,
                    timestamp=ts,
                    source_uri=source_uri,
                    thread_id=m.get("thread_id"),
                    attachments=m.get("attachments", []),
                    reactions=m.get("reactions", []),
                    metadata=m.get("metadata", {})
                ))
            return messages

        # 4. List of raw message dictionaries
        if isinstance(raw_export, list):
            for item in raw_export:
                if isinstance(item, ChannelMessage):
                    if not isinstance(item.timestamp, datetime) or item.timestamp is None:
                        raise ValueError(f"ChannelMessage '{item.message_id}' missing or invalid timestamp: datetime required.")
                    messages.append(item)
                elif isinstance(item, dict):
                    msg_id = str(item.get("id") or item.get("message_id") or "")
                    if not msg_id:
                        continue
                    author_obj = item.get("author", {})
                    if isinstance(author_obj, dict):
                        author_ext_id = str(author_obj.get("id") or item.get("author_id") or item.get("author_external_id") or "unknown")
                        author_name = author_obj.get("nickname") or author_obj.get("name") or item.get("author_name") or "Unknown"
                    else:
                        author_ext_id = str(item.get("author_id") or item.get("author_external_id") or "unknown")
                        author_name = str(item.get("author_name") or "Unknown")

                    guild_id = str(item.get("guild_id") or "")
                    channel_id = str(item.get("channel_id") or "general")
                    source_uri = item.get("source_uri") or (
                        f"https://discord.com/channels/{guild_id or '@me'}/{channel_id}/{msg_id}"
                    )

                    messages.append(ChannelMessage(
                        message_id=msg_id,
                        channel_type=ChannelType.DISCORD,
                        organization_id=organization_id,
                        guild_id=guild_id or None,
                        guild_name=item.get("guild_name"),
                        channel_id=channel_id,
                        channel_name=item.get("channel_name"),
                        author_external_id=author_ext_id,
                        author_name=author_name,
                        content=item.get("content", ""),
                        timestamp=parse_iso_datetime(item.get("timestamp")),
                        source_uri=source_uri,
                        thread_id=item.get("thread_id"),
                        attachments=item.get("attachments", []),
                        reactions=item.get("reactions", []),
                        metadata=item.get("metadata", {})
                    ))
            return messages

        # 5. Single raw message dictionary
        if isinstance(raw_export, dict):
            return self.parse_export([raw_export], organization_id=organization_id)

        return messages

    def ingest_message(
        self,
        message: ChannelMessage,
        organization_id: str
    ) -> Tuple[SourceRecord, List[MemoryChunk], IngestionReceipt]:
        """
        Ingest a single ChannelMessage from a manual file export.
        Unverified internal messages are quarantined into PENDING_REVIEW (excluded from retrieval).
        """
        # 0. Revalidate timestamp
        if not isinstance(message.timestamp, datetime) or message.timestamp is None:
            raise ValueError(f"Message '{message.message_id}' has missing or invalid timestamp: datetime strictly required.")

        # 1. Exact Guild & Channel Policy Lookup
        policy = self.policy_store.get_policy(
            organization_id=organization_id,
            channel_type=ChannelType.DISCORD,
            channel_id=message.channel_id,
            guild_id=message.guild_id
        )

        is_internal_channel_bound = (
            policy is not None
            and policy.is_active
            and policy.permission == PermissionLevel.INTERNAL_CORE
        )

        # 2. Resolve Identity Mapping
        mapping = self.membership_store.resolve_identity_mapping(
            organization_id=organization_id,
            channel_type=ChannelType.DISCORD,
            external_user_id=message.author_external_id
        )

        is_mapped = mapping is not None
        if is_mapped:
            ident = self.membership_store.get_identity_context(
                user_id=mapping.internal_user_id,
                organization_id=organization_id
            )
            person = self.membership_store.get_person(mapping.internal_user_id)
            author_id = mapping.internal_user_id
            author_name = person.name if person else (mapping.external_username or message.author_name)
            author_role = ident.assigned_roles[0].role_name if ident.assigned_roles else "Member"

            has_internal_scope = PermissionLevel.INTERNAL_CORE in ident.permission_scopes and ident.is_active
        else:
            author_id = None
            author_name = message.author_name
            author_role = "Discord Contributor"
            has_internal_scope = False

        # 3. Source URI & Hash
        source_uri = message.source_uri or (
            f"https://discord.com/channels/{message.guild_id or '@me'}/{message.channel_id}/{message.message_id}"
        )
        record_hash = hashlib.sha256(
            f"discord:{organization_id}:{message.message_id}:{source_uri}:{message.content}".encode("utf-8")
        ).hexdigest()

        # 4. P0 CONFIDENTIALITY ENFORCEMENT:
        # Manual file export imports are unverified.
        # If an unverified export targets an internal channel from a mapped active organizer:
        # It is QUARANTINED into non-retrievable PENDING_REVIEW.
        # It is NEVER downgraded or published as PUBLIC_COMMUNITY!
        if is_internal_channel_bound and has_internal_scope:
            permission = PermissionLevel.PENDING_REVIEW
            quarantine = True
            review_status = "quarantined_pending_organizer_approval"
        else:
            permission = PermissionLevel.PUBLIC_COMMUNITY
            quarantine = False
            review_status = "public"

        # 5. Deterministic identifiers
        record_id = f"sr_discord_{organization_id}_{message.message_id}"
        chunk_id = f"chk_discord_{organization_id}_{message.message_id}"

        # 6. Authoritative metadata protection
        raw_payload_metadata = dict(message.metadata or {})
        record_metadata = {
            "payload_metadata": raw_payload_metadata,
            "guild_id": message.guild_id,
            "guild_name": message.guild_name,
            "channel_id": message.channel_id,
            "channel_name": message.channel_name,
            "message_id": message.message_id,
            "author_external_id": message.author_external_id,
            "is_mapped": is_mapped,
            "internal_user_id": author_id,
            "thread_id": message.thread_id,
            "channel_policy_id": policy.id if policy else None,
            "channel_policy_scope": policy.permission.value if policy else PermissionLevel.PUBLIC_COMMUNITY.value,
            "trust_mode": IngestionTrustMode.UNVERIFIED_FILE_IMPORT.value,
            "quarantined_from_internal": quarantine,
            "review_status": review_status,
            "import_hash": record_hash
        }

        # 7. SourceRecord
        source_record = SourceRecord(
            id=record_id,
            organization_id=organization_id,
            source_type=SourceType.DISCORD,
            source_uri=source_uri,
            external_id=message.message_id,
            author_id=author_id,
            author_name=author_name,
            author_role=author_role,
            timestamp=message.timestamp,
            raw_content=message.content,
            permission=permission,
            metadata=record_metadata,
            hash=record_hash
        )

        # 8. MemoryChunk
        chunk_provenance = {
            "source_record_id": record_id,
            "source_type": SourceType.DISCORD.value,
            "source_uri": source_uri,
            "guild_id": message.guild_id,
            "guild_name": message.guild_name,
            "channel_id": message.channel_id,
            "channel_name": message.channel_name,
            "message_id": message.message_id,
            "author_external_id": message.author_external_id,
            "author_name": author_name,
            "is_mapped": is_mapped,
            "internal_user_id": author_id,
            "channel_policy_scope": policy.permission.value if policy else PermissionLevel.PUBLIC_COMMUNITY.value,
            "trust_mode": IngestionTrustMode.UNVERIFIED_FILE_IMPORT.value,
            "quarantined_from_internal": quarantine,
            "review_status": review_status,
            "import_hash": record_hash,
            "record_hash": record_hash,
            "ingested_at": datetime.now(timezone.utc).isoformat(),
            "adapter": "DiscordExportAdapter"
        }

        channel_display = f"#{message.channel_name}" if message.channel_name else f"Channel {message.channel_id}"
        chunk = MemoryChunk(
            id=chunk_id,
            source_record_id=record_id,
            organization_id=organization_id,
            source_type=SourceType.DISCORD,
            source_uri=source_uri,
            author=author_name,
            author_role=author_role,
            title=f"Discord {channel_display}",
            content=message.content,
            timestamp=message.timestamp,
            permission=permission,
            tags=["discord", message.channel_name or "chat"],
            entities={
                "guild": message.guild_name,
                "channel": message.channel_name,
                "author": author_name
            },
            provenance=chunk_provenance
        )

        # 9. IngestionReceipt
        receipt = IngestionReceipt(
            organization_id=organization_id,
            source_type=SourceType.DISCORD,
            source_uri=source_uri,
            records_ingested=1,
            chunks_created=1,
            status="success",
            provenance_summary={
                "record_id": record_id,
                "message_id": message.message_id,
                "channel_id": message.channel_id,
                "author_external_id": message.author_external_id,
                "author": author_name,
                "permission": permission.value,
                "is_mapped": is_mapped,
                "policy_bound": policy is not None,
                "trust_mode": IngestionTrustMode.UNVERIFIED_FILE_IMPORT.value,
                "quarantined_from_internal": quarantine,
                "import_hash": record_hash
            }
        )

        return source_record, [chunk], receipt

    def ingest_export(
        self,
        raw_export: Union[Dict[str, Any], List[Dict[str, Any]], ChannelMessage, List[ChannelMessage]],
        organization_id: str = "gdg_mcet"
    ) -> Tuple[List[SourceRecord], List[MemoryChunk], IngestionReceipt]:
        """Ingest full export batch through unverified file import pipeline."""
        messages = self.parse_export(raw_export, organization_id=organization_id)
        records: List[SourceRecord] = []
        chunks: List[MemoryChunk] = []

        seen_message_ids = set()
        quarantined_count = 0
        for msg in messages:
            if msg.message_id in seen_message_ids:
                continue
            seen_message_ids.add(msg.message_id)

            rec, chks, rec_receipt = self.ingest_message(msg, organization_id=organization_id)
            if rec_receipt.provenance_summary.get("quarantined_from_internal"):
                quarantined_count += 1

            records.append(rec)
            chunks.extend(chks)

        summary_receipt = IngestionReceipt(
            organization_id=organization_id,
            source_type=SourceType.DISCORD,
            source_uri=messages[0].source_uri if messages else None,
            records_ingested=len(records),
            chunks_created=len(chunks),
            status="success",
            provenance_summary={
                "message_count": len(messages),
                "unique_records": len(records),
                "chunks_created": len(chunks),
                "quarantined_count": quarantined_count,
                "trust_mode": IngestionTrustMode.UNVERIFIED_FILE_IMPORT.value
            }
        )

        return records, chunks, summary_receipt

class _TrustedDiscordConnectorService:
    """
    Server-internal trusted ingestion pipeline for verified live Discord streams
    (such as cryptographically signed Discord Webhooks or an authenticated Discord gateway bot).

    SECURITY CONTRACT:
    - NOT a ChannelAdapter and NOT exposed for arbitrary file imports.
    - Can ONLY be invoked by verified code paths that have already validated Discord's
      cryptographic Ed25519 signature and timestamp.
    - Sets IngestionTrustMode.VERIFIED_CONNECTOR internally.
    """
    def __init__(
        self,
        membership: Optional[MembershipStore] = None,
        policy_store: Optional[ChannelPolicyStore] = None
    ):
        self.membership_store = membership or membership_store
        self.policy_store = policy_store or channel_policy_store

    def ingest_live_message(
        self,
        message: ChannelMessage,
        organization_id: str
    ) -> Tuple[SourceRecord, List[MemoryChunk], IngestionReceipt]:
        if not isinstance(message.timestamp, datetime) or message.timestamp is None:
            raise ValueError(f"Message '{message.message_id}' missing or invalid timestamp.")

        policy = self.policy_store.get_policy(
            organization_id=organization_id,
            channel_type=ChannelType.DISCORD,
            channel_id=message.channel_id,
            guild_id=message.guild_id
        )
        is_internal_channel_bound = (
            policy is not None
            and policy.is_active
            and policy.permission == PermissionLevel.INTERNAL_CORE
        )

        mapping = self.membership_store.resolve_identity_mapping(
            organization_id=organization_id,
            channel_type=ChannelType.DISCORD,
            external_user_id=message.author_external_id
        )

        is_mapped = mapping is not None
        if is_mapped:
            ident = self.membership_store.get_identity_context(mapping.internal_user_id, organization_id)
            person = self.membership_store.get_person(mapping.internal_user_id)
            author_id = mapping.internal_user_id
            author_name = person.name if person else (mapping.external_username or message.author_name)
            author_role = ident.assigned_roles[0].role_name if ident.assigned_roles else "Member"
            has_internal_scope = PermissionLevel.INTERNAL_CORE in ident.permission_scopes and ident.is_active
        else:
            author_id = None
            author_name = message.author_name
            author_role = "Discord Contributor"
            has_internal_scope = False

        source_uri = message.source_uri or (
            f"https://discord.com/channels/{message.guild_id or '@me'}/{message.channel_id}/{message.message_id}"
        )
        record_hash = hashlib.sha256(
            f"discord:{organization_id}:{message.message_id}:{source_uri}:{message.content}".encode("utf-8")
        ).hexdigest()

        # VERIFIED CONNECTOR: Internal channel + mapped active member => INTERNAL_CORE
        if is_internal_channel_bound and has_internal_scope:
            permission = PermissionLevel.INTERNAL_CORE
            review_status = "verified_internal"
        else:
            permission = PermissionLevel.PUBLIC_COMMUNITY
            review_status = "public"

        record_id = f"sr_discord_{organization_id}_{message.message_id}"
        chunk_id = f"chk_discord_{organization_id}_{message.message_id}"

        raw_payload_metadata = dict(message.metadata or {})
        record_metadata = {
            "payload_metadata": raw_payload_metadata,
            "guild_id": message.guild_id,
            "guild_name": message.guild_name,
            "channel_id": message.channel_id,
            "channel_name": message.channel_name,
            "message_id": message.message_id,
            "author_external_id": message.author_external_id,
            "is_mapped": is_mapped,
            "internal_user_id": author_id,
            "thread_id": message.thread_id,
            "channel_policy_id": policy.id if policy else None,
            "channel_policy_scope": policy.permission.value if policy else PermissionLevel.PUBLIC_COMMUNITY.value,
            "trust_mode": IngestionTrustMode.VERIFIED_CONNECTOR.value,
            "quarantined_from_internal": False,
            "review_status": review_status,
            "import_hash": record_hash
        }

        source_record = SourceRecord(
            id=record_id,
            organization_id=organization_id,
            source_type=SourceType.DISCORD,
            source_uri=source_uri,
            external_id=message.message_id,
            author_id=author_id,
            author_name=author_name,
            author_role=author_role,
            timestamp=message.timestamp,
            raw_content=message.content,
            permission=permission,
            metadata=record_metadata,
            hash=record_hash
        )

        chunk_provenance = {
            "source_record_id": record_id,
            "source_type": SourceType.DISCORD.value,
            "source_uri": source_uri,
            "guild_id": message.guild_id,
            "guild_name": message.guild_name,
            "channel_id": message.channel_id,
            "channel_name": message.channel_name,
            "message_id": message.message_id,
            "author_external_id": message.author_external_id,
            "author_name": author_name,
            "is_mapped": is_mapped,
            "internal_user_id": author_id,
            "channel_policy_scope": policy.permission.value if policy else PermissionLevel.PUBLIC_COMMUNITY.value,
            "trust_mode": IngestionTrustMode.VERIFIED_CONNECTOR.value,
            "quarantined_from_internal": False,
            "review_status": review_status,
            "import_hash": record_hash,
            "record_hash": record_hash,
            "ingested_at": datetime.now(timezone.utc).isoformat(),
            "adapter": "DiscordWebhookConnector"
        }

        channel_display = f"#{message.channel_name}" if message.channel_name else f"Channel {message.channel_id}"
        chunk = MemoryChunk(
            id=chunk_id,
            source_record_id=record_id,
            organization_id=organization_id,
            source_type=SourceType.DISCORD,
            source_uri=source_uri,
            author=author_name,
            author_role=author_role,
            title=f"Discord {channel_display}",
            content=message.content,
            timestamp=message.timestamp,
            permission=permission,
            tags=["discord", message.channel_name or "chat"],
            entities={
                "guild": message.guild_name,
                "channel": message.channel_name,
                "author": author_name
            },
            provenance=chunk_provenance
        )

        receipt = IngestionReceipt(
            organization_id=organization_id,
            source_type=SourceType.DISCORD,
            source_uri=source_uri,
            records_ingested=1,
            chunks_created=1,
            status="success",
            provenance_summary={
                "record_id": record_id,
                "message_id": message.message_id,
                "channel_id": message.channel_id,
                "author_external_id": message.author_external_id,
                "author": author_name,
                "permission": permission.value,
                "is_mapped": is_mapped,
                "policy_bound": policy is not None,
                "trust_mode": IngestionTrustMode.VERIFIED_CONNECTOR.value,
                "quarantined_from_internal": False,
                "import_hash": record_hash
            }
        )

        return source_record, [chunk], receipt

trusted_discord_connector_service = _TrustedDiscordConnectorService()
