import os
import json
import logging
from typing import List, Dict, Any, Optional

from app.core.config import settings

logger = logging.getLogger("thread.tools.resources")

INITIAL_RESOURCES = [
    {
        "category": "Contribution",
        "title": "Contributing to Thread Agent",
        "url": "https://github.com/MdTowfikomer/Thread_agent",
        "description": "Comprehensive guide for setting up local virtualenv, running tests with pytest, adhering to permission policies, and opening pull requests.",
        "tags": ["github", "contribution", "setup", "developer", "git"]
    },
    {
        "category": "Community",
        "title": "GDG MCET Community Guidelines & Discord Etiquette",
        "url": "https://discord.gg/gdgmcet",
        "description": "Code of conduct, channel etiquette, bot interaction rules, and team lead contacts.",
        "tags": ["rules", "conduct", "community", "discord"]
    },
    {
        "category": "AI & Learning",
        "title": "Google DeepMind Agentic AI & Gemini Roadmap",
        "url": "https://developers.google.com",
        "description": "Learning path and tutorials for LangGraph, Gemini 2.5 Flash, multi-agent synthesis, and pgvector RAG systems.",
        "tags": ["ai", "gemini", "langgraph", "rag", "roadmap"]
    },
    {
        "category": "FAQ",
        "title": "How do I link my Discord and Telegram accounts?",
        "url": None,
        "description": "Run `!link` on one platform to generate an account link token. Then send `!link <token>` on the other platform to merge your community profile.",
        "tags": ["faq", "account", "link", "identity", "discord", "telegram"]
    },
    {
        "category": "FAQ",
        "title": "How does Thread Agent search old discussions and team records?",
        "url": None,
        "description": "Tag the agent with your inquiry. It runs a hybrid search combining dense pgvector cosine similarity with PostgreSQL full-text search (RRF) while strictly verifying pre-retrieval Access Control Lists (ACL).",
        "tags": ["faq", "search", "rag", "retrieval", "privacy"]
    }
]

class ResourceAssistant:
    """
    Community Resource and FAQ Lookup Tool.
    Allows community members across Slack, Discord, and Telegram to find documentation,
    contribution guides, official links, and answers to common community questions.
    """
    def __init__(self):
        self._cache: List[Dict[str, Any]] = []
        self._ensure_seeded()

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

    def _ensure_seeded(self) -> None:
        """Seed initial community resources and FAQs if table is empty."""
        conn = self._get_db_conn()
        if not conn:
            self._cache = list(INITIAL_RESOURCES)
            return

        try:
            with conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT count(*) FROM community_resources;")
                    count = cur.fetchone()[0]
                    if count == 0:
                        for res in INITIAL_RESOURCES:
                            cur.execute("""
                                INSERT INTO community_resources (
                                    organization_id, category, title, url, description, tags, permission_scope
                                ) VALUES (%s, %s, %s, %s, %s, %s, %s);
                            """, (
                                "gdg_mcet",
                                res["category"],
                                res["title"],
                                res.get("url"),
                                res["description"],
                                res.get("tags", []),
                                "PUBLIC_COMMUNITY",
                            ))
        except Exception as e:
            logger.warning(f"Error seeding resources: {e}")
            self._cache = list(INITIAL_RESOURCES)
        finally:
            try:
                conn.close()
            except Exception:
                pass

    def search_resources(
        self,
        query: str = "",
        org_id: str = "gdg_mcet",
        category: Optional[str] = None,
        limit: int = 5
    ) -> List[Dict[str, Any]]:
        """Search community resources by keyword, category, or tags."""
        conn = self._get_db_conn()
        if not conn:
            results = []
            q_lower = query.lower()
            for r in self._cache:
                if category and r.get("category", "").lower() != category.lower():
                    continue
                if not query or q_lower in r["title"].lower() or q_lower in r["description"].lower() or any(q_lower in t.lower() for t in r.get("tags", [])):
                    results.append(r)
            return results[:limit]

        try:
            with conn:
                with conn.cursor() as cur:
                    if query and category:
                        cur.execute("""
                            SELECT id, category, title, url, description, tags
                            FROM community_resources
                            WHERE organization_id = %s
                              AND LOWER(category) = LOWER(%s)
                              AND (title ILIKE %s OR description ILIKE %s OR %s = ANY(tags))
                            LIMIT %s;
                        """, (org_id, category, f"%{query}%", f"%{query}%", query.lower(), limit))
                    elif category:
                        cur.execute("""
                            SELECT id, category, title, url, description, tags
                            FROM community_resources
                            WHERE organization_id = %s
                              AND LOWER(category) = LOWER(%s)
                            LIMIT %s;
                        """, (org_id, category, limit))
                    elif query:
                        cur.execute("""
                            SELECT id, category, title, url, description, tags
                            FROM community_resources
                            WHERE organization_id = %s
                              AND (title ILIKE %s OR description ILIKE %s OR %s = ANY(tags))
                            LIMIT %s;
                        """, (org_id, f"%{query}%", f"%{query}%", query.lower(), limit))
                    else:
                        cur.execute("""
                            SELECT id, category, title, url, description, tags
                            FROM community_resources
                            WHERE organization_id = %s
                            LIMIT %s;
                        """, (org_id, limit))

                    rows = cur.fetchall()
                    if rows:
                        resources = []
                        for r in rows:
                            resources.append({
                                "id": str(r[0]),
                                "category": r[1],
                                "title": r[2],
                                "url": r[3],
                                "description": r[4],
                                "tags": r[5] or []
                            })
                        return resources
        except Exception as e:
            logger.warning(f"Failed to query community_resources: {e}")
        finally:
            try:
                conn.close()
            except Exception:
                pass

        return []

    def format_resources_response(self, resources: List[Dict[str, Any]]) -> str:
        """Format resources and FAQs into a clean markdown reply."""
        if not resources:
            return (
                "📚 **Community Resources & FAQs**\n\n"
                "No matching resources or FAQs found for your query. Try searching with a different keyword or type `!faq` to see common questions!"
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
