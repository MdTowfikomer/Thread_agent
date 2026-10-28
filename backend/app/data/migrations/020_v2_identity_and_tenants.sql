-- V2 service metadata. IDs are text to preserve explicit legacy identities;
-- new accounts and memberships receive UUIDs in the application.
CREATE TABLE IF NOT EXISTS thread_users (
    id TEXT PRIMARY KEY,
    email TEXT NOT NULL UNIQUE CHECK (email = lower(email)),
    password_hash TEXT,
    name TEXT NOT NULL,
    created_at BIGINT NOT NULL
);
CREATE TABLE IF NOT EXISTS organizations (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    created_at BIGINT NOT NULL
);
CREATE TABLE IF NOT EXISTS memberships (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES thread_users(id),
    organization_id TEXT NOT NULL REFERENCES organizations(id),
    role TEXT NOT NULL CHECK (role IN ('owner', 'admin', 'member')),
    created_at BIGINT NOT NULL,
    UNIQUE (user_id, organization_id)
);
CREATE UNIQUE INDEX IF NOT EXISTS one_workspace_owner ON memberships(organization_id) WHERE role = 'owner';
CREATE TABLE IF NOT EXISTS assistant_configurations (
    organization_id TEXT PRIMARY KEY REFERENCES organizations(id),
    default_agent_name TEXT NOT NULL DEFAULT 'Thread',
    system_prompt TEXT NOT NULL DEFAULT 'Answer organizational questions using authorized evidence. Acknowledge missing evidence.',
    configured_roles JSONB NOT NULL DEFAULT '[]'
);
CREATE TABLE IF NOT EXISTS invitations (
    id TEXT PRIMARY KEY,
    organization_id TEXT NOT NULL REFERENCES organizations(id),
    email TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('admin', 'member')),
    token_hash TEXT NOT NULL UNIQUE,
    expires_at BIGINT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('pending', 'accepted', 'revoked')),
    created_by TEXT NOT NULL REFERENCES thread_users(id)
);
CREATE TABLE IF NOT EXISTS user_sessions (
    token_hash TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES thread_users(id),
    active_organization_id TEXT REFERENCES organizations(id),
    expires_at BIGINT NOT NULL
);
CREATE INDEX IF NOT EXISTS sessions_user ON user_sessions(user_id);

-- Explicit compatibility fixture: these accounts cannot log in with passwords.
INSERT INTO organizations(id, name, description, created_at)
VALUES ('gdg_mcet', 'GDG MCET', 'Google Developer Groups MCET demo workspace.', 0)
ON CONFLICT DO NOTHING;
INSERT INTO assistant_configurations(organization_id) VALUES ('gdg_mcet') ON CONFLICT DO NOTHING;
INSERT INTO thread_users(id, email, name, created_at) VALUES
('usr_towfik', 'towfik@gdgmcet.org', 'Towfik Omer', 0),
('usr_arjun', 'arjun@gdgmcet.org', 'Arjun Sharma', 0),
('usr_priya', 'priya@gdgmcet.org', 'Priya Ramesh', 0),
('usr_student_rohan', 'rohan@student.mcet.edu', 'Rohan Verma', 0),
('usr_inactive_lead', 'siddharth.former@mcet.edu', 'Siddharth Rao', 0),
('demo_organizer', 'organizer.demo@gdgmcet.org', 'Demo Organizer', 0),
('demo_community', 'community.demo@student.mcet.edu', 'Demo Community Member', 0),
('demo_judge', 'viewer.demo@gdgmcet.org', 'Demo Viewer', 0)
ON CONFLICT DO NOTHING;
INSERT INTO memberships(id, user_id, organization_id, role, created_at) VALUES
('legacy-towfik', 'usr_towfik', 'gdg_mcet', 'owner', 0),
('legacy-arjun', 'usr_arjun', 'gdg_mcet', 'admin', 0),
('legacy-priya', 'usr_priya', 'gdg_mcet', 'admin', 0),
('legacy-rohan', 'usr_student_rohan', 'gdg_mcet', 'member', 0),
('legacy-organizer', 'demo_organizer', 'gdg_mcet', 'admin', 0),
('legacy-community', 'demo_community', 'gdg_mcet', 'member', 0),
('legacy-viewer', 'demo_judge', 'gdg_mcet', 'member', 0)
ON CONFLICT DO NOTHING;

-- PostgreSQL access boundary: browser Supabase roles have no direct access.
DO $$
DECLARE table_name TEXT;
BEGIN
    FOREACH table_name IN ARRAY ARRAY['thread_users','organizations','memberships','assistant_configurations','invitations','user_sessions'] LOOP
        EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', table_name);
        EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY', table_name);
        EXECUTE format('REVOKE ALL ON %I FROM PUBLIC', table_name);
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN
            EXECUTE format('REVOKE ALL ON %I FROM anon', table_name);
        END IF;
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN
            EXECUTE format('REVOKE ALL ON %I FROM authenticated', table_name);
        END IF;
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'service_role') THEN
            EXECUTE format('GRANT ALL ON %I TO service_role', table_name);
            EXECUTE format('DROP POLICY IF EXISTS service_backend ON %I', table_name);
            EXECUTE format('CREATE POLICY service_backend ON %I FOR ALL TO service_role USING (true) WITH CHECK (true)', table_name);
        END IF;
    END LOOP;
END $$;
