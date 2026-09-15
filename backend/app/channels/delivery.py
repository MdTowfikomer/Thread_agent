import os
import logging
from enum import Enum
from typing import Optional, Dict, Any, Tuple
from datetime import datetime, timezone, timedelta
from app.core.config import settings

logger = logging.getLogger("thread.channels.delivery")

class DeliveryStatus(str, Enum):
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"

class DeliveryLedgerError(RuntimeError):
    """Raised when durable webhook delivery tracking fails or is unavailable."""
    pass

class WebhookDeliveryStore:
    """
    Authoritative replay protection and delivery lifecycle ledger.
    Tracks states ('processing', 'completed', 'failed') to ensure:
    1. Duplicate deliveries with status='completed' are rejected (200 duplicate).
    2. Deliveries in-flight with status='processing' (< stale_timeout) are rejected as in-progress (409).
    3. Transient failures during parsing or persistence mark the delivery as 'failed',
       allowing GitHub retries to succeed rather than permanently losing events.
    4. Database failures fail closed whenever a database is configured or in production.
    5. Unit test cleanup never mutates live production database tables.
    """
    def __init__(self):
        # In-memory storage for offline dev and fast lookups
        self._deliveries: Dict[str, Dict[str, Any]] = {}

    def claim_delivery(
        self,
        delivery_id: str,
        organization_id: str,
        channel_type: str,
        event_type: str,
        repository_id: Optional[str] = None,
        ttl_hours: int = 72,
        stale_timeout_seconds: int = 60
    ) -> Tuple[bool, str, Optional[str]]:
        """
        Attempts to claim a delivery for processing.
        Returns (can_process, status_code, message):
        - (False, "duplicate", message): Already successfully completed.
        - (False, "in_progress", message): Another worker is currently processing this delivery.
        - (True, "claimed", None): Delivery claimed and transitioned to 'processing'.
        """
        if not delivery_id:
            return False, "invalid", "Missing delivery ID."

        now = datetime.now(timezone.utc)
        db_url = os.getenv("SUPABASE_DB_URL") or os.getenv("DATABASE_URL")

        if db_url:
            try:
                import psycopg2
                with psycopg2.connect(db_url) as conn:
                    with conn.cursor() as cur:
                        # Query existing delivery record
                        cur.execute(
                            "SELECT status, processed_at FROM processed_webhook_deliveries WHERE delivery_id = %s FOR UPDATE;",
                            (delivery_id,)
                        )
                        row = cur.fetchone()
                        if row:
                            curr_status, processed_at = row[0], row[1]
                            if curr_status == DeliveryStatus.COMPLETED.value:
                                return False, "duplicate", f"Delivery {delivery_id} already processed."
                            elif curr_status == DeliveryStatus.PROCESSING.value:
                                if processed_at and (now - processed_at).total_seconds() < stale_timeout_seconds:
                                    return False, "in_progress", f"Delivery {delivery_id} is currently being processed."
                                # Stale processing timeout: take over
                                cur.execute("""
                                    UPDATE processed_webhook_deliveries
                                    SET status = %s, processed_at = %s, error_message = NULL
                                    WHERE delivery_id = %s;
                                """, (DeliveryStatus.PROCESSING.value, now, delivery_id))
                                conn.commit()
                                return True, "claimed", None
                            elif curr_status == DeliveryStatus.FAILED.value:
                                # Previous attempt failed: allow retry!
                                cur.execute("""
                                    UPDATE processed_webhook_deliveries
                                    SET status = %s, processed_at = %s, error_message = NULL
                                    WHERE delivery_id = %s;
                                """, (DeliveryStatus.PROCESSING.value, now, delivery_id))
                                conn.commit()
                                return True, "claimed", None

                        # No existing record: insert new 'processing' delivery
                        expires_at = now + timedelta(hours=ttl_hours)
                        cur.execute("""
                            INSERT INTO processed_webhook_deliveries
                                (delivery_id, organization_id, channel_type, repository_id, event_type, status, processed_at, expires_at)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                            ON CONFLICT (delivery_id) DO NOTHING
                            RETURNING delivery_id;
                        """, (
                            delivery_id,
                            organization_id,
                            channel_type,
                            str(repository_id) if repository_id else None,
                            event_type,
                            DeliveryStatus.PROCESSING.value,
                            now,
                            expires_at
                        ))
                        inserted = cur.fetchone()
                        conn.commit()
                        if inserted:
                            return True, "claimed", None

                        # If conflict occurred on insert, re-check row
                        cur.execute("SELECT status FROM processed_webhook_deliveries WHERE delivery_id = %s;", (delivery_id,))
                        conflicted_row = cur.fetchone()
                        if conflicted_row and conflicted_row[0] == DeliveryStatus.COMPLETED.value:
                            return False, "duplicate", f"Delivery {delivery_id} already processed."
                        return False, "in_progress", f"Delivery {delivery_id} is currently being processed."

            except Exception as e:
                logger.error(f"Delivery ledger database failure during claim_delivery: {e}")
                # Fail closed: never accept delivery without durable recording when DB configured
                raise DeliveryLedgerError(f"Delivery ledger database unavailable: {e}") from e

        # Offline / in-memory path (dev & unit tests without DB)
        if settings.APP_ENV != "development" and not os.getenv("THREAD_ALLOW_OFFLINE_LEDGER"):
            raise DeliveryLedgerError("Delivery ledger database is not configured in production.")

        if delivery_id in self._deliveries:
            record = self._deliveries[delivery_id]
            curr_status = record["status"]
            processed_at = record["processed_at"]

            if curr_status == DeliveryStatus.COMPLETED:
                return False, "duplicate", f"Delivery {delivery_id} already processed."
            elif curr_status == DeliveryStatus.PROCESSING:
                if (now - processed_at).total_seconds() < stale_timeout_seconds:
                    return False, "in_progress", f"Delivery {delivery_id} is currently being processed."

        # Mark as processing in memory
        self._deliveries[delivery_id] = {
            "status": DeliveryStatus.PROCESSING,
            "processed_at": now,
            "organization_id": organization_id,
            "channel_type": channel_type,
            "event_type": event_type,
            "repository_id": repository_id,
            "error_message": None
        }
        return True, "claimed", None

    def mark_completed(self, delivery_id: str):
        """Marks delivery as successfully completed."""
        if not delivery_id:
            return

        db_url = os.getenv("SUPABASE_DB_URL") or os.getenv("DATABASE_URL")
        if db_url:
            try:
                import psycopg2
                with psycopg2.connect(db_url) as conn:
                    with conn.cursor() as cur:
                        cur.execute("""
                            UPDATE processed_webhook_deliveries
                            SET status = %s, error_message = NULL
                            WHERE delivery_id = %s;
                        """, (DeliveryStatus.COMPLETED.value, delivery_id))
                    conn.commit()
            except Exception as e:
                logger.error(f"Failed to mark delivery {delivery_id} completed in DB: {e}")
                raise DeliveryLedgerError(f"Failed to record delivery completion: {e}") from e

        if delivery_id in self._deliveries:
            self._deliveries[delivery_id]["status"] = DeliveryStatus.COMPLETED
            self._deliveries[delivery_id]["error_message"] = None

    def mark_failed(self, delivery_id: str, error_message: str):
        """Marks delivery as failed, allowing subsequent retries."""
        if not delivery_id:
            return

        db_url = os.getenv("SUPABASE_DB_URL") or os.getenv("DATABASE_URL")
        if db_url:
            try:
                import psycopg2
                with psycopg2.connect(db_url) as conn:
                    with conn.cursor() as cur:
                        cur.execute("""
                            UPDATE processed_webhook_deliveries
                            SET status = %s, error_message = %s
                            WHERE delivery_id = %s;
                        """, (DeliveryStatus.FAILED.value, str(error_message)[:1000], delivery_id))
                    conn.commit()
            except Exception as e:
                logger.critical(
                    f"OPERATIONAL ALERT: Failed to update delivery ledger status to 'failed' for {delivery_id} in DB: {e}. "
                    f"Original processing error: {error_message}. Delivery will remain in 'processing' until stale timeout expires."
                )

        if delivery_id in self._deliveries:
            self._deliveries[delivery_id]["status"] = DeliveryStatus.FAILED
            self._deliveries[delivery_id]["error_message"] = str(error_message)

    def get_delivery_status(self, delivery_id: str) -> Optional[str]:
        """Returns current status of delivery ('processing', 'completed', 'failed', or None)."""
        db_url = os.getenv("SUPABASE_DB_URL") or os.getenv("DATABASE_URL")
        if db_url:
            try:
                import psycopg2
                with psycopg2.connect(db_url) as conn:
                    with conn.cursor() as cur:
                        cur.execute("SELECT status FROM processed_webhook_deliveries WHERE delivery_id = %s;", (delivery_id,))
                        row = cur.fetchone()
                        if row:
                            return row[0]
            except Exception as e:
                raise DeliveryLedgerError(f"Database query failed: {e}") from e

        if delivery_id in self._deliveries:
            status_val = self._deliveries[delivery_id]["status"]
            return status_val.value if isinstance(status_val, DeliveryStatus) else status_val
        return None

    def clear(self):
        """
        Clears local in-memory delivery store only.
        NEVER connects to or mutates remote/production database.
        """
        self._deliveries.clear()

webhook_delivery_store = WebhookDeliveryStore()
