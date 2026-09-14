-- Migration 002: Provenance & Schema Hardening
-- Upgrades existing tables idempotently with explicit ALTER TABLE statements,
-- quarantine preservation for unverifiable legacy rows, and safe vector/FTS migration.

-- 1. Upgrade source_records columns
ALTER TABLE source_records ADD COLUMN IF NOT EXISTS source_uri TEXT;
ALTER TABLE source_records ADD COLUMN IF NOT EXISTS external_id TEXT;
ALTER TABLE source_records ADD COLUMN IF NOT EXISTS author_id TEXT;
ALTER TABLE source_records ADD COLUMN IF NOT EXISTS author_role TEXT;
ALTER TABLE source_records ADD COLUMN IF NOT EXISTS metadata JSONB DEFAULT '{}'::jsonb;
ALTER TABLE source_records ADD COLUMN IF NOT EXISTS hash TEXT;
ALTER TABLE source_records ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ DEFAULT TIMEZONE('utc'::text, NOW()) NOT NULL;

-- 2. Upgrade memory_chunks basic columns
ALTER TABLE memory_chunks ADD COLUMN IF NOT EXISTS source_uri TEXT;
ALTER TABLE memory_chunks ADD COLUMN IF NOT EXISTS source_timestamp TIMESTAMPTZ;
ALTER TABLE memory_chunks ADD COLUMN IF NOT EXISTS source_hash TEXT;
ALTER TABLE memory_chunks ADD COLUMN IF NOT EXISTS ingestion_version TEXT DEFAULT 'v0';
ALTER TABLE memory_chunks ADD COLUMN IF NOT EXISTS policy_version TEXT DEFAULT 'v0';
ALTER TABLE memory_chunks ADD COLUMN IF NOT EXISTS author_role TEXT;
ALTER TABLE memory_chunks ADD COLUMN IF NOT EXISTS title TEXT;
ALTER TABLE memory_chunks ADD COLUMN IF NOT EXISTS tags TEXT[] DEFAULT '{}'::text[];
ALTER TABLE memory_chunks ADD COLUMN IF NOT EXISTS entities JSONB DEFAULT '{}'::jsonb;
ALTER TABLE memory_chunks ADD COLUMN IF NOT EXISTS embedding_model TEXT DEFAULT 'models/text-embedding-004';
ALTER TABLE memory_chunks ADD COLUMN IF NOT EXISTS embedding_dimension INT DEFAULT 768;
ALTER TABLE memory_chunks ADD COLUMN IF NOT EXISTS provenance JSONB DEFAULT '{}'::jsonb;
ALTER TABLE memory_chunks ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ DEFAULT TIMEZONE('utc'::text, NOW()) NOT NULL;

-- 3. Provenance Preservation: Authoritative Backfill & Quarantine Archive
-- Backfill source_timestamp strictly from parent source_records
UPDATE memory_chunks mc
SET source_timestamp = sr.timestamp
FROM source_records sr
WHERE mc.source_record_id = sr.id
  AND mc.source_timestamp IS NULL
  AND sr.timestamp IS NOT NULL;

-- Secondary backfill from authoritatively recorded provenance timestamp
UPDATE memory_chunks
SET source_timestamp = (provenance->>'timestamp')::TIMESTAMPTZ
WHERE source_timestamp IS NULL
  AND provenance->>'timestamp' IS NOT NULL;

-- Quarantine unrecoverable legacy rows instead of fabricating event time or silently deleting
CREATE TABLE IF NOT EXISTS legacy_unverifiable_chunks (
    id TEXT PRIMARY KEY,
    source_record_id TEXT,
    organization_id TEXT NOT NULL,
    source_type TEXT NOT NULL,
    source_uri TEXT,
    author TEXT NOT NULL,
    author_role TEXT,
    title TEXT,
    content TEXT NOT NULL,
    permission TEXT NOT NULL,
    tags TEXT[] DEFAULT '{}'::text[],
    entities JSONB DEFAULT '{}'::jsonb,
    provenance JSONB DEFAULT '{}'::jsonb,
    quarantined_at TIMESTAMPTZ DEFAULT TIMEZONE('utc'::text, NOW()) NOT NULL,
    quarantine_reason TEXT NOT NULL,
    remediation_status TEXT DEFAULT 'pending_remediation' NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_legacy_unverifiable_org ON legacy_unverifiable_chunks(organization_id);

-- Archive unverifiable rows to audit quarantine before removing from active retrieval
INSERT INTO legacy_unverifiable_chunks (
    id, source_record_id, organization_id, source_type, source_uri,
    author, author_role, title, content, permission,
    tags, entities, provenance, quarantined_at, quarantine_reason, remediation_status
)
SELECT 
    mc.id, mc.source_record_id, mc.organization_id, mc.source_type, mc.source_uri,
    mc.author, mc.author_role, mc.title, mc.content, mc.permission,
    mc.tags, mc.entities, mc.provenance, TIMEZONE('utc'::text, NOW()),
    'unrecoverable_missing_source_timestamp', 'pending_remediation'
FROM memory_chunks mc
WHERE mc.source_timestamp IS NULL
ON CONFLICT (id) DO NOTHING;

-- Remove archived unverifiable rows from active retrieval table
DELETE FROM memory_chunks WHERE source_timestamp IS NULL;

-- Enforce strict NOT NULL constraint on active memory chunks
ALTER TABLE memory_chunks ALTER COLUMN source_timestamp SET NOT NULL;

-- 4. Safe Generated FTS Column Upgrade
CREATE OR REPLACE FUNCTION immutable_array_to_string(text[], text)
RETURNS text LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
    SELECT array_to_string($1, $2);
$$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name = 'memory_chunks' AND column_name = 'fts'
    ) THEN
        ALTER TABLE memory_chunks ADD COLUMN fts TSVECTOR GENERATED ALWAYS AS (
            to_tsvector('english', 
                COALESCE(title, '') || ' ' || 
                content || ' ' || 
                COALESCE(author, '') || ' ' || 
                COALESCE(immutable_array_to_string(tags, ' '), '')
            )
        ) STORED;
    END IF;
END $$;

-- 5. Safe Vector Dimension Migration (embedding_v2 vector(768) pattern)
ALTER TABLE memory_chunks ADD COLUMN IF NOT EXISTS embedding_v2 VECTOR(768);

DO $$
DECLARE
    current_dim INT;
BEGIN
    -- Check if embedding column exists and dimension
    SELECT atttypmod INTO current_dim
    FROM pg_attribute 
    WHERE attrelid = 'memory_chunks'::regclass AND attname = 'embedding';

    IF current_dim IS NOT NULL THEN
        -- If current column is already 768, populate embedding_v2 if null
        IF current_dim = 768 THEN
            UPDATE memory_chunks 
            SET embedding_v2 = embedding 
            WHERE embedding IS NOT NULL AND embedding_v2 IS NULL;
        ELSE
            -- Incompatible older dimension (e.g. vector(128)); swap column to clean vector(768)
            DROP INDEX IF EXISTS idx_memory_chunks_embedding;
            ALTER TABLE memory_chunks DROP COLUMN embedding;
            ALTER TABLE memory_chunks RENAME COLUMN embedding_v2 TO embedding;
        END IF;
    ELSE
        -- embedding column does not exist yet; rename embedding_v2 to embedding
        ALTER TABLE memory_chunks RENAME COLUMN embedding_v2 TO embedding;
    END IF;

    -- Clean up temporary column if embedding is already present and 768
    IF EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name = 'memory_chunks' AND column_name = 'embedding_v2'
    ) THEN
        ALTER TABLE memory_chunks DROP COLUMN embedding_v2;
    END IF;
END $$;

-- 6. Upgrade guild_installations, import_approvals, and processed_interactions
ALTER TABLE guild_installations ADD COLUMN IF NOT EXISTS guild_name TEXT;
ALTER TABLE guild_installations ADD COLUMN IF NOT EXISTS is_active BOOLEAN DEFAULT TRUE NOT NULL;

ALTER TABLE import_approvals ADD COLUMN IF NOT EXISTS quarantined_chunk_ids TEXT[] DEFAULT '{}'::text[];
ALTER TABLE import_approvals ADD COLUMN IF NOT EXISTS promoted_chunk_ids TEXT[] DEFAULT '{}'::text[];
ALTER TABLE import_approvals ADD COLUMN IF NOT EXISTS metadata JSONB DEFAULT '{}'::jsonb;

-- 7. Ensure indexes exist safely
CREATE INDEX IF NOT EXISTS idx_source_records_org ON source_records(organization_id);
CREATE INDEX IF NOT EXISTS idx_source_records_ext ON source_records(organization_id, source_type, external_id);
CREATE INDEX IF NOT EXISTS idx_memory_chunks_org_perm ON memory_chunks(organization_id, permission);
CREATE INDEX IF NOT EXISTS idx_memory_chunks_fts ON memory_chunks USING GIN(fts);
CREATE INDEX IF NOT EXISTS idx_memory_chunks_embedding ON memory_chunks USING hnsw (embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS idx_guild_installations_org ON guild_installations(organization_id);
CREATE INDEX IF NOT EXISTS idx_import_approvals_hash ON import_approvals(import_hash);
CREATE INDEX IF NOT EXISTS idx_import_approvals_org ON import_approvals(organization_id);
CREATE INDEX IF NOT EXISTS idx_processed_interactions_expires ON processed_interactions(expires_at);
