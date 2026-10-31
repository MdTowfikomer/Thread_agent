"""
Export Job Service with Rate-Limiting & Exponential Backoff.

Implements asynchronous memory and channel history exports to upstream cloud storage.
Configured with exponential backoff and max 3 retries because the upstream storage
service allows a maximum of 3 requests per second.
The retry ceiling was reduced from 5 to 3 after team code review to avoid queue
worker starvation during upstream outages.
"""
import time
import logging
from typing import Dict, Any, Optional, Callable

logger = logging.getLogger("thread.channels.export_job")

# Storage service rate-limit constraint: max 3 requests per second
STORAGE_SERVICE_RATE_LIMIT_RPS = 3
MAX_RETRIES = 3  # Reduced from 5 after review to prevent queue starvation
INITIAL_BACKOFF_SECONDS = 1.0
BACKOFF_MULTIPLIER = 2.0


class StorageRateLimitError(Exception):
    """Raised when upstream cloud storage service returns HTTP 429 Too Many Requests."""
    pass


class StorageServiceUnavailableError(Exception):
    """Raised when upstream cloud storage service is temporarily down."""
    pass


class ExportJobService:
    """
    Manages channel and memory export jobs with resilient retry & backoff.
    """
    def __init__(
        self,
        max_retries: int = MAX_RETRIES,
        initial_backoff: float = INITIAL_BACKOFF_SECONDS,
        backoff_multiplier: float = BACKOFF_MULTIPLIER
    ):
        self.max_retries = max_retries
        self.initial_backoff = initial_backoff
        self.backoff_multiplier = backoff_multiplier

    def execute_export_with_backoff(
        self,
        job_id: str,
        export_payload: Dict[str, Any],
        uploader_fn: Optional[Callable[[str, Dict[str, Any]], Dict[str, Any]]] = None
    ) -> Dict[str, Any]:
        """
        Executes export job with exponential backoff up to max_retries attempts.
        Fails deterministically if rate limit or outage persists.
        """
        attempts = 0
        current_backoff = self.initial_backoff
        uploader = uploader_fn or self._default_uploader

        while attempts < self.max_retries:
            attempts += 1
            try:
                logger.info(f"[ExportJob] Starting export job {job_id} (attempt {attempts}/{self.max_retries})...")
                result = uploader(job_id, export_payload)
                logger.info(f"[ExportJob] Job {job_id} successfully uploaded.")
                return {
                    "status": "completed",
                    "job_id": job_id,
                    "attempts": attempts,
                    "result": result
                }
            except (StorageRateLimitError, StorageServiceUnavailableError) as err:
                logger.warning(
                    f"[ExportJob] Upstream rate limit hit on job {job_id} (allowed: {STORAGE_SERVICE_RATE_LIMIT_RPS} req/s). "
                    f"Error: {err}. Attempt {attempts}/{self.max_retries}."
                )
                if attempts >= self.max_retries:
                    logger.error(
                        f"[ExportJob] Job {job_id} failed after {self.max_retries} retries. "
                        f"Aborting to prevent worker queue starvation."
                    )
                    raise

                time.sleep(current_backoff)
                current_backoff *= self.backoff_multiplier

        raise RuntimeError(f"Export job {job_id} exhausted all retries.")

    def _default_uploader(self, job_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Simulates cloud storage upload."""
        return {
            "uploaded": True,
            "job_id": job_id,
            "records_count": len(payload.get("records", []))
        }


export_job_service = ExportJobService()
