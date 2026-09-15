from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field
from app.core.canonical import (
    AccessContext,
    EvidencePack,
    Citation,
    PermissionLevel
)

class GraphState(BaseModel):
    query: str
    organization_id: str = "gdg_mcet"
    access_context: Optional[AccessContext] = None
    
    # Session / Multi-Turn persistence
    session_key: str = ""
    chat_history: List[Dict[str, str]] = Field(default_factory=list)
    intent_category: str = "ORGANIZATIONAL_FACTS"  # "GENERAL_KNOWLEDGE", "ORGANIZATIONAL_FACTS", "TOOL_EXECUTION"
    tool_name: Optional[str] = None
    tool_args: Optional[str] = None
    
    # Triage step
    triage_intent: str = ""
    target_role_id: str = ""
    target_role_name: str = ""
    
    # Retrieval step: Agents ONLY receive this EvidencePack
    evidence_pack: Optional[EvidencePack] = None
    
    # Consultation step
    needs_consultation: bool = False
    consulted_role_id: Optional[str] = None
    
    # Output
    final_answer: str = ""
    trace: List[Dict[str, Any]] = Field(default_factory=list)
