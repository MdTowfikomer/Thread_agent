import hashlib
import hmac
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from app.channels.installation import slack_binding_store
from app.channels.policy import channel_policy_store
from app.core.canonical import (
    ChannelType,
    IngestionReceipt,
    MemoryChunk,
    PermissionLevel,
    SourceRecord,
    SourceType,
)
from app.core.config import settings
from app.identity.service import CrossChannelIdentityService, identity_service


SLACK_MAX_TIMESTAMP_AGE_SECONDS = 300


def verify_slack_signature(
    signature: Optional[str],
    timestamp: Optional[str],
    body: bytes,
    signing_secret: Optional[str] = None,
) -> bool:
    if not signature or not timestamp:
        return False
    try:
        timestamp_int = int(timestamp)
    except (TypeError, ValueError):
        return False
    if abs(time.time() - timestamp_int) > SLACK_MAX_TIMESTAMP_AGE_SECONDS:
        return False
    secret = signing_secret or settings.slack_signing_secret
    if not secret:
        return False
    base = f"v0:{timestamp}:{body.decode('utf-8')}".encode("utf-8")
    expected = "v0=" + hmac.new(secret.encode("utf-8"), base, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


class SlackMessageEvent:
    def __init__(
        self,
        event_id: str,
        team_id: str,
        channel_id: str,
        user_id: str,
        text: str,
        timestamp: datetime,
        organization_id: str,
        source_uri: str,
        channel_name: Optional[str] = None,
        author_name: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ):
        self.event_id = event_id
        self.team_id = team_id
        self.channel_id = channel_id
        self.user_id = user_id
        self.text = text
        self.timestamp = timestamp
        self.organization_id = organization_id
        self.source_uri = source_uri
        self.channel_name = channel_name
        self.author_name = author_name or user_id
        self.metadata = metadata or {}


class SlackConnector:
    def __init__(self, identity_svc: Optional[CrossChannelIdentityService] = None):
        self.identity_service = identity_svc or identity_service

    def parse_event(self, payload: Dict[str, Any], organization_id: str) -> Optional[SlackMessageEvent]:
        event = payload.get("event") or {}
        if event.get("type") not in ("message", "app_mention") or event.get("subtype") or event.get("bot_id"):
            return None
        text = str(event.get("text") or "").strip()
        event_id = str(payload.get("event_id") or "").strip()
        team_id = str(payload.get("team_id") or "").strip()
        channel_id = str(event.get("channel") or "").strip()
        user_id = str(event.get("user") or "").strip()
        event_ts = str(event.get("ts") or "").strip()
        if not all((event_id, team_id, channel_id, user_id, event_ts, text)):
            raise ValueError("Malformed Slack message event.")
        try:
            timestamp = datetime.fromtimestamp(float(event_ts), tz=timezone.utc)
        except ValueError as exc:
            raise ValueError("Malformed Slack event timestamp.") from exc
        return SlackMessageEvent(
            event_id=event_id,
            team_id=team_id,
            channel_id=channel_id,
            user_id=user_id,
            text=text,
            timestamp=timestamp,
            organization_id=organization_id,
            source_uri=f"https://app.slack.com/client/{team_id}/{channel_id}/p{event_ts.replace('.', '')}",
            channel_name=event.get("channel_name"),
            author_name=event.get("user_name"),
            metadata={"event_id": event_id, "event_ts": event_ts},
        )

    def ingest_message(
        self, event: SlackMessageEvent
    ) -> Tuple[SourceRecord, List[MemoryChunk], IngestionReceipt]:
        link = self.identity_service.resolve_identity(
            organization_id=event.organization_id,
            channel_type=ChannelType.SLACK,
            account_id=event.user_id,
            username=event.author_name,
            display_name=event.author_name,
        )
        policy = channel_policy_store.get_policy(
            organization_id=event.organization_id,
            channel_type=ChannelType.SLACK,
            channel_id=event.channel_id,
        )
        is_verified_internal_member = (
            link.is_registered_member
            and link.is_verified
            and PermissionLevel.INTERNAL_CORE in link.allowed_scopes
        )
        if policy and policy.is_active and policy.permission_scope == PermissionLevel.INTERNAL_CORE:
            permission = (
                PermissionLevel.INTERNAL_CORE
                if is_verified_internal_member
                else PermissionLevel.PENDING_REVIEW
            )
        else:
            permission = PermissionLevel.PUBLIC_COMMUNITY
        event_ts = event.metadata.get("event_ts") or event.event_id
        source_hash = hashlib.sha256(
            f"slack:{event.organization_id}:{event.team_id}:{event.channel_id}:{event_ts}".encode()
        ).hexdigest()
        author = (
            link.channel_link.display_name
            if link.channel_link and link.channel_link.display_name
            else event.author_name
        )
        record_id = f"src_slack_{source_hash[:16]}"
        record = SourceRecord(
            id=record_id,
            organization_id=event.organization_id,
            source_type=SourceType.SLACK,
            source_uri=event.source_uri,
            external_id=event.event_id,
            author_id=link.person_id,
            author_name=author,
            author_role=link.permission_level.value,
            timestamp=event.timestamp,
            raw_content=event.text,
            permission=permission,
            metadata={
                "event_id": event.event_id,
                "team_id": event.team_id,
                "channel_id": event.channel_id,
                "user_id": event.user_id,
                "channel_name": event.channel_name,
                "provenance": "slack_events_api",
            },
            hash=source_hash,
        )
        chunk = MemoryChunk(
            id=f"chk_slack_{source_hash[:16]}",
            source_record_id=record_id,
            organization_id=event.organization_id,
            source_type=SourceType.SLACK,
            source_uri=event.source_uri,
            author=author,
            author_role=link.permission_level.value,
            title=f"Slack #{event.channel_name or event.channel_id}",
            content=event.text,
            timestamp=event.timestamp,
            permission=permission,
            tags=["slack", event.channel_name or event.channel_id],
            entities={"team_id": event.team_id, "channel_id": event.channel_id},
            provenance={
                **event.metadata,
                "source_record_id": record_id,
                "source_uri": event.source_uri,
                "author_id": event.user_id,
                "team_id": event.team_id,
                "channel_id": event.channel_id,
                "adapter": "SlackConnector",
            },
        )
        receipt = IngestionReceipt(
            organization_id=event.organization_id,
            source_type=SourceType.SLACK,
            source_uri=event.source_uri,
            records_ingested=1,
            chunks_created=1,
            provenance_summary={
                "record_id": record_id,
                "event_id": event.event_id,
                "team_id": event.team_id,
                "channel_id": event.channel_id,
            },
        )
        return record, [chunk], receipt


slack_connector = SlackConnector()
