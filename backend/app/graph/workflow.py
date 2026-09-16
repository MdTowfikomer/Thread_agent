import os
from datetime import datetime, timezone
from typing import Dict, Any, Tuple, Optional
from langgraph.graph import StateGraph, END
from app.graph.state import GraphState
from app.core.organizations import get_workspace, get_role_agent
from app.core.config import settings
from app.memory.retrieval import retrieval_service, derive_access_context

from app.tools.events import event_assistant
from app.tools.resources import resource_assistant
from app.tools.summarizer import summarizer_assistant
from app.tools.github_helper import github_helper
from app.tools.account_link import account_link_tool


def get_llm():
    """Return LangChain LLM with fallback."""
    if os.environ.get("THREAD_FORCE_DETERMINISTIC_SYNTHESIS") == "1" or os.environ.get("THREAD_FORCE_DETERMINISTIC_EMBEDDINGS") == "1":
        return None

    if settings.has_gemini:
        try:
            from langchain_google_genai import ChatGoogleGenerativeAI
            gemini_model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
            return ChatGoogleGenerativeAI(
                model=gemini_model,
                google_api_key=settings.GEMINI_API_KEY,
                temperature=0.1
            )
        except Exception:
            pass

    if settings.has_openai:
        try:
            from langchain_openai import ChatOpenAI
            return ChatOpenAI(
                model="gpt-4o",
                openai_api_key=settings.OPENAI_API_KEY,
                temperature=0.1
            )
        except Exception:
            pass

    return None


def classify_intent_and_routing(query: str, ws) -> Tuple[str, Optional[str], Optional[str], Any]:
    """
    Classify incoming inquiry into:
      - 'TOOL_EXECUTION': Community utilities (!events, !faq, !summary, !github, !link)
      - 'GENERAL_KNOWLEDGE': Conversational greetings, general software questions, direct LLM answers
      - 'ORGANIZATIONAL_FACTS': Inquiries requiring authoritative vector retrieval against verified team records
    """
    q_stripped = query.strip()
    q_lower = q_stripped.lower()

    # 1. Explicit command triggers
    if q_lower.startswith("!events") or q_lower.startswith("!event"):
        role = next((r for r in ws.roles if r.id == "organizer_lead"), ws.roles[0])
        return "TOOL_EXECUTION", "events", q_stripped[7:].strip(), role
    if q_lower.startswith("!faq") or q_lower.startswith("!resources") or q_lower.startswith("!resource"):
        role = next((r for r in ws.roles if r.id == "community_lead"), ws.roles[0])
        arg = q_stripped.split(maxsplit=1)[1] if len(q_stripped.split()) > 1 else ""
        return "TOOL_EXECUTION", "resources", arg.strip(), role
    if q_lower.startswith("!summary") or q_lower.startswith("!summarize"):
        return "TOOL_EXECUTION", "summary", "", ws.roles[0]
    if q_lower.startswith("!github") or q_lower.startswith("!repo"):
        role = next((r for r in ws.roles if r.id == "tech_lead"), ws.roles[0])
        return "TOOL_EXECUTION", "github", "", role
    if q_lower.startswith("!link"):
        role = next((r for r in ws.roles if r.id == "community_lead"), ws.roles[0])
        arg = q_stripped[5:].strip()
        return "TOOL_EXECUTION", "link", arg, role

    # 2. Natural language tool queries
    if any(k in q_lower for k in ("upcoming event", "next event", "upcoming workshop", "when is the hackathon", "event schedule", "events list")):
        role = next((r for r in ws.roles if r.id == "organizer_lead"), ws.roles[0])
        return "TOOL_EXECUTION", "events", "", role
    if any(k in q_lower for k in ("github repo", "github link", "how to contribute to github", "source code repo", "official repository")):
        role = next((r for r in ws.roles if r.id == "tech_lead"), ws.roles[0])
        return "TOOL_EXECUTION", "github", "", role
    if any(k in q_lower for k in ("summarize this channel", "summarize our discussion", "recap discussion", "summarize channel")):
        return "TOOL_EXECUTION", "summary", "", ws.roles[0]
    if any(k in q_lower for k in ("community guidelines", "discord rules", "code of conduct", "how do i link")):
        role = next((r for r in ws.roles if r.id == "community_lead"), ws.roles[0])
        return "TOOL_EXECUTION", "resources", q_lower, role

    # 3. Conversational greetings and small talk
    greetings = ("hello", "hi", "hey", "good morning", "good evening", "good afternoon", "greetings")
    conversational_phrases = ("how are you", "who are you", "what can you do", "help me", "can you help", "tell me about yourself", "what is your name")

    if (
        any(q_lower.startswith(g) for g in greetings)
        or any(p in q_lower for p in conversational_phrases)
        or q_lower in greetings
    ):
        return "GENERAL_KNOWLEDGE", None, None, ws.roles[0]

    # Explicit organizational indicators
    org_indicators = (
        "gdg", "mcet", "devfest", "budget", "sponsor", "sponsorship", "meeting", "minutes",
        "decision", "reimbursement", "vendor", "venue", "internal", "quarantine", "provenance",
        "policy", "attendance", "proposal", "retro", "receipt", "audit", "secret", "private",
        "mariana", "submarine", "protocol", "record", "records", "event announced", "updates event",
        "workshop", "prerequisite", "prerequisites", "launch", "titan", "project", "channel", "ingest"
    )

    is_org_query = any(ind in q_lower for ind in org_indicators)

    best_role = ws.roles[0]
    matched_expertise = False
    for role in ws.roles:
        for tag in role.expertise:
            if tag.lower() in q_lower:
                best_role = role
                matched_expertise = True
                break
        if matched_expertise:
            break

    # If it matched role expertise or explicit org indicators, it's ORGANIZATIONAL_FACTS
    if matched_expertise or is_org_query:
        return "ORGANIZATIONAL_FACTS", None, None, best_role

    # Pure general conceptual/educational questions (e.g. "what is state space in RL") with no role match
    general_question_starters = ("what is a ", "what is an ", "can you explain", "can u explain", "how does ", "explain ")
    if any(q_lower.startswith(s) for s in general_question_starters):
        return "GENERAL_KNOWLEDGE", None, None, best_role

    return "ORGANIZATIONAL_FACTS", None, None, best_role


