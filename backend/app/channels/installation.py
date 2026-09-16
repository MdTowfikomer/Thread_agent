import os
import json
import uuid
from typing import Dict, Optional, List, Any
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
    Durable storage backed by PostgreSQL discord_guild_installations table.
    Contains ZERO hardcoded runtime or fixture defaults.
    """
    def __init__(self):
        self._installations: Dict[str, GuildInstallation] = {}

    def load_from_database(self, fail_on_error: bool = True) -> int:
        """
        Load authoritative active Discord guild installations from PostgreSQL.
        Fails closed with RuntimeError on database read error.
        """
        db_url = os.getenv("SUPABASE_DB_URL") or os.getenv("DATABASE_URL")
        if not db_url:
            if fail_on_error:
                raise RuntimeError("[GuildInstallationStore] Cannot load installations: SUPABASE_DB_URL is not set.")
            return 0

        try:
            import psycopg2
            with psycopg2.connect(db_url) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT guild_id, organization_id, guild_name, is_active "
                        "FROM discord_guild_installations WHERE is_active = TRUE;"
                    )
                    rows = cur.fetchall()
                    self._installations.clear()
                    for r in rows:
                        gid, org_id, name, active = r[0], r[1], r[2], r[3]
                        self._installations[str(gid)] = GuildInstallation(
                            guild_id=str(gid),
                            organization_id=org_id,
                            guild_name=name,
                            is_active=bool(active)
                        )
            return len(self._installations)
        except Exception as exc:
            if fail_on_error:
                raise RuntimeError(f"[GuildInstallationStore] Database error reading Discord guild installations: {exc}") from exc
            return 0

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

        db_url = os.getenv("SUPABASE_DB_URL") or os.getenv("DATABASE_URL")
        if db_url:
            try:
                import psycopg2
                with psycopg2.connect(db_url) as conn:
                    with conn.cursor() as cur:
                        cur.execute("""
                            INSERT INTO discord_guild_installations (guild_id, organization_id, guild_name, is_active)
                            VALUES (%s, %s, %s, %s)
                            ON CONFLICT (guild_id) DO UPDATE SET
                                organization_id = EXCLUDED.organization_id,
                                guild_name = EXCLUDED.guild_name,
                                is_active = EXCLUDED.is_active;
                        """, (inst.guild_id, inst.organization_id, inst.guild_name, inst.is_active))
                    conn.commit()
            except Exception:
                pass

        return inst

    def get_organization_for_guild(self, guild_id: Optional[str]) -> Optional[str]:
        if not guild_id:
            return None
        gid = str(guild_id)
        inst = self._installations.get(gid)
        if inst and inst.is_active:
            return inst.organization_id

        db_url = os.getenv("SUPABASE_DB_URL") or os.getenv("DATABASE_URL")
        if db_url:
            try:
                import psycopg2
                with psycopg2.connect(db_url) as conn:
                    with conn.cursor() as cur:
                        cur.execute(
                            "SELECT organization_id FROM discord_guild_installations WHERE guild_id = %s AND is_active = TRUE;",
                            (gid,)
                        )
                        row = cur.fetchone()
                        if row:
                            return row[0]
            except Exception:
                pass
        return None

    def get_installation(self, guild_id: str) -> Optional[GuildInstallation]:
        gid = str(guild_id)
        if gid in self._installations:
            return self._installations[gid]

        db_url = os.getenv("SUPABASE_DB_URL") or os.getenv("DATABASE_URL")
        if db_url:
            try:
                import psycopg2
                with psycopg2.connect(db_url) as conn:
                    with conn.cursor() as cur:
                        cur.execute(
                            "SELECT guild_id, organization_id, guild_name, is_active FROM discord_guild_installations WHERE guild_id = %s;",
                            (gid,)
                        )
                        r = cur.fetchone()
                        if r:
                            inst = GuildInstallation(guild_id=r[0], organization_id=r[1], guild_name=r[2], is_active=r[3])
                            self._installations[gid] = inst
                            return inst
            except Exception:
                pass
        return None

    def clear(self):
        self._installations.clear()

guild_installation_store = GuildInstallationStore()

class GitHubRepositoryBinding(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    organization_id: str
    installation_id: Optional[str] = None
    repository_id: str
    repository_name: str
    is_active: bool = True
    bound_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: Dict[str, Any] = Field(default_factory=dict)

class GitHubRepositoryBindingStore:
    """
    Server-owned authoritative repository mapping GitHub repositories and App installations
    to Thread organizations.
    Resolves repository_id / installation_id -> organization_id securely.
    Rejects caller-supplied organization override parameters on webhooks.
    """
    def __init__(self):
        self._bindings_by_id: Dict[str, GitHubRepositoryBinding] = {}
        self._bindings_by_name: Dict[str, GitHubRepositoryBinding] = {}
        self._init_defaults()

    def _init_defaults(self):
        # Authoritative binding for Thread_Agent production repository
        self.register_binding(
            repository_id="1371393965",
            repository_name="mdtowfikomer/thread_agent",
            organization_id="gdg_mcet",
            installation_id="gh_inst_thread_agent"
        )

    def register_binding(
        self,
        repository_id: str,
        repository_name: str,
        organization_id: str,
        installation_id: Optional[str] = None,
        is_active: bool = True,
        metadata: Optional[Dict[str, Any]] = None
    ) -> GitHubRepositoryBinding:
        binding = GitHubRepositoryBinding(
            repository_id=str(repository_id).strip(),
            repository_name=repository_name.strip().lower(),
            organization_id=organization_id.strip(),
            installation_id=str(installation_id).strip() if installation_id else None,
            is_active=is_active,
            metadata=metadata or {}
        )
        self._bindings_by_id[binding.repository_id] = binding
        self._bindings_by_name[binding.repository_name] = binding

        # Mirror to PostgreSQL if database URL is available
        db_url = os.getenv("SUPABASE_DB_URL") or os.getenv("DATABASE_URL")
        if db_url:
            try:
                import psycopg2
                with psycopg2.connect(db_url) as conn:
                    with conn.cursor() as cur:
                        cur.execute("""
                            INSERT INTO github_repository_bindings 
                                (id, organization_id, installation_id, repository_id, repository_name, is_active, bound_at)
                            VALUES (%s, %s, %s, %s, %s, %s, %s)
                            ON CONFLICT (repository_id) DO UPDATE SET
                                organization_id = EXCLUDED.organization_id,
                                repository_name = EXCLUDED.repository_name,
                                installation_id = EXCLUDED.installation_id,
                                is_active = EXCLUDED.is_active;
                        """, (binding.id, binding.organization_id, binding.installation_id, binding.repository_id, binding.repository_name, binding.is_active, binding.bound_at))
                    conn.commit()
            except Exception:
                pass

        return binding

    def get_organization_for_repository(
        self,
        repository_id: Optional[str],
        repository_name: Optional[str] = None
    ) -> Optional[str]:
        # 1. Primary lookup by numeric repository_id
        if repository_id:
            b = self._bindings_by_id.get(str(repository_id).strip())
            if b and b.is_active:
                return b.organization_id

        # 2. Secondary lookup by canonical repository_name (org/repo)
        if repository_name:
            b = self._bindings_by_name.get(repository_name.strip().lower())
            if b and b.is_active:
                return b.organization_id

        # 3. Database lookup if connected
        db_url = os.getenv("SUPABASE_DB_URL") or os.getenv("DATABASE_URL")
        if db_url:
            try:
                import psycopg2
                with psycopg2.connect(db_url) as conn:
                    with conn.cursor() as cur:
                        if repository_id:
                            cur.execute(
                                "SELECT organization_id FROM github_repository_bindings WHERE repository_id = %s AND is_active = TRUE;",
                                (str(repository_id).strip(),)
                            )
                            row = cur.fetchone()
                            if row:
                                return row[0]
                        if repository_name:
                            cur.execute(
                                "SELECT organization_id FROM github_repository_bindings WHERE repository_name = %s AND is_active = TRUE;",
                                (repository_name.strip().lower(),)
                            )
                            row = cur.fetchone()
                            if row:
                                return row[0]
            except Exception:
                pass

        return None

    def clear(self):
        self._bindings_by_id.clear()
        self._bindings_by_name.clear()
        self._init_defaults()

github_binding_store = GitHubRepositoryBindingStore()


# =====================================================================
# TELEGRAM CHAT BINDINGS
# =====================================================================

class TelegramChatBinding(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    organization_id: str
    chat_id: str
    chat_title: Optional[str] = None
    chat_type: Optional[str] = None  # "group", "supergroup", "channel", "private"
    is_active: bool = True
    bound_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: Dict[str, Any] = Field(default_factory=dict)


class TelegramChatBindingStore:
    """
    Server-owned authoritative repository mapping Telegram chat IDs to Thread organizations.
    Resolves chat_id -> organization_id securely.
    Rejects any caller or payload attempts to override the organization boundary.
    """
    def __init__(self):
        self._bindings_by_id: Dict[str, TelegramChatBinding] = {}
        self._load_from_database()

    def _load_from_database(self):
        db_url = os.getenv("SUPABASE_DB_URL") or os.getenv("DATABASE_URL")
        if not db_url:
            return
        try:
            import psycopg2
            with psycopg2.connect(db_url) as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT id, organization_id, chat_id, chat_title, chat_type, is_active, bound_at, metadata FROM telegram_chat_bindings;")
                    for row in cur.fetchall():
                        self._bindings_by_id[str(row[2])] = TelegramChatBinding(
                            id=row[0], organization_id=row[1], chat_id=str(row[2]),
                            chat_title=row[3], chat_type=row[4], is_active=row[5],
                            bound_at=row[6], metadata=row[7] or {}
                        )
        except Exception:
            pass

    def register_binding(
        self,
        chat_id: str,
        organization_id: str,
        chat_title: Optional[str] = None,
        chat_type: Optional[str] = None,
        is_active: bool = True,
        metadata: Optional[Dict[str, Any]] = None
    ) -> TelegramChatBinding:
        binding = TelegramChatBinding(
            chat_id=str(chat_id).strip(),
            organization_id=organization_id.strip(),
            chat_title=chat_title.strip() if chat_title else None,
            chat_type=chat_type.strip() if chat_type else None,
            is_active=is_active,
            metadata=metadata or {}
        )
        # Mirror to PostgreSQL if database URL is available
        db_url = os.getenv("SUPABASE_DB_URL") or os.getenv("DATABASE_URL")
        if db_url:
            import psycopg2
            with psycopg2.connect(db_url) as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                            INSERT INTO telegram_chat_bindings 
                                (id, organization_id, chat_id, chat_title, chat_type, is_active, bound_at, metadata)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                            ON CONFLICT (chat_id) DO UPDATE SET
                                organization_id = EXCLUDED.organization_id,
                                chat_title = EXCLUDED.chat_title,
                                chat_type = EXCLUDED.chat_type,
                                is_active = EXCLUDED.is_active,
                                metadata = EXCLUDED.metadata;
                        """, (
                            binding.id,
                            binding.organization_id,
                            binding.chat_id,
                            binding.chat_title,
                            binding.chat_type,
                            binding.is_active,
                            binding.bound_at,
                            json.dumps(binding.metadata) if hasattr(binding, 'metadata') else '{}'
                        ))
                conn.commit()
        elif os.getenv("APP_ENV", "production").lower() != "development" and os.getenv("THREAD_ALLOW_OFFLINE_BINDINGS") != "1":
            raise RuntimeError("Durable Telegram bindings require SUPABASE_DB_URL in production.")

        self._bindings_by_id[binding.chat_id] = binding
        return binding

    def get_organization_for_chat(self, chat_id: Optional[str]) -> Optional[str]:
        if not chat_id:
            return None
        cid = str(chat_id).strip()
        db_url = os.getenv("SUPABASE_DB_URL") or os.getenv("DATABASE_URL")
        if db_url:
            import psycopg2
            with psycopg2.connect(db_url) as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT organization_id FROM telegram_chat_bindings WHERE chat_id = %s AND is_active = TRUE;", (cid,))
                    row = cur.fetchone()
                    return row[0] if row else None
        b = self._bindings_by_id.get(cid)
        if b and b.is_active:
            return b.organization_id

        return None

    def get_binding(self, chat_id: str) -> Optional[TelegramChatBinding]:
        cid = str(chat_id).strip()
        db_url = os.getenv("SUPABASE_DB_URL") or os.getenv("DATABASE_URL")
        if db_url:
            import psycopg2
            with psycopg2.connect(db_url) as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT id, organization_id, chat_id, chat_title, chat_type, is_active, bound_at, metadata FROM telegram_chat_bindings WHERE chat_id = %s;", (cid,))
                    row = cur.fetchone()
                    if row:
                        return TelegramChatBinding(id=row[0], organization_id=row[1], chat_id=str(row[2]), chat_title=row[3], chat_type=row[4], is_active=row[5], bound_at=row[6], metadata=row[7] or {})
                    return None
        return self._bindings_by_id.get(cid)

    def clear(self):
        self._bindings_by_id.clear()

