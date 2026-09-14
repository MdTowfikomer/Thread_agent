from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional
from app.core.canonical import Citation
from app.core.organizations import get_workspace, get_role_agent
from app.core.auth import AuthenticatedPrincipal, get_current_principal
from app.graph.state import GraphState
from app.graph.workflow import app_graph

router = APIRouter(prefix="/chat", tags=["Chat"])

class ChatRequest(BaseModel):
    query: str = Field(..., json_schema_extra={"example": "What are the prerequisites for the GenAI workshop and where is the repo?"})
    organization_id: str = Field(default="gdg_mcet", json_schema_extra={"example": "gdg_mcet"})
    user_id: Optional[str] = Field(default=None, description="Ignored. Identity is derived exclusively from verified Bearer token.")
    user_role: Optional[str] = Field(default=None, description="Ignored. Identity is derived exclusively from verified Bearer token.")

class ChatResponse(BaseModel):
    query: str
    answer: str
    role_agent: Dict[str, Any]
    citations: List[Citation]
    confidence_score: float
    trace: List[Dict[str, Any]]
    organization_id: str
    receipt: Optional[Dict[str, Any]] = None
    sufficient_evidence: bool = True

@router.post("", response_model=ChatResponse)
async def chat_endpoint(
    req: ChatRequest,
    principal: AuthenticatedPrincipal = Depends(get_current_principal)
):
    if not req.query.strip():
        raise HTTPException(status_code=400, detail="Query cannot be empty")

    if req.organization_id and req.organization_id != principal.organization_id:
        raise HTTPException(
            status_code=403,
            detail=f"Forbidden: Cross-organization access is denied. Requested '{req.organization_id}', principal is '{principal.organization_id}'."
        )

    # Authoritative permissions derived exclusively from verified AuthenticatedPrincipal
    initial_state = GraphState(
        query=req.query,
        organization_id=principal.organization_id,
        access_context=principal.access_context
    )

    try:
        result = app_graph.invoke(initial_state)
        
        ws = get_workspace(principal.organization_id)
        role_id = result.get("target_role_id", ws.default_role_id)
        role_info = get_role_agent(principal.organization_id, role_id)
        evidence_pack = result.get("evidence_pack")

        citations = evidence_pack.citations if evidence_pack else []
        confidence = evidence_pack.confidence_score if evidence_pack else 0.0
        sufficient = evidence_pack.sufficient_evidence if evidence_pack else False
        receipt_dict = evidence_pack.receipt.model_dump() if evidence_pack and evidence_pack.receipt else None

        return ChatResponse(
            query=req.query,
            answer=result.get("final_answer", ""),
            role_agent={
                "id": role_info.id if role_info else role_id,
                "name": role_info.name if role_info else "Thread Agent",
                "role": role_info.role if role_info else "Lead",
                "avatar": role_info.avatar if role_info else "",
                "department": role_info.department if role_info else "Core"
            },
            citations=citations,
            confidence_score=confidence,
            trace=result.get("trace", []),
            organization_id=principal.organization_id,
            receipt=receipt_dict,
            sufficient_evidence=sufficient
        )
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Graph execution failed: {str(e)}")
