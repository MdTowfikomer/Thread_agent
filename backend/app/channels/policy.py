import os
import json
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
    Backing store: PostgreSQL channel_policies table.
    Contains ZERO hardcoded runtime or fixture defaults.
    """
    def __init__(self):
        self._policies: Dict[str, ChannelPolicy] = {}

    def _make_key(self, organization_id: str, channel_type: ChannelType, guild_id: Optional[str], channel_id: str) -> str:
        gid = guild_id or "*"
        return f"{organization_id}:{channel_type.value}:{gid}:{channel_id}"

    def load_from_database(self, fail_on_error: bool = True) -> int:
        """
        Load authoritative active channel policies from PostgreSQL channel_policies table.
        Fails closed with RuntimeError on database read error.
        """
        db_url = os.getenv("SUPABASE_DB_URL") or os.getenv("DATABASE_URL")
        if not db_url:
            if fail_on_error:
                raise RuntimeError("[ChannelPolicyStore] Cannot load channel policies: SUPABASE_DB_URL is not set.")
            return 0

        try:
            import psycopg2
            with psycopg2.connect(db_url) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT organization_id, channel_type, guild_id, channel_id, channel_name, "
                        "permission_scope, is_active, metadata FROM channel_policies WHERE is_active = TRUE;"
                    )
                    rows = cur.fetchall()
                    self._policies.clear()
                    for r in rows:
                        org_id, c_type, gid, cid, name, scope, active, meta = r[0], r[1], r[2], r[3], r[4], r[5], r[6], r[7]
                        policy = ChannelPolicy(
                            organization_id=org_id,
                            channel_type=ChannelType(c_type),
                            guild_id=gid,
                            channel_id=str(cid),
                            channel_name=name,
                            permission_scope=PermissionLevel(str(scope).upper()),
                            is_active=bool(active),
                            metadata=meta or {}
                        )
                        key = self._make_key(org_id, policy.channel_type, gid, str(cid))
                        self._policies[key] = policy
            return len(self._policies)
        except Exception as exc:
            if fail_on_error:
                raise RuntimeError(f"[ChannelPolicyStore] Database error reading channel policies: {exc}") from exc
            return 0

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

        db_url = os.getenv("SUPABASE_DB_URL") or os.getenv("DATABASE_URL")
        if db_url:
            try:
                import psycopg2
                with psycopg2.connect(db_url) as conn:
                    with conn.cursor() as cur:
                        cur.execute("""
                            INSERT INTO channel_policies 
                                (organization_id, channel_type, guild_id, channel_id, channel_name, permission_scope, is_active, metadata)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                            ON CONFLICT (organization_id, channel_type, guild_id, channel_id) DO UPDATE SET
                                channel_name = EXCLUDED.channel_name,
                                permission_scope = EXCLUDED.permission_scope,
                                is_active = EXCLUDED.is_active,
                                metadata = EXCLUDED.metadata,
                                updated_at = NOW();
                        """, (
                            policy.organization_id,
                            policy.channel_type.value,
                            policy.guild_id,
                            policy.channel_id,
                            policy.channel_name,
                            policy.permission_scope.value,
                            policy.is_active,
                            json.dumps(policy.metadata)
                        ))
                    conn.commit()
            except Exception:
                pass

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
        cid = str(channel_id)
        if channel_type == ChannelType.DISCORD:
            if not guild_id:
                return None
            exact_key = self._make_key(organization_id, channel_type, guild_id, cid)
            p = self._policies.get(exact_key)
            if p and p.is_active:
                return p

            # Query database if available
            db_url = os.getenv("SUPABASE_DB_URL") or os.getenv("DATABASE_URL")
            if db_url:
                try:
                    import psycopg2
                    with psycopg2.connect(db_url) as conn:
                        with conn.cursor() as cur:
                            cur.execute(
                                "SELECT organization_id, channel_type, guild_id, channel_id, channel_name, "
                                "permission_scope, is_active, metadata FROM channel_policies "
                                "WHERE organization_id = %s AND channel_type = %s AND guild_id = %s AND channel_id = %s AND is_active = TRUE;",
                                (organization_id, channel_type.value, guild_id, cid)
                            )
                            r = cur.fetchone()
                            if r:
                                policy = ChannelPolicy(
                                    organization_id=r[0],
                                    channel_type=ChannelType(r[1]),
                                    guild_id=r[2],
                                    channel_id=str(r[3]),
                                    channel_name=r[4],
                                    permission_scope=PermissionLevel(str(r[5]).upper()),
                                    is_active=bool(r[6]),
                                    metadata=r[7] or {}
                                )
                                self._policies[exact_key] = policy
                                return policy
                except Exception:
                    pass
            return None

        # Non-Discord (Slack, etc.)
        if guild_id:
            exact_key = self._make_key(organization_id, channel_type, guild_id, cid)
            if exact_key in self._policies:
                return self._policies[exact_key]
        return self._policies.get(self._make_key(organization_id, channel_type, None, cid))

    def clear(self):
        self._policies.clear()

channel_policy_store = ChannelPolicyStore()
