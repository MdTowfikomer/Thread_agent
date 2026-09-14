-- Migration 007: Re-embedding Leases, Retries, and Dead-Letter Queue
-- Adds reembed_attempts, reembed_lease_until, and reembed_error columns to memory_chunks
-- to support non-blocking lease claiming, provider failure resilience, and dead-lettering.

-- 1. Add lease, attempt tracking, and error tracking columns
ALTER TABLE memory_chunks ADD COLUMN IF NOT EXISTS reembed_attempts INT DEFAULT 0 NOT NULL;
ALTER TABLE memory_chunks ADD COLUMN IF NOT EXISTS reembed_lease_until TIMESTAMPTZ;
ALTER TABLE memory_chunks ADD COLUMN IF NOT EXISTS reembed_error TEXT;

-- 2. Index for high-throughput batch claiming (pending or expired leases)
CREATE INDEX IF NOT EXISTS idx_memory_chunks_reembed_queue 
    ON memory_chunks(embedding_status, reembed_lease_until)
    WHERE embedding_status IN ('pending_reembed', 'processing');

-- 3. Index for operator error auditing
CREATE INDEX IF NOT EXISTS idx_memory_chunks_reembed_failed
    ON memory_chunks(organization_id, embedding_status)
    WHERE embedding_status = 'failed_reembed';
