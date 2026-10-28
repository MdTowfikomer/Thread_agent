import os
from fastapi import HTTPException
from app.core.canonical import OrganizationWorkspace, RoleAgentConfig
from app.tenancy.repository import tenant_repository


class OrganizationNotFoundError(HTTPException):
    def __init__(self):
        super().__init__(404, "Workspace not found.")


def get_workspace(workspace_id: str) -> OrganizationWorkspace:
    if tenant_repository.configured:
        row = tenant_repository.workspace(workspace_id)
        general = RoleAgentConfig(id="general_assistant", name=row["default_agent_name"],
                                  role="Organizational Assistant", department="Knowledge",
                                  style=row["system_prompt"], avatar="", expertise=[])
        return OrganizationWorkspace(id=row["id"], name=row["name"], description=row["description"],
                                     default_role_id=general.id,
                                     roles=[general] + [RoleAgentConfig(**role) for role in row["configured_roles"]])
    if os.getenv("THREAD_ALLOW_OFFLINE_IDENTITY") == "1":
        from app.core.demo_workspaces import WORKSPACES
        if workspace_id in WORKSPACES:
            return WORKSPACES[workspace_id]
        raise OrganizationNotFoundError()
    raise HTTPException(503, "Workspace service database is not configured.")


def get_role_agent(workspace_id: str, role_id: str):
    workspace = get_workspace(workspace_id)
    return next((role for role in workspace.roles if role.id == role_id), workspace.roles[0])
