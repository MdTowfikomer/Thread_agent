import re
import uuid
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from app.api.v2.auth import normalize_email
from app.core.canonical import RoleAgentConfig
from app.tenancy.auth import get_current_membership, get_current_user
from app.tenancy.repository import tenant_repository

router = APIRouter(prefix="/api/v2", tags=["V2 workspaces"])


class OrganizationInput(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=2000)

    @field_validator("name")
    @classmethod
    def name_not_blank(cls, value):
        if not value.strip():
            raise ValueError("Workspace name is required.")
        return value.strip()


class WorkspaceUpdate(OrganizationInput):
    default_agent_name: str = Field(default="Thread", min_length=1, max_length=100)
    system_prompt: str = Field(default="Answer organizational questions using authorized evidence. Acknowledge missing evidence.", max_length=8000)
    configured_roles: list[RoleAgentConfig] = Field(default_factory=list, max_length=10)

    @field_validator("configured_roles")
    @classmethod
    def unique_roles(cls, roles):
        ids = [role.id for role in roles]
        if len(set(ids)) != len(ids) or "general_assistant" in ids:
            raise ValueError("Specialist role IDs must be unique and cannot use general_assistant.")
        return roles


class InvitationInput(BaseModel):
    email: str
    role: Literal["admin", "member"] = "member"
    _email = field_validator("email")(normalize_email)


class RoleInput(BaseModel):
    role: Literal["owner", "admin", "member"]


@router.post("/organizations", status_code=201)
def create(body: OrganizationInput, user=Depends(get_current_user)):
    slug = re.sub(r"[^a-z0-9]+", "-", body.name.lower()).strip("-")[:48] or "workspace"
    org_id = f"{slug}-{uuid.uuid4().hex[:12]}"
    return tenant_repository.create_organization(user["user_id"], org_id, body.name, body.description, user["token_hash"])


@router.get("/organizations")
def list_organizations(user=Depends(get_current_user)):
    return tenant_repository.organizations(user["user_id"])


@router.post("/organizations/{org_id}/switch")
def switch(org_id: str, user=Depends(get_current_user)):
    tenant_repository.switch(org_id, user["user_id"], user["token_hash"])
    return {"active_organization_id": org_id}


@router.get("/organizations/{org_id}")
def workspace(org_id: str, context=Depends(get_current_membership)):
    return {**tenant_repository.workspace(org_id), "role": context.role}


@router.patch("/organizations/{org_id}")
def update(org_id: str, body: WorkspaceUpdate, user=Depends(get_current_user)):
    tenant_repository.update_workspace(org_id, user["user_id"], body.name, body.description,
                                       body.model_dump(exclude={"name", "description"}))
    return {"updated": True}


@router.get("/organizations/{org_id}/members")
def members(org_id: str, user=Depends(get_current_user)):
    return tenant_repository.members(org_id, user["user_id"])


@router.post("/organizations/{org_id}/invitations", status_code=201)
def invite(org_id: str, body: InvitationInput, user=Depends(get_current_user)):
    token = tenant_repository.invite(org_id, user["user_id"], body.email, body.role)
    return {"invitation_path": f"/invite/{token}", "expires_in_seconds": 604800}


@router.post("/invitations/{token}/accept")
def accept(token: str, user=Depends(get_current_user)):
    if len(token) > 256:
        raise HTTPException(404, "Invitation not found.")
    org_id = tenant_repository.accept(token, user["user_id"], user["email"])
    tenant_repository.switch(org_id, user["user_id"], user["token_hash"])
    return {"active_organization_id": org_id}


@router.patch("/organizations/{org_id}/members/{user_id}")
def change_role(org_id: str, user_id: str, body: RoleInput, user=Depends(get_current_user)):
    tenant_repository.change_member(org_id, user["user_id"], user_id, body.role)
    return {"updated": True}


@router.delete("/organizations/{org_id}/members/{user_id}")
def remove(org_id: str, user_id: str, user=Depends(get_current_user)):
    tenant_repository.change_member(org_id, user["user_id"], user_id, remove=True)
    return {"removed": True}
