-- Migration 012: Server-Owned Telegram & Slack Bindings
-- Stores authoritative mappings from Telegram chat IDs and Slack workspace team IDs
-- to Thread organizations with strict RLS.

-- 1. Telegram Chat Bindings
CREATE TABLE IF NOT EXISTS telegram_chat_bindings (
    id TEXT PRIMARY KEY,
    organization_id TEXT NOT NULL,
    chat_id TEXT NOT NULL,
    chat_title TEXT,
    chat_type TEXT,
    is_active BOOLEAN DEFAULT TRUE NOT NULL,
    bound_at TIMESTAMPTZ DEFAULT TIMEZONE('utc'::text, NOW()) NOT NULL,
    metadata JSONB DEFAULT '{}'::jsonb,
    CONSTRAINT uq_telegram_chat UNIQUE (chat_id)
);

-- 2. Slack Workspace Bindings
CREATE TABLE IF NOT EXISTS slack_workspace_bindings (
    id TEXT PRIMARY KEY,
    organization_id TEXT NOT NULL,
    team_id TEXT NOT NULL,
    team_domain TEXT,
    is_active BOOLEAN DEFAULT TRUE NOT NULL,
    bound_at TIMESTAMPTZ DEFAULT TIMEZONE('utc'::text, NOW()) NOT NULL,
    metadata JSONB DEFAULT '{}'::jsonb,
    CONSTRAINT uq_slack_team UNIQUE (team_id)
);

-- 3. Indexes
CREATE INDEX IF NOT EXISTS idx_telegram_chat_org ON telegram_chat_bindings(organization_id);
CREATE INDEX IF NOT EXISTS idx_telegram_chat_id ON telegram_chat_bindings(chat_id);
CREATE INDEX IF NOT EXISTS idx_slack_workspace_org ON slack_workspace_bindings(organization_id);
CREATE INDEX IF NOT EXISTS idx_slack_team_id ON slack_workspace_bindings(team_id);

-- 4. Row Level Security Hardening
ALTER TABLE telegram_chat_bindings ENABLE ROW LEVEL SECURITY;
ALTER TABLE telegram_chat_bindings FORCE ROW LEVEL SECURITY;
ALTER TABLE slack_workspace_bindings ENABLE ROW LEVEL SECURITY;
ALTER TABLE slack_workspace_bindings FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "service_role_all_telegram_chats" ON telegram_chat_bindings;
CREATE POLICY "service_role_all_telegram_chats" ON telegram_chat_bindings
    FOR ALL
    TO service_role
    USING (true)
    WITH CHECK (true);

DROP POLICY IF EXISTS "service_role_all_slack_workspaces" ON slack_workspace_bindings;
CREATE POLICY "service_role_all_slack_workspaces" ON slack_workspace_bindings
    FOR ALL
    TO service_role
    USING (true)
    WITH CHECK (true);

REVOKE ALL ON telegram_chat_bindings FROM PUBLIC, anon, authenticated;
GRANT ALL ON telegram_chat_bindings TO service_role;

REVOKE ALL ON slack_workspace_bindings FROM PUBLIC, anon, authenticated;
GRANT ALL ON slack_workspace_bindings TO service_role;
