import re
import logging
from difflib import SequenceMatcher
from typing import Dict, Any, List, Optional, Set
from datetime import datetime, timezone

from app.core.canonical import ChannelType, PermissionLevel, Citation
from app.core.auth import AuthenticatedPrincipal
from app.core.organizations import get_workspace, get_role_agent
from app.graph.state import GraphState
from app.graph.workflow import app_graph
from app.memory.conversation import conversation_store
from app.channels.outbound import channel_message_delivery_service

logger = logging.getLogger(__name__)


def normalize_text(text: str) -> str:
    """Normalize text for anti-echo comparison."""
    if not text:
        return ""
    text = re.sub(r"[^\w\s]", "", text.lower())
    return " ".join(text.split())


def is_substantially_echoing(
    output_text: str,
    query: str,
    recent_user_turns: Optional[List[str]] = None
) -> bool:
    """
    Returns True if output_text substantially echoes/repeats the query or recent user conversation turns.
    """
    norm_out = normalize_text(output_text)
    if not norm_out:
        return False

    norm_query = normalize_text(query)
    if norm_query:
        # Check direct similarity ratio
        ratio = SequenceMatcher(None, norm_out, norm_query).ratio()
        if ratio > 0.70:
            return True
        # Check if output is contained within query or query within output when sufficiently long
        if len(norm_query) > 10 and (norm_query in norm_out or norm_out in norm_query):
            return True

    if recent_user_turns:
        for turn in recent_user_turns:
            norm_turn = normalize_text(turn)
            if norm_turn:
                ratio = SequenceMatcher(None, norm_out, norm_turn).ratio()
                if ratio > 0.70:
                    return True

    return False


def validate_output(
    output_text: Any,
    query: str,
    recent_user_turns: Optional[List[str]] = None,
    intent_category: Optional[str] = None
) -> str:
    """
    Shared pre-send output validator.
    Blocks outputs substantially echoing the current query or recent user conversation turns.
    On LLM failure or empty response, returns a brief, transparent unavailable response.
    """
    if isinstance(output_text, list):
        text_parts = []
        for item in output_text:
            if isinstance(item, dict):
                text_parts.append(str(item.get("text") or item.get("content") or ""))
            else:
                text_parts.append(str(item))
        output_text = " ".join([t for t in text_parts if t])
    elif not isinstance(output_text, str):
        output_text = str(output_text or "")

    cleaned = output_text.strip()

    if not cleaned:
        return "I can't reach the language model right now. Please try again shortly."

    if is_substantially_echoing(cleaned, query, recent_user_turns):
        q_lower = query.strip().lower()
        if any(p in q_lower for p in ("can you see this", "can u see this", "are you online", "status", "ping", "test")):
            return "Yes, I can see your message! I am online and active."
        if any(p in q_lower for p in ("what can you do", "what do you do", "capabilities", "help")):
            return "I am ThreadAgent. I can answer technical questions, check community events, search verified records, and guide you on developer topics."
        if any(p in q_lower for p in ("what tools do you have", "what tools have you got")):
            return "I have community tools like !events (upcoming workshops), !faq (resources), !github (repo info), and !summary (channel recaps), along with grounded search."
        return "I am online and ready to assist you. Ask me any question about GDG MCET records or general software topics!"

    return cleaned


