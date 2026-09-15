from typing import Dict, Optional, Any
from app.core.canonical import (
    ChannelType,
    PermissionLevel,
    ChannelPolicy,
    ChannelBinding
)

class ChannelPolicyStore:
    """
    Server-managed policy repository controlling channel-level permission boundaries.
    Classification of channel messages is strictly determined by policy bindings
    keyed by organization_id + channel_type + guild_id + channel_id, never by untrusted
    payload metadata or dynamic channel names.
    """
    def __init__(self):
        self._policies: Dict[str, ChannelPolicy] = {}
        self._init_default_policies()

    def _make_key(self, organization_id: str, channel_type: ChannelType, guild_id: Optional[str], channel_id: str) -> str:
        gid = guild_id or "*"
        return f"{organization_id}:{channel_type.value}:{gid}:{channel_id}"

    def register_policy(
        self,
        organization_id: str,
        channel_type: ChannelType,
        channel_id: str,
        permission_scope: PermissionLevel,
        guild_id: Optional[str] = None,
        channel_name: Optional[str] = None,
        is_active: bool = True,
        metadata: Optional[Dict[str, Any]] = None
    ) -> ChannelPolicy:
        policy = ChannelPolicy(
            organization_id=organization_id,
            channel_type=channel_type,
            guild_id=guild_id,
            channel_id=str(channel_id),
            channel_name=channel_name,
            permission_scope=permission_scope,
            is_active=is_active,
            metadata=metadata or {}
        )
        key = self._make_key(organization_id, channel_type, guild_id, str(channel_id))
        self._policies[key] = policy
        return policy

    def get_policy(
        self,
        organization_id: str,
        channel_type: ChannelType,
        channel_id: str,
        guild_id: Optional[str] = None
    ) -> Optional[ChannelPolicy]:
        """
        Lookup authoritative policy.
        For Discord, strictly requires an exact guild_id and channel_id match.
        Wildcard guild fallbacks are disallowed to prevent cross-guild privilege leakage.
        """
        if channel_type == ChannelType.DISCORD:
            if not guild_id:
                return None
            exact_key = self._make_key(organization_id, channel_type, guild_id, str(channel_id))
            return self._policies.get(exact_key)

        if guild_id:
            exact_key = self._make_key(organization_id, channel_type, guild_id, str(channel_id))
            if exact_key in self._policies:
                return self._policies[exact_key]

        return self._policies.get(self._make_key(organization_id, channel_type, None, str(channel_id)))

    def _init_default_policies(self):
        # GDG MCET default channel policies
        self.register_policy(
            organization_id="gdg_mcet",
            channel_type=ChannelType.DISCORD,
            guild_id="11223344",
            channel_id="99001122",
            channel_name="core-team",
            permission_scope=PermissionLevel.INTERNAL_CORE
        )
        self.register_policy(
            organization_id="gdg_mcet",
            channel_type=ChannelType.DISCORD,
            guild_id="11223344",
            channel_id="77889900",
            channel_name="organizers-budget",
            permission_scope=PermissionLevel.INTERNAL_CORE
        )
        self.register_policy(
            organization_id="gdg_mcet",
            channel_type=ChannelType.DISCORD,
            guild_id="11223344",
            channel_id="55667788",
            channel_name="general",
            permission_scope=PermissionLevel.PUBLIC_COMMUNITY
        )
        self.register_policy(
            organization_id="gdg_mcet",
            channel_type=ChannelType.DISCORD,
            guild_id="11223344",
            channel_id="11112222",
            channel_name="general-help",
            permission_scope=PermissionLevel.PUBLIC_COMMUNITY
        )
        self.register_policy(
            organization_id="gdg_mcet",
            channel_type=ChannelType.DISCORD,
            guild_id="11223344",
            channel_id="33445566",
            channel_name="announcements",
            permission_scope=PermissionLevel.PUBLIC_COMMUNITY
        )

        # Real production GDG MCET Discord server channel policies (guild 1549162455874412667)
        self.register_policy(
            organization_id="gdg_mcet",
            channel_type=ChannelType.DISCORD,
            guild_id="1549162455874412667",
            channel_id="1549434796772560967",
            channel_name="core-team",
            permission_scope=PermissionLevel.INTERNAL_CORE
        )
        self.register_policy(
            organization_id="gdg_mcet",
            channel_type=ChannelType.DISCORD,
            guild_id="1549162455874412667",
            channel_id="1549434872584474735",
            channel_name="organizers",
            permission_scope=PermissionLevel.INTERNAL_CORE
        )
        self.register_policy(
            organization_id="gdg_mcet",
            channel_type=ChannelType.DISCORD,
            guild_id="1549162455874412667",
            channel_id="1549162457359065110",
            channel_name="general",
            permission_scope=PermissionLevel.PUBLIC_COMMUNITY
        )
        self.register_policy(
            organization_id="gdg_mcet",
            channel_type=ChannelType.DISCORD,
            guild_id="1549162455874412667",
            channel_id="1549434693735157820",
            channel_name="public_community",
            permission_scope=PermissionLevel.PUBLIC_COMMUNITY
        )

        # Real production GDG MCET Slack #general channel
        self.register_policy(
            organization_id="gdg_mcet",
            channel_type=ChannelType.SLACK,
            guild_id="T0C21JVKS49",
            channel_id="C0C21QPFB6E",
            channel_name="general",
            permission_scope=PermissionLevel.PUBLIC_COMMUNITY,
        )

    def clear(self):
        self._policies.clear()
        self._init_default_policies()

channel_policy_store = ChannelPolicyStore()
