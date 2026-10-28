-- Managed-memory tables. Service identities may live in a different database,
-- so organization/user authorization is revalidated through the service layer.
CREATE TABLE IF NOT EXISTS conversations (
    id TEXT PRIMARY KEY,
    organization_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    platform TEXT NOT NULL,
    session_key TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    UNIQUE (organization_id, user_id, platform, session_key),
    UNIQUE (id, organization_id)
);
CREATE TABLE IF NOT EXISTS execution_traces (
    id TEXT PRIMARY KEY,
    organization_id TEXT NOT NULL,
    conversation_id TEXT NOT NULL,
    turn_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    outcome TEXT NOT NULL CHECK (outcome IN ('running','completed','refused','failed')),
    stages JSONB NOT NULL DEFAULT '[]',
    metrics JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL,
    FOREIGN KEY (conversation_id,organization_id) REFERENCES conversations(id,organization_id),
    UNIQUE (organization_id,turn_id)
);
CREATE INDEX IF NOT EXISTS trace_conversation_order ON execution_traces(organization_id,conversation_id,created_at);

-- PostgreSQL access boundary: trusted backend only.
DO $$
DECLARE table_name TEXT;
BEGIN
    FOREACH table_name IN ARRAY ARRAY['conversations','execution_traces'] LOOP
        EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', table_name);
        EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY', table_name);
        EXECUTE format('REVOKE ALL ON %I FROM PUBLIC', table_name);
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='anon') THEN
            EXECUTE format('REVOKE ALL ON %I FROM anon', table_name);
        END IF;
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='authenticated') THEN
            EXECUTE format('REVOKE ALL ON %I FROM authenticated', table_name);
        END IF;
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='service_role') THEN
            EXECUTE format('GRANT ALL ON %I TO service_role', table_name);
            EXECUTE format('CREATE POLICY service_backend ON %I FOR ALL TO service_role USING (true) WITH CHECK (true)', table_name);
        END IF;
    END LOOP;
END $$;
