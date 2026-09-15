-- Migration 011: GitHub OAuth Verification, Revocation State, Audit Log, and Manual Link Requests
-- Hardens channel_account_links with revocation tracking, provides an immutable audit log,
-- and creates an organizer-reviewed manual link request pipeline.

-- 1. Hardening channel_account_links with revocation state
ALTER TABLE channel_account_links ADD COLUMN IF NOT EXISTS is_active BOOLEAN DEFAULT TRUE NOT NULL;
ALTER TABLE channel_account_links ADD COLUMN IF NOT EXISTS revoked_at TIMESTAMPTZ;
ALTER TABLE channel_account_links ADD COLUMN IF NOT EXISTS revoked_by TEXT;

CREATE INDEX IF NOT EXISTS idx_channel_account_active ON channel_account_links(organization_id, channel_type, account_id) WHERE is_active = TRUE;

-- 2. Identity Audit Log
CREATE TABLE IF NOT EXISTS identity_audit_log (
    id TEXT PRIMARY KEY,
    organization_id TEXT NOT NULL,
    person_id TEXT NOT NULL,
    channel_type TEXT NOT NULL,
    account_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    actor_person_id TEXT NOT NULL,
    evidence JSONB DEFAULT '{}'::jsonb NOT NULL,
    created_at TIMESTAMPTZ DEFAULT TIMEZONE('utc'::text, NOW()) NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_identity_audit_person ON identity_audit_log(organization_id, person_id);
CREATE INDEX IF NOT EXISTS idx_identity_audit_account ON identity_audit_log(organization_id, channel_type, account_id);
CREATE INDEX IF NOT EXISTS idx_identity_audit_created ON identity_audit_log(created_at DESC);

-- 3. Organizer-Reviewed Manual Link Requests
CREATE TABLE IF NOT EXISTS manual_link_requests (
    id TEXT PRIMARY KEY,
    organization_id TEXT NOT NULL,
    person_id TEXT NOT NULL,
    channel_type TEXT NOT NULL,
    account_id TEXT NOT NULL,
    username TEXT,
    reason TEXT NOT NULL,
    evidence_notes TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    requested_at TIMESTAMPTZ DEFAULT TIMEZONE('utc'::text, NOW()) NOT NULL,
    reviewed_by TEXT,
    reviewed_at TIMESTAMPTZ,
    review_notes TEXT
);

CREATE INDEX IF NOT EXISTS idx_manual_link_status ON manual_link_requests(organization_id, status);
CREATE INDEX IF NOT EXISTS idx_manual_link_person ON manual_link_requests(organization_id, person_id);

-- 4. Single-Use OAuth State Nonces (Replay Protection)
CREATE TABLE IF NOT EXISTS oauth_state_nonces (
    nonce TEXT PRIMARY KEY,
    organization_id TEXT NOT NULL,
    person_id TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT TIMEZONE('utc'::text, NOW()) NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    consumed_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_oauth_nonce_exp ON oauth_state_nonces(expires_at);

-- 5. Row-Level Security Hardening (Zero Direct Access)
ALTER TABLE identity_audit_log ENABLE ROW LEVEL SECURITY;
ALTER TABLE identity_audit_log FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "service_role_all_identity_audit" ON identity_audit_log;
CREATE POLICY "service_role_all_identity_audit" ON identity_audit_log FOR ALL TO service_role USING (TRUE) WITH CHECK (TRUE);
REVOKE ALL ON identity_audit_log FROM PUBLIC, anon, authenticated;
GRANT ALL ON identity_audit_log TO service_role;

ALTER TABLE manual_link_requests ENABLE ROW LEVEL SECURITY;
ALTER TABLE manual_link_requests FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "service_role_all_manual_link" ON manual_link_requests;
CREATE POLICY "service_role_all_manual_link" ON manual_link_requests FOR ALL TO service_role USING (TRUE) WITH CHECK (TRUE);
REVOKE ALL ON manual_link_requests FROM PUBLIC, anon, authenticated;
GRANT ALL ON manual_link_requests TO service_role;

ALTER TABLE oauth_state_nonces ENABLE ROW LEVEL SECURITY;
ALTER TABLE oauth_state_nonces FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "service_role_all_oauth_nonces" ON oauth_state_nonces;
CREATE POLICY "service_role_all_oauth_nonces" ON oauth_state_nonces FOR ALL TO service_role USING (TRUE) WITH CHECK (TRUE);
REVOKE ALL ON oauth_state_nonces FROM PUBLIC, anon, authenticated;
GRANT ALL ON oauth_state_nonces TO service_role;
