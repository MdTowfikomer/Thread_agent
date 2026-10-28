from typing import Literal
import re
from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field, SecretStr

from app.core.crypto import encrypt_secret
from app.tenancy.auth import get_current_membership
from app.tenancy.credentials import (
    DEFAULT_MODEL, SUPPORTED_MODELS, credential_aad, credential_record,
    public_metadata, revoke_credential, save_credential,
)
from app.tenancy.models import google_provider

router = APIRouter(prefix="/api/v2/organizations", tags=["V2 model credentials"])


class ModelCredentialInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    provider: Literal["google"] = "google"
    api_key: SecretStr = Field(min_length=12, max_length=1024)
    model_name: str = Field(default=DEFAULT_MODEL, max_length=100)


def require_admin(context):
    if context.role not in ("owner", "admin"):
        raise HTTPException(403, "Workspace administrator access is required.")


@router.get("/{org_id}/credentials/model")
def get_credentials(org_id: str, response: Response, context=Depends(get_current_membership)):
    require_admin(context)
    response.headers["Cache-Control"] = "no-store"
    return public_metadata(org_id, context.user_id)


@router.post("/{org_id}/credentials/model")
def set_credentials(org_id: str, body: ModelCredentialInput, response: Response, context=Depends(get_current_membership)):
    require_admin(context)
    if body.model_name not in SUPPORTED_MODELS:
        raise HTTPException(400, "Select a supported chat model.")
    key = body.api_key.get_secret_value().strip()
    # Google Auth keys can contain dots (AQ.); provider validation is authoritative.
    if not re.fullmatch(r"[A-Za-z0-9_.-]{12,1024}", key):
        raise HTTPException(400, "Enter a valid Google API key without whitespace or non-key characters.")
    row = credential_record(org_id)
    expected_revision = row["revision"] if row else 0
    # Validate encryption configuration before transmitting any key to the provider.
    encrypted = encrypt_secret(key, associated_data=credential_aad(org_id))
    google_provider.validate(key, body.model_name)
    save_credential(org_id, context.user_id, encrypted, key[-4:], body.model_name, expected_revision)
    response.headers["Cache-Control"] = "no-store"
    return public_metadata(org_id, context.user_id)


@router.delete("/{org_id}/credentials/model")
def delete_credentials(org_id: str, response: Response, context=Depends(get_current_membership)):
    require_admin(context)
    revoke_credential(org_id, context.user_id)
    response.headers["Cache-Control"] = "no-store"
    return public_metadata(org_id, context.user_id)
