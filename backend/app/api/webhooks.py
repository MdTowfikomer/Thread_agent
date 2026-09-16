import os
import json
import time
import logging
import secrets
from datetime import datetime, timezone
from typing import Dict, Any, Optional, Set
from fastapi import APIRouter, Request, HTTPException, BackgroundTasks, status
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from cryptography.exceptions import InvalidSignature
import httpx
import re

from app.core.config import settings
from app.core.auth import AuthenticatedPrincipal
from app.core.canonical import (
    ChannelType,
    AccessContext,
    PermissionLevel
)
from app.channels.installation import guild_installation_store, github_binding_store, telegram_binding_store, slack_binding_store
from app.channels.delivery import webhook_delivery_store
from app.channels.telegram import telegram_connector
from app.channels.slack import slack_connector, verify_slack_signature
from app.channels.outbound import channel_message_delivery_service
from app.identity.service import identity_service
from app.memory.repository import memory_repository
from app.core.membership import membership_store
from app.graph.state import GraphState
from app.graph.workflow import app_graph

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhooks", tags=["Webhooks"])

# Replay protection cache (records processed interaction IDs)
# UPCOMING ROADMAP: Persist replay records and guild bindings in Supabase when database is connected.
_processed_interaction_ids: Set[str] = set()

# Freshness window for Discord signature timestamps (5 minutes)
MAX_TIMESTAMP_AGE_SECONDS = 300

# Discord Message Flags: 1 << 6 (64) is EPHEMERAL.
# Essential for zero-confidentiality-leak ACL: all slash responses must be visible ONLY to invoking user.
DISCORD_EPHEMERAL_FLAG = 64

def clear_processed_interactions():
    """Helper for stateless testing."""
    _processed_interaction_ids.clear()

def verify_discord_signature(signature_hex: Optional[str], timestamp_str: Optional[str], body_bytes: bytes) -> bool:
    """
    Cryptographically verify Discord's Ed25519 signature over (timestamp + body).
    """
    if not signature_hex or not timestamp_str:
        return False

    public_key_hex = settings.discord_public_key
    if not public_key_hex:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Discord public key is not configured on the server."
        )

    try:
        public_key_bytes = bytes.fromhex(public_key_hex)
        verify_key = Ed25519PublicKey.from_public_bytes(public_key_bytes)
        signature_bytes = bytes.fromhex(signature_hex)
        message = timestamp_str.encode("utf-8") + body_bytes
        verify_key.verify(signature_bytes, message)
        return True
    except (ValueError, InvalidSignature):
        return False
    except Exception:
        return False

async def _process_and_followup_interaction(
    application_id: Optional[str],
    interaction_token: Optional[str],
    graph_state: GraphState
):
    """Execute graph reconstruction and patch original deferred message on Discord."""
    try:
        import asyncio
        result = await asyncio.to_thread(app_graph.invoke, graph_state)
        final_answer = result.get("final_answer", "").strip()
        if not final_answer:
            final_answer = "Based on verified organizational records, no conclusive answer could be derived."
        if len(final_answer) > 1990:
            final_answer = final_answer[:1990] + "..."

        app_id = application_id or os.getenv("DISCORD_APPLICATION_ID", "1549157747495280641")
        if app_id and interaction_token:
            url = f"https://discord.com/api/v10/webhooks/{app_id}/{interaction_token}/messages/@original"
            async with httpx.AsyncClient(timeout=25.0) as http_client:
                resp = await http_client.patch(url, json={"content": final_answer})
                if not resp.is_success:
                    logger.error(f"[Discord Follow-up] Failed to patch interaction: {resp.status_code} - {resp.text}")
                else:
                    logger.info("[Discord Follow-up] Successfully patched interaction response.")
    except Exception as e:
        logger.exception(f"Discord interaction follow-up dispatch failed: {e}")