# --- NODE 1: TRIAGE ROUTER ---
def triage_node(state: GraphState) -> Dict[str, Any]:
    ws = get_workspace(state.organization_id)
    intent_category, tool_name, tool_args, best_role = classify_intent_and_routing(state.query, ws)

    intent_desc = f"Identified intent: {intent_category}"
    if tool_name:
        intent_desc += f" (Tool: {tool_name})"
    else:
        intent_desc += f" concerning {', '.join(best_role.expertise[:3])}"

    new_trace = list(state.trace)
    new_trace.append({
        "step": "triage_router",
        "agent_id": "triage_router",
        "agent_name": "Triage Router",
        "status": "completed",
        "message": f"Routed query to {best_role.name} ({best_role.role}) under {intent_category}.",
        "timestamp": datetime.now(timezone.utc).isoformat()
    })

    return {
        "intent_category": intent_category,
        "tool_name": tool_name,
        "tool_args": tool_args,
        "triage_intent": intent_desc,
        "target_role_id": best_role.id,
        "target_role_name": f"{best_role.name} ({best_role.role})",
        "trace": new_trace
    }


# --- NODE 2: RETRIEVAL SERVICE (AGENTS NEVER ACCESS RAW MEMORY DIRECTLY) ---
def retrieval_node(state: GraphState) -> Dict[str, Any]:
    ctx = state.access_context
    if not ctx:
        ctx = derive_access_context(
            user_id="anon",
            organization_id=state.organization_id,
            role_id="community"
        )

    # Bypass dense vector retrieval for direct tools and conversational knowledge
    if state.intent_category in ("TOOL_EXECUTION", "GENERAL_KNOWLEDGE"):
        new_trace = list(state.trace)
        new_trace.append({
            "step": "retrieval_service",
            "agent_id": "retrieval_service",
            "agent_name": "Deterministic Retrieval Service",
            "status": "completed",
            "message": f"Direct response route ({state.intent_category}): Vector retrieval bypassed.",
            "timestamp": datetime.now(timezone.utc).isoformat()
        })
        return {
            "access_context": ctx,
            "evidence_pack": None,
            "trace": new_trace
        }

    # Retrieval service evaluates ACL strictly before candidate scoring
    evidence_pack = retrieval_service.retrieve(
        query=state.query,
        access_context=ctx,
        top_k=4,
        threshold=0.42
    )

    new_trace = list(state.trace)
    new_trace.append({
        "step": "retrieval_service",
        "agent_id": "retrieval_service",
        "agent_name": "Deterministic Retrieval Service",
        "status": "completed",
        "message": (
            f"Pre-retrieval ACL evaluated: {evidence_pack.receipt.candidates_after_acl}/"
            f"{evidence_pack.receipt.candidates_before_acl} candidates authorized. "
            f"Selected {len(evidence_pack.citations)} citations (Receipt: {evidence_pack.receipt.receipt_id[:8]})."
        ),
        "timestamp": datetime.now(timezone.utc).isoformat()
    })

    return {
        "access_context": ctx,
        "evidence_pack": evidence_pack,
        "trace": new_trace
    }


