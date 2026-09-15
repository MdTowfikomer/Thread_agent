import os
import json
import logging
from collections import defaultdict, deque
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional

from app.core.config import settings

logger = logging.getLogger("thread.conversation")

class ConversationTurnStore:
    """
    Durable and cached multi-turn conversation memory store.
    Persists user queries and assistant responses to 'conversation_turns' table in PostgreSQL/Supabase,
    providing sliding-window conversational context across Slack, Discord, and Telegram.
    """
    def __init__(self, max_cached_turns: int = 20):
        self._max_cached = max_cached_turns
        self._memory_cache: Dict[str, deque] = defaultdict(lambda: deque(maxlen=self._max_cached))

    @staticmethod
    def format_session_key(platform: str, channel_id: str, user_or_thread_id: str) -> str:
        """
        Generate deterministic session identifier.
        e.g. 'discord:123456:987654', 'telegram:-100123:554433', 'slack:C123:1710000000.12'
        """
        plat = str(platform).lower().replace("channeltype.", "")
        return f"{plat}:{channel_id}:{user_or_thread_id}"

    def record_turn(
        self,
        session_key: str,
        platform: str,
        organization_id: str,
        initiating_user_id: str,
        role: str,
        content: str
    ) -> None:
        """
        Record a conversation turn for both persistent storage and immediate memory window.
        """
        if role not in ("user", "assistant", "system"):
            raise ValueError(f"Invalid conversation role: {role}")

        turn_data = {
            "role": role,
            "content": content,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        # In-memory buffer
        self._memory_cache[session_key].append(turn_data)

        # Durable PostgreSQL write
        db_url = os.getenv("SUPABASE_DB_URL") or os.getenv("DATABASE_URL")
        if db_url:
            try:
                import psycopg2
                with psycopg2.connect(db_url) as conn:
                    with conn.cursor() as cur:
                        cur.execute("""
                            INSERT INTO conversation_turns (
                                session_key, platform, organization_id, initiating_user_id, role, content, created_at
                            ) VALUES (%s, %s, %s, %s, %s, %s, %s);
                        """, (
                            session_key,
                            str(platform).lower().replace("channeltype.", ""),
                            organization_id,
                            initiating_user_id,
                            role,
                            content,
                            datetime.now(timezone.utc),
                        ))
                    conn.commit()
            except Exception as e:
                logger.warning(f"Could not persist conversation turn to DB: {e}")

    def get_recent_turns(self, session_key: str, limit: int = 10) -> List[Dict[str, str]]:
        """
        Fetch the most recent turns in chronological order for LLM context window.
        Returns: [{'role': 'user', 'content': '...'}, {'role': 'assistant', 'content': '...'}]
        """
        db_url = os.getenv("SUPABASE_DB_URL") or os.getenv("DATABASE_URL")
        if db_url:
            try:
                import psycopg2
                with psycopg2.connect(db_url) as conn:
                    with conn.cursor() as cur:
                        cur.execute("""
                            SELECT role, content
                            FROM (
                                SELECT role, content, created_at
                                FROM conversation_turns
                                WHERE session_key = %s
                                ORDER BY created_at DESC
                                LIMIT %s
                            ) sub
                            ORDER BY created_at ASC;
                        """, (session_key, limit))
                        rows = cur.fetchall()
                        if rows:
                            return [{"role": r[0], "content": r[1]} for r in rows]
            except Exception as e:
                logger.warning(f"Failed to query conversation_turns from DB: {e}")

        # Fallback to memory cache
        cached = list(self._memory_cache.get(session_key, []))
        return [{"role": t["role"], "content": t["content"]} for t in cached[-limit:]]

    def clear_session(self, session_key: str) -> None:
        """Clear cached session turns."""
        if session_key in self._memory_cache:
            del self._memory_cache[session_key]


conversation_store = ConversationTurnStore()
