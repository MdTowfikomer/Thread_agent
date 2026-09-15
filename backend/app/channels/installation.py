import os
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
        try:
            from app.core.config import settings
            for gid in settings.discord_allowed_guild_ids:
                self.register_installation(
                    guild_id=gid,
                    organization_id="gdg_mcet",
                    guild_name=f"Discord Guild {gid}"
                )
        except Exception:
            pass

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