# --- NODE 3: ROLE AGENT VERIFICATION ---
def role_agent_node(state: GraphState) -> Dict[str, Any]:
    role = get_role_agent(state.organization_id, state.target_role_id)
    role_title = role.role if role else "Role Agent"
    role_name = role.name if role else "Agent"
    new_trace = list(state.trace)

    if state.intent_category in ("TOOL_EXECUTION", "GENERAL_KNOWLEDGE"):
        new_trace.append({
            "step": "role_agent_verification",
            "agent_id": state.target_role_id or "role_agent",
            "agent_name": f"{role_name} ({role_title})",
            "status": "completed",
            "message": f"Verified request under {state.intent_category}. Forwarding to direct execution.",
            "timestamp": datetime.now(timezone.utc).isoformat()
        })
        return {"trace": new_trace}

    evidence = state.evidence_pack
    if not evidence or not evidence.sufficient_evidence:
        new_trace.append({
            "step": "role_agent_verification",
            "agent_id": state.target_role_id,
            "agent_name": f"{role_name} ({role_title})",
            "status": "completed",
            "message": f"Inspected EvidencePack. Insufficient authorized evidence found (Sufficient: False). Flagged no-bluffing exit.",
            "timestamp": datetime.now(timezone.utc).isoformat()
        })
    else:
        new_trace.append({
            "step": "role_agent_verification",
            "agent_id": state.target_role_id,
            "agent_name": f"{role_name} ({role_title})",
            "status": "completed",
            "message": f"Verified {len(evidence.citations)} citations in EvidencePack. Proceeding to synthesis.",
            "timestamp": datetime.now(timezone.utc).isoformat()
        })

    return {
        "trace": new_trace
    }


