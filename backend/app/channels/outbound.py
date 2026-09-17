import hashlib
import json
import os
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Protocol, Tuple

import httpx

from app.channels.formatter import coerce_model_text, format_response_for_platform
from app.channels.installation import guild_installation_store, slack_binding_store, telegram_binding_store
from app.channels.policy import channel_policy_store
from app.core.auth import AuthenticatedPrincipal
from app.core.canonical import ChannelType, PermissionLevel
from app.core.config import settings
from app.graph.state import GraphState
from app.graph.workflow import app_graph
from app.memory.conversation import conversation_store


class OutboundProviderError(RuntimeError):
    pass


class OutboundTimeoutError(OutboundProviderError):
    """Raised when an outbound provider request times out ambiguously."""
    pass


class OutboundRateLimitError(OutboundProviderError):
    """Raised when an outbound provider responds with HTTP 429 rate limit."""
    def __init__(self, message: str, retry_after: Optional[float] = None):
        super().__init__(message)
        self.retry_after = retry_after


class OutboundAdapter(Protocol):
    def send(self, destination: Dict[str, str], text: str, idempotency_key: str) -> str:
        ...


def _provider_post(url: str, headers: Dict[str, str], payload: Dict[str, Any]) -> Dict[str, Any]:
    last_error = "provider request failed"
    for attempt in range(3):
        try:
            response = httpx.post(url, headers=headers, json=payload, timeout=20)
            if response.status_code == 429:
                ra_val = response.headers.get("Retry-After") or response.headers.get("retry-after")
                retry_after = None
                if ra_val is not None:
                    try:
                        retry_after = float(ra_val)
                    except (ValueError, TypeError):
                        pass
                if retry_after is None:
                    try:
                        body_json = response.json()
                        if isinstance(body_json, dict) and "retry_after" in body_json:
                            retry_after = float(body_json["retry_after"])
                    except Exception:
                        pass

                last_error = f"provider 429 rate limited (retry_after={retry_after})"
                if attempt < 1:  # retry once respecting Retry-After
                    sleep_time = (retry_after if retry_after is not None and retry_after > 0 else 1.0)
                    time.sleep(sleep_time)
                    continue
                raise OutboundRateLimitError(last_error, retry_after=retry_after)

            if response.status_code in (500, 502, 503, 504):
                last_error = f"provider status {response.status_code}"
                if attempt < 2:
                    time.sleep(0.25 * (attempt + 1))
                    continue
            response.raise_for_status()
            data = response.json()
            if data.get("ok") is False:
                raise OutboundProviderError(str(data.get("error") or "provider rejected message"))
            return data
        except httpx.TimeoutException as exc:
            # Ambiguous timeout: provider may have received and posted the message.
            # Do NOT blindly retry!
            raise OutboundTimeoutError(f"Provider request timed out ambiguously: {exc}") from exc
        except OutboundRateLimitError:
            raise
        except httpx.NetworkError as exc:
            last_error = str(exc)
            if attempt < 2:
                time.sleep(0.25 * (attempt + 1))
                continue
            raise OutboundProviderError(last_error) from exc
    raise OutboundProviderError(last_error)


class SlackOutboundAdapter:
    def send(self, destination, text, idempotency_key):
        if not settings.slack_bot_token:
            raise OutboundProviderError("SLACK_BOT_TOKEN is not configured.")
        formatted_text = format_response_for_platform(text, ChannelType.SLACK)
        data = _provider_post(
            "https://slack.com/api/chat.postMessage",
            {"Authorization": f"Bearer {settings.slack_bot_token}"},
            {"channel": destination["channel_id"], "text": formatted_text},
        )
        return str(data.get("ts") or data.get("message", {}).get("ts") or "")


class TelegramOutboundAdapter:
    def send(self, destination, text, idempotency_key):
        if not settings.telegram_bot_token:
            raise OutboundProviderError("TELEGRAM_BOT_TOKEN is not configured.")
        formatted_text = format_response_for_platform(text, ChannelType.TELEGRAM)
        data = _provider_post(
            f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage",
            {},
            {"chat_id": destination["chat_id"], "text": formatted_text, "parse_mode": "HTML"},
        )
        return str(data.get("result", {}).get("message_id") or "")


