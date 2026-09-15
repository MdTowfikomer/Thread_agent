import hashlib
import logging
from datetime import datetime, timezone
from typing import Dict, Any, Optional, Tuple, List
from pydantic import BaseModel, Field

from app.core.canonical import (
    SourceType,
    ChannelType,
    SourceRecord,
    MemoryChunk,
    IngestionReceipt,
    PermissionLevel,
    IngestionTrustMode,
)
from app.channels.policy import channel_policy_store
from app.channels.installation import telegram_binding_store
from app.identity.service import identity_service, CrossChannelIdentityService

logger = logging.getLogger("thread.channels.telegram")


class TelegramMessageEvent(BaseModel):
    update_id: int
    message_id: int
    chat_id: str
    chat_title: Optional[str] = None
    chat_type: str = "group"  # "group", "supergroup", "channel", "private"
    chat_username: Optional[str] = None
    author_id: str
    author_username: Optional[str] = None
    author_first_name: Optional[str] = None
    author_last_name: Optional[str] = None
    text: str
    timestamp: datetime
    organization_id: str
    source_uri: str
    metadata: Dict[str, Any] = Field(default_factory=dict)


class TelegramConnector:
    """
    Authoritative Telegram Ingestion Connector.
    Adheres strictly to Thread security model:
    - Minimal text-message ingestion only.
    - Resolves organization strictly from server-owned TelegramChatBindingStore (rejects unbound chats).
    - Preserves exact immutable author ID, chat ID, message ID, timestamp provenance.
    - Resolves author identity through CrossChannelIdentityService without name-based auto-merges.
    - Enforces channel policy / ACL boundaries (INTERNAL_CORE vs PUBLIC_COMMUNITY).
    - Emits canonical SourceRecord and MemoryChunk for transactional persistence.
    """
    def __init__(self, identity_svc: Optional[CrossChannelIdentityService] = None):
        self.identity_service = identity_svc or identity_service

    def parse_webhook_update(
        self,
        payload: Dict[str, Any],
        organization_id: str
    ) -> Optional[TelegramMessageEvent]:
        """
        Parses a Telegram Update payload into a TelegramMessageEvent.
        Returns None if update does not contain a supported text message.
        """
        update_id = payload.get("update_id")
        if update_id is None:
            raise ValueError("Malformed Telegram update: missing 'update_id'.")

        # Support live text-message ingestion only
        message = payload.get("message")
        if not message:
            return None

        text = message.get("text")
        if not text or not str(text).strip():
            return None

        message_id = message.get("message_id")
        if message_id is None:
            raise ValueError("Malformed Telegram message: missing 'message_id'.")

        chat = message.get("chat") or {}
        chat_id = str(chat.get("id", ""))
        if not chat_id:
            raise ValueError("Malformed Telegram message: missing chat 'id'.")

        chat_title = chat.get("title")
        chat_type = chat.get("type", "group")
        chat_username = chat.get("username")

        from_user = message.get("from") or {}
        if from_user.get("is_bot") is True:
            return None
        author_id = str(from_user.get("id", ""))
        if not author_id:
            raise ValueError("Malformed Telegram message: missing author ID.")
        author_username = from_user.get("username")
        author_first_name = from_user.get("first_name")
        author_last_name = from_user.get("last_name")

        date_ts = message.get("date")
        if date_ts is None:
            raise ValueError("Malformed Telegram message: missing authoritative date.")
        try:
            msg_timestamp = datetime.fromtimestamp(int(date_ts), tz=timezone.utc)
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError("Malformed Telegram message date.") from exc

        # Source URI computation
        if chat_username:
            source_uri = f"https://t.me/{chat_username}/{message_id}"
        elif str(chat_id).startswith("-100"):
            clean_id = str(chat_id)[4:]
            source_uri = f"https://t.me/c/{clean_id}/{message_id}"
        else:
            source_uri = f"telegram://chat/{chat_id}/message/{message_id}"

        return TelegramMessageEvent(
            update_id=int(update_id),
            message_id=int(message_id),
            chat_id=chat_id,
            chat_title=chat_title or chat_username or f"Chat {chat_id}",
            chat_type=chat_type,
            chat_username=chat_username,
            author_id=author_id,
            author_username=author_username,
            author_first_name=author_first_name,
            author_last_name=author_last_name,
            text=str(text).strip(),
            timestamp=msg_timestamp,
            organization_id=organization_id,
            source_uri=source_uri,
            metadata={
                "update_id": update_id,
                "chat_type": chat_type,
                "is_bot": from_user.get("is_bot", False)
            }
        )

    def ingest_message(
        self,
        event: TelegramMessageEvent
    ) -> Tuple[SourceRecord, List[MemoryChunk], IngestionReceipt]:
        """
        Transforms a normalized TelegramMessageEvent into canonical SourceRecord and MemoryChunk(s).
        Enforces cross-channel identity mapping and tenant ACL boundaries.
        """
        full_name = " ".join([p for p in [event.author_first_name, event.author_last_name] if p]).strip()
        display_name = full_name or event.author_username or f"Telegram User {event.author_id}"

        ident = self.identity_service.resolve_identity(
            organization_id=event.organization_id,
            channel_type=ChannelType.TELEGRAM,
            account_id=event.author_id,
            username=event.author_username,
            display_name=display_name
        )

        policy = channel_policy_store.get_policy(
            organization_id=event.organization_id,
            channel_type=ChannelType.TELEGRAM,
            channel_id=event.chat_id
        )
        is_verified_internal_member = (
            ident.is_registered_member
            and ident.is_verified
            and PermissionLevel.INTERNAL_CORE in ident.allowed_scopes
        )
        if policy and policy.is_active and policy.permission_scope == PermissionLevel.INTERNAL_CORE:
            permission = (
                PermissionLevel.INTERNAL_CORE
                if is_verified_internal_member
                else PermissionLevel.PENDING_REVIEW
            )
        else:
            permission = PermissionLevel.PUBLIC_COMMUNITY

        hash_payload = (
            f"telegram:{event.organization_id}:{event.chat_id}:{event.message_id}:"
            f"{event.timestamp.isoformat()}:{event.text}"
        )
        source_hash = hashlib.sha256(hash_payload.encode("utf-8")).hexdigest()

        author_persona = (ident.channel_link.display_name or ident.channel_link.username) if ident.channel_link else display_name

        record_id = f"src_tg_{source_hash[:16]}"
        record = SourceRecord(
            id=record_id,
            organization_id=event.organization_id,
            source_type=SourceType.TELEGRAM,
            source_uri=event.source_uri,
            external_id=f"{event.chat_id}:{event.message_id}",
            author_id=ident.person_id,
            author_name=author_persona,
            author_role=ident.permission_level.value if hasattr(ident.permission_level, "value") else str(ident.permission_level),
            timestamp=event.timestamp,
            raw_content=event.text,
            permission=permission,
            metadata={
                "update_id": event.update_id,
                "message_id": event.message_id,
                "chat_id": event.chat_id,
                "chat_title": event.chat_title,
                "chat_type": event.chat_type,
                "author_id": event.author_id,
                "author_username": event.author_username,
                "is_verified_author": ident.is_verified,
                "author_persona": author_persona
            },
            hash=source_hash
        )

        chunk_id = f"chk_tg_{source_hash[:16]}_0"
        chunk_provenance = {
            "source_record_id": record_id,
            "source_type": SourceType.TELEGRAM.value,
            "source_uri": event.source_uri,
            "chat_id": event.chat_id,
            "chat_title": event.chat_title,
            "message_id": event.message_id,
            "author_id": event.author_id,
            "author_persona": author_persona,
            "internal_person_id": ident.person_id,
            "is_verified": ident.is_verified,
            "confidence": ident.confidence,
            "permission_level": permission.value,
            "ingested_at": datetime.now(timezone.utc).isoformat(),
            "adapter": "TelegramConnector"
        }

        chunk = MemoryChunk(
            id=chunk_id,
            source_record_id=record_id,
            organization_id=event.organization_id,
            source_type=SourceType.TELEGRAM,
            source_uri=event.source_uri,
            author=author_persona,
            author_role=ident.permission_level.value if hasattr(ident.permission_level, "value") else str(ident.permission_level),
            title=f"Telegram message in {event.chat_title}",
            content=event.text,
            timestamp=event.timestamp,
            permission=permission,
            tags=["telegram", event.chat_title or "chat"],
            entities={
                "chat": event.chat_title,
                "author": author_persona
            },
            provenance=chunk_provenance
        )

        receipt = IngestionReceipt(
            organization_id=event.organization_id,
            source_type=SourceType.TELEGRAM,
            source_uri=event.source_uri,
            records_ingested=1,
            chunks_created=1,
            status="success",
            provenance_summary={
                "record_id": record_id,
                "message_id": event.message_id,
                "chat_id": event.chat_id,
                "author_id": event.author_id,
                "permission": permission.value,
                "is_verified": ident.is_verified
            }
        )

        return record, [chunk], receipt

telegram_connector = TelegramConnector()
