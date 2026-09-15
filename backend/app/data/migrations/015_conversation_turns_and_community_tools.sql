-- Migration 015: Multi-turn conversation turns, structured events, resources, and account link tokens

-- 1. Multi-turn conversation turns sliding window
CREATE TABLE IF NOT EXISTS conversation_turns (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_key TEXT NOT NULL,
    platform TEXT NOT NULL,
    organization_id TEXT NOT NULL DEFAULT 'gdg_mcet',
    initiating_user_id TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('user', 'assistant', 'system')),
    content TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_conversation_turns_session ON conversation_turns(session_key, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_conversation_turns_org ON conversation_turns(organization_id);

ALTER TABLE conversation_turns ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "Service role full access on conversation_turns" ON conversation_turns;
CREATE POLICY "Service role full access on conversation_turns"
    ON conversation_turns
    FOR ALL
    TO service_role
    USING (true)
    WITH CHECK (true);

-- 2. Structured Community Events
CREATE TABLE IF NOT EXISTS community_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id TEXT NOT NULL DEFAULT 'gdg_mcet',
    title TEXT NOT NULL,
    description TEXT,
    start_time TIMESTAMPTZ NOT NULL,
    end_time TIMESTAMPTZ,
    location_or_url TEXT,
    rsvp_url TEXT,
    speakers JSONB DEFAULT '[]'::jsonb,
    status TEXT NOT NULL DEFAULT 'upcoming' CHECK (status IN ('upcoming', 'in_progress', 'completed', 'cancelled')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_community_events_time ON community_events(organization_id, start_time ASC);

ALTER TABLE community_events ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "Service role full access on community_events" ON community_events;
CREATE POLICY "Service role full access on community_events"
    ON community_events
    FOR ALL
    TO service_role
    USING (true)
    WITH CHECK (true);

-- 3. Community Resources & FAQs
CREATE TABLE IF NOT EXISTS community_resources (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id TEXT NOT NULL DEFAULT 'gdg_mcet',
    category TEXT NOT NULL,
    title TEXT NOT NULL,
    url TEXT,
    description TEXT NOT NULL,
    tags TEXT[] DEFAULT ARRAY[]::TEXT[],
    permission_scope TEXT NOT NULL DEFAULT 'PUBLIC_COMMUNITY',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_community_resources_cat ON community_resources(organization_id, category);

ALTER TABLE community_resources ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "Service role full access on community_resources" ON community_resources;
CREATE POLICY "Service role full access on community_resources"
    ON community_resources
    FOR ALL
    TO service_role
    USING (true)
    WITH CHECK (true);

-- 4. Cross-Platform Account Link Tokens
CREATE TABLE IF NOT EXISTS account_link_tokens (
    token TEXT PRIMARY KEY,
    initiating_platform TEXT NOT NULL,
    initiating_account_id TEXT NOT NULL,
    initiating_username TEXT NOT NULL,
    person_id TEXT NOT NULL,
    organization_id TEXT NOT NULL DEFAULT 'gdg_mcet',
    expires_at TIMESTAMPTZ NOT NULL,
    used BOOLEAN NOT NULL DEFAULT FALSE
);

ALTER TABLE account_link_tokens ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "Service role full access on account_link_tokens" ON account_link_tokens;
CREATE POLICY "Service role full access on account_link_tokens"
    ON account_link_tokens
    FOR ALL
    TO service_role
    USING (true)
    WITH CHECK (true);