telegram_binding_store = TelegramChatBindingStore()


# =====================================================================
# SLACK WORKSPACE BINDINGS
# =====================================================================

class SlackWorkspaceBinding(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    organization_id: str
    team_id: str
    team_domain: Optional[str] = None
    is_active: bool = True
    bound_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: Dict[str, Any] = Field(default_factory=dict)


class SlackWorkspaceBindingStore:
    """
    Server-owned authoritative repository mapping Slack team/workspace IDs to Thread organizations.
    Resolves team_id -> organization_id securely.
    """
    def __init__(self):
        self._bindings_by_id: Dict[str, SlackWorkspaceBinding] = {}
        self._load_from_database()

    def _load_from_database(self):
        db_url = os.getenv("SUPABASE_DB_URL") or os.getenv("DATABASE_URL")
        if not db_url:
            return
        try:
            import psycopg2
            with psycopg2.connect(db_url) as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT id, organization_id, team_id, team_domain, is_active, bound_at, metadata FROM slack_workspace_bindings;")
                    for row in cur.fetchall():
                        self._bindings_by_id[str(row[2])] = SlackWorkspaceBinding(
                            id=row[0], organization_id=row[1], team_id=str(row[2]),
                            team_domain=row[3], is_active=row[4], bound_at=row[5],
                            metadata=row[6] or {}
                        )
        except Exception:
            pass

    def register_binding(
        self,
        team_id: str,
        organization_id: str,
        team_domain: Optional[str] = None,
        is_active: bool = True,
        metadata: Optional[Dict[str, Any]] = None
    ) -> SlackWorkspaceBinding:
        binding = SlackWorkspaceBinding(
            team_id=str(team_id).strip(),
            organization_id=organization_id.strip(),
            team_domain=team_domain.strip().lower() if team_domain else None,
            is_active=is_active,
            metadata=metadata or {}
        )
        # Mirror to PostgreSQL if database URL is available
        db_url = os.getenv("SUPABASE_DB_URL") or os.getenv("DATABASE_URL")
        if db_url:
            import psycopg2
            with psycopg2.connect(db_url) as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                            INSERT INTO slack_workspace_bindings 
                                (id, organization_id, team_id, team_domain, is_active, bound_at, metadata)
                            VALUES (%s, %s, %s, %s, %s, %s, %s)
                            ON CONFLICT (team_id) DO UPDATE SET
                                organization_id = EXCLUDED.organization_id,
                                team_domain = EXCLUDED.team_domain,
                                is_active = EXCLUDED.is_active,
                                metadata = EXCLUDED.metadata;
                        """, (
                            binding.id,
                            binding.organization_id,
                            binding.team_id,
                            binding.team_domain,
                            binding.is_active,
                            binding.bound_at,
                            json.dumps(binding.metadata) if hasattr(binding, 'metadata') else '{}'
                        ))
                conn.commit()
        elif os.getenv("APP_ENV", "production").lower() != "development" and os.getenv("THREAD_ALLOW_OFFLINE_BINDINGS") != "1":
            raise RuntimeError("Durable Slack bindings require SUPABASE_DB_URL in production.")

        self._bindings_by_id[binding.team_id] = binding
        return binding

    def get_organization_for_team(self, team_id: Optional[str]) -> Optional[str]:
        if not team_id:
            return None
        tid = str(team_id).strip()
        db_url = os.getenv("SUPABASE_DB_URL") or os.getenv("DATABASE_URL")
        if db_url:
            import psycopg2
            with psycopg2.connect(db_url) as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT organization_id FROM slack_workspace_bindings WHERE team_id = %s AND is_active = TRUE;", (tid,))
                    row = cur.fetchone()
                    return row[0] if row else None
        b = self._bindings_by_id.get(tid)
        if b and b.is_active:
            return b.organization_id

        return None

    def get_binding(self, team_id: str) -> Optional[SlackWorkspaceBinding]:
        tid = str(team_id).strip()
        db_url = os.getenv("SUPABASE_DB_URL") or os.getenv("DATABASE_URL")
        if db_url:
            import psycopg2
            with psycopg2.connect(db_url) as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT id, organization_id, team_id, team_domain, is_active, bound_at, metadata FROM slack_workspace_bindings WHERE team_id = %s;", (tid,))
                    row = cur.fetchone()
                    if row:
                        return SlackWorkspaceBinding(id=row[0], organization_id=row[1], team_id=str(row[2]), team_domain=row[3], is_active=row[4], bound_at=row[5], metadata=row[6] or {})
                    return None
        return self._bindings_by_id.get(tid)

    def get_binding_for_channel(self, channel_id: str) -> Optional[SlackWorkspaceBinding]:
        cid = str(channel_id).strip()
        db_url = os.getenv("SUPABASE_DB_URL") or os.getenv("DATABASE_URL")
        if db_url:
            import psycopg2
            with psycopg2.connect(db_url) as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT id, organization_id, team_id, team_domain, is_active, bound_at, metadata FROM slack_workspace_bindings WHERE is_active=TRUE AND metadata->'channel_ids' ? %s LIMIT 1", (cid,))
                    row = cur.fetchone()
                    if row:
                        return SlackWorkspaceBinding(id=row[0], organization_id=row[1], team_id=str(row[2]), team_domain=row[3], is_active=row[4], bound_at=row[5], metadata=row[6] or {})
                    return None
        for binding in self._bindings_by_id.values():
            if binding.is_active and cid in {str(value) for value in binding.metadata.get("channel_ids", [])}:
                return binding
        return None

    def get_organization_for_channel(self, team_id: str, channel_id: str) -> Optional[str]:
        binding = self.get_binding(team_id)
        if not binding or not binding.is_active:
            return None
        allowed_channels = binding.metadata.get("channel_ids", [])
        if not allowed_channels or str(channel_id) not in {str(value) for value in allowed_channels}:
            return None
        return binding.organization_id

    def clear(self):
        self._bindings_by_id.clear()

slack_binding_store = SlackWorkspaceBindingStore()


if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(description="Authoritative Thread Organization & Repository Binding Admin Tool")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # Bind command
    bind_parser = subparsers.add_parser("bind", help="Bind a GitHub repository to a Thread organization")
    bind_parser.add_argument("--repo-id", required=True, help="GitHub numeric repository ID (e.g. 1371393965)")
    bind_parser.add_argument("--repo-name", required=True, help="GitHub repository full name (e.g. MdTowfikomer/Thread_agent)")
    bind_parser.add_argument("--org", required=True, help="Thread organization ID (e.g. gdg_mcet)")
    bind_parser.add_argument("--installation-id", default=None, help="GitHub App installation ID (optional)")

    # List command
    subparsers.add_parser("list", help="List all active repository bindings from DB and memory")

    # Remove command
    remove_parser = subparsers.add_parser("remove", help="Remove or deactivate a repository binding")
    remove_parser.add_argument("--repo-id", required=True, help="GitHub numeric repository ID to remove")

    args = parser.parse_args()

    if args.command == "bind":
        binding = github_binding_store.register_binding(
            repository_id=args.repo_id,
            repository_name=args.repo_name,
            organization_id=args.org,
            installation_id=args.installation_id,
            is_active=True,
            metadata={"full_name": args.repo_name}
        )
        print(f"[SUCCESS] Bound repository '{binding.repository_name}' (ID: {binding.repository_id}) to organization '{binding.organization_id}'.")

    elif args.command == "list":
        db_url = os.getenv("SUPABASE_DB_URL") or os.getenv("DATABASE_URL")
        print("\n--- In-Memory Bindings ---")
        for rid, b in github_binding_store._bindings_by_id.items():
            print(f"  Repo ID: {rid} | Repo: {b.repository_name} | Org: {b.organization_id} | Active: {b.is_active}")
        if db_url:
            print("\n--- Database Bindings (PostgreSQL) ---")
            try:
                import psycopg2
                with psycopg2.connect(db_url) as conn:
                    with conn.cursor() as cur:
                        cur.execute("SELECT repository_id, repository_name, organization_id, is_active FROM github_repository_bindings ORDER BY bound_at;")
                        rows = cur.fetchall()
                        for r in rows:
                            print(f"  Repo ID: {r[0]} | Repo: {r[1]} | Org: {r[2]} | Active: {r[3]}")
            except Exception as e:
                print(f"  Error fetching from DB: {e}")

    elif args.command == "remove":
        rid = str(args.repo_id).strip()
        github_binding_store._bindings_by_id.pop(rid, None)
        db_url = os.getenv("SUPABASE_DB_URL") or os.getenv("DATABASE_URL")
        if db_url:
            try:
                import psycopg2
                with psycopg2.connect(db_url) as conn:
                    with conn.cursor() as cur:
                        cur.execute("DELETE FROM github_repository_bindings WHERE repository_id = %s;", (rid,))
                    conn.commit()
                print(f"[SUCCESS] Removed repository binding for ID '{rid}' from database and memory.")
            except Exception as e:
                print(f"[ERROR] Failed to delete from database: {e}")
                sys.exit(1)
        else:
            print(f"[SUCCESS] Removed repository binding for ID '{rid}' from memory.")