@router.post("/discord")
async def discord_interactions_endpoint(request: Request, background_tasks: BackgroundTasks):
    """
    Discord Live Interactions Endpoint (for /ask-thread slash commands & interactions).

    SECURITY CONTRACT & SPECIFICATION:
    1. Cryptographically authenticates Discord requests via Ed25519 signature.
    2. Enforces timestamp freshness (rejects stale requests outside 300s window).
    3. Replay protection: tracks and rejects previously processed interaction IDs (409 Conflict).
    4. Guild-to-Org binding: resolves guild_id authoritatively from server-owned GuildInstallationStore.
       Neither query parameters nor payload overrides are permitted. Unknown guilds are rejected with 403.
    5. Interaction Deadline Compliance:
       Immediately returns a Deferred Interaction Response (Type 5: DEFERRED_CHANNEL_MESSAGE_WITH_SOURCE)
       within Discord's 3-second window, and asynchronously dispatches synthesis to the follow-up endpoint.
       (Immediate Type 4 execution is preserved when requested via X-Test-Immediate-Response header or payload.immediate).
    """
    signature = request.headers.get("X-Signature-Ed25519")
    timestamp = request.headers.get("X-Signature-Timestamp")
    body_bytes = await request.body()

    if not signature or not timestamp:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized: Missing Discord signature headers (X-Signature-Ed25519, X-Signature-Timestamp)."
        )

    # 1. Freshness window check (P2 Replay mitigation)
    try:
        ts_float = float(timestamp)
    except (ValueError, TypeError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized: Invalid signature timestamp format."
        )

    current_time = time.time()
    if abs(current_time - ts_float) > MAX_TIMESTAMP_AGE_SECONDS:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=(
                f"Unauthorized: Signature timestamp is outside the freshness window "
                f"(age: {abs(current_time - ts_float):.1f}s, max: {MAX_TIMESTAMP_AGE_SECONDS}s)."
            )
        )

    # 2. Cryptographic signature check
    is_valid = verify_discord_signature(signature, timestamp, body_bytes)
    if not is_valid:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized: Invalid Discord Ed25519 cryptographic signature."
        )

    # 3. Parse JSON payload
    try:
        payload = json.loads(body_bytes.decode("utf-8"))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Malformed JSON: {str(e)}")

    interaction_id = str(payload.get("id") or "")
    if not interaction_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing interaction ID.")

    # 4. Anti-Replay ID verification
    if interaction_id in _processed_interaction_ids:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Conflict: Replay detected. Interaction '{interaction_id}' has already been processed."
        )
    _processed_interaction_ids.add(interaction_id)

    interaction_type = payload.get("type")

    # 5. Handle Discord Interaction PING (type == 1)
    if interaction_type == 1:
        return {"type": 1}

    # 6. Handle Discord Application Command (type == 2, e.g. /ask-thread)
    if interaction_type == 2:
        guild_id = str(payload.get("guild_id") or "")
        if not guild_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Forbidden: Interactions must originate from an installed guild."
            )

        # Authoritative guild -> organization resolution (no caller or payload override)
        org_id = guild_installation_store.get_organization_for_guild(guild_id)
        if not org_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Forbidden: Guild '{guild_id}' is not installed or bound to any organization."
            )

        cmd_data = payload.get("data") or {}
        cmd_name = cmd_data.get("name")
        options = {opt.get("name"): opt.get("value") for opt in cmd_data.get("options", [])}
        user_query = options.get("query") or options.get("question") or ""

        # Extract user identity
        member_data = payload.get("member") or {}
        user_data = member_data.get("user") or payload.get("user") or {}
        author_external_id = str(user_data.get("id") or "")

        # Resolve identity mapping authoritatively
        mapping = membership_store.resolve_identity_mapping(
            organization_id=org_id,
            channel_type=ChannelType.DISCORD,
            external_user_id=author_external_id
        )

        if mapping:
            access_context = membership_store.derive_access_context(mapping.internal_user_id, org_id)
        else:
            access_context = AccessContext(
                user_id=f"discord_{author_external_id}" if author_external_id else "discord_anon",
                organization_id=org_id,
                role_id="public_guest",
                user_permission=PermissionLevel.PUBLIC_COMMUNITY,
                allowed_scopes=[PermissionLevel.PUBLIC_COMMUNITY]
            )

        graph_state = GraphState(
            query=user_query,
            organization_id=org_id,
            access_context=access_context,
            exclude_message_ids=[interaction_id]
        )

        app_id = payload.get("application_id") or os.getenv("DISCORD_APPLICATION_ID", "1549157747495280641")
        token = payload.get("token")
        is_immediate = (
            request.headers.get("X-Test-Immediate-Response") == "true"
            or payload.get("immediate") is True
        )

        if is_immediate:
            # Synchronous response for direct testing
            result = app_graph.invoke(graph_state)
            final_answer = result.get("final_answer", "")
            evidence_pack = result.get("evidence_pack")

            return {
                "type": 4,  # CHANNEL_MESSAGE_WITH_SOURCE
                "data": {
                    "content": final_answer,
                    "flags": DISCORD_EPHEMERAL_FLAG  # Confidentiality protection: ephemeral, visible only to invoking user
                },
                "thread_meta": {
                    "organization_id": org_id,
                    "user_id": access_context.user_id,
                    "allowed_scopes": [s.value for s in access_context.allowed_scopes],
                    "sufficient_evidence": evidence_pack.sufficient_evidence if evidence_pack else False,
                    "citations_count": len(evidence_pack.citations) if evidence_pack else 0
                }
            }

        # Discord 3-second deadline compliance: Immediate Type 5 Deferred Response
        background_tasks.add_task(
            _process_and_followup_interaction,
            application_id=app_id,
            interaction_token=token,
            graph_state=graph_state
        )

        return {
            "type": 5,  # DEFERRED_CHANNEL_MESSAGE_WITH_SOURCE
            "data": {
                "flags": DISCORD_EPHEMERAL_FLAG  # Confidentiality protection: ephemeral, visible only to invoking user
            },
            "thread_meta": {
                "status": "deferred",
                "interaction_id": interaction_id,
                "organization_id": org_id,
                "user_id": access_context.user_id,
                "allowed_scopes": [s.value for s in access_context.allowed_scopes]
            }
        }

    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=f"Unsupported interaction type: {interaction_type}"
    )

