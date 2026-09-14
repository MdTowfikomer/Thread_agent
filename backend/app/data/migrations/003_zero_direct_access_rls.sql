-- Migration 003: Zero-Direct-Access RLS Enforcement
-- Enables and forces RLS, revokes untrusted access, and installs idempotent service_role policies

-- Enable and force RLS on all tables
ALTER TABLE source_records ENABLE ROW LEVEL SECURITY;
ALTER TABLE source_records FORCE ROW LEVEL SECURITY;

ALTER TABLE memory_chunks ENABLE ROW LEVEL SECURITY;
ALTER TABLE memory_chunks FORCE ROW LEVEL SECURITY;

ALTER TABLE guild_installations ENABLE ROW LEVEL SECURITY;
ALTER TABLE guild_installations FORCE ROW LEVEL SECURITY;

ALTER TABLE import_approvals ENABLE ROW LEVEL SECURITY;
ALTER TABLE import_approvals FORCE ROW LEVEL SECURITY;

ALTER TABLE processed_interactions ENABLE ROW LEVEL SECURITY;
ALTER TABLE processed_interactions FORCE ROW LEVEL SECURITY;

-- Revoke all table, sequence, and function permissions from untrusted roles
REVOKE ALL ON ALL TABLES IN SCHEMA public FROM PUBLIC, anon, authenticated;
REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM PUBLIC, anon, authenticated;
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA public FROM PUBLIC, anon, authenticated;

-- Grant access strictly to backend service_role
GRANT ALL ON ALL TABLES IN SCHEMA public TO service_role;
GRANT ALL ON ALL SEQUENCES IN SCHEMA public TO service_role;
GRANT ALL ON ALL FUNCTIONS IN SCHEMA public TO service_role;

-- Safe Repeatable Policies: Drop if exists before create
DROP POLICY IF EXISTS "service_role_all_source_records" ON source_records;
CREATE POLICY "service_role_all_source_records" ON source_records
    FOR ALL TO service_role USING (true) WITH CHECK (true);

DROP POLICY IF EXISTS "service_role_all_memory_chunks" ON memory_chunks;
CREATE POLICY "service_role_all_memory_chunks" ON memory_chunks
    FOR ALL TO service_role USING (true) WITH CHECK (true);

DROP POLICY IF EXISTS "service_role_all_guild_installations" ON guild_installations;
CREATE POLICY "service_role_all_guild_installations" ON guild_installations
    FOR ALL TO service_role USING (true) WITH CHECK (true);

DROP POLICY IF EXISTS "service_role_all_import_approvals" ON import_approvals;
CREATE POLICY "service_role_all_import_approvals" ON import_approvals
    FOR ALL TO service_role USING (true) WITH CHECK (true);

DROP POLICY IF EXISTS "service_role_all_processed_interactions" ON processed_interactions;
CREATE POLICY "service_role_all_processed_interactions" ON processed_interactions
    FOR ALL TO service_role USING (true) WITH CHECK (true);