class DiscordOutboundAdapter:
    def send(self, destination, text, idempotency_key):
        if not settings.discord_bot_token:
            raise OutboundProviderError("DISCORD_BOT_TOKEN is not configured.")
        formatted_text = format_response_for_platform(text, ChannelType.DISCORD)
        safe_text = formatted_text if len(formatted_text) <= 1950 else formatted_text[:1940] + "...\n*(truncated)*"
        data = _provider_post(
            f"https://discord.com/api/v10/channels/{destination['channel_id']}/messages",
            {"Authorization": f"Bot {settings.discord_bot_token}"},
            {"content": safe_text},
        )
        return str(data.get("id") or "")


class OutboundAuditStore:
    def __init__(self):
        self._rows: Dict[str, Dict[str, Any]] = {}

    def claim(self, key: str, row: Dict[str, Any], stale_timeout_seconds: int = 60) -> Tuple[bool, Optional[Dict[str, Any]]]:
        now = datetime.now(timezone.utc)
        db_url = os.getenv("SUPABASE_DB_URL") or os.getenv("DATABASE_URL")
        if db_url:
            import psycopg2
            with psycopg2.connect(db_url) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT id, delivery_status, provider_response_id, delivered_at FROM outbound_message_deliveries WHERE idempotency_key=%s FOR UPDATE",
                        (key,)
                    )
                    existing = cur.fetchone()
                    if existing:
                        curr_id, curr_status, curr_provider_id, curr_delivered_at = str(existing[0]), existing[1], existing[2], existing[3]
                        if curr_status == "sent":
                            return False, {"id": curr_id, "status": "sent", "provider_response_id": curr_provider_id}
                        elif curr_status == "unknown":
                            return False, {"id": curr_id, "status": "unknown", "provider_response_id": curr_provider_id}
                        elif curr_status == "processing":
                            if curr_delivered_at and (now - curr_delivered_at).total_seconds() < stale_timeout_seconds:
                                return False, {"id": curr_id, "status": "processing", "provider_response_id": curr_provider_id}
                            # Stale processing timeout: take over
                            cur.execute(
                                "UPDATE outbound_message_deliveries SET delivery_status='processing', delivered_at=%s WHERE idempotency_key=%s",
                                (now, key)
                            )
                            conn.commit()
                            return True, None
                        elif curr_status == "failed":
                            # Controlled retry for failed deliveries
                            cur.execute(
                                "UPDATE outbound_message_deliveries SET delivery_status='processing', delivered_at=%s WHERE idempotency_key=%s",
                                (now, key)
                            )
                            conn.commit()
                            return True, None

                    cur.execute(
                        """INSERT INTO outbound_message_deliveries
                        (idempotency_key, platform, organization_id, destination, initiating_user_id,
                         retrieval_receipt_id, source_citations, delivered_at, delivery_status)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
                        (key, row["platform"], row["organization_id"], json.dumps(row["destination"]),
                         row["initiating_user_id"], row["retrieval_receipt_id"],
                         json.dumps(row["source_citations"]), now, "processing"),
                    )
                    row["id"] = str(cur.fetchone()[0])
                conn.commit()
            return True, None

        if key in self._rows:
            existing = self._rows[key]
            curr_status = existing.get("delivery_status")
            curr_delivered_at = existing.get("timestamp")
            if curr_status == "sent":
                return False, {"id": existing["id"], "status": "sent", "provider_response_id": existing.get("provider_response_id")}
            elif curr_status == "unknown":
                return False, {"id": existing["id"], "status": "unknown", "provider_response_id": existing.get("provider_response_id")}
            elif curr_status == "processing":
                if curr_delivered_at and (now - curr_delivered_at).total_seconds() < stale_timeout_seconds:
                    return False, {"id": existing["id"], "status": "processing", "provider_response_id": existing.get("provider_response_id")}
                # Stale processing: take over
                existing["delivery_status"] = "processing"
                existing["timestamp"] = now
                return True, None
            elif curr_status == "failed":
                # Controlled retry for failed deliveries
                existing["delivery_status"] = "processing"
                existing["timestamp"] = now
                return True, None

        audit_entry = {**row, "id": key, "delivery_status": "processing", "timestamp": now}
        self._rows[key] = audit_entry
        if "raw_idempotency_key" in row and row["raw_idempotency_key"] != key:
            self._rows[row["raw_idempotency_key"]] = audit_entry
        return True, None

    def finish(self, key: str, status: str, provider_response_id: Optional[str] = None):
        db_url = os.getenv("SUPABASE_DB_URL") or os.getenv("DATABASE_URL")
        if db_url:
            import psycopg2
            with psycopg2.connect(db_url) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "UPDATE outbound_message_deliveries SET delivery_status=%s, provider_response_id=%s, delivered_at=%s WHERE idempotency_key=%s",
                        (status, provider_response_id, datetime.now(timezone.utc), key),
                    )
                conn.commit()
        if key in self._rows:
            self._rows[key].update({"delivery_status": status, "provider_response_id": provider_response_id})


class ChannelMessageDeliveryService:
    def __init__(self, audit_store: Optional[OutboundAuditStore] = None):
        self.audit_store = audit_store or outbound_audit_store
        self.adapters = {
            ChannelType.DISCORD: DiscordOutboundAdapter(),
            ChannelType.TELEGRAM: TelegramOutboundAdapter(),
            ChannelType.SLACK: SlackOutboundAdapter(),
        }

    @staticmethod
    def scope_idempotency_key(organization_id: str, user_id: str, platform: ChannelType, destination_id: str, raw_key: str) -> str:
        return hashlib.sha256(
            f"{organization_id}:{user_id}:{platform.value}:{destination_id}:{raw_key}".encode()
        ).hexdigest()

    def _resolve_destination(self, platform: ChannelType, destination_id: str, organization_id: str):
        if platform == ChannelType.TELEGRAM:
            binding = telegram_binding_store.get_binding(destination_id)
            if not binding or not binding.is_active or binding.organization_id != organization_id:
                raise PermissionError("Telegram destination is not server-bound.")
            return {"chat_id": binding.chat_id}
        if platform == ChannelType.SLACK:
            binding = slack_binding_store.get_binding_for_channel(destination_id)
            if not binding or not binding.is_active or binding.organization_id != organization_id:
                raise PermissionError("Slack destination is not server-bound.")
            return {"team_id": binding.team_id, "channel_id": destination_id}
        if platform == ChannelType.DISCORD:
            matches = []
            for guild_id, installation in guild_installation_store._installations.items():
                if installation.organization_id != organization_id or not installation.is_active:
                    continue
                policy = channel_policy_store.get_policy(organization_id, ChannelType.DISCORD, destination_id, guild_id)
                if policy and policy.is_active:
                    matches.append({"guild_id": guild_id, "channel_id": destination_id})
            if len(matches) != 1:
                raise PermissionError("Discord destination is not uniquely server-bound.")
            return matches[0]
        raise ValueError("Unsupported outbound platform.")

    def send_message(
        self,
        principal: AuthenticatedPrincipal,
        platform: ChannelType,
        destination_id: str,
        query: str,
        idempotency_key: Optional[str] = None,
        exclude_message_ids: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """Backward compatibility alias delegating to synthesize_and_send."""
        return self.synthesize_and_send(
            principal=principal,
            platform=platform,
            destination_id=destination_id,
            query=query,
            idempotency_key=idempotency_key,
            exclude_message_ids=exclude_message_ids
        )

    def synthesize_and_send(
        self,
        principal: AuthenticatedPrincipal,
        platform: ChannelType,
        destination_id: str,
        query: str,
        idempotency_key: Optional[str] = None,
        exclude_message_ids: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """Path 1: Synthesize response via graph run for explicit server/API requests, then deliver."""
        if not query.strip():
            raise ValueError("Query cannot be empty.")

        session_key = conversation_store.format_session_key(platform.value, destination_id, principal.user_id)
        chat_history = conversation_store.get_recent_turns(session_key=session_key, organization_id=principal.organization_id, limit=10)

        result = app_graph.invoke(GraphState(
            query=query,
            organization_id=principal.organization_id,
            access_context=principal.access_context,
            session_key=session_key,
            chat_history=chat_history,
            exclude_message_ids=exclude_message_ids
        ))

        intent = result.get("intent_category", "ORGANIZATIONAL_FACTS") if isinstance(result, dict) else getattr(result, "intent_category", "ORGANIZATIONAL_FACTS")
        final_answer = result.get("final_answer") if isinstance(result, dict) else getattr(result, "final_answer", "")
        evidence = result.get("evidence_pack") if isinstance(result, dict) else getattr(result, "evidence_pack", None)

        if intent == "ORGANIZATIONAL_FACTS":
            if not evidence or not getattr(evidence, "sufficient_evidence", False) or not getattr(evidence, "citations", []):
                receipt_id = getattr(evidence.receipt, "receipt_id", None) if (evidence and getattr(evidence, "receipt", None)) else None
                conversation_store.record_turn(session_key, platform.value, principal.organization_id, principal.user_id, "user", query)
                conversation_store.record_turn(session_key, platform.value, principal.organization_id, principal.user_id, "assistant", final_answer or "Insufficient evidence.")
                return {"status": "insufficient_evidence", "answer": final_answer or "Insufficient evidence.", "retrieval_receipt_id": receipt_id, "citations": []}

        destination = self._resolve_destination(platform, destination_id, principal.organization_id)

        if intent == "ORGANIZATIONAL_FACTS" and evidence and getattr(evidence, "citations", []):
            guild_id = destination.get("guild_id") or destination.get("team_id")
            dest_policy = channel_policy_store.get_policy(
                principal.organization_id, platform, destination_id, guild_id
            )
            dest_scope = dest_policy.permission_scope if dest_policy and dest_policy.is_active else PermissionLevel.PUBLIC_COMMUNITY
            for c in evidence.citations:
                if c.permission == PermissionLevel.PENDING_REVIEW:
                    raise PermissionError("Evidence with PENDING_REVIEW permission is never sendable.")
                if dest_scope == PermissionLevel.PUBLIC_COMMUNITY and c.permission != PermissionLevel.PUBLIC_COMMUNITY:
                    raise PermissionError(
                        f"Destination channel '{destination_id}' is PUBLIC_COMMUNITY but evidence contains '{c.permission.value}' citations."
                    )
            citations = [{"item_id": c.item_id, "source": c.source.value, "source_uri": c.source_uri, "permission": c.permission.value, "relevance_score": c.relevance_score} for c in evidence.citations]
            receipt_id = getattr(evidence.receipt, "receipt_id", "rcpt-direct") if getattr(evidence, "receipt", None) else "rcpt-direct"
            raw_key = idempotency_key or f"receipt_{receipt_id}"
        else:
            citations = []
            receipt_id = "direct_synthesis"
            raw_key = idempotency_key or hashlib.sha256(f"{principal.user_id}:{query}:{datetime.now(timezone.utc).isoformat()}".encode()).hexdigest()

        key = hashlib.sha256(
            f"{principal.organization_id}:{principal.user_id}:{platform.value}:{destination_id}:{raw_key}".encode()
        ).hexdigest()

        claimed, existing = self.audit_store.claim(key, {
            "platform": platform.value, "organization_id": principal.organization_id, "destination": destination,
            "initiating_user_id": principal.user_id, "retrieval_receipt_id": receipt_id,
            "source_citations": citations, "timestamp": datetime.now(timezone.utc),
            "raw_idempotency_key": raw_key,
        })
        if not claimed:
            curr_st = existing.get("status") if existing else "duplicate"
            if curr_st == "unknown":
                return {
                    "status": "unknown",
                    "delivery_id": existing["id"],
                    "provider_response_id": existing.get("provider_response_id"),
                    "message": "Delivery status unknown due to prior provider timeout. Automatic re-post is blocked.",
                }
            return {"status": "duplicate", "delivery_id": existing["id"], "provider_response_id": existing.get("provider_response_id")}
        try:
            outbound_text = final_answer or "No content available."
            provider_id = self.adapters[platform].send(destination, outbound_text, key)
            self.audit_store.finish(key, "sent", provider_id)
            conversation_store.record_turn(session_key, platform.value, principal.organization_id, principal.user_id, "user", query)
            conversation_store.record_turn(session_key, platform.value, principal.organization_id, principal.user_id, "assistant", outbound_text)
        except OutboundTimeoutError:
            self.audit_store.finish(key, "unknown", None)
            raise
        except Exception:
            self.audit_store.finish(key, "failed", None)
            raise
        return {
            "status": "sent",
            "delivery_id": key,
            "provider_response_id": provider_id,
            "retrieval_receipt_id": receipt_id,
            "citations": citations,
            "destination": destination,
            "final_answer": outbound_text
        }

    def send_prepared_message(
        self,
        principal: AuthenticatedPrincipal,
        platform: ChannelType,
        destination_id: str,
        text: Any,
        citations: Optional[List[Any]] = None,
        receipt: Optional[Any] = None,
        idempotency_key: Optional[str] = None
    ) -> Dict[str, Any]:
        """Path 2: Deliver an already validated plain-text answer without invoking app_graph."""
        # Platform adapters own formatting. Formatting here as well would make
        # Telegram escape its already-generated HTML on the second pass.
        outbound_text = coerce_model_text(text).strip()
        if not outbound_text.strip():
            raise ValueError("Text cannot be empty.")

        destination = self._resolve_destination(platform, destination_id, principal.organization_id)

        serialized_citations = []
        if citations:
            guild_id = destination.get("guild_id") or destination.get("team_id")
            dest_policy = channel_policy_store.get_policy(
                principal.organization_id, platform, destination_id, guild_id
            )
            dest_scope = dest_policy.permission_scope if dest_policy and dest_policy.is_active else PermissionLevel.PUBLIC_COMMUNITY
            for c in citations:
                perm_val = c.get("permission") if isinstance(c, dict) else getattr(c, "permission", PermissionLevel.PUBLIC_COMMUNITY)
                perm_enum = PermissionLevel(perm_val) if isinstance(perm_val, str) else perm_val
                if perm_enum == PermissionLevel.PENDING_REVIEW:
                    raise PermissionError("Evidence with PENDING_REVIEW permission is never sendable.")
                if dest_scope == PermissionLevel.PUBLIC_COMMUNITY and perm_enum != PermissionLevel.PUBLIC_COMMUNITY:
                    raise PermissionError(
                        f"Destination channel '{destination_id}' is PUBLIC_COMMUNITY but evidence contains '{perm_enum.value}' citations."
                    )
                if isinstance(c, dict):
                    serialized_citations.append(c)
                else:
                    serialized_citations.append({
                        "item_id": getattr(c, "item_id", ""),
                        "source": getattr(c.source, "value", str(c.source)) if hasattr(c, "source") else "source",
                        "source_uri": getattr(c, "source_uri", ""),
                        "permission": perm_enum.value,
                        "relevance_score": getattr(c, "relevance_score", 0.0)
                    })

        receipt_id = None
        if receipt:
            if isinstance(receipt, dict):
                receipt_id = receipt.get("receipt_id")
            else:
                receipt_id = getattr(receipt, "receipt_id", None)
        if not receipt_id:
            receipt_id = "prepared_msg"

        raw_key = idempotency_key or f"receipt_{receipt_id}"
        key = self.scope_idempotency_key(principal.organization_id, principal.user_id, platform, destination_id, raw_key)

        claimed, existing = self.audit_store.claim(key, {
            "platform": platform.value,
            "organization_id": principal.organization_id,
            "destination": destination,
            "initiating_user_id": principal.user_id,
            "retrieval_receipt_id": receipt_id,
            "source_citations": serialized_citations,
            "timestamp": datetime.now(timezone.utc),
            "raw_idempotency_key": raw_key,
        })
        if not claimed:
            curr_st = existing.get("status") if existing else "duplicate"
            if curr_st == "unknown":
                return {
                    "status": "unknown",
                    "delivery_id": existing["id"],
                    "provider_response_id": existing.get("provider_response_id"),
                    "message": "Delivery status unknown due to prior provider timeout. Automatic re-post is blocked.",
                }
            return {"status": "duplicate", "delivery_id": existing["id"], "provider_response_id": existing.get("provider_response_id")}

        try:
            provider_id = self.adapters[platform].send(destination, outbound_text, key)
            self.audit_store.finish(key, "sent", provider_id)
        except OutboundTimeoutError:
            self.audit_store.finish(key, "unknown", None)
            raise
        except Exception:
            self.audit_store.finish(key, "failed", None)
            raise

        return {
            "status": "sent",
            "delivery_id": key,
            "provider_response_id": provider_id,
            "retrieval_receipt_id": receipt_id,
            "citations": serialized_citations,
            "destination": destination,
            "final_answer": outbound_text,
            "answer": outbound_text,
        }


outbound_audit_store = OutboundAuditStore()
channel_message_delivery_service = ChannelMessageDeliveryService()
