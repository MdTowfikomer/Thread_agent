from fastapi import APIRouter, Depends, Response
from app.tenancy.auth import get_current_membership
from app.core.membership import membership_store
from app.tracing.repository import trace_repository
from app.tracing.sanitize import trace_sanitizer

router = APIRouter(prefix="/api/v2/organizations", tags=["V2 execution traces"])


@router.get("/{org_id}/traces/{trace_id}")
def read_trace(org_id: str, trace_id: str, response: Response, context=Depends(get_current_membership)):
    row = trace_repository.read(org_id, trace_id, context.user_id, context.role)
    scopes = [scope.value for scope in membership_store.derive_access_context(context.user_id, org_id).allowed_scopes]
    response.headers["Cache-Control"] = "no-store"
    return trace_sanitizer.for_reader(row, scopes)


@router.get("/{org_id}/conversations/{conversation_id}/traces")
def list_traces(org_id: str, conversation_id: str, response: Response, context=Depends(get_current_membership)):
    response.headers["Cache-Control"] = "no-store"
    return trace_repository.list_for_conversation(org_id, conversation_id, context.user_id, context.role)
