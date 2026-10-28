from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import StreamingResponse
import json
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
    organization_id: Optional[str] = Field(default=None, description="Optional assertion; active organization is derived from the authenticated session.")
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
    trace_id: Optional[str] = None
    conversation_id: Optional[str] = None
    turn_id: Optional[str] = None

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
            sufficient_evidence=res["sufficient_evidence"],
            trace_id=res.get("trace_id"), conversation_id=res.get("conversation_id"), turn_id=res.get("turn_id")
        )
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=500, detail="The query could not be completed. Retry later.") from None

@router.post("/stream")
async def chat_stream_endpoint(
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

    def event_generator():
        try:
            for event in inbound_agent_query_service.process_query_stream(
                query=req.query,
                organization_id=principal.organization_id,
                principal=principal,
                platform=ChannelType.WEB_CHAT,
                destination_id="web_chat"
            ):
                yield f"data: {json.dumps(event, default=str)}\n\n"
        except HTTPException as exc:
            logger.warning("HTTPException in chat_stream_endpoint: %s", exc.detail)
            err_data = json.dumps({"type": "error", "error": exc.detail, "status": exc.status_code}, default=str)
            yield f"data: {err_data}\n\n"
        except Exception as exc:
            logger.exception("Unexpected error in chat_stream_endpoint: %s", exc)
            err_data = json.dumps({"type": "error", "error": "The query could not be completed. Retry later.", "status": 500}, default=str)
            yield f"data: {err_data}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )
