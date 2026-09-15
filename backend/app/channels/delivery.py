import os
import logging
from typing import Optional, Set
from datetime import datetime, timezone, timedelta

logger = logging.getLogger("thread.channels.delivery")

class WebhookDeliveryStore:
    """
    Replay protection store for webhook deliveries (e.g. X-GitHub-Delivery).
    Deduplicates events in-memory and persists to Supabase processed_webhook_deliveries.
    """
    def __init__(self):
        self._processed: Set[str] = set()

    def is_processed(self, delivery_id: str) -> bool:
        if not delivery_id:
            return False
        if delivery_id in self._processed:
            return True

        db_url = os.getenv("SUPABASE_DB_URL") or os.getenv("DATABASE_URL")
        if db_url:
            try:
                import psycopg2
                with psycopg2.connect(db_url) as conn:
                    with conn.cursor() as cur:
                        cur.execute(
                            "SELECT 1 FROM processed_webhook_deliveries WHERE delivery_id = %s;",
                            (delivery_id,)
                        )
                        if cur.fetchone():
                            self._processed.add(delivery_id)
                            return True
            except Exception as e:
                logger.warning(f"Failed to check processed_webhook_deliveries in DB: {e}")
        return False

    def record_delivery_if_new(
        self,
        delivery_id: str,
        organization_id: str,
        channel_type: str,
        event_type: str,
        repository_id: Optional[str] = None,
        ttl_hours: int = 72
    ) -> bool:
        """
        Atomically records delivery if it has not been processed yet.
        Returns True if newly recorded, False if it was already processed (duplicate/replay).
        """
        if not delivery_id:
            return False

        if delivery_id in self._processed:
            return False

        db_url = os.getenv("SUPABASE_DB_URL") or os.getenv("DATABASE_URL")
        if db_url:
            try:
                import psycopg2
                with psycopg2.connect(db_url) as conn:
                    with conn.cursor() as cur:
                        now = datetime.now(timezone.utc)
                        expires_at = now + timedelta(hours=ttl_hours)
                        cur.execute("""
                            INSERT INTO processed_webhook_deliveries
                                (delivery_id, organization_id, channel_type, repository_id, event_type, processed_at, expires_at)
                            VALUES (%s, %s, %s, %s, %s, %s, %s)
                            ON CONFLICT (delivery_id) DO NOTHING
                            RETURNING delivery_id;
                        """, (
                            delivery_id,
                            organization_id,
                            channel_type,
                            str(repository_id) if repository_id else None,
                            event_type,
                            now,
                            expires_at
                        ))
                        row = cur.fetchone()
                        conn.commit()
                        if row is None:
                            # Conflict occurred: already processed
                            self._processed.add(delivery_id)
                            return False
            except Exception as e:
                logger.warning(f"Failed to persist delivery {delivery_id} to DB: {e}")

        self._processed.add(delivery_id)
        return True

    def clear(self, test_only: bool = True):
        self._processed.clear()
        db_url = os.getenv("SUPABASE_DB_URL") or os.getenv("DATABASE_URL")
        if db_url:
            try:
                import psycopg2
                with psycopg2.connect(db_url) as conn:
                    with conn.cursor() as cur:
                        if test_only:
                            cur.execute("DELETE FROM processed_webhook_deliveries WHERE delivery_id LIKE 'del_%';")
                        else:
                            cur.execute("DELETE FROM processed_webhook_deliveries;")
                    conn.commit()
            except Exception as e:
                logger.warning(f"Failed to clear processed_webhook_deliveries in DB: {e}")

webhook_delivery_store = WebhookDeliveryStore()
