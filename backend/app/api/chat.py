from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional
from app.core.canonical import Citation
from app.core.organizations import get_workspace, get_role_agent
from app.core.auth import AuthenticatedPrincipal, get_current_principal
from app.graph.state import GraphState
from app.graph.workflow import app_graph

from app.channels.inbound_service import inbound_agent_query_service, ChannelType

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

    try:
        res = inbound_agent_query_service.process_query(
            query=req.query,
            organization_id=principal.organization_id,
            principal=principal,
            platform=ChannelType.WEB_CHAT,
            destination_id="web_chat"
        )

        return ChatResponse(
            query=res["query"],
            answer=res["answer"],
            role_agent=res["role_agent"],
            citations=res["citations"],
            confidence_score=res["confidence_score"],
            trace=res["trace"],
            organization_id=principal.organization_id,
            receipt=res["receipt"],
            sufficient_evidence=res["sufficient_evidence"]
        )
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Graph execution failed: {str(e)}")
