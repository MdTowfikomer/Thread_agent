from typing import Dict, List, Optional, Any
from datetime import datetime, timezone
import uuid
from app.core.canonical import (
    Person,
    OrganizationMember,
    RoleAssignment,
    PermissionLevel,
    AccessContext,
    IdentityContext,
    ChannelType,
    IdentityMapping
)

class MembershipStore:
    """
    Authoritative server-side identity, membership, and role repository.
    Strictly controls permissions and access derivation without relying on client-supplied role claims.
    """
    def __init__(self):
        self._persons: Dict[str, Person] = {}
        self._members: Dict[str, OrganizationMember] = {}  # member_id -> OrganizationMember
        self._org_user_to_member: Dict[str, str] = {}     # f"{org_id}:{user_id}" -> member_id
        self._roles: Dict[str, List[RoleAssignment]] = {}  # member_id -> List[RoleAssignment]
        self._identity_mappings: Dict[str, IdentityMapping] = {}  # f"{org_id}:{channel_type.value}:{external_user_id}" -> IdentityMapping
        self._init_default_members()

    def _init_default_members(self):
        # 1. Lead Organizer: Arjun Sharma
        self.register_member(
            user_id="usr_arjun",
            name="Arjun Sharma",
            email="arjun@gdgmcet.org",
            organization_id="gdg_mcet",
            role_id="organizer_lead",
            role_name="Lead Organizer",
            permission=PermissionLevel.INTERNAL_CORE,
            is_active=True
        )

        # 2. Tech Lead: Priya Ramesh
        self.register_member(
            user_id="usr_priya",
            name="Priya Ramesh",
            email="priya@gdgmcet.org",
            organization_id="gdg_mcet",
            role_id="tech_lead",
            role_name="Tech Lead",
            permission=PermissionLevel.INTERNAL_CORE,
            is_active=True
        )

        # 3. Active Community Member: Rohan
        self.register_member(
            user_id="usr_student_rohan",
            name="Rohan Verma",
            email="rohan@student.mcet.edu",
            organization_id="gdg_mcet",
            role_id="community_member",
            role_name="Community Member",
            permission=PermissionLevel.PUBLIC_COMMUNITY,
            is_active=True
        )

        # 4. Inactive Member: Former Core Lead who left/graduated
        self.register_member(
            user_id="usr_inactive_lead",
            name="Siddharth Rao",
            email="siddharth.former@mcet.edu",
            organization_id="gdg_mcet",
            role_id="organizer_lead",
            role_name="Past Lead Organizer",
            permission=PermissionLevel.INTERNAL_CORE,
            is_active=False  # INACTIVE! Must get NO internal access
        )

        # 5. Authenticated Demo Personas (for zero-auth UI demo sessions)
        self.register_member(
            user_id="demo_organizer",
            name="Demo Organizer",
            email="organizer.demo@gdgmcet.org",
            organization_id="gdg_mcet",
            role_id="organizer_lead",
            role_name="Lead Organizer",
            permission=PermissionLevel.INTERNAL_CORE,
            is_active=True
        )

        self.register_member(
            user_id="demo_community",
            name="Demo Community Member",
            email="community.demo@student.mcet.edu",
            organization_id="gdg_mcet",
            role_id="community_member",
            role_name="Community Member",
            permission=PermissionLevel.PUBLIC_COMMUNITY,
            is_active=True
        )

        # Default Discord identity mapping for Arjun
        self.register_identity_mapping(
            organization_id="gdg_mcet",
            channel_type=ChannelType.DISCORD,
            external_user_id="discord_arjun_101",
            internal_user_id="usr_arjun",
            external_username="arjun_gdg"
        )

    def register_identity_mapping(
        self,
        organization_id: str,
        channel_type: ChannelType,
        external_user_id: str,
        internal_user_id: str,
        external_username: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> IdentityMapping:
        member_id = self._org_user_to_member.get(f"{organization_id}:{internal_user_id}")
        if not member_id:
            # Distinguish user belonging to another organization from completely unknown user
            if internal_user_id in self._persons:
                raise ValueError(
                    f"Cannot register identity mapping: cross-organization mapping rejected. "
                    f"User '{internal_user_id}' does not belong to organization '{organization_id}'."
                )
            raise ValueError(
                f"Cannot register identity mapping: user '{internal_user_id}' is not a registered member "
                f"of organization '{organization_id}'."
            )

        member = self._members.get(member_id)
        if not member or member.organization_id != organization_id:
            raise ValueError(
                f"Cannot register identity mapping: cross-organization mapping rejected. Member '{internal_user_id}' "
                f"does not belong to organization '{organization_id}'."
            )

        if not member.is_active:
            raise ValueError(
                f"Cannot register identity mapping: member '{internal_user_id}' is inactive in organization '{organization_id}'."
            )

        mapping = IdentityMapping(
            organization_id=organization_id,
            channel_type=channel_type,
            external_user_id=str(external_user_id),
            external_username=external_username,
            internal_user_id=internal_user_id,
            internal_member_id=member_id,
            metadata=metadata or {}
        )
        key = f"{organization_id}:{channel_type.value}:{external_user_id}"
        self._identity_mappings[key] = mapping
        return mapping

    def resolve_identity_mapping(
        self,
        organization_id: str,
        channel_type: ChannelType,
        external_user_id: str
    ) -> Optional[IdentityMapping]:
        key = f"{organization_id}:{channel_type.value}:{external_user_id}"
        return self._identity_mappings.get(key)

    def get_person(self, user_id: str) -> Optional[Person]:
        return self._persons.get(user_id)

    def register_member(
        self,
        user_id: str,
        name: str,
        organization_id: str,
        role_id: str,
        role_name: str,
        permission: PermissionLevel,
        email: Optional[str] = None,
        is_active: bool = True
    ) -> OrganizationMember:
        person = Person(id=user_id, name=name, email=email)
        self._persons[user_id] = person

        member_id = str(uuid.uuid4())
        member = OrganizationMember(
            id=member_id,
            organization_id=organization_id,
            person_id=user_id,
            is_active=is_active
        )
        self._members[member_id] = member
        self._org_user_to_member[f"{organization_id}:{user_id}"] = member_id

        role_assignment = RoleAssignment(
            organization_id=organization_id,
            member_id=member_id,
            role_id=role_id,
            role_name=role_name,
            permission=permission
        )
        self._roles.setdefault(member_id, []).append(role_assignment)
        return member

    def get_identity_context(self, user_id: str, organization_id: str) -> IdentityContext:
        member_id = self._org_user_to_member.get(f"{organization_id}:{user_id}")
        if not member_id:
            # Unknown user: public scope only, inactive membership
            return IdentityContext(
                user_id=user_id,
                organization_id=organization_id,
                member_id=None,
                is_active=False,
                assigned_roles=[],
                permission_scopes=[PermissionLevel.PUBLIC_COMMUNITY]
            )

        member = self._members[member_id]
        roles = self._roles.get(member_id, [])

        if not member.is_active:
            # Inactive member: strictly revoked internal access
            return IdentityContext(
                user_id=user_id,
                organization_id=organization_id,
                member_id=member_id,
                is_active=False,
                assigned_roles=roles,
                permission_scopes=[PermissionLevel.PUBLIC_COMMUNITY]
            )

        # Active member: evaluate permissions from assigned roles
        scopes = [PermissionLevel.PUBLIC_COMMUNITY]
        has_internal = any(r.permission == PermissionLevel.INTERNAL_CORE for r in roles)
        if has_internal:
            scopes.append(PermissionLevel.INTERNAL_CORE)

        return IdentityContext(
            user_id=user_id,
            organization_id=organization_id,
            member_id=member_id,
            is_active=True,
            assigned_roles=roles,
            permission_scopes=scopes
        )

    def derive_access_context(self, user_id: str, organization_id: str) -> AccessContext:
        ident = self.get_identity_context(user_id=user_id, organization_id=organization_id)
        
        has_internal = PermissionLevel.INTERNAL_CORE in ident.permission_scopes
        primary_role = ident.assigned_roles[0].role_id if ident.assigned_roles else "community"

        return AccessContext(
            user_id=user_id,
            organization_id=organization_id,
            role_id=primary_role,
            user_permission=PermissionLevel.INTERNAL_CORE if has_internal else PermissionLevel.PUBLIC_COMMUNITY,
            allowed_scopes=ident.permission_scopes
        )

    def clear(self):
        self._persons.clear()
        self._members.clear()
        self._org_user_to_member.clear()
        self._roles.clear()
        self._identity_mappings.clear()

    def seed(self):
        self._init_default_members()

    def reset(self):
        self.clear()
        self.seed()

membership_store = MembershipStore()
