from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from app.channels.outbound import ChannelMessageDeliveryService, channel_message_delivery_service
from app.core.auth import AuthenticatedPrincipal, get_current_principal
from app.core.canonical import ChannelType

router = APIRouter(prefix="/agent", tags=["Agent Delivery"])

class AgentSendRequest(BaseModel):
    platform: ChannelType
    destination_id: str = Field(..., min_length=1)
    query: str = Field(..., min_length=1)
    idempotency_key: Optional[str] = None

@router.post("/send")
def send_agent_message(
    request: AgentSendRequest,
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
    service: ChannelMessageDeliveryService = Depends(lambda: channel_message_delivery_service),
):
    try:
        return service.send_message(principal, request.platform, request.destination_id, request.query, request.idempotency_key)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Outbound provider delivery failed: {exc}")
