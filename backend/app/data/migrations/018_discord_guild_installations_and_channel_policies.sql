-- Migration 018: Server-Owned Discord Guild Installations & Channel Policies
-- Moves all Discord guild installations and ChannelPolicy records completely to PostgreSQL.
-- Enables strict RLS, unique constraints, and seeds authoritative production records for GDG MCET.

-- 1. Discord Guild Installations Table
CREATE TABLE IF NOT EXISTS discord_guild_installations (
    id TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
    guild_id TEXT NOT NULL,
    organization_id TEXT NOT NULL,
    guild_name TEXT,
    is_active BOOLEAN DEFAULT TRUE NOT NULL,
    installed_at TIMESTAMPTZ DEFAULT TIMEZONE('utc'::text, NOW()) NOT NULL,
    metadata JSONB DEFAULT '{}'::jsonb,
    CONSTRAINT uq_discord_guild_id UNIQUE (guild_id)
);

-- 2. Channel Policies Table
CREATE TABLE IF NOT EXISTS channel_policies (
    id TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
    organization_id TEXT NOT NULL,
    channel_type TEXT NOT NULL,
    guild_id TEXT,
    channel_id TEXT NOT NULL,
    channel_name TEXT,
    permission_scope TEXT NOT NULL,
    is_active BOOLEAN DEFAULT TRUE NOT NULL,
    metadata JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ DEFAULT TIMEZONE('utc'::text, NOW()) NOT NULL,
    updated_at TIMESTAMPTZ DEFAULT TIMEZONE('utc'::text, NOW()) NOT NULL,
    CONSTRAINT uq_channel_policies UNIQUE (organization_id, channel_type, guild_id, channel_id)
);

-- 3. Performance & Lookup Indexes
CREATE INDEX IF NOT EXISTS idx_discord_guild_org ON discord_guild_installations(organization_id);
CREATE INDEX IF NOT EXISTS idx_discord_guild_id ON discord_guild_installations(guild_id);
CREATE INDEX IF NOT EXISTS idx_discord_guild_active ON discord_guild_installations(is_active);

CREATE INDEX IF NOT EXISTS idx_channel_policies_lookup ON channel_policies(organization_id, channel_type, guild_id, channel_id);
CREATE INDEX IF NOT EXISTS idx_channel_policies_active ON channel_policies(channel_type, is_active);

-- 4. Row Level Security Hardening
ALTER TABLE discord_guild_installations ENABLE ROW LEVEL SECURITY;
ALTER TABLE discord_guild_installations FORCE ROW LEVEL SECURITY;
ALTER TABLE channel_policies ENABLE ROW LEVEL SECURITY;
ALTER TABLE channel_policies FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "service_role_all_discord_guild_installations" ON discord_guild_installations;
CREATE POLICY "service_role_all_discord_guild_installations" ON discord_guild_installations
    FOR ALL
    TO service_role
    USING (true)
    WITH CHECK (true);

DROP POLICY IF EXISTS "service_role_all_channel_policies" ON channel_policies;
CREATE POLICY "service_role_all_channel_policies" ON channel_policies
    FOR ALL
    TO service_role
    USING (true)
    WITH CHECK (true);

REVOKE ALL ON discord_guild_installations FROM PUBLIC, anon, authenticated;
GRANT ALL ON discord_guild_installations TO service_role;

REVOKE ALL ON channel_policies FROM PUBLIC, anon, authenticated;
GRANT ALL ON channel_policies TO service_role;

-- 5. Seed Authoritative Production Bindings for GDG MCET
-- Production Discord Guild
INSERT INTO discord_guild_installations (guild_id, organization_id, guild_name, is_active)
VALUES ('1549162455874412667', 'gdg_mcet', 'GDG MCET Discord', TRUE)
ON CONFLICT (guild_id) DO UPDATE SET
    organization_id = EXCLUDED.organization_id,
    guild_name = EXCLUDED.guild_name,
    is_active = EXCLUDED.is_active;

-- Production Discord Channel Policies
INSERT INTO channel_policies (organization_id, channel_type, guild_id, channel_id, channel_name, permission_scope, is_active)
VALUES
    ('gdg_mcet', 'discord', '1549162455874412667', '1549434796772560967', 'core-team', 'internal_core', TRUE),
    ('gdg_mcet', 'discord', '1549162455874412667', '1549434872584474735', 'organizers', 'internal_core', TRUE),
    ('gdg_mcet', 'discord', '1549162455874412667', '1549162457359065110', 'general', 'public_community', TRUE),
    ('gdg_mcet', 'discord', '1549162455874412667', '1549434693735157820', 'public_community', 'public_community', TRUE),
    ('gdg_mcet', 'slack', 'T0C21JVKS49', 'C0C21QPFB6E', 'general', 'public_community', TRUE)
ON CONFLICT (organization_id, channel_type, guild_id, channel_id) DO UPDATE SET
    channel_name = EXCLUDED.channel_name,
    permission_scope = EXCLUDED.permission_scope,
    is_active = EXCLUDED.is_active,
    updated_at = NOW();
