-- ============================================================================
-- Thread: AI Organizational Context Agent
-- Supabase Schema & Hybrid Retrieval Migration (v2 Production Hardened)
-- ============================================================================

-- 1. Enable Required Extensions
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Immutable helper for generated FTS column
CREATE OR REPLACE FUNCTION immutable_array_to_string(text[], text)
RETURNS text LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
    SELECT array_to_string($1, $2);
$$;

-- Schema Migrations Tracker
CREATE TABLE IF NOT EXISTS schema_migrations (
    version TEXT PRIMARY KEY,
    applied_at TIMESTAMPTZ DEFAULT TIMEZONE('utc'::text, NOW()) NOT NULL
);

-- 2. Source Records Table
-- Stores raw documents, chat messages, issues, commits, and manual exports.
CREATE TABLE IF NOT EXISTS source_records (
    id TEXT PRIMARY KEY,
    organization_id TEXT NOT NULL,
    source_type TEXT NOT NULL,
    source_uri TEXT,
    external_id TEXT,
    author_id TEXT,
    author_name TEXT NOT NULL,
    author_role TEXT,
    timestamp TIMESTAMPTZ NOT NULL,
    raw_content TEXT NOT NULL,
    permission TEXT NOT NULL,
    metadata JSONB DEFAULT '{}'::jsonb,
    hash TEXT,
    created_at TIMESTAMPTZ DEFAULT TIMEZONE('utc'::text, NOW()) NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_source_records_org ON source_records(organization_id);
CREATE INDEX IF NOT EXISTS idx_source_records_ext ON source_records(organization_id, source_type, external_id);

-- 3. Memory Chunks Table
-- Normalized memory fragments with embeddings, full provenance, and full-text search vectors.
CREATE TABLE IF NOT EXISTS memory_chunks (
    id TEXT PRIMARY KEY,
    source_record_id TEXT REFERENCES source_records(id) ON DELETE CASCADE,
    organization_id TEXT NOT NULL,
    source_type TEXT NOT NULL,
    source_uri TEXT,
    source_timestamp TIMESTAMPTZ NOT NULL,
    source_hash TEXT,
    ingestion_version TEXT DEFAULT 'v0',
    policy_version TEXT DEFAULT 'v0',
    author TEXT NOT NULL,
    author_role TEXT,
    title TEXT,
    content TEXT NOT NULL,
    permission TEXT NOT NULL,
    tags TEXT[] DEFAULT '{}'::text[],
    entities JSONB DEFAULT '{}'::jsonb,
    embedding VECTOR(768) NOT NULL,
    embedding_model TEXT DEFAULT 'models/text-embedding-004',
    embedding_dimension INT DEFAULT 768,
    provenance JSONB DEFAULT '{}'::jsonb,
    fts TSVECTOR GENERATED ALWAYS AS (
        to_tsvector('english', 
            COALESCE(title, '') || ' ' || 
            content || ' ' || 
            COALESCE(author, '') || ' ' || 
            COALESCE(immutable_array_to_string(tags, ' '), '')
        )
    ) STORED,
    created_at TIMESTAMPTZ DEFAULT TIMEZONE('utc'::text, NOW()) NOT NULL
);

-- Indexes for memory chunks
CREATE INDEX IF NOT EXISTS idx_memory_chunks_org_perm ON memory_chunks(organization_id, permission);
CREATE INDEX IF NOT EXISTS idx_memory_chunks_fts ON memory_chunks USING GIN(fts);
CREATE INDEX IF NOT EXISTS idx_memory_chunks_embedding ON memory_chunks USING hnsw (embedding vector_cosine_ops);

-- 4. Server-Authoritative Guild Installation Store
CREATE TABLE IF NOT EXISTS guild_installations (
    guild_id TEXT PRIMARY KEY,
    organization_id TEXT NOT NULL,
    guild_name TEXT,
    installed_at TIMESTAMPTZ DEFAULT TIMEZONE('utc'::text, NOW()) NOT NULL,
    is_active BOOLEAN DEFAULT TRUE NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_guild_installations_org ON guild_installations(organization_id);

-- 5. Organizer Import Approval & Quarantine Audit Trail
CREATE TABLE IF NOT EXISTS import_approvals (
    id TEXT PRIMARY KEY,
    organization_id TEXT NOT NULL,
    import_hash TEXT NOT NULL,
    approved_by_user_id TEXT NOT NULL,
    approved_at TIMESTAMPTZ DEFAULT TIMEZONE('utc'::text, NOW()) NOT NULL,
    quarantined_chunk_ids TEXT[] DEFAULT '{}'::text[],
    promoted_chunk_ids TEXT[] DEFAULT '{}'::text[],
    metadata JSONB DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_import_approvals_hash ON import_approvals(import_hash);
CREATE INDEX IF NOT EXISTS idx_import_approvals_org ON import_approvals(organization_id);

-- 6. Discord Interaction Replay Cache
CREATE TABLE IF NOT EXISTS processed_interactions (
    interaction_id TEXT PRIMARY KEY,
    processed_at TIMESTAMPTZ DEFAULT TIMEZONE('utc'::text, NOW()) NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_processed_interactions_expires ON processed_interactions(expires_at);

-- ============================================================================
-- 7. IDEMPOTENT SCHEMA UPGRADE (P1 Fix)
-- Explicit ALTER TABLE statements to upgrade older tables without data loss.
-- ============================================================================

ALTER TABLE source_records ADD COLUMN IF NOT EXISTS source_uri TEXT;
ALTER TABLE source_records ADD COLUMN IF NOT EXISTS external_id TEXT;
ALTER TABLE source_records ADD COLUMN IF NOT EXISTS author_id TEXT;
ALTER TABLE source_records ADD COLUMN IF NOT EXISTS author_role TEXT;
ALTER TABLE source_records ADD COLUMN IF NOT EXISTS metadata JSONB DEFAULT '{}'::jsonb;
ALTER TABLE source_records ADD COLUMN IF NOT EXISTS hash TEXT;
ALTER TABLE source_records ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ DEFAULT TIMEZONE('utc'::text, NOW()) NOT NULL;

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

-- Safe Generated FTS Column Upgrade
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
                array_to_string(tags, ' ')
            )
        ) STORED;
    END IF;
END $$;

-- Safe Vector Dimension Migration (128-to-768 explicit re-embedding state)
ALTER TABLE memory_chunks ADD COLUMN IF NOT EXISTS embedding_status TEXT DEFAULT 'ready' NOT NULL;
ALTER TABLE memory_chunks ADD COLUMN IF NOT EXISTS legacy_embedding_128 VECTOR(128);
ALTER TABLE memory_chunks ADD COLUMN IF NOT EXISTS embedding_v2 VECTOR(768);

DO $$
DECLARE
    current_dim INT;
BEGIN
    SELECT atttypmod INTO current_dim
    FROM pg_attribute 
    WHERE attrelid = 'memory_chunks'::regclass AND attname = 'embedding';

    IF current_dim IS NOT NULL THEN
        IF current_dim = 768 THEN
            UPDATE memory_chunks 
            SET embedding_v2 = embedding 
            WHERE embedding IS NOT NULL AND embedding_v2 IS NULL;
        ELSE
            -- Preserve legacy vectors into legacy_embedding_128
            UPDATE memory_chunks 
            SET legacy_embedding_128 = embedding 
            WHERE embedding IS NOT NULL;

            -- Mark chunks requiring 768-dim upgrade as pending_reembed
            UPDATE memory_chunks 
            SET embedding_status = 'pending_reembed' 
            WHERE legacy_embedding_128 IS NOT NULL;

            -- Drop old index and replace embedding column with clean vector(768)
            DROP INDEX IF EXISTS idx_memory_chunks_embedding;
            ALTER TABLE memory_chunks DROP COLUMN embedding;
            ALTER TABLE memory_chunks RENAME COLUMN embedding_v2 TO embedding;
        END IF;
    ELSE
        ALTER TABLE memory_chunks RENAME COLUMN embedding_v2 TO embedding;
    END IF;

    IF EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name = 'memory_chunks' AND column_name = 'embedding_v2'
    ) THEN
        ALTER TABLE memory_chunks DROP COLUMN embedding_v2;
    END IF;

    IF NOT EXISTS (SELECT 1 FROM memory_chunks WHERE embedding_status = 'pending_reembed' OR embedding IS NULL) THEN
        ALTER TABLE memory_chunks ALTER COLUMN embedding SET NOT NULL;
    END IF;
END $$;

ALTER TABLE guild_installations ADD COLUMN IF NOT EXISTS guild_name TEXT;
ALTER TABLE guild_installations ADD COLUMN IF NOT EXISTS is_active BOOLEAN DEFAULT TRUE NOT NULL;

ALTER TABLE import_approvals ADD COLUMN IF NOT EXISTS quarantined_chunk_ids TEXT[] DEFAULT '{}'::text[];
ALTER TABLE import_approvals ADD COLUMN IF NOT EXISTS promoted_chunk_ids TEXT[] DEFAULT '{}'::text[];
ALTER TABLE import_approvals ADD COLUMN IF NOT EXISTS metadata JSONB DEFAULT '{}'::jsonb;

-- ============================================================================
-- 8. ZERO-DIRECT-ACCESS RLS ENFORCEMENT (P0 Fix)
-- Enable and force RLS on every table.
-- Revoke ALL access from PUBLIC, anon, and authenticated.
-- Only the backend service_role is granted access.
-- ============================================================================

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

-- Revoke all table and sequence permissions from untrusted client roles
REVOKE ALL ON ALL TABLES IN SCHEMA public FROM PUBLIC, anon, authenticated;
REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM PUBLIC, anon, authenticated;
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA public FROM PUBLIC, anon, authenticated;

-- Grant access strictly to backend service_role
GRANT ALL ON ALL TABLES IN SCHEMA public TO service_role;
GRANT ALL ON ALL SEQUENCES IN SCHEMA public TO service_role;
GRANT ALL ON ALL FUNCTIONS IN SCHEMA public TO service_role;

-- Safe Repeatable Policies: Drop if exists before create (P1 Fix)
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

-- ============================================================================
-- 9. PRE-RETRIEVAL ACL HYBRID SEARCH RPC
-- SECURITY INVOKER: Runs under caller privileges (service_role only).
-- Explicitly ordered CTEs guarantee top-ranked candidates before fusion.
-- ============================================================================

CREATE OR REPLACE FUNCTION hybrid_search(
    query_text TEXT,
    query_embedding VECTOR(768),
    match_count INT,
    filter_organization_id TEXT,
    filter_permissions TEXT[],
    rrf_k INT DEFAULT 60
) RETURNS TABLE (
    id TEXT,
    source_record_id TEXT,
    organization_id TEXT,
    source_type TEXT,
    source_uri TEXT,
    source_timestamp TIMESTAMPTZ,
    source_hash TEXT,
    ingestion_version TEXT,
    policy_version TEXT,
    author TEXT,
    author_role TEXT,
    title TEXT,
    content TEXT,
    permission TEXT,
    tags TEXT[],
    entities JSONB,
    provenance JSONB,
    similarity FLOAT,
    fts_rank FLOAT,
    combined_score FLOAT,
    dense_rank INT,
    lexical_rank INT
) LANGUAGE plpgsql SECURITY INVOKER AS $$
BEGIN
    RETURN QUERY
    WITH pre_filtered_chunks AS (
        -- 1. STRICT PRE-RETRIEVAL ACL ENFORCEMENT AT SQL LAYER
        SELECT mc.*
        FROM memory_chunks mc
        WHERE mc.organization_id = filter_organization_id
          AND mc.permission = ANY(filter_permissions)
    ),
    vector_results AS (
        -- 2. DENSE VECTOR RETRIEVAL ON AUTHORIZED CHUNKS (Explicitly sorted before LIMIT)
        SELECT 
            pfc.id,
            1.0 - (pfc.embedding <=> query_embedding) AS cos_sim,
            ROW_NUMBER() OVER (ORDER BY pfc.embedding <=> query_embedding ASC) AS rank_v
        FROM pre_filtered_chunks pfc
        WHERE pfc.embedding IS NOT NULL
          AND pfc.embedding_status = 'ready'
        ORDER BY pfc.embedding <=> query_embedding ASC
        LIMIT match_count * 3
    ),
    fts_results AS (
        -- 3. FULL-TEXT SEARCH (SPARSE) ON AUTHORIZED CHUNKS (Explicitly sorted before LIMIT)
        SELECT 
            pfc.id,
            ts_rank_cd(pfc.fts, plainto_tsquery('english', query_text))::FLOAT AS text_rank,
            ROW_NUMBER() OVER (ORDER BY ts_rank_cd(pfc.fts, plainto_tsquery('english', query_text)) DESC) AS rank_t
        FROM pre_filtered_chunks pfc
        WHERE pfc.fts @@ plainto_tsquery('english', query_text)
        ORDER BY text_rank DESC
        LIMIT match_count * 3
    ),
    combined_ranks AS (
        -- 4. RECIPROCAL RANK FUSION (RRF)
        SELECT 
            COALESCE(v.id, f.id) AS chunk_id,
            COALESCE(v.cos_sim, 0.0)::FLOAT AS sim,
            COALESCE(f.text_rank, 0.0)::FLOAT AS fts_score,
            (COALESCE(1.0 / (rrf_k + v.rank_v), 0.0) + COALESCE(1.0 / (rrf_k + f.rank_t), 0.0))::FLOAT AS score,
            v.rank_v::INT AS d_rank,
            f.rank_t::INT AS l_rank
        FROM vector_results v
        FULL OUTER JOIN fts_results f ON v.id = f.id
    )
    SELECT 
        c.id,
        c.source_record_id,
        c.organization_id,
        c.source_type,
        c.source_uri,
        c.source_timestamp,
        c.source_hash,
        c.ingestion_version,
        c.policy_version,
        c.author,
        c.author_role,
        c.title,
        c.content,
        c.permission,
        c.tags,
        c.entities,
        c.provenance,
        cr.sim::FLOAT AS similarity,
        cr.fts_score::FLOAT AS fts_rank,
        cr.score::FLOAT AS combined_score,
        COALESCE(cr.d_rank, 0) AS dense_rank,
        COALESCE(cr.l_rank, 0) AS lexical_rank
    FROM combined_ranks cr
    JOIN memory_chunks c ON cr.chunk_id = c.id
    ORDER BY cr.score DESC
    LIMIT match_count;
END;
$$;

-- Revoke execution from untrusted roles, grant exclusively to service_role
REVOKE EXECUTE ON FUNCTION hybrid_search(TEXT, VECTOR(768), INT, TEXT, TEXT[], INT) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION hybrid_search(TEXT, VECTOR(768), INT, TEXT, TEXT[], INT) TO service_role;

-- ============================================================================
-- 9. TRANSACTIONAL PERSISTENCE RPC (P1 Fix)
-- Atomically inserts or updates a SourceRecord and its derived MemoryChunks.
-- If any chunk insertion fails (e.g. invalid dimension, constraint violation),
-- the entire transaction rolls back cleanly.
-- Accessible exclusively to service_role.
-- ============================================================================

CREATE OR REPLACE FUNCTION persist_record_and_chunks(
    record_data JSONB,
    chunks_data JSONB
) RETURNS JSONB LANGUAGE plpgsql SECURITY INVOKER AS $$
DECLARE
    chunk_elem JSONB;
    inserted_chunks INT := 0;
BEGIN
    -- 1. Upsert Source Record
    INSERT INTO source_records (
        id, organization_id, source_type, source_uri, external_id,
        author_id, author_name, author_role, timestamp, raw_content,
        permission, metadata, hash, created_at
    ) VALUES (
        record_data->>'id',
        record_data->>'organization_id',
        record_data->>'source_type',
        record_data->>'source_uri',
        record_data->>'external_id',
        record_data->>'author_id',
        record_data->>'author_name',
        record_data->>'author_role',
        (record_data->>'timestamp')::TIMESTAMPTZ,
        record_data->>'raw_content',
        record_data->>'permission',
        COALESCE(record_data->'metadata', '{}'::jsonb),
        COALESCE(record_data->>'hash', ''),
        COALESCE((record_data->>'created_at')::TIMESTAMPTZ, TIMEZONE('utc'::text, NOW()))
    )
    ON CONFLICT (id) DO UPDATE SET
        organization_id = EXCLUDED.organization_id,
        source_type = EXCLUDED.source_type,
        source_uri = EXCLUDED.source_uri,
        external_id = EXCLUDED.external_id,
        author_id = EXCLUDED.author_id,
        author_name = EXCLUDED.author_name,
        author_role = EXCLUDED.author_role,
        timestamp = EXCLUDED.timestamp,
        raw_content = EXCLUDED.raw_content,
        permission = EXCLUDED.permission,
        metadata = EXCLUDED.metadata,
        hash = EXCLUDED.hash;

    -- 2. Upsert All Memory Chunks atomically
    FOR chunk_elem IN SELECT * FROM jsonb_array_elements(chunks_data)
    LOOP
        INSERT INTO memory_chunks (
            id, source_record_id, organization_id, source_type,
            source_uri, source_timestamp, source_hash, ingestion_version, policy_version,
            author, author_role, title, content, permission,
            tags, entities, embedding, embedding_status, embedding_model, embedding_dimension,
            provenance, created_at
        ) VALUES (
            chunk_elem->>'id',
            chunk_elem->>'source_record_id',
            chunk_elem->>'organization_id',
            chunk_elem->>'source_type',
            chunk_elem->>'source_uri',
            (chunk_elem->>'source_timestamp')::TIMESTAMPTZ,
            COALESCE(chunk_elem->>'source_hash', ''),
            COALESCE(chunk_elem->>'ingestion_version', 'v0'),
            COALESCE(chunk_elem->>'policy_version', 'v0'),
            chunk_elem->>'author',
            chunk_elem->>'author_role',
            chunk_elem->>'title',
            chunk_elem->>'content',
            chunk_elem->>'permission',
            ARRAY(SELECT jsonb_array_elements_text(COALESCE(chunk_elem->'tags', '[]'::jsonb))),
            COALESCE(chunk_elem->'entities', '{}'::jsonb),
            (chunk_elem->>'embedding')::VECTOR(768),
            COALESCE(chunk_elem->>'embedding_status', 'ready'),
            COALESCE(chunk_elem->>'embedding_model', 'models/text-embedding-004'),
            COALESCE((chunk_elem->>'embedding_dimension')::INT, 768),
            COALESCE(chunk_elem->'provenance', '{}'::jsonb),
            COALESCE((chunk_elem->>'created_at')::TIMESTAMPTZ, TIMEZONE('utc'::text, NOW()))
        )
        ON CONFLICT (id) DO UPDATE SET
            source_record_id = EXCLUDED.source_record_id,
            organization_id = EXCLUDED.organization_id,
            source_type = EXCLUDED.source_type,
            source_uri = EXCLUDED.source_uri,
            source_timestamp = EXCLUDED.source_timestamp,
            source_hash = EXCLUDED.source_hash,
            ingestion_version = EXCLUDED.ingestion_version,
            policy_version = EXCLUDED.policy_version,
            author = EXCLUDED.author,
            author_role = EXCLUDED.author_role,
            title = EXCLUDED.title,
            content = EXCLUDED.content,
            permission = EXCLUDED.permission,
            tags = EXCLUDED.tags,
            entities = EXCLUDED.entities,
            embedding = EXCLUDED.embedding,
            embedding_status = EXCLUDED.embedding_status,
            embedding_model = EXCLUDED.embedding_model,
            embedding_dimension = EXCLUDED.embedding_dimension,
            provenance = EXCLUDED.provenance;

        inserted_chunks := inserted_chunks + 1;
    END LOOP;

    RETURN jsonb_build_object(
        'success', true,
        'record_id', record_data->>'id',
        'chunks_count', inserted_chunks
    );
END;
$$;

REVOKE EXECUTE ON FUNCTION persist_record_and_chunks(JSONB, JSONB) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION persist_record_and_chunks(JSONB, JSONB) TO service_role;

-- ============================================================================
-- 10. DURABLE PROMOTION & APPROVAL RPC (P1 Fix)
-- Atomically promotes quarantined chunks in PostgreSQL and logs approval.
-- Accessible exclusively to service_role.
-- ============================================================================

CREATE OR REPLACE FUNCTION promote_quarantined_chunks(
    p_organization_id TEXT,
    p_import_hash TEXT,
    p_approved_by_user_id TEXT,
    p_approval_id TEXT
) RETURNS JSONB LANGUAGE plpgsql SECURITY INVOKER AS $$
DECLARE
    promoted_ids TEXT[] := '{}'::text[];
    chunk_row RECORD;
BEGIN
    FOR chunk_row IN 
        SELECT id, provenance FROM memory_chunks
        WHERE organization_id = p_organization_id
          AND permission = 'PENDING_REVIEW'
          AND (provenance->>'import_hash' = p_import_hash OR provenance->>'source_hash' = p_import_hash)
    LOOP
        UPDATE memory_chunks
        SET permission = 'INTERNAL_CORE',
            provenance = jsonb_set(
                jsonb_set(
                    jsonb_set(provenance, '{quarantined_from_internal}', 'false'::jsonb),
                    '{review_status}', '"approved_internal"'::jsonb
                ),
                '{approved_by_user_id}', to_jsonb(p_approved_by_user_id)
            )
        WHERE id = chunk_row.id;

        promoted_ids := array_append(promoted_ids, chunk_row.id);
    END LOOP;

    -- Also update matching source_records
    UPDATE source_records
    SET permission = 'INTERNAL_CORE',
        metadata = jsonb_set(
            jsonb_set(metadata, '{quarantined_from_internal}', 'false'::jsonb),
            '{review_status}', '"approved_internal"'::jsonb
        )
    WHERE organization_id = p_organization_id
      AND (hash = p_import_hash OR metadata->>'import_hash' = p_import_hash);

    -- Insert approval audit trail
    INSERT INTO import_approvals (
        id, organization_id, import_hash, approved_by_user_id, approved_at, promoted_chunk_ids
    ) VALUES (
        p_approval_id, p_organization_id, p_import_hash, p_approved_by_user_id,
        TIMEZONE('utc'::text, NOW()), promoted_ids
    );

    RETURN jsonb_build_object(
        'success', true,
        'promoted_count', array_length(promoted_ids, 1),
        'promoted_chunk_ids', promoted_ids
    );
END;
$$;

REVOKE EXECUTE ON FUNCTION promote_quarantined_chunks(TEXT, TEXT, TEXT, TEXT) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION promote_quarantined_chunks(TEXT, TEXT, TEXT, TEXT) TO service_role;
