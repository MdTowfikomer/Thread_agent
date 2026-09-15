import os
import json
import logging
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any, Optional

from app.core.config import settings

logger = logging.getLogger("thread.tools.events")

INITIAL_EVENTS = [
    {
        "title": "GDG MCET Agentic AI Hackathon 2026",
        "description": "Build autonomous agents, multi-agent workflows, and collaborative tools using Gemini 2.5 Flash and LangGraph.",
        "start_time": (datetime.now(timezone.utc) + timedelta(days=7)).replace(hour=4, minute=0, second=0, microsecond=0),
        "end_time": (datetime.now(timezone.utc) + timedelta(days=8)).replace(hour=12, minute=0, second=0, microsecond=0),
        "location_or_url": "MCET Tech Hub / Virtual",
        "rsvp_url": "https://gdg.community.dev/events/details/developer-student-clubs-dr-mahalingam-college-of-engineering-and-technology-pollachi-presents-agentic-ai-hackathon/",
        "speakers": ["Google Developer Experts", "Core Tech Leads"],
        "status": "upcoming"
    },
    {
        "title": "Open Source Git & GitHub Hands-on Workshop",
        "description": "Master branching strategies, PR etiquette, automated CI/CD checks, and contribute to the open-source Thread Agent project.",
        "start_time": (datetime.now(timezone.utc) + timedelta(days=14)).replace(hour=8, minute=30, second=0, microsecond=0),
        "end_time": (datetime.now(timezone.utc) + timedelta(days=14)).replace(hour=11, minute=30, second=0, microsecond=0),
        "location_or_url": "MCET Computer Lab 3 & Discord Voice",
        "rsvp_url": "https://gdg.community.dev/events/mcet-git-github-workshop/",
        "speakers": ["Towfik Omer (Lead)", "Tech Team"],
        "status": "upcoming"
    },
    {
        "title": "Cloud, Microservices & Docker BootCamp",
        "description": "Deep dive into containerizing backend applications, PostgreSQL pgvector setup, and deploying with zero-downtime.",
        "start_time": (datetime.now(timezone.utc) + timedelta(days=25)).replace(hour=4, minute=0, second=0, microsecond=0),
        "end_time": (datetime.now(timezone.utc) + timedelta(days=25)).replace(hour=10, minute=0, second=0, microsecond=0),
        "location_or_url": "Main Campus Auditorium",
        "rsvp_url": "https://gdg.community.dev/events/mcet-cloud-docker-bootcamp/",
        "speakers": ["Cloud Architects", "DevOps Specialists"],
        "status": "upcoming"
    }
]

class EventAssistant:
    """
    Community Event Assistant tool.
    Allows community members across Slack, Discord, and Telegram to discover upcoming
    workshops, hackathons, speaker sessions, and RSVP links.
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
            logger.warning(f"Failed to connect to database for events: {e}")
            return None

    def _ensure_seeded(self) -> None:
        """Seed initial events if table is empty."""
        conn = self._get_db_conn()
        if not conn:
            self._cache = list(INITIAL_EVENTS)
            return

        try:
            with conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT count(*) FROM community_events;")
                    count = cur.fetchone()[0]
                    if count == 0:
                        for ev in INITIAL_EVENTS:
                            cur.execute("""
                                INSERT INTO community_events (
                                    organization_id, title, description, start_time, end_time,
                                    location_or_url, rsvp_url, speakers, status
                                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s);
                            """, (
                                "gdg_mcet",
                                ev["title"],
                                ev["description"],
                                ev["start_time"],
                                ev["end_time"],
                                ev["location_or_url"],
                                ev["rsvp_url"],
                                json.dumps(ev["speakers"]),
                                ev["status"],
                            ))
        except Exception as e:
            logger.warning(f"Error seeding events: {e}")
            self._cache = list(INITIAL_EVENTS)
        finally:
            try:
                conn.close()
            except Exception:
                pass

    def list_upcoming_events(self, org_id: str = "gdg_mcet", limit: int = 5) -> List[Dict[str, Any]]:
        """Fetch upcoming events for organization."""
        conn = self._get_db_conn()
        if not conn:
            return self._cache[:limit]

        try:
            with conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT id, title, description, start_time, end_time, location_or_url, rsvp_url, speakers, status
                        FROM community_events
                        WHERE organization_id = %s
                          AND status IN ('upcoming', 'in_progress')
                        ORDER BY start_time ASC
                        LIMIT %s;
                    """, (org_id, limit))
                    rows = cur.fetchall()
                    if rows:
                        events = []
                        for r in rows:
                            events.append({
                                "id": str(r[0]),
                                "title": r[1],
                                "description": r[2],
                                "start_time": r[3],
                                "end_time": r[4],
                                "location_or_url": r[5],
                                "rsvp_url": r[6],
                                "speakers": r[7] if isinstance(r[7], list) else (json.loads(r[7]) if r[7] else []),
                                "status": r[8]
                            })
                        return events
        except Exception as e:
            logger.warning(f"Failed to query community_events: {e}")
        finally:
            try:
                conn.close()
            except Exception:
                pass

        return self._cache[:limit]

    def format_events_response(self, events: List[Dict[str, Any]]) -> str:
        """Format events list into a clear markdown response."""
        if not events:
            return (
                "📅 **Upcoming Community Events**\n\n"
                "There are no upcoming events scheduled at this moment. Stay tuned for announcements in our community channels!"
            )

        lines = ["📅 **Upcoming Community Events for GDG MCET:**\n"]
        for idx, ev in enumerate(events, 1):
            st = ev.get("start_time")
            if isinstance(st, datetime):
                date_str = st.strftime("%A, %b %d, %Y at %I:%M %p UTC")
            else:
                date_str = str(st)

            lines.append(f"### {idx}. {ev.get('title')}")
            lines.append(f"⏱ **When**: {date_str}")
            if ev.get("location_or_url"):
                lines.append(f"📍 **Where**: {ev.get('location_or_url')}")
            if ev.get("description"):
                lines.append(f"ℹ️ **About**: {ev.get('description')}")
            speakers = ev.get("speakers")
            if speakers:
                lines.append(f"🎙 **Speakers / Hosts**: {', '.join(speakers)}")
            if ev.get("rsvp_url"):
                lines.append(f"🔗 **RSVP Link**: [Register Here]({ev.get('rsvp_url')})")
            lines.append("")

        lines.append("*(Type `!events` anytime to get the latest schedule!)*")
        return "\n".join(lines)


event_assistant = EventAssistant()
