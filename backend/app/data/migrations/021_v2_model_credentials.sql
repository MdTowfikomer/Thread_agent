-- Service metadata only. A revoked row retains configuration/revision, no key.
CREATE TABLE IF NOT EXISTS model_credentials (
    id TEXT PRIMARY KEY,
    organization_id TEXT NOT NULL UNIQUE REFERENCES organizations(id),
    provider TEXT NOT NULL CHECK (provider = 'google'),
    encrypted_api_key TEXT,
    key_suffix TEXT,
    model_name TEXT NOT NULL,
    embedding_model TEXT NOT NULL DEFAULT 'models/gemini-embedding-001'
        CHECK (embedding_model = 'models/gemini-embedding-001'),
    embedding_dimensions INTEGER NOT NULL DEFAULT 768 CHECK (embedding_dimensions = 768),
    status TEXT NOT NULL CHECK (status IN ('active', 'invalid', 'revoked')),
    revision BIGINT NOT NULL DEFAULT 1,
    last_validated_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ NOT NULL,
    CHECK (status <> 'active' OR encrypted_api_key IS NOT NULL),
    CHECK (status <> 'revoked' OR (encrypted_api_key IS NULL AND key_suffix IS NULL))
);

-- PostgreSQL access boundary: backend credentials only.
ALTER TABLE model_credentials ENABLE ROW LEVEL SECURITY;
ALTER TABLE model_credentials FORCE ROW LEVEL SECURITY;
REVOKE ALL ON model_credentials FROM PUBLIC;
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN
        REVOKE ALL ON model_credentials FROM anon;
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN
        REVOKE ALL ON model_credentials FROM authenticated;
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'service_role') THEN
        GRANT ALL ON model_credentials TO service_role;
        DROP POLICY IF EXISTS service_backend ON model_credentials;
        CREATE POLICY service_backend ON model_credentials FOR ALL TO service_role USING (true) WITH CHECK (true);
    END IF;
END $$;
