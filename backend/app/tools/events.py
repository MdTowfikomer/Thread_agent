import os
import json
import logging
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional

from app.core.config import settings

logger = logging.getLogger("thread.tools.events")

class EventAssistant:
    """
    Authoritative Community Event Assistant tool.
    Strictly queries published community events from Supabase PostgreSQL.
    CRITICAL RULE: Never fabricates or seeds mock events. Fails closed with
    'no published events' when the database contains no verified events.
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
            logger.warning(f"Failed to connect to database for events: {e}")
            return None

    def list_upcoming_events(self, org_id: str = "gdg_mcet", limit: int = 5) -> List[Dict[str, Any]]:
        """
        Fetch upcoming published events for the organization strictly from the database.
        Returns an empty list if none exist or if database is unreachable (fail-closed).
        """
        conn = self._get_db_conn()
        if not conn:
            logger.warning("Event lookup failed closed: Database unreachable.")
            return []

        try:
            with conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT id, title, description, start_time, end_time, location_or_url, rsvp_url, speakers, status
                        FROM community_events
                        WHERE organization_id = %s
                          AND status IN ('upcoming', 'in_progress')
                          AND start_time >= NOW() - INTERVAL '1 day'
                        ORDER BY start_time ASC
                        LIMIT %s;
                    """, (org_id, limit))
                    rows = cur.fetchall()
                    events = []
                    for r in rows:
                        speakers_raw = r[7]
                        if isinstance(speakers_raw, list):
                            speakers = speakers_raw
                        elif isinstance(speakers_raw, str):
                            try:
                                speakers = json.loads(speakers_raw)
                            except Exception:
                                speakers = []
                        else:
                            speakers = []

                        events.append({
                            "id": str(r[0]),
                            "title": r[1],
                            "description": r[2],
                            "start_time": r[3],
                            "end_time": r[4],
                            "location_or_url": r[5],
                            "rsvp_url": r[6],
                            "speakers": speakers,
                            "status": r[8]
                        })
                    return events
        except Exception as e:
            logger.error(f"Failed to query community_events: {e}")
            return []
        finally:
            try:
                conn.close()
            except Exception:
                pass

    def create_event(
        self,
        org_id: str,
        title: str,
        start_time: datetime,
        end_time: Optional[datetime] = None,
        description: Optional[str] = None,
        location_or_url: Optional[str] = None,
        rsvp_url: Optional[str] = None,
        speakers: Optional[List[str]] = None,
        status: str = "upcoming"
    ) -> Optional[Dict[str, Any]]:
        """
        Persist a verified community event into the database.
        Must only be called by authorized organizational organizers.
        """
        conn = self._get_db_conn()
        if not conn:
            raise RuntimeError("Database unavailable for event creation.")

        try:
            with conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        INSERT INTO community_events (
                            organization_id, title, description, start_time, end_time,
                            location_or_url, rsvp_url, speakers, status
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s)
                        RETURNING id, title, start_time;
                    """, (
                        org_id,
                        title.strip(),
                        description.strip() if description else None,
                        start_time,
                        end_time,
                        location_or_url.strip() if location_or_url else None,
                        rsvp_url.strip() if rsvp_url else None,
                        json.dumps(speakers or []),
                        status
                    ))
                    row = cur.fetchone()
                    return {"id": str(row[0]), "title": row[1], "start_time": row[2]}
        finally:
            try:
                conn.close()
            except Exception:
                pass

    def format_events_response(self, events: List[Dict[str, Any]]) -> str:
        """
        Format published events into clean markdown. Fails closed with
        'no published events' when none exist.
        """
        if not events:
            return (
                "📅 **Community Events**\n\n"
                "There are currently no published events scheduled for GDG MCET.\n"
                "Stay tuned to this channel for future workshop and hackathon announcements!"
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
