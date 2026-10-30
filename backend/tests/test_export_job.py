import pytest
from unittest.mock import MagicMock
from app.channels.export_job import (
    ExportJobService,
    StorageRateLimitError,
    STORAGE_SERVICE_RATE_LIMIT_RPS,
    MAX_RETRIES
)

def test_export_job_constants():
    """Verify rate limit and retry ceiling matches architectural constraints."""
    assert STORAGE_SERVICE_RATE_LIMIT_RPS == 3
    assert MAX_RETRIES == 3  # Reduced from 5 after review to prevent queue starvation

def test_export_job_success_on_first_try():
    service = ExportJobService(max_retries=3, initial_backoff=0.01)
    uploader = MagicMock(return_value={"uploaded": True})
    
    result = service.execute_export_with_backoff("job_1", {"records": [1, 2]}, uploader_fn=uploader)
    assert result["status"] == "completed"
    assert result["attempts"] == 1
    uploader.assert_called_once()

def test_export_job_retries_on_rate_limit_and_succeeds():
    service = ExportJobService(max_retries=3, initial_backoff=0.01)
    
    # Fails twice with rate limit, succeeds on 3rd attempt
    uploader = MagicMock(side_effect=[
        StorageRateLimitError("429 Too Many Requests"),
        StorageRateLimitError("429 Too Many Requests"),
        {"uploaded": True}
    ])
    
    result = service.execute_export_with_backoff("job_retry_success", {"records": [1]}, uploader_fn=uploader)
    assert result["status"] == "completed"
    assert result["attempts"] == 3
    assert uploader.call_count == 3

def test_export_job_fails_after_max_retries():
    service = ExportJobService(max_retries=3, initial_backoff=0.01)
    
    # Always fails with 429
    uploader = MagicMock(side_effect=StorageRateLimitError("429 Too Many Requests"))
    
    with pytest.raises(StorageRateLimitError):
        service.execute_export_with_backoff("job_fail", {"records": []}, uploader_fn=uploader)
        
    assert uploader.call_count == 3
