CREATE TABLE IF NOT EXISTS outbound_message_deliveries (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    idempotency_key TEXT NOT NULL UNIQUE,
    platform TEXT NOT NULL,
    organization_id TEXT NOT NULL,
    destination JSONB NOT NULL,
    initiating_user_id TEXT NOT NULL,
    retrieval_receipt_id TEXT NOT NULL,
    source_citations JSONB NOT NULL DEFAULT '[]'::jsonb,
    provider_response_id TEXT,
    delivered_at TIMESTAMPTZ NOT NULL,
    delivery_status TEXT NOT NULL CHECK (delivery_status IN ('processing', 'sent', 'failed'))
);
CREATE INDEX IF NOT EXISTS idx_outbound_deliveries_org ON outbound_message_deliveries(organization_id);
CREATE INDEX IF NOT EXISTS idx_outbound_deliveries_receipt ON outbound_message_deliveries(retrieval_receipt_id);
ALTER TABLE outbound_message_deliveries ENABLE ROW LEVEL SECURITY;
ALTER TABLE outbound_message_deliveries FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "service_role_all_outbound_deliveries" ON outbound_message_deliveries;
CREATE POLICY "service_role_all_outbound_deliveries" ON outbound_message_deliveries FOR ALL TO service_role USING (true) WITH CHECK (true);
REVOKE ALL ON outbound_message_deliveries FROM PUBLIC, anon, authenticated;
GRANT ALL ON outbound_message_deliveries TO service_role;
