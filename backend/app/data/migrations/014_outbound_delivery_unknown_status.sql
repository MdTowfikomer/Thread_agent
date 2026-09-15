-- Migration 014: Add unknown delivery status for ambiguous outbound timeouts
ALTER TABLE outbound_message_deliveries 
DROP CONSTRAINT IF EXISTS outbound_message_deliveries_delivery_status_check;

ALTER TABLE outbound_message_deliveries 
ADD CONSTRAINT outbound_message_deliveries_delivery_status_check 
CHECK (delivery_status IN ('processing', 'sent', 'failed', 'unknown'));
