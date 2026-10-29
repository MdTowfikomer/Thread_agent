"""Transactional service metadata repository. Production uses PostgreSQL only.

The optional DB-API connection factory is an offline test seam, never a fallback.
No credentials or connection exception details are included in API errors.
"""
from contextlib import contextmanager
import hashlib
import json
import os
import secrets
import time
import uuid

from fastapi import HTTPException


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


class TenantRepository:
    def __init__(self, connection_factory=None, *, dialect="postgres"):
        self.connection_factory = connection_factory
        self.dialect = dialect

    @property
    def configured(self):
        return bool(self.connection_factory or os.getenv("THREAD_SERVICE_DB_URL") or os.getenv("SUPABASE_DB_URL") or os.getenv("DATABASE_URL"))

    @contextmanager
    def transaction(self):
        conn = None
        try:
            if self.connection_factory:
                conn = self.connection_factory()
            else:
                import psycopg2
                url = os.getenv("THREAD_SERVICE_DB_URL") or os.getenv("SUPABASE_DB_URL") or os.getenv("DATABASE_URL")
                if not url:
                    raise HTTPException(503, "Workspace service database is not configured.")
                from app.data.postgres import connect
                conn = connect(url)
            if self.dialect == "sqlite":
                conn.execute("BEGIN IMMEDIATE")
            yield conn.cursor()
            conn.commit()
        except HTTPException:
            if conn:
                conn.rollback()
            raise
        except Exception as exc:
            if conn:
                conn.rollback()
            if getattr(exc, "pgcode", None) == "23505" or exc.__class__.__name__ == "IntegrityError":
                raise HTTPException(409, "This account or workspace already exists.") from None
            raise HTTPException(503, "Workspace service is unavailable. Check database setup and migrations.") from None
        finally:
            if conn:
                conn.close()

    def execute(self, cur, sql, params=()):
        if self.dialect == "sqlite":
            sql = sql.replace("%s", "?").replace(" FOR UPDATE", "")
        cur.execute(sql, params)
        return cur

    def one(self, cur, sql, params=()):
        self.execute(cur, sql, params)
        row = cur.fetchone()
        return dict(zip([column[0] for column in cur.description], row)) if row else None

    def many(self, cur, sql, params=()):
        self.execute(cur, sql, params)
        return [dict(zip([column[0] for column in cur.description], row)) for row in cur.fetchall()]

    def create_user(self, email, name, password_hash):
        user_id = str(uuid.uuid4())
        with self.transaction() as cur:
            self.execute(cur, "INSERT INTO thread_users(id,email,name,password_hash,created_at) VALUES (%s,%s,%s,%s,%s)",
                         (user_id, email, name, password_hash, int(time.time())))
        return {"id": user_id, "email": email, "name": name}

    def find_user(self, *, email=None, user_id=None):
        with self.transaction() as cur:
            if email is not None:
                return self.one(cur, "SELECT * FROM thread_users WHERE email=%s", (email,))
            return self.one(cur, "SELECT * FROM thread_users WHERE id=%s", (user_id,))

    def list_people(self):
        with self.transaction() as cur:
            return self.many(cur, "SELECT id,name,email FROM thread_users")

    def new_session(self, user_id):
        token = secrets.token_urlsafe(32)
        with self.transaction() as cur:
            first = self.one(cur, "SELECT organization_id FROM memberships WHERE user_id=%s ORDER BY created_at,organization_id LIMIT 1", (user_id,))
            self.execute(cur, "INSERT INTO user_sessions(token_hash,user_id,active_organization_id,expires_at) VALUES (%s,%s,%s,%s)",
                         (digest(token), user_id, first["organization_id"] if first else None, int(time.time()) + 86400))
        return token

    def session(self, token):
        if not token or len(token) > 256:
            raise HTTPException(401, "Sign in to continue.")
        with self.transaction() as cur:
            row = self.one(cur, "SELECT s.*,u.email,u.name FROM user_sessions s JOIN thread_users u ON u.id=s.user_id WHERE token_hash=%s AND expires_at>%s",
                           (digest(token), int(time.time())))
        if not row:
            raise HTTPException(401, "Session expired or revoked. Sign in again.")
        return row

    def logout(self, token):
        if token:
            with self.transaction() as cur:
                self.execute(cur, "DELETE FROM user_sessions WHERE token_hash=%s", (digest(token),))

    def _membership(self, cur, org_id, user_id):
        if not self.one(cur, "SELECT id FROM organizations WHERE id=%s", (org_id,)):
            raise HTTPException(404, "Workspace not found.")
        row = self.one(cur, "SELECT * FROM memberships WHERE organization_id=%s AND user_id=%s", (org_id, user_id))
        if not row:
            raise HTTPException(403, "You are not a member of this workspace.")
        return row

    def membership(self, org_id, user_id):
        with self.transaction() as cur:
            return self._membership(cur, org_id, user_id)

    def _admin(self, cur, org_id, user_id):
        row = self._membership(cur, org_id, user_id)
        if row["role"] not in ("owner", "admin"):
            raise HTTPException(403, "Workspace administrator access is required.")
        return row

    def organizations(self, user_id):
        with self.transaction() as cur:
            return self.many(cur, "SELECT o.*,m.role FROM organizations o JOIN memberships m ON m.organization_id=o.id WHERE m.user_id=%s ORDER BY o.created_at,o.id", (user_id,))

    def create_organization(self, user_id, org_id, name, description, session_hash):
        with self.transaction() as cur:
            self.execute(cur, "INSERT INTO organizations(id,name,description,created_at) VALUES (%s,%s,%s,%s)", (org_id, name, description, int(time.time())))
            self.execute(cur, "INSERT INTO memberships(id,user_id,organization_id,role,created_at) VALUES (%s,%s,%s,'owner',%s)",
                         (str(uuid.uuid4()), user_id, org_id, int(time.time())))
            self.execute(cur, "INSERT INTO assistant_configurations(organization_id) VALUES (%s)", (org_id,))
            self.execute(cur, "UPDATE user_sessions SET active_organization_id=%s WHERE token_hash=%s AND user_id=%s", (org_id, session_hash, user_id))
        return {"id": org_id, "name": name, "description": description, "role": "owner"}

    def switch(self, org_id, user_id, session_hash):
        with self.transaction() as cur:
            self._membership(cur, org_id, user_id)
            self.execute(cur, "UPDATE user_sessions SET active_organization_id=%s WHERE token_hash=%s AND user_id=%s", (org_id, session_hash, user_id))

    def workspace(self, org_id):
        with self.transaction() as cur:
            row = self.one(cur, "SELECT o.*,a.default_agent_name,a.system_prompt,a.configured_roles FROM organizations o JOIN assistant_configurations a ON a.organization_id=o.id WHERE o.id=%s", (org_id,))
        if not row:
            raise HTTPException(404, "Workspace not found.")
        if isinstance(row["configured_roles"], str):
            row["configured_roles"] = json.loads(row["configured_roles"])
        return row

    def update_workspace(self, org_id, user_id, name, description, config):
        with self.transaction() as cur:
            self.execute(cur, "SELECT id FROM organizations WHERE id=%s FOR UPDATE", (org_id,))
            self._admin(cur, org_id, user_id)
            self.execute(cur, "UPDATE organizations SET name=%s,description=%s WHERE id=%s", (name, description, org_id))
            self.execute(cur, "UPDATE assistant_configurations SET default_agent_name=%s,system_prompt=%s,configured_roles=%s WHERE organization_id=%s",
                         (config["default_agent_name"], config["system_prompt"], json.dumps(config["configured_roles"]), org_id))

    def members(self, org_id, user_id):
        with self.transaction() as cur:
            self._membership(cur, org_id, user_id)
            return self.many(cur, "SELECT u.id,u.email,u.name,m.role FROM memberships m JOIN thread_users u ON u.id=m.user_id WHERE m.organization_id=%s ORDER BY m.created_at,u.id", (org_id,))

    def invite(self, org_id, user_id, email, role):
        token = secrets.token_urlsafe(32)
        with self.transaction() as cur:
            self.execute(cur, "SELECT id FROM organizations WHERE id=%s FOR UPDATE", (org_id,))
            actor = self._admin(cur, org_id, user_id)
            if role == "admin" and actor["role"] != "owner":
                raise HTTPException(403, "Only the owner may invite administrators.")
            self.execute(cur, "UPDATE invitations SET status='revoked' WHERE organization_id=%s AND email=%s AND status='pending'", (org_id, email))
            self.execute(cur, "INSERT INTO invitations(id,organization_id,email,role,token_hash,expires_at,status,created_by) VALUES (%s,%s,%s,%s,%s,%s,'pending',%s)",
                         (str(uuid.uuid4()), org_id, email, role, digest(token), int(time.time()) + 604800, user_id))
        return token

    def accept(self, token, user_id, email):
        with self.transaction() as cur:
            # Lock workspace before invitation to use the same lock order as invite/remove.
            lookup = self.one(cur, "SELECT organization_id FROM invitations WHERE token_hash=%s", (digest(token),))
            if not lookup:
                raise HTTPException(404, "Invitation not found.")
            org_id = lookup["organization_id"]
            self.execute(cur, "SELECT id FROM organizations WHERE id=%s FOR UPDATE", (org_id,))
            invitation = self.one(cur, "SELECT * FROM invitations WHERE token_hash=%s FOR UPDATE", (digest(token),))
            if invitation["status"] != "pending" or invitation["expires_at"] <= int(time.time()):
                raise HTTPException(410, "Invitation expired or already used.")
            if invitation["email"] != email:
                raise HTTPException(403, "Sign in with the email address on this invitation.")
            # Recheck issuer authority; stale invitations cannot restore removed privileges.
            issuer = self._admin(cur, org_id, invitation["created_by"])
            if invitation["role"] == "admin" and issuer["role"] != "owner":
                raise HTTPException(403, "Invitation issuer no longer has authority.")
            self.execute(cur, "INSERT INTO memberships(id,user_id,organization_id,role,created_at) VALUES (%s,%s,%s,%s,%s) ON CONFLICT (user_id,organization_id) DO NOTHING",
                         (str(uuid.uuid4()), user_id, org_id, invitation["role"], int(time.time())))
            self.execute(cur, "UPDATE invitations SET status='accepted' WHERE id=%s", (invitation["id"],))
        return org_id

    def change_member(self, org_id, actor_id, target_id, role=None, *, remove=False):
        with self.transaction() as cur:
            # Serialize membership mutations, including transfers, on the workspace row.
            self.execute(cur, "SELECT id FROM organizations WHERE id=%s FOR UPDATE", (org_id,))
            actor = self._admin(cur, org_id, actor_id)
            target = self._membership(cur, org_id, target_id)
            if target["role"] == "owner":
                raise HTTPException(409, "Transfer ownership to another member before removing or demoting the owner.")
            if actor["role"] != "owner" and (target["role"] != "member" or role not in (None, "member")):
                raise HTTPException(403, "Only the owner may manage administrator roles or transfer ownership.")
            if remove:
                self.execute(cur, "DELETE FROM memberships WHERE id=%s", (target["id"],))
                self.execute(cur, "UPDATE invitations SET status='revoked' WHERE organization_id=%s AND (email=(SELECT email FROM thread_users WHERE id=%s) OR created_by=%s) AND status='pending'", (org_id, target_id, target_id))
            else:
                if role == "owner":
                    self.execute(cur, "UPDATE memberships SET role='admin' WHERE id=%s", (actor["id"],))
                self.execute(cur, "UPDATE memberships SET role=%s WHERE id=%s", (role, target["id"]))


tenant_repository = TenantRepository()
