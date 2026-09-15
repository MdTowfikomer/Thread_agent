import os
import json
import logging
from typing import List, Dict, Any, Optional

from app.core.config import settings
from app.core.canonical import AccessContext, PermissionLevel

logger = logging.getLogger("thread.tools.resources")

class ResourceAssistant:
    """
    Authoritative Community Resource and FAQ Lookup Tool.
    Strictly filters records by requester's authorized AccessContext permission scopes.
    CRITICAL SECURITY GUARANTEES:
    1. ZERO DATA LEAKAGE: Evaluates permission_scope in SQL before returning rows.
       A public community member can NEVER receive INTERNAL_CORE or PENDING_REVIEW resources.
    2. ZERO FABRICATION: Never seeds or returns mock/synthetic data.
    """
    def __init__(self):
        pass

    def _get_db_conn(self):
        db_url = os.getenv("SUPABASE_DB_URL") or os.getenv("DATABASE_URL")
        if not db_url:
            return None
        try:
            import psycopg2
            return psycopg2.connect(db_url)
        except Exception as e:
            logger.warning(f"Failed to connect to database for resources: {e}")
            return None

    def search_resources(
        self,
        query: str = "",
        org_id: str = "gdg_mcet",
        category: Optional[str] = None,
        access_context: Optional[AccessContext] = None,
        limit: int = 5
    ) -> List[Dict[str, Any]]:
        """
        Search community resources strictly filtered by requester's allowed scopes.
        Fails closed with empty list if database is unreachable.
        """
        conn = self._get_db_conn()
        if not conn:
            logger.warning("Resource lookup failed closed: Database unreachable.")
            return []

        # Enforce pre-retrieval allowed scopes
        if access_context and access_context.allowed_scopes:
            allowed_scopes = [s.value if hasattr(s, "value") else str(s) for s in access_context.allowed_scopes]
        else:
            allowed_scopes = [PermissionLevel.PUBLIC_COMMUNITY.value]

        try:
            with conn:
                with conn.cursor() as cur:
                    base_sql = """
                        SELECT id, category, title, url, description, tags, permission_scope
                        FROM community_resources
                        WHERE organization_id = %s
                          AND permission_scope = ANY(%s)
                    """
                    params = [org_id, allowed_scopes]

                    if category:
                        base_sql += " AND LOWER(category) = LOWER(%s)"
                        params.append(category)

                    if query.strip():
                        base_sql += " AND (title ILIKE %s OR description ILIKE %s OR %s = ANY(tags))"
                        q_like = f"%{query.strip()}%"
                        params.extend([q_like, q_like, query.strip().lower()])

                    base_sql += " ORDER BY created_at DESC LIMIT %s;"
                    params.append(limit)

                    cur.execute(base_sql, tuple(params))
                    rows = cur.fetchall()
                    resources = []
                    for r in rows:
                        resources.append({
                            "id": str(r[0]),
                            "category": r[1],
                            "title": r[2],
                            "url": r[3],
                            "description": r[4],
                            "tags": r[5] or [],
                            "permission_scope": r[6]
                        })
                    return resources
        except Exception as e:
            logger.error(f"Failed to query community_resources: {e}")
            return []
        finally:
            try:
                conn.close()
            except Exception:
                pass

    def add_resource(
        self,
        org_id: str,
        category: str,
        title: str,
        description: str,
        url: Optional[str] = None,
        tags: Optional[List[str]] = None,
        permission_scope: PermissionLevel = PermissionLevel.PUBLIC_COMMUNITY
    ) -> Optional[Dict[str, Any]]:
        """
        Persist a verified resource into the database with explicit permission scope.
        """
        conn = self._get_db_conn()
        if not conn:
            raise RuntimeError("Database unavailable for resource insertion.")

        try:
            with conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        INSERT INTO community_resources (
                            organization_id, category, title, url, description, tags, permission_scope
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                        RETURNING id, title, permission_scope;
                    """, (
                        org_id,
                        category.strip(),
                        title.strip(),
                        url.strip() if url else None,
                        description.strip(),
                        tags or [],
                        permission_scope.value if hasattr(permission_scope, "value") else str(permission_scope)
                    ))
                    row = cur.fetchone()
                    return {"id": str(row[0]), "title": row[1], "permission_scope": row[2]}
        finally:
            try:
                conn.close()
            except Exception:
                pass

    def format_resources_response(self, resources: List[Dict[str, Any]]) -> str:
        """
        Format resources into clean markdown. Fails closed when none found.
        """
        if not resources:
            return (
                "📚 **Community Resources & FAQs**\n\n"
                "No published resources or FAQs found matching your inquiry within your authorized scope.\n"
                "Contact a community lead or check back later for updates."
            )

        lines = ["📚 **Community Resources & Helpful Guides for GDG MCET:**\n"]
        for idx, item in enumerate(resources, 1):
            category = item.get("category", "General")
            title = item.get("title")
            url = item.get("url")
            desc = item.get("description")

            lines.append(f"### {idx}. [{category}] {title}")
            lines.append(f"📝 {desc}")
            if url:
                lines.append(f"🔗 [Link / Documentation]({url})")
            lines.append("")

        lines.append("*(Type `!faq` or `!resources <keyword>` anytime!)*")
        return "\n".join(lines)


resource_assistant = ResourceAssistant()
