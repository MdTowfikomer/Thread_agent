from typing import Dict, Optional, List
from datetime import datetime, timezone
from pydantic import BaseModel, Field

class GuildInstallation(BaseModel):
    guild_id: str
    organization_id: str
    guild_name: Optional[str] = None
    installed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    is_active: bool = True

class GuildInstallationStore:
    """
    Server-owned authoritative repository mapping Discord guilds to Thread organizations.
    Resolves guild_id -> organization_id securely.
    Rejects any caller or payload attempts to override the organization boundary.
    """
    def __init__(self):
        self._installations: Dict[str, GuildInstallation] = {}
        self._init_defaults()

    def _init_defaults(self):
        # Default GDG MCET Discord guild binding
        self.register_installation(
            guild_id="11223344",
            organization_id="gdg_mcet",
            guild_name="GDG MCET Discord"
        )

    def register_installation(
        self,
        guild_id: str,
        organization_id: str,
        guild_name: Optional[str] = None,
        is_active: bool = True
    ) -> GuildInstallation:
        inst = GuildInstallation(
            guild_id=str(guild_id),
            organization_id=organization_id,
            guild_name=guild_name,
            is_active=is_active
        )
        self._installations[str(guild_id)] = inst
        return inst

    def get_organization_for_guild(self, guild_id: Optional[str]) -> Optional[str]:
        if not guild_id:
            return None
        inst = self._installations.get(str(guild_id))
        if inst and inst.is_active:
            return inst.organization_id
        return None

    def get_installation(self, guild_id: str) -> Optional[GuildInstallation]:
        return self._installations.get(str(guild_id))

    def clear(self):
        self._installations.clear()
        self._init_defaults()

guild_installation_store = GuildInstallationStore()
