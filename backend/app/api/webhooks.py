import json
import time
import logging
from datetime import datetime, timezone
from typing import Dict, Any, Optional, Set
from fastapi import APIRouter, Request, HTTPException, BackgroundTasks, status
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from cryptography.exceptions import InvalidSignature
import httpx

from app.core.config import settings
from app.core.canonical import (
    ChannelType,
    AccessContext,
    PermissionLevel
)
from app.channels.installation import guild_installation_store
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
        result = app_graph.invoke(graph_state)
        final_answer = result.get("final_answer", "")
        if application_id and interaction_token:
            url = f"https://discord.com/api/v10/webhooks/{application_id}/{interaction_token}/messages/@original"
            async with httpx.AsyncClient() as http_client:
                await http_client.patch(url, json={"content": final_answer})
    except Exception as e:
        logger.warning(f"Discord interaction follow-up dispatch failed: {e}")

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
            access_context=access_context
        )

        app_id = payload.get("application_id")
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
    Enforces HMAC-SHA256 signature verification, cross-channel identity resolution,
    and stores records in the memory repository.
    """
    from app.channels.github import github_connector, verify_github_signature

    body_bytes = await request.body()
    sig_header = request.headers.get("X-Hub-Signature-256")
    event_type = request.headers.get("X-GitHub-Event")

    if not event_type:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing X-GitHub-Event header."
        )

    secret = settings.github_webhook_secret
    if secret:
        if not verify_github_signature(body_bytes, sig_header, secret):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid GitHub webhook HMAC-SHA256 signature."
            )

    try:
        payload = json.loads(body_bytes.decode("utf-8"))
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Malformed JSON payload: {e}"
        )

    org_id = request.query_params.get("organization_id", settings.DEFAULT_DOMAIN)

    try:
        events = github_connector.parse_webhook_payload(event_type, payload, org_id)
    except Exception as e:
        logger.warning(f"Error parsing GitHub event '{event_type}': {e}")
        return {"status": "skipped", "reason": str(e), "event_type": event_type}

    ingested_records = []
    ingested_chunks = []
    for ev in events:
        record, chunks, receipt = github_connector.ingest_event(ev)
        github_connector.memory_store.add_record(record)
        for chunk in chunks:
            github_connector.memory_store.add_chunk(chunk)
        ingested_records.append(record.id)
        ingested_chunks.extend([c.id for c in chunks])

    return {
        "status": "ingested",
        "event_type": event_type,
        "organization_id": org_id,
        "records_count": len(ingested_records),
        "chunks_count": len(ingested_chunks),
        "record_ids": ingested_records,
        "chunk_ids": ingested_chunks
    }
