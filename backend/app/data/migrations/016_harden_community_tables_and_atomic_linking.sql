-- Migration 016: Harden Community Tables, Force Zero-Direct RLS, Purge Fake Seeds, and Atomic Linking Schema

-- 1. Purge any unverified/synthetic test rows from community tables (fail-closed)
DELETE FROM community_events;
DELETE FROM community_resources;

-- 2. Force Row Level Security on all community tables
ALTER TABLE conversation_turns ENABLE ROW LEVEL SECURITY;
ALTER TABLE conversation_turns FORCE ROW LEVEL SECURITY;

ALTER TABLE community_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE community_events FORCE ROW LEVEL SECURITY;

ALTER TABLE community_resources ENABLE ROW LEVEL SECURITY;
ALTER TABLE community_resources FORCE ROW LEVEL SECURITY;

-- 3. Revoke all privileges from untrusted roles
REVOKE ALL ON conversation_turns FROM PUBLIC, anon, authenticated;
REVOKE ALL ON community_events FROM PUBLIC, anon, authenticated;
REVOKE ALL ON community_resources FROM PUBLIC, anon, authenticated;

-- 4. Grant privileges strictly to service_role
GRANT ALL ON conversation_turns TO service_role;
GRANT ALL ON community_events TO service_role;
GRANT ALL ON community_resources TO service_role;

-- 5. Safe idempotent service_role policies
DROP POLICY IF EXISTS "Service role full access on conversation_turns" ON conversation_turns;
DROP POLICY IF EXISTS "service_role_all_conversation_turns" ON conversation_turns;
CREATE POLICY "service_role_all_conversation_turns" ON conversation_turns
    FOR ALL TO service_role USING (true) WITH CHECK (true);

DROP POLICY IF EXISTS "Service role full access on community_events" ON community_events;
DROP POLICY IF EXISTS "service_role_all_community_events" ON community_events;
CREATE POLICY "service_role_all_community_events" ON community_events
    FOR ALL TO service_role USING (true) WITH CHECK (true);

DROP POLICY IF EXISTS "Service role full access on community_resources" ON community_resources;
DROP POLICY IF EXISTS "service_role_all_community_resources" ON community_resources;
CREATE POLICY "service_role_all_community_resources" ON community_resources
    FOR ALL TO service_role USING (true) WITH CHECK (true);

-- 6. Upgrade account_link_tokens to 256-bit hashed token storage with atomic consumption and audit fields
DROP TABLE IF EXISTS account_link_tokens;
CREATE TABLE IF NOT EXISTS account_link_tokens (
    token_hash TEXT PRIMARY KEY,
    person_id TEXT NOT NULL,
    organization_id TEXT NOT NULL,
    initiating_platform TEXT NOT NULL,
    initiating_account_id TEXT NOT NULL,
    initiating_username TEXT NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    used BOOLEAN NOT NULL DEFAULT FALSE,
    used_at TIMESTAMPTZ,
    redeemed_by_platform TEXT,
    redeemed_by_account_id TEXT,
    attempts INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_account_link_tokens_lookup ON account_link_tokens(token_hash, used, expires_at);
CREATE INDEX IF NOT EXISTS idx_account_link_tokens_org ON account_link_tokens(organization_id, initiating_account_id);

ALTER TABLE account_link_tokens ENABLE ROW LEVEL SECURITY;
ALTER TABLE account_link_tokens FORCE ROW LEVEL SECURITY;

REVOKE ALL ON account_link_tokens FROM PUBLIC, anon, authenticated;
GRANT ALL ON account_link_tokens TO service_role;

DROP POLICY IF EXISTS "Service role full access on account_link_tokens" ON account_link_tokens;
DROP POLICY IF EXISTS "service_role_all_account_link_tokens" ON account_link_tokens;
CREATE POLICY "service_role_all_account_link_tokens" ON account_link_tokens
    FOR ALL TO service_role USING (true) WITH CHECK (true);