@router.post("/github", status_code=status.HTTP_200_OK)
async def github_webhook(request: Request):
    """
    GitHub Webhook Ingestion Endpoint.
    Handles pull_request, pull_request_review, issue_comment, issues, and push events.
    Enforces:
    1. Unconditional HMAC-SHA256 signature verification (reject missing/invalid with 401).
    2. Server-owned installation binding (resolves repository_id / repository_name -> organization_id; 403 if unbound).
    3. Replay protection (deduplicates X-GitHub-Delivery).
    4. Durable transactional persistence via memory_repository.
    """
    from app.channels.github import github_connector, verify_github_signature, SUPPORTED_GITHUB_EVENTS

    # 1. Unconditional signature enforcement
    secret = settings.github_webhook_secret
    if not secret:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="GitHub webhook secret is not configured on server."
        )

    body_bytes = await request.body()
    sig_header = request.headers.get("X-Hub-Signature-256")
    if not sig_header or not verify_github_signature(body_bytes, sig_header, secret):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid GitHub webhook HMAC-SHA256 signature."
        )

    # 2. Required Delivery ID and Event headers
    delivery_id = request.headers.get("X-GitHub-Delivery")
    if not delivery_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing X-GitHub-Delivery header."
        )

    event_type = request.headers.get("X-GitHub-Event")
    if not event_type:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing X-GitHub-Event header."
        )

    # 3. Parse JSON payload
    try:
        payload = json.loads(body_bytes.decode("utf-8"))
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Malformed JSON payload: {e}"
        )

    # 4. Resolve organization strictly via server-owned repository binding
    repo = payload.get("repository", {})
    repo_id = str(repo.get("id")) if repo.get("id") is not None else None
    repo_name = repo.get("full_name") or repo.get("name")

    org_id = github_binding_store.get_organization_for_repository(repo_id, repo_name)
    if not org_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Repository '{repo_name}' (ID: {repo_id}) is not bound to any organization."
        )

    # 5. Delivery claiming & replay protection (lifecycle states)
    try:
        can_process, claim_status, message = webhook_delivery_store.claim_delivery(
            delivery_id=delivery_id,
            organization_id=org_id,
            channel_type="github",
            event_type=event_type,
            repository_id=repo_id
        )
    except Exception as e:
        logger.error(f"Delivery ledger error for delivery {delivery_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Delivery ledger unavailable: {e}"
        )

    if not can_process:
        if claim_status == "duplicate":
            return {
                "status": "duplicate",
                "delivery_id": delivery_id,
                "event_type": event_type,
                "organization_id": org_id,
                "records_count": 0,
                "chunks_count": 0,
                "message": message or f"Delivery {delivery_id} already processed."
            }
        elif claim_status == "in_progress":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=message or f"Delivery {delivery_id} is currently being processed."
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=message or f"Cannot process delivery {delivery_id}."
            )

    # Check if event is intentionally unsupported / ignored
    if event_type not in SUPPORTED_GITHUB_EVENTS:
        logger.info(f"Ignoring unsupported GitHub event '{event_type}' for delivery {delivery_id}.")
        webhook_delivery_store.mark_completed(delivery_id)
        return {
            "status": "ignored",
            "event_type": event_type,
            "delivery_id": delivery_id,
            "organization_id": org_id,
            "records_count": 0,
            "chunks_count": 0,
            "message": f"Event '{event_type}' is intentionally ignored."
        }

    # 6. Parse and transactionally persist events
    try:
        try:
            events = github_connector.parse_webhook_payload(event_type, payload, org_id)
        except Exception as e:
            logger.error(f"Error parsing supported GitHub event '{event_type}' for delivery {delivery_id}: {e}")
            webhook_delivery_store.mark_failed(delivery_id, f"Parse error: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Malformed or unparseable payload for supported event '{event_type}': {e}"
            )

        ingested_records = []
        ingested_chunks = []
        for ev in events:
            record, chunks, receipt = github_connector.ingest_event(ev)
            ok, _ = memory_repository.persist_record_and_chunks(record, chunks)
            if not ok:
                raise RuntimeError("Failed to persist record and chunks to memory repository.")
            ingested_records.append(record.id)
            ingested_chunks.extend([c.id for c in chunks])

        # Mark successfully completed
        webhook_delivery_store.mark_completed(delivery_id)

    except Exception as e:
        logger.error(f"GitHub webhook processing failure for delivery {delivery_id}: {e}")
        webhook_delivery_store.mark_failed(delivery_id, str(e))
        if isinstance(e, HTTPException):
            raise
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Webhook ingestion error: {e}"
        )

    return {
        "status": "ingested",
        "event_type": event_type,
        "organization_id": org_id,
        "delivery_id": delivery_id,
        "records_count": len(ingested_records),
        "chunks_count": len(ingested_chunks),
        "record_ids": ingested_records,
        "chunk_ids": ingested_chunks
    }


