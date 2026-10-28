import os
import json
import logging
from fastapi import HTTPException
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any, Optional

from app.core.config import settings
from app.core.canonical import AccessContext, PermissionLevel

logger = logging.getLogger("thread.tools.summarizer")

DEFAULT_SUMMARY_WINDOW_HOURS = 48


class SummarizerAssistant:
    """
    Channel and discussion summarizer tool (!summary).
    Summarizes the last 24–48 hours of authorized human channel discussions from
    'source_records', strictly filtered by the requester's authorized AccessContext scopes.
    
    SECURITY & INTEGRITY GUARANTEES:
    1. Pre-Retrieval ACL: Only messages with permissions matching access_context.allowed_scopes
       are retrievable. Public users cannot summarize internal discussions.
    2. Real-Data Grounding: Analyzes real ingested messages within the time window.
    3. Fails Closed: Emits 'no discussion found' if no authorized messages exist.
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
            logger.error(f"Summarizer database connection failed: {e}")
            return None

    def fetch_channel_messages(
        self,
        organization_id: str,
        channel_id: str,
        platform: Optional[str] = None,
        access_context: Optional[AccessContext] = None,
        window_hours: int = DEFAULT_SUMMARY_WINDOW_HOURS,
        limit: int = 50
    ) -> List[Dict[str, Any]]:
        """
        Fetch ingested channel messages from the last window_hours strictly scoped by ACL.
        """
        conn = self._get_db_conn()
        if not conn:
            return []

        if access_context and access_context.allowed_scopes:
            allowed_scopes = [s.value if hasattr(s, "value") else str(s) for s in access_context.allowed_scopes]
        else:
            allowed_scopes = [PermissionLevel.PUBLIC_COMMUNITY.value]

        try:
            with conn:
                with conn.cursor() as cur:
                    chan_str = str(channel_id).strip()
                    like_pattern = f"%/{chan_str}/%"

                    cur.execute("""
                        SELECT author_name, raw_content, timestamp, permission, source_type
                        FROM source_records
                        WHERE organization_id = %s
                          AND permission = ANY(%s)
                          AND timestamp >= NOW() - (%s * INTERVAL '1 hour')
                          AND (
                              metadata->>'channel_id' = %s
                              OR metadata->>'chat_id' = %s
                              OR source_uri ILIKE %s
                              OR external_id = %s
                          )
                        ORDER BY timestamp ASC
                        LIMIT %s;
                    """, (organization_id, allowed_scopes, window_hours, chan_str, chan_str, like_pattern, chan_str, limit))

                    rows = cur.fetchall()
                    messages = []
                    for r in rows:
                        messages.append({
                            "author": r[0],
                            "content": r[1],
                            "timestamp": r[2],
                            "permission": r[3],
                            "source_type": r[4]
                        })
                    return messages
        except Exception as e:
            logger.error(f"Failed to fetch channel messages for summary: {e}")
            return []
        finally:
            try:
                conn.close()
            except Exception:
                pass

    def summarize_channel_discussion(
        self,
        organization_id: str,
        channel_id: str,
        platform: str = "discord",
        access_context: Optional[AccessContext] = None,
        window_hours: int = DEFAULT_SUMMARY_WINDOW_HOURS
    ) -> str:
        """
        Summarize authorized channel messages from the last 24-48 hours.
        """
        messages = self.fetch_channel_messages(
            organization_id=organization_id,
            channel_id=channel_id,
            platform=platform,
            access_context=access_context,
            window_hours=window_hours
        )

        if not messages:
            return (
                f"**Channel Discussion Summary (Past {window_hours}h)**\n\n"
                f"No authorized channel discussion was found within the last {window_hours} hours to summarize.\n"
                f"Once team members exchange messages in this channel, use `!summary` for a structured recap!"
            )

        # Build transcript of human discussion
        transcript_lines = []
        for m in messages:
            ts = m["timestamp"].strftime("%b %d, %H:%M UTC") if isinstance(m["timestamp"], datetime) else str(m["timestamp"])
            transcript_lines.append(f"[{ts}] {m['author']}: {m['content']}")
        transcript = "\n".join(transcript_lines)

        from app.graph.workflow import get_llm, invoke_llm_with_fallback
        from app.tenancy.repository import tenant_repository
        from app.tenancy.auth import TenantContext
        from app.core.organizations import get_workspace
        tenant_context = None
        if tenant_repository.configured:
            tenant_context = TenantContext(organization_id, access_context.user_id if access_context else "anon", access_context.role_id if access_context else "member")
        llm = get_llm(tenant_context) if tenant_context else get_llm()
        if llm:
            prompt = f"""You are an executive conversation summarizer for {get_workspace(organization_id).name}.
Analyze the following authentic channel discussion from the past {window_hours} hours.
Produce a structured Markdown summary strictly based on the transcript below.

Include:
- **Main Topics Discussed** (1-3 clear bullet points)
- **Key Decisions & Takeaways** (1-3 clear bullet points)
- **Next Steps / Action Items** (if applicable)

CRITICAL RULES:
- Only summarize facts, names, and topics present in the transcript. Never invent or hallucinate discussion points.
- Keep the tone objective and executive.

Channel Discussion Transcript ({len(messages)} messages):
{transcript}
"""
            try:
                content = invoke_llm_with_fallback(llm, prompt, tenant_context=tenant_context)
                if content:
                    return f"**Channel Discussion Summary (Past {window_hours}h — {len(messages)} messages):**\n\n{content}"
            except HTTPException:
                raise
            except Exception:
                logger.warning("LLM summarization failed; provider details withheld.")

        # Deterministic fallback summary
        first_author = messages[0]["author"]
        last_author = messages[-1]["author"]
        return (
            f"**Channel Discussion Summary (Past {window_hours}h — {len(messages)} messages):**\n\n"
            f"- **Recent Activity**: {len(messages)} messages recorded between {messages[0]['timestamp']} and {messages[-1]['timestamp']}.\n"
            f"- **Active Participants**: {', '.join(sorted(set(m['author'] for m in messages))[:5])}\n"
            f"- **Latest Update**: {last_author} said: \"{messages[-1]['content'][:120]}...\""
        )


summarizer_assistant = SummarizerAssistant()
