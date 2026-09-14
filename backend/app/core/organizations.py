from typing import Dict, Optional, List
from app.core.canonical import OrganizationWorkspace, RoleAgentConfig

# Organizations registry: Thread engine is 100% organization-agnostic.
# GDG MCET is our primary deployment & demo workspace.
WORKSPACES: Dict[str, OrganizationWorkspace] = {
    "gdg_mcet": OrganizationWorkspace(
        id="gdg_mcet",
        name="GDG MCET",
        description="Google Developer Groups MCET — Core team, speaker rolodex, workshop codelabs, and community context.",
        default_role_id="organizer_lead",
        roles=[
            RoleAgentConfig(
                id="organizer_lead",
                name="Arjun Sharma",
                role="Lead Organizer",
                department="Core Leadership",
                style="Strategic, community-first, organized, authoritative on event schedules and approvals.",
                avatar="https://api.dicebear.com/7.x/bottts/svg?seed=Arjun",
                expertise=["event planning", "speaker relations", "college permissions", "core team management", "DevFest", "dates", "venue"]
            ),
            RoleAgentConfig(
                id="tech_lead",
                name="Priya Ramesh",
                role="Tech Lead",
                department="Engineering & Workshops",
                style="Technical, precise, hands-on, focused on workshop prerequisites, GitHub repos, and lab setups.",
                avatar="https://api.dicebear.com/7.x/bottts/svg?seed=Priya",
                expertise=["GenAI workshops", "cloud labs", "GitHub repos", "hands-on codelabs", "tech stack", "mentorship", "prerequisites"]
            ),
            RoleAgentConfig(
                id="sponsorship_lead",
                name="Karthik Verma",
                role="Sponsorship & Finance Lead",
                department="Finance & Partnerships",
                style="Pragmatic, metrics-driven, guarded with internal budget figures, focused on sponsor deliverables.",
                avatar="https://api.dicebear.com/7.x/bottts/svg?seed=Karthik",
                expertise=["budgeting", "swag vendor procurement", "sponsor pitch decks", "reimbursements", "venue food catering", "cost"]
            ),
            RoleAgentConfig(
                id="community_lead",
                name="Sneha Nair",
                role="Community & PR Lead",
                department="Public Relations & Outreach",
                style="Warm, engaging, transparent, focused on student onboarding, RSVP links, and certificate distribution.",
                avatar="https://api.dicebear.com/7.x/bottts/svg?seed=Sneha",
                expertise=["social media", "RSVP tracking", "event marketing", "volunteer onboarding", "certificates", "student FAQ", "registration"]
            )
        ]
    )
}

def get_workspace(workspace_id: str = "gdg_mcet") -> OrganizationWorkspace:
    return WORKSPACES.get(workspace_id, WORKSPACES["gdg_mcet"])

def get_role_agent(workspace_id: str, role_id: str) -> Optional[RoleAgentConfig]:
    ws = get_workspace(workspace_id)
    for r in ws.roles:
        if r.id == role_id:
            return r
    return ws.roles[0] if ws.roles else None