# =====================================================================
# TELEGRAM LIVE WEBHOOK INGESTION
# =====================================================================

@router.post("/telegram")
async def handle_telegram_webhook(request: Request):
    """
    Authoritative Telegram Ingestion Webhook.
    Security Guarantees:
    1. Cryptographic secret token verification:
       Requires X-Telegram-Bot-Api-Secret-Token matching configured telegram_webhook_secret.
       Fails closed with 401 Unauthorized if missing, mismatched, or unconfigured.
    2. Tenant isolation via server-owned TelegramChatBindingStore:
       Rejects messages from unknown or unbound chats with 403 Forbidden.
    3. Replay protection & delivery ledger:
       Deduplicates on delivery ID (tg_update_{update_id}) with claim_delivery.
    4. Text-only message support:
       Ignores unsupported update types / non-text messages safely with 200 ignored.
    5. Fail-closed transactional persistence into memory_repository.
    """
    # 1. Cryptographic Secret Token Verification
    secret_header = request.headers.get("X-Telegram-Bot-Api-Secret-Token")
    expected_secret = settings.telegram_webhook_secret

    if not expected_secret:
        logger.error("Telegram webhook secret is not configured on the server.")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Telegram webhook secret is not configured."
        )

    if not secret_header or not secrets.compare_digest(secret_header, expected_secret):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing Telegram webhook secret token."
        )

    # 2. Parse JSON Payload
    body_bytes = await request.body()
    try:
        payload = json.loads(body_bytes.decode("utf-8"))
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Malformed JSON payload: {e}"
        )

    update_id = payload.get("update_id")
    if update_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing update_id in Telegram update."
        )

    delivery_id = f"tg_update_{update_id}"

    # 3. Extract Message & Chat
    message = payload.get("message")
    if not message:
        # Unsupported update type (callback_query, channel_post, etc.)
        return {
            "status": "ignored",
            "delivery_id": delivery_id,
            "message": "Update does not contain a supported user message."
        }

    chat = message.get("chat") or {}
    chat_id = str(chat.get("id", ""))
    if not chat_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing chat ID in Telegram message."
        )

    # 4. Resolve Organization Strictly via Server-Owned Chat Binding
    org_id = telegram_binding_store.get_organization_for_chat(chat_id)
    if not org_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Chat '{chat_id}' is not bound to any organization."
        )

    # 5. Delivery Claiming & Replay Protection
    try:
        can_process, claim_status, claim_msg = webhook_delivery_store.claim_delivery(
            delivery_id=delivery_id,
            organization_id=org_id,
            channel_type="telegram",
            event_type="message",
            repository_id=chat_id
        )
    except Exception as e:
        logger.error(f"Delivery ledger error for Telegram delivery {delivery_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Delivery ledger unavailable: {e}"
        )

    if not can_process:
        if claim_status == "duplicate":
            return {
                "status": "duplicate",
                "delivery_id": delivery_id,
                "organization_id": org_id,
                "message": claim_msg or f"Delivery {delivery_id} already processed."
            }
        elif claim_status == "in_progress":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=claim_msg or f"Delivery {delivery_id} is currently being processed."
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=claim_msg or f"Cannot process delivery {delivery_id}."
            )

    # 6. Check for Text-Message Only Support
    text = message.get("text")
    if not text or not str(text).strip():
        webhook_delivery_store.mark_completed(delivery_id)
        return {
            "status": "ignored",
            "delivery_id": delivery_id,
            "organization_id": org_id,
            "message": "Only text messages are supported."
        }

    raw_text = str(text).strip()
    chat_type = str(chat.get("type") or "group")
    is_private = chat_type == "private"

    entities = message.get("entities") or []
    is_bot_mention_entity = any(
        e.get("type") == "bot_command"
        or (
            e.get("type") == "mention"
            and any(k in raw_text[e["offset"]:e["offset"] + e["length"]].lower() for k in ("thread", "bot"))
        )
        for e in entities
        if "offset" in e and "length" in e
    )
    has_text_mention = bool(
        re.search(r"@GDGCThreadBot\b", raw_text, re.IGNORECASE)
        or re.search(r"@\w*thread\w*bot\b", raw_text, re.IGNORECASE)
        or re.search(r"@ThreadAgent\b", raw_text, re.IGNORECASE)
    )
    is_reply_to_bot = bool(
        message.get("reply_to_message", {}).get("from", {}).get("is_bot") is True
    )

    should_reply = is_private or is_bot_mention_entity or has_text_mention or is_reply_to_bot

    from app.channels.inbound_service import inbound_agent_query_service

    # 7. Agent-Directed Branch: Process via InboundAgentQueryService without source_record ingestion
    if should_reply:
        msg_id_str = str(message.get("message_id") or delivery_id)
        inbound_agent_query_service.mark_agent_message(msg_id_str)
        inbound_agent_query_service.mark_agent_message(delivery_id)

        reply_delivery_id = f"tg_reply_{chat_id}_{msg_id_str}"
        can_reply, reply_status, reply_msg = webhook_delivery_store.claim_delivery(
            delivery_id=reply_delivery_id,
            organization_id=org_id,
            channel_type="telegram",
            event_type="mention_reply",
            repository_id=chat_id,
        )

        if can_reply:
            try:
                from app.channels.policy import channel_policy_store
                from app.channels.outbound import TelegramOutboundAdapter

                clean_query = re.sub(r"@\w*thread\w*bot\b", "", raw_text, flags=re.IGNORECASE)
                clean_query = re.sub(r"@ThreadAgent\b", "", clean_query, flags=re.IGNORECASE)
                clean_query = re.sub(r"^/\w+\s*", "", clean_query).strip()

                from_user = message.get("from") or {}
                user_id = str(from_user.get("id") or "telegram_anon")
                username = from_user.get("username") or user_id
                first_name = from_user.get("first_name") or ""
                last_name = from_user.get("last_name") or ""
                display_name = f"{first_name} {last_name}".strip() or username

                adapter = TelegramOutboundAdapter()

                if not clean_query:
                    adapter.send(
                        {"chat_id": chat_id},
                        "Hello! I am Thread Agent for GDG MCET. Ask me anything about our team, events, or verified records!",
                        reply_delivery_id,
                    )
                    webhook_delivery_store.mark_completed(reply_delivery_id)
                    webhook_delivery_store.mark_completed(delivery_id)
                    return {
                        "status": "responded",
                        "channel": "telegram",
                        "organization_id": org_id,
                        "delivery_id": delivery_id,
                        "reply_delivery_id": reply_delivery_id,
                    }

                link = identity_service.resolve_identity(
                    organization_id=org_id,
                    channel_type=ChannelType.TELEGRAM,
                    account_id=user_id,
                    username=username,
                    display_name=display_name,
                )
                access_context = membership_store.derive_access_context(
                    user_id=link.person_id,
                    organization_id=org_id,
                )
                principal = AuthenticatedPrincipal(
                    user_id=link.person_id,
                    organization_id=org_id,
                    access_context=access_context,
                )

                policy = channel_policy_store.get_policy(org_id, ChannelType.TELEGRAM, chat_id)
                if not policy or not policy.is_active:
                    channel_policy_store.register_policy(
                        organization_id=org_id,
                        channel_type=ChannelType.TELEGRAM,
                        channel_id=chat_id,
                        permission_scope=PermissionLevel.PUBLIC_COMMUNITY,
                        channel_name=chat.get("title") or chat.get("username") or "Telegram Chat",
                    )

                send_result = inbound_agent_query_service.process_and_deliver(
                    principal=principal,
                    platform=ChannelType.TELEGRAM,
                    destination_id=chat_id,
                    query=clean_query,
                    idempotency_key=reply_delivery_id,
                    exclude_message_ids=[msg_id_str, delivery_id, reply_delivery_id],
                    triggering_message_id=msg_id_str
                )

                if send_result.get("status") == "insufficient_evidence":
                    adapter.send(
                        {"chat_id": chat_id},
                        "Based on verified organizational records, there is insufficient evidence to answer this inquiry within this chat's scope.",
                        reply_delivery_id,
                    )

                webhook_delivery_store.mark_completed(reply_delivery_id)
                webhook_delivery_store.mark_completed(delivery_id)
                return {
                    "status": "responded",
                    "channel": "telegram",
                    "organization_id": org_id,
                    "delivery_id": delivery_id,
                    "reply_delivery_id": reply_delivery_id,
                    "chat_id": chat_id,
                    "message_id": msg_id_str,
                    "send_result": send_result,
                }
            except Exception as e:
                logger.error(f"Telegram mention reply error for delivery {delivery_id}: {e}")
                webhook_delivery_store.mark_failed(reply_delivery_id, str(e))
                webhook_delivery_store.mark_failed(delivery_id, str(e))
                return {
                    "status": "reply_failed",
                    "delivery_id": delivery_id,
                    "error": str(e),
                }

    # 8. Ordinary Non-Agent Channel Discussion Ingestion (canonical source_records)
    try:
        event = telegram_connector.parse_webhook_update(payload, org_id)
        if not event or inbound_agent_query_service.is_agent_message(str(event.message_id)):
            webhook_delivery_store.mark_completed(delivery_id)
            return {
                "status": "ignored",
                "delivery_id": delivery_id,
                "organization_id": org_id,
                "message": "Message ignored or already handled as agent query."
            }

        record, chunks, receipt = telegram_connector.ingest_message(event)
        ok, _ = memory_repository.persist_record_and_chunks(record, chunks)
        if not ok:
            raise RuntimeError("Failed to persist record and chunks to memory repository.")

        webhook_delivery_store.mark_completed(delivery_id)
        return {
            "status": "ingested",
            "channel": "telegram",
            "organization_id": org_id,
            "delivery_id": delivery_id,
            "chat_id": event.chat_id,
            "message_id": event.message_id,
            "record_id": record.id,
            "chunk_ids": [c.id for c in chunks]
        }
    except Exception as e:
        logger.error(f"Telegram webhook processing failure for delivery {delivery_id}: {e}")
        webhook_delivery_store.mark_failed(delivery_id, str(e))
        if isinstance(e, HTTPException):
            raise
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Telegram ingestion error: {e}"
        )


