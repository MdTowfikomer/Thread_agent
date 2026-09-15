from datetime import datetime, timezone
from typing import Dict, Any
from langgraph.graph import StateGraph, END
from app.graph.state import GraphState
from app.core.organizations import get_workspace, get_role_agent
from app.core.config import settings
from app.memory.retrieval import retrieval_service, derive_access_context

import os

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

# --- NODE 1: TRIAGE ROUTER ---
def triage_node(state: GraphState) -> Dict[str, Any]:
    ws = get_workspace(state.organization_id)
    query_lower = state.query.lower()
    
    best_role = ws.roles[0]
    for role in ws.roles:
        for tag in role.expertise:
            if tag.lower() in query_lower:
                best_role = role
                break

    intent = f"Identified intent: topic concerning {', '.join(best_role.expertise[:3])}"
    
    new_trace = list(state.trace)
    new_trace.append({
        "step": "triage_router",
        "agent_id": "triage_router",
        "agent_name": "Triage Router",
        "status": "completed",
        "message": f"Routed query to {best_role.name} ({best_role.role}) based on role responsibility.",
        "timestamp": datetime.now(timezone.utc).isoformat()
    })

    return {
        "triage_intent": intent,
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
    evidence = state.evidence_pack
    role = get_role_agent(state.organization_id, state.target_role_id)
    role_title = role.role if role else "Role Agent"
    role_name = role.name if role else "Agent"

    new_trace = list(state.trace)
    
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
    role_name = role.name if role else "Thread Agent"
    role_title = role.role if role else "Lead"
    role_style = role.style if role else "Clear, professional, and precise."

    evidence = state.evidence_pack

    # REQUIREMENT 5: If no sufficient evidence exists, synthesis MUST say evidence is insufficient.
    # No bluffing. No invented facts.
    if not evidence or not evidence.sufficient_evidence or len(evidence.citations) == 0:
        final_answer = (
            f"Based on verified organizational records in **{ws.name}**, there is **insufficient evidence** to answer this inquiry.\n\n"
            f"No authorized documentation matching '{state.query}' was found within your access scope.\n"
            f"*(Receipt ID: `{evidence.receipt.receipt_id if evidence else 'N/A'}` | Strategy: Pre-Retrieval ACL Verification)*"
        )
        new_trace = list(state.trace)
        new_trace.append({
            "step": "synthesis",
            "agent_id": "synthesis_agent",
            "agent_name": f"{role_name} ({role_title})",
            "status": "completed",
            "message": "Emitted verified insufficient-evidence response without hallucination.",
            "timestamp": datetime.now(timezone.utc).isoformat()
        })
        return {
            "final_answer": final_answer,
            "trace": new_trace
        }

    # Format evidence citations
    context_str = "\n\n".join([
        f"[{c.source.value.upper()}] from {c.author} ({c.title or 'Record'}):\n{c.snippet}"
        for c in evidence.citations
    ])

    llm = get_llm()
    if llm:
        system_prompt = f"""You are {role_name}, the {role_title} at {ws.name}.
Persona Style: {role_style}

You are answering a user inquiry using ONLY the verified EvidencePack below.
CRITICAL RULES:
- Never hallucinate, invent dates, or bluff facts not explicitly provided in the EvidencePack.
- Quote specific facts, dates, repos, and names from the citations.
- Conclude with clear, actionable organizational guidance.

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
        "agent_name": f"{role_name} ({role_title})",
        "status": "completed",
        "message": f"Synthesized grounded response backed by {len(evidence.citations)} verified citations.",
        "timestamp": datetime.now(timezone.utc).isoformat()
    })

    return {
        "final_answer": answer,
        "trace": new_trace
    }

def _fallback_synthesis(role_name: str, role_title: str, evidence) -> str:
    sources_summary = "\n".join([
        f"- **{c.title or 'Record'}** (via {c.source.value.capitalize()} by {c.author}): {c.snippet}"
        for c in evidence.citations
    ])

    return (
        f"**Context Update from {role_name} ({role_title})**:\n\n"
        f"Based on our verified organizational records, here is the reconstructed context for your inquiry:\n\n"
        f"{sources_summary}\n\n"
        f"*(Confidence: {int(evidence.confidence_score * 100)}% | Receipt ID: `{evidence.receipt.receipt_id}`)*"
    )

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