class InboundAgentQueryService:
    """
    Shared, platform-neutral service for processing agent-directed inquiries across Discord, Slack, Telegram, and Web Chat.

    SECURITY & DESIGN GUARANTEES:
    1. Agent-directed messages are stored ONLY in conversation_turns, NEVER in canonical source_records or memory_chunks.
    2. Paired platform message events check agent_directed_message_ids ledger and skip dual-ingestion into source_records.
    3. Capability / status / greeting / general-knowledge queries route to direct synthesis without retrieval.
    4. Organizational-fact queries route to ACL-protected retrieval with exclude_message_ids propagation.
    5. Output validation blocks query echoing and returns brief transparent fallback on LLM failure.
    """

    def __init__(self):
        self._agent_directed_message_ids: Set[str] = set()

    def mark_agent_message(self, message_id: str) -> None:
        """Register a platform message ID as an agent-directed message."""
        if message_id:
            self._agent_directed_message_ids.add(str(message_id))

    def is_agent_message(self, message_id: str) -> bool:
        """Check if a platform message ID was handled as an agent-directed query."""
        return str(message_id) in self._agent_directed_message_ids if message_id else False

    def process_query(
        self,
        query: str,
        organization_id: str,
        principal: AuthenticatedPrincipal,
        platform: ChannelType = ChannelType.WEB_CHAT,
        destination_id: Optional[str] = None,
        exclude_message_ids: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """
        Execute agent query workflow for web chat or generic API requests.
        Records turns exclusively in conversation_turns, NEVER in source_records / memory_chunks.
        """
        dest = destination_id or "web_chat"
        session_key = conversation_store.format_session_key(platform.value, dest, principal.user_id)
        recent_turns = conversation_store.get_recent_turns(session_key=session_key, organization_id=organization_id, limit=10)

        user_turn_texts = [t.get("content", "") for t in recent_turns if t.get("role") == "user"]

        all_exclude = list(exclude_message_ids or [])

        initial_state = GraphState(
            query=query,
            organization_id=organization_id,
            access_context=principal.access_context,
            session_key=session_key,
            chat_history=recent_turns,
            exclude_message_ids=all_exclude if all_exclude else None
        )

        try:
            result = app_graph.invoke(initial_state)

            ws = get_workspace(organization_id)
            role_id = result.get("target_role_id", ws.default_role_id)
            role_info = get_role_agent(organization_id, role_id)
            evidence_pack = result.get("evidence_pack")
            intent_cat = result.get("intent_category", "ORGANIZATIONAL_FACTS")

            raw_answer = result.get("final_answer", "")
            validated_answer = validate_output(
                output_text=raw_answer,
                query=query,
                recent_user_turns=user_turn_texts,
                intent_category=intent_cat
            )

            # Record turn exclusively in conversation_turns
            conversation_store.record_turn(session_key, platform.value, organization_id, principal.user_id, "user", query)
            conversation_store.record_turn(session_key, platform.value, organization_id, principal.user_id, "assistant", validated_answer)

            citations = evidence_pack.citations if evidence_pack else []
            confidence = evidence_pack.confidence_score if evidence_pack else 0.0
            sufficient = evidence_pack.sufficient_evidence if evidence_pack else False
            receipt_dict = evidence_pack.receipt.model_dump() if evidence_pack and evidence_pack.receipt else None

            return {
                "query": query,
                "answer": validated_answer,
                "intent_category": intent_cat,
                "role_agent": {
                    "id": role_info.id if role_info else role_id,
                    "name": role_info.name if role_info else "Thread Agent",
                    "role": role_info.role if role_info else "Lead",
                    "avatar": role_info.avatar if role_info else "",
                    "department": role_info.department if role_info else "Core"
                },
                "citations": citations,
                "confidence_score": confidence,
                "trace": result.get("trace", []),
                "organization_id": organization_id,
                "receipt": receipt_dict,
                "sufficient_evidence": sufficient
            }
        except Exception as e:
            logger.error(f"[InboundAgentQueryService] Graph execution failed: {e}")
            fallback_msg = "I can't reach the language model right now. Please try again shortly."
            conversation_store.record_turn(session_key, platform.value, organization_id, principal.user_id, "user", query)
            conversation_store.record_turn(session_key, platform.value, organization_id, principal.user_id, "assistant", fallback_msg)
            return {
                "query": query,
                "answer": fallback_msg,
                "intent_category": "GENERAL_KNOWLEDGE",
                "role_agent": {"id": "community", "name": "Thread Agent", "role": "Lead", "avatar": "", "department": "Core"},
                "citations": [],
                "confidence_score": 0.0,
                "trace": [],
                "organization_id": organization_id,
                "receipt": None,
                "sufficient_evidence": False
            }

    def process_and_deliver(
        self,
        principal: AuthenticatedPrincipal,
        platform: ChannelType,
        destination_id: str,
        query: str,
        idempotency_key: Optional[str] = None,
        exclude_message_ids: Optional[List[str]] = None,
        triggering_message_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Execute agent query and deliver response to destination channel (Discord, Slack, Telegram).
        Ensures triggering message ID is marked in agent ledger and excluded from retrieval.
        """
        if triggering_message_id:
            self.mark_agent_message(triggering_message_id)

        all_exclude = list(exclude_message_ids or [])
        if triggering_message_id and triggering_message_id not in all_exclude:
            all_exclude.append(triggering_message_id)

        session_key = conversation_store.format_session_key(platform.value, destination_id, principal.user_id)
        recent_turns = conversation_store.get_recent_turns(session_key=session_key, organization_id=principal.organization_id, limit=10)
        user_turn_texts = [t.get("content", "") for t in recent_turns if t.get("role") == "user"]

        delivery_res = channel_message_delivery_service.send_message(
            principal=principal,
            platform=platform,
            destination_id=destination_id,
            query=query,
            idempotency_key=idempotency_key,
            exclude_message_ids=all_exclude if all_exclude else None
        )

        final_ans = delivery_res.get("final_answer") or delivery_res.get("answer") or ""
        validated_ans = validate_output(final_ans, query, user_turn_texts)

        delivery_res["final_answer"] = validated_ans
        delivery_res["answer"] = validated_ans
        return delivery_res


inbound_agent_query_service = InboundAgentQueryService()
