-- Migration 008: Cross-Channel Identity Persistence & GitHub Repository Bindings
-- Persists channel account links, verification evidence, server-owned GitHub repo bindings,
-- and webhook delivery replay protection with strict RLS.

-- 1. Persistent Channel Account Links
CREATE TABLE IF NOT EXISTS channel_account_links (
    id TEXT PRIMARY KEY,
    organization_id TEXT NOT NULL,
    person_id TEXT NOT NULL,
    channel_type TEXT NOT NULL,
    account_id TEXT NOT NULL,
    username TEXT,
    display_name TEXT,
    email TEXT,
    link_type TEXT NOT NULL,
    confidence FLOAT NOT NULL DEFAULT 0.0,
    evidence JSONB DEFAULT '{}'::jsonb NOT NULL,
    is_verified BOOLEAN DEFAULT FALSE NOT NULL,
    linked_at TIMESTAMPTZ DEFAULT TIMEZONE('utc'::text, NOW()) NOT NULL,
    CONSTRAINT uq_channel_account UNIQUE (organization_id, channel_type, account_id)
);

-- 2. Server-Owned GitHub Repository Bindings
CREATE TABLE IF NOT EXISTS github_repository_bindings (
    id TEXT PRIMARY KEY,
    organization_id TEXT NOT NULL,
    installation_id TEXT,
    repository_id TEXT NOT NULL,
    repository_name TEXT NOT NULL,
    is_active BOOLEAN DEFAULT TRUE NOT NULL,
    bound_at TIMESTAMPTZ DEFAULT TIMEZONE('utc'::text, NOW()) NOT NULL,
    metadata JSONB DEFAULT '{}'::jsonb,
    CONSTRAINT uq_github_repo UNIQUE (repository_id)
);

-- 3. Webhook Delivery Replay Deduplication
CREATE TABLE IF NOT EXISTS processed_webhook_deliveries (
    delivery_id TEXT PRIMARY KEY,
    organization_id TEXT NOT NULL,
    channel_type TEXT NOT NULL,
    repository_id TEXT,
    event_type TEXT NOT NULL,
    processed_at TIMESTAMPTZ DEFAULT TIMEZONE('utc'::text, NOW()) NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL
);

-- 4. Indexes
CREATE INDEX IF NOT EXISTS idx_channel_account_person ON channel_account_links(organization_id, person_id);
CREATE INDEX IF NOT EXISTS idx_channel_account_lookup ON channel_account_links(organization_id, channel_type, account_id);
CREATE INDEX IF NOT EXISTS idx_github_repo_name ON github_repository_bindings(repository_name);
CREATE INDEX IF NOT EXISTS idx_github_repo_org ON github_repository_bindings(organization_id);
CREATE INDEX IF NOT EXISTS idx_webhook_deliveries_expires ON processed_webhook_deliveries(expires_at);

-- 5. Row Level Security Hardening
ALTER TABLE channel_account_links ENABLE ROW LEVEL SECURITY;
ALTER TABLE channel_account_links FORCE ROW LEVEL SECURITY;

ALTER TABLE github_repository_bindings ENABLE ROW LEVEL SECURITY;
ALTER TABLE github_repository_bindings FORCE ROW LEVEL SECURITY;

ALTER TABLE processed_webhook_deliveries ENABLE ROW LEVEL SECURITY;
ALTER TABLE processed_webhook_deliveries FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "service_role_all_channel_account_links" ON channel_account_links;
CREATE POLICY "service_role_all_channel_account_links" ON channel_account_links
    FOR ALL TO service_role USING (true) WITH CHECK (true);

DROP POLICY IF EXISTS "service_role_all_github_repo_bindings" ON github_repository_bindings;
CREATE POLICY "service_role_all_github_repo_bindings" ON github_repository_bindings
    FOR ALL TO service_role USING (true) WITH CHECK (true);

DROP POLICY IF EXISTS "service_role_all_webhook_deliveries" ON processed_webhook_deliveries;
CREATE POLICY "service_role_all_webhook_deliveries" ON processed_webhook_deliveries
    FOR ALL TO service_role USING (true) WITH CHECK (true);

REVOKE ALL ON channel_account_links FROM PUBLIC, anon, authenticated;
GRANT ALL ON channel_account_links TO service_role;

REVOKE ALL ON github_repository_bindings FROM PUBLIC, anon, authenticated;
GRANT ALL ON github_repository_bindings TO service_role;

REVOKE ALL ON processed_webhook_deliveries FROM PUBLIC, anon, authenticated;
GRANT ALL ON processed_webhook_deliveries TO service_role;