# --- NODE 4: SYNTHESIS AGENT (STRICT GROUNDING - NO BLUFFING) ---
def synthesis_node(state: GraphState) -> Dict[str, Any]:
    ws = get_workspace(state.organization_id)
    role = get_role_agent(state.organization_id, state.target_role_id)
    role_name = role.name if role else "ThreadAgent"
    role_title = role.role if role else "Assistant"
    role_style = role.style if role else "Clear, professional, and precise."

    # 1. TOOL EXECUTION BRANCH
    if state.intent_category == "TOOL_EXECUTION":
        final_answer = ""
        tool = state.tool_name or ""
        if tool == "events":
            events = event_assistant.list_upcoming_events(state.organization_id)
            final_answer = event_assistant.format_events_response(events)
        elif tool == "resources":
            resources = resource_assistant.search_resources(
                query=state.tool_args or "",
                org_id=state.organization_id,
                access_context=state.access_context
            )
            final_answer = resource_assistant.format_resources_response(resources)
        elif tool == "summary":
            parts = (state.session_key or "").split(":")
            platform = parts[0] if len(parts) > 0 and parts[0] else "discord"
            channel_id = parts[1] if len(parts) > 1 and parts[1] else (state.session_key or "")
            final_answer = summarizer_assistant.summarize_channel_discussion(
                organization_id=state.organization_id,
                channel_id=channel_id,
                platform=platform,
                access_context=state.access_context,
                window_hours=48
            )
        elif tool == "github":
            repo = github_helper.get_bound_repository(state.organization_id)
            final_answer = github_helper.format_github_response(repo)
        elif tool == "link":
            arg = (state.tool_args or "").strip()
            parts = (state.session_key or "").split(":")
            plat = parts[0] if len(parts) > 0 and parts[0] else "community"
            user_id = state.access_context.user_id if state.access_context else "anon"
            if arg:
                _, final_answer = account_link_tool.redeem_link_token(
                    raw_token=arg,
                    target_platform=plat,
                    target_account_id=user_id,
                    target_username=user_id,
                    org_id=state.organization_id
                )
            else:
                tok = account_link_tool.generate_link_token(
                    initiating_platform=plat,
                    initiating_account_id=user_id,
                    initiating_username=user_id,
                    person_id=user_id,
                    org_id=state.organization_id
                )
                final_answer = (
                    f"🔗 **Cross-Platform Account Linking**\n\n"
                    f"Here is your temporary linking token: `{tok}` *(valid for 30 minutes)*.\n\n"
                    f"**Next Steps:**\n"
                    f"1. Open Slack, Telegram, or Discord (wherever your other account is).\n"
                    f"2. Send `!link {tok}` to ThreadAgent.\n"
                    f"3. Your accounts, conversation history, and roles will be synchronized across platforms!"
                )
        else:
            final_answer = f"Tool '{tool}' executed."

        new_trace = list(state.trace)
        new_trace.append({
            "step": "synthesis",
            "agent_id": "synthesis_agent",
            "agent_name": "ThreadAgent",
            "status": "completed",
            "message": f"Executed tool '{tool}' successfully.",
            "timestamp": datetime.now(timezone.utc).isoformat()
        })
        return {
            "final_answer": final_answer,
            "trace": new_trace
        }

    # 2. GENERAL KNOWLEDGE / CONVERSATION BRANCH
    if state.intent_category == "GENERAL_KNOWLEDGE":
        llm = get_llm()
        if llm:
            history_str = ""
            if state.chat_history:
                history_str = "Recent Conversation History:\n" + "\n".join([
                    f"{h.get('role', 'user').capitalize()}: {h.get('content', '')}" for h in state.chat_history[-6:]
                ]) + "\n\n"

            system_prompt = f"""You are ThreadAgent, an intelligent and helpful AI community assistant for {ws.name}.
Persona Style: Friendly, clear, intelligent, and concise.

You are conversing with a community member in an open developer channel.
Answer questions directly, politely, and accurately using your general knowledge. Do NOT pre-pend role headers or debug prefixes.

{history_str}User Message: {state.query}
"""
            try:
                res = llm.invoke(system_prompt)
                answer = res.content if hasattr(res, "content") else str(res)
            except Exception:
                answer = (
                    f"Hello! I am ThreadAgent, your community assistant for {ws.name}.\n\n"
                    f"I can help answer your technical questions, guide you on developer topics, and provide updates about our community events and records. "
                    f"Feel free to ask me anything or type `!events`, `!faq`, `!github`, or `!summary`!"
                )
        else:
            answer = (
                f"Hello! I am ThreadAgent, your community assistant for {ws.name}.\n\n"
                f"I can help answer your technical questions, guide you on developer topics, and provide updates about our community events and records. "
                f"Feel free to ask me anything or type `!events`, `!faq`, `!github`, or `!summary`!"
            )

        new_trace = list(state.trace)
        new_trace.append({
            "step": "synthesis",
            "agent_id": "synthesis_agent",
            "agent_name": "ThreadAgent",
            "status": "completed",
            "message": "Synthesized direct conversational response.",
            "timestamp": datetime.now(timezone.utc).isoformat()
        })
        return {
            "final_answer": answer,
            "trace": new_trace
        }

    # 3. ORGANIZATIONAL FACTS BRANCH (STRICT GROUNDING - NO BLUFFING)
    evidence = state.evidence_pack

    if not evidence or not evidence.sufficient_evidence or len(evidence.citations) == 0:
        final_answer = (
            f"Based on verified organizational records in **{ws.name}**, there is **insufficient evidence** to answer this inquiry.\n\n"
            f"No authorized documentation matching '{state.query}' was found within your access scope."
        )
        new_trace = list(state.trace)
        new_trace.append({
            "step": "synthesis",
            "agent_id": "synthesis_agent",
            "agent_name": "ThreadAgent",
            "status": "completed",
            "message": "Emitted verified insufficient-evidence response without hallucination.",
            "timestamp": datetime.now(timezone.utc).isoformat()
        })
        return {
            "final_answer": final_answer,
            "trace": new_trace
        }

    # Format evidence citations into a clear narrative context
    context_str = "\n\n".join([
        f"[{c.source.value.upper()}] from {c.author} ({c.title or 'Record'}):\n{c.snippet}"
        for c in evidence.citations
    ])

    llm = get_llm()
    if llm:
        system_prompt = f"""You are ThreadAgent, the community assistant at {ws.name}.

Synthesize a clear, helpful, human-readable summary answering the user's query based ONLY on the verified EvidencePack below.
RULES:
- Never include raw context update headers like "Context Update from..." or internal debug logs.
- Never output receipt IDs or confidence percentages in your response.
- Summarize the relevant facts into a readable, natural narrative in ThreadAgent's voice.
- Quote specific dates, names, or updates when relevant.

Verified EvidencePack:
{context_str}

User Query: {state.query}
"""
        try:
            response = llm.invoke(system_prompt)
            answer = response.content if hasattr(response, "content") else str(response)
        except Exception:
            answer = _fallback_synthesis(role_name, role_title, evidence)
    else:
        answer = _fallback_synthesis(role_name, role_title, evidence)

    new_trace = list(state.trace)
    new_trace.append({
        "step": "synthesis",
        "agent_id": "synthesis_agent",
        "agent_name": "ThreadAgent",
        "status": "completed",
        "message": f"Synthesized grounded response backed by {len(evidence.citations)} verified citations.",
        "timestamp": datetime.now(timezone.utc).isoformat()
    })

    return {
        "final_answer": answer,
        "trace": new_trace
    }


def _fallback_synthesis(role_name: str, role_title: str, evidence) -> str:
    if evidence and evidence.citations:
        sources_summary = "\n".join([
            f"• {c.title or 'Record'} ({c.source.value.capitalize()}): {c.snippet}"
            for c in evidence.citations[:3]
        ])
        return (
            f"Based on our community records, here is the relevant context for your query:\n\n"
            f"{sources_summary}"
        )
    return "Based on verified organizational records, no matching authorized documentation was found."


# Build & Compile Graph
workflow = StateGraph(GraphState)
workflow.add_node("triage", triage_node)
workflow.add_node("retrieval", retrieval_node)
workflow.add_node("role_agent", role_agent_node)
workflow.add_node("synthesis", synthesis_node)

workflow.set_entry_point("triage")
workflow.add_edge("triage", "retrieval")
workflow.add_edge("retrieval", "role_agent")
workflow.add_edge("role_agent", "synthesis")
workflow.add_edge("synthesis", END)

app_graph = workflow.compile()