async def _process_slack_app_mention_background(
    principal: AuthenticatedPrincipal,
    channel_id: str,
    query: str,
    reply_delivery_id: str,
    event_delivery_id: str,
    event_id: str,
    team_id: str,
    event_ts: str
):
    """Background worker executing synthesis and Slack outbound posting after HTTP 200 acknowledgement."""
    try:
        from app.channels.inbound_service import inbound_agent_query_service
        send_result = inbound_agent_query_service.process_and_deliver(
            principal=principal,
            platform=ChannelType.SLACK,
            destination_id=channel_id,
            query=query,
            idempotency_key=reply_delivery_id,
            exclude_message_ids=[event_ts, event_id, reply_delivery_id],
            triggering_message_id=event_ts
        )
        webhook_delivery_store.mark_completed(reply_delivery_id)
        webhook_delivery_store.mark_completed(event_delivery_id)
    except Exception as exc:
        logger.exception(
            "[Slack App Mention Exception] Event processing error in background worker",
            extra={
                "event_id": event_id,
                "team_id": team_id,
                "channel_id": channel_id,
                "event_ts": event_ts,
                "delivery_id": reply_delivery_id,
                "processing_phase": "synthesis_and_delivery",
                "exception_type": type(exc).__name__,
            }
        )
        webhook_delivery_store.mark_failed(reply_delivery_id, str(exc))
        webhook_delivery_store.mark_failed(event_delivery_id, str(exc))
        try:
            from app.channels.outbound import SlackOutboundAdapter
            adapter = SlackOutboundAdapter()
            adapter.send(
                {"channel_id": channel_id},
                "I can't reach the language model right now. Please try again shortly.",
                f"{reply_delivery_id}_fallback"
            )
        except Exception:
            pass


