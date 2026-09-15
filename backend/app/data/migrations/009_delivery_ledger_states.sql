-- Migration 009: Webhook Delivery Processing Lifecycle States
-- Adds 'processing', 'completed', 'failed' states to prevent permanent loss
-- of GitHub events when transient parsing or persistence errors occur.

ALTER TABLE processed_webhook_deliveries
    ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'completed',
    ADD COLUMN IF NOT EXISTS error_message TEXT;

CREATE INDEX IF NOT EXISTS idx_webhook_deliveries_status ON processed_webhook_deliveries(status);
