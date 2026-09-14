from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, Field
from typing import List
from app.core.canonical import PermissionLevel
from app.core.auth import AuthenticatedPrincipal, get_current_principal
from app.channels.approval import approval_store
from app.memory.store import memory_store

router = APIRouter(prefix="/imports", tags=["Imports"])

class ApproveImportRequest(BaseModel):
    import_hash: str = Field(..., description="SHA-256 hash of the quarantined import to promote.")

class ApproveImportResponse(BaseModel):
    status: str
    approval_id: str
    organization_id: str
    import_hash: str
    approved_by: str
    promoted_count: int
    promoted_chunk_ids: List[str]

@router.post("/approve", response_model=ApproveImportResponse)
def approve_import_endpoint(
    req: ApproveImportRequest,
    principal: AuthenticatedPrincipal = Depends(get_current_principal)
):
    # 1. Authorize: Only active organizers with INTERNAL_CORE can approve imports
    if PermissionLevel.INTERNAL_CORE not in principal.access_context.allowed_scopes:
        raise HTTPException(
            status_code=403,
            detail="Forbidden: Only organizers with INTERNAL_CORE permissions can approve quarantined imports."
        )

    # 2. Derive approver strictly from authenticated bearer token
    approver_user_id = principal.user_id
    org_id = principal.organization_id

    # 3. Promote quarantined records
    approval_record = approval_store.approve_import(
        organization_id=org_id,
        import_hash=req.import_hash,
        approved_by_user_id=approver_user_id,
        store=memory_store
    )

    if not approval_record.promoted_chunk_ids:
        raise HTTPException(
            status_code=404,
            detail=f"No quarantined records found for import_hash '{req.import_hash}' in organization '{org_id}'."
        )

    return ApproveImportResponse(
        status="success",
        approval_id=approval_record.id,
        organization_id=org_id,
        import_hash=approval_record.import_hash,
        approved_by=approval_record.approved_by_user_id,
        promoted_count=len(approval_record.promoted_chunk_ids),
        promoted_chunk_ids=approval_record.promoted_chunk_ids
    )