@router.post("/slack")
async def handle_slack_events(request: Request, background_tasks: BackgroundTasks):
    """Ingest verified Slack Events API message events and handle app_mention queries with sub-3s HTTP 200 acknowledgement."""
    body_bytes = await request.body()
    if not verify_slack_signature(
        request.headers.get("X-Slack-Signature"),
        request.headers.get("X-Slack-Request-Timestamp"),
        body_bytes,
    ):
        raise HTTPException(status_code=401, detail="Invalid or stale Slack signature.")
    try:
        payload = json.loads(body_bytes.decode("utf-8"))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Malformed JSON payload: {exc}")
    if payload.get("type") == "url_verification":
        return {"challenge": payload.get("challenge")}
    if payload.get("type") != "event_callback":
        return {"status": "ignored", "message": "Unsupported Slack event type."}

    event = payload.get("event") or {}
    event_type = str(event.get("type") or "")
    event_id = str(payload.get("event_id") or "")
    team_id = str(payload.get("team_id") or "")
    channel_id = str(event.get("channel") or "")
    event_ts = str(event.get("ts") or "")

    # 1. Authoritative server-bound workspace and channel verification
    org_id = slack_binding_store.get_organization_for_channel(team_id, channel_id)
    if not org_id:
        raise HTTPException(status_code=403, detail="Slack workspace or channel is not bound.")
    if not event_id:
        raise HTTPException(status_code=400, detail="Missing Slack event_id.")

    # 2. Replay protection for Slack event delivery
    event_delivery_id = f"slack_event_{event_id}"
    can_process_event, event_claim_status, event_claim_msg = webhook_delivery_store.claim_delivery(
        delivery_id=event_delivery_id,
        organization_id=org_id,
        channel_type="slack",
        event_type=event_type,
        repository_id=channel_id,
    )
    if not can_process_event:
        if event_claim_status == "duplicate":
            return {"status": "duplicate", "event_id": event_id}
        raise HTTPException(status_code=409, detail=event_claim_msg or "Slack event is already processing.")

    # 3. Rule: Ignore bot messages and message subtypes
    if event.get("bot_id") or event.get("subtype"):
        webhook_delivery_store.mark_completed(event_delivery_id)
        return {"status": "ignored", "event_id": event_id, "reason": "bot_or_subtype"}

    # Canonical message identifier for deduplicating message ingestion
    msg_canonical_id = f"slack_msg_{team_id}_{channel_id}_{event_ts}" if event_ts else event_delivery_id

    from app.channels.inbound_service import inbound_agent_query_service

    # 4. Dedicated app_mention branch: fast HTTP 200 acknowledgement, background worker execution
    if event_type == "app_mention":
        try:
            inbound_agent_query_service.mark_agent_message(msg_canonical_id)
            inbound_agent_query_service.mark_agent_message(event_ts)
            inbound_agent_query_service.mark_agent_message(event_id)

            reply_delivery_id = f"slack_reply_{team_id}_{channel_id}_{event_ts}" if event_ts else f"slack_reply_{event_id}"
            can_reply, reply_claim_status, reply_claim_msg = webhook_delivery_store.claim_delivery(
                delivery_id=reply_delivery_id,
                organization_id=org_id,
                channel_type="slack",
                event_type="app_mention_reply",
                repository_id=channel_id,
            )
            if not can_reply:
                webhook_delivery_store.mark_completed(event_delivery_id)
                if reply_claim_status == "duplicate":
                    return {"status": "duplicate", "event_id": event_id, "delivery_id": reply_delivery_id}
                raise HTTPException(status_code=409, detail=reply_claim_msg or "Mention reply already processing.")

            raw_text = str(event.get("text") or "")
            authorizations = payload.get("authorizations") or []
            bot_user_id = authorizations[0].get("user_id") if authorizations else None
            if bot_user_id:
                query = re.sub(rf"<@{re.escape(bot_user_id)}(?:\|[^>]*)?>", "", raw_text).strip()
            else:
                query = re.sub(r"<@[A-Z0-9]+(?:\|[^>]*)?>", "", raw_text, count=1).strip()

            user_id = str(event.get("user") or "")
            author_name = str(event.get("user_name") or user_id)
            link = identity_service.resolve_identity(
                organization_id=org_id,
                channel_type=ChannelType.SLACK,
                account_id=user_id,
                username=author_name,
                display_name=author_name,
            )
            access_context = membership_store.derive_access_context(
                user_id=link.person_id,
                organization_id=org_id,
            )
            principal = AuthenticatedPrincipal(
                user_id=link.person_id,
                organization_id=org_id,
                access_context=access_context,
            )

            # Schedule background worker for synthesis & outbound posting
            background_tasks.add_task(
                _process_slack_app_mention_background,
                principal=principal,
                channel_id=channel_id,
                query=query,
                reply_delivery_id=reply_delivery_id,
                event_delivery_id=event_delivery_id,
                event_id=event_id,
                team_id=team_id,
                event_ts=event_ts
            )

            # Acknowledge HTTP 200 under 3 seconds
            return {
                "status": "ok",
                "event_id": event_id,
                "team_id": team_id,
                "channel_id": channel_id,
                "delivery_id": reply_delivery_id,
                "message": "Event acknowledged for background processing."
            }
        except PermissionError as exc:
            webhook_delivery_store.mark_failed(event_delivery_id, str(exc))
            logger.exception(
                "[Slack App Mention Exception] Permission error",
                extra={
                    "event_id": event_id,
                    "team_id": team_id,
                    "channel_id": channel_id,
                    "event_ts": event_ts,
                    "delivery_id": event_delivery_id,
                    "processing_phase": "permission_validation",
                    "exception_type": "PermissionError",
                }
            )
            raise HTTPException(status_code=403, detail=str(exc))
        except Exception as exc:
            webhook_delivery_store.mark_failed(event_delivery_id, str(exc))
            logger.exception(
                "[Slack App Mention Exception] Unexpected error during acknowledgement setup",
                extra={
                    "event_id": event_id,
                    "team_id": team_id,
                    "channel_id": channel_id,
                    "event_ts": event_ts,
                    "delivery_id": event_delivery_id,
                    "processing_phase": "acknowledgement_setup",
                    "exception_type": type(exc).__name__,
                }
            )
            raise HTTPException(status_code=500, detail=f"Slack mention response error: {type(exc).__name__}")

    # 5. Inbound message.channels events: skip agent-directed messages, ingest ordinary discussion
    if inbound_agent_query_service.is_agent_message(msg_canonical_id) or inbound_agent_query_service.is_agent_message(event_ts):
        webhook_delivery_store.mark_completed(event_delivery_id)
        return {"status": "ignored", "event_id": event_id, "reason": "agent_directed_message"}

    can_ingest_msg, msg_claim_status, msg_claim_msg = webhook_delivery_store.claim_delivery(
        delivery_id=msg_canonical_id,
        organization_id=org_id,
        channel_type="slack",
        event_type="message",
        repository_id=channel_id,
    )
    if not can_ingest_msg:
        webhook_delivery_store.mark_completed(event_delivery_id)
        if msg_claim_status == "duplicate":
            return {"status": "duplicate", "event_id": event_id, "canonical_id": msg_canonical_id}
        raise HTTPException(status_code=409, detail=msg_claim_msg or "Slack message is already processing.")

    try:
        parsed = slack_connector.parse_event(payload, org_id)
        if not parsed:
            webhook_delivery_store.mark_completed(msg_canonical_id)
            webhook_delivery_store.mark_completed(event_delivery_id)
            return {"status": "ignored", "event_id": event_id}
        record, chunks, _ = slack_connector.ingest_message(parsed)
        ok, _ = memory_repository.persist_record_and_chunks(record, chunks)
        if not ok:
            webhook_delivery_store.mark_failed(msg_canonical_id, "Failed to persist Slack event.")
            webhook_delivery_store.mark_failed(event_delivery_id, "Failed to persist Slack event.")
            raise RuntimeError("Failed to persist Slack event.")
        webhook_delivery_store.mark_completed(msg_canonical_id)
        webhook_delivery_store.mark_completed(event_delivery_id)
        return {
            "status": "ingested",
            "channel": "slack",
            "organization_id": org_id,
            "event_id": event_id,
            "team_id": team_id,
            "channel_id": channel_id,
            "message_ts": event_ts,
            "record_id": record.id,
            "chunk_ids": [chunk.id for chunk in chunks],
        }
    except Exception as exc:
        webhook_delivery_store.mark_failed(msg_canonical_id, str(exc))
        webhook_delivery_store.mark_failed(event_delivery_id, str(exc))
        logger.exception(
            "[Slack Message Ingestion Exception] Error during message ingestion",
            extra={
                "event_id": event_id,
                "team_id": team_id,
                "channel_id": channel_id,
                "event_ts": event_ts,
                "delivery_id": msg_canonical_id,
                "processing_phase": "message_ingestion",
                "exception_type": type(exc).__name__,
            }
        )
        raise HTTPException(status_code=500, detail=f"Slack ingestion error: {type(exc).__name__}")
