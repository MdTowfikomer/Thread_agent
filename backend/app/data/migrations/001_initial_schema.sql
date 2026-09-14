-- Migration 001: Initial Schema
-- Base tables, extensions, and indexes for Thread AI Organizational Context Agent

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

-- 1. Source Records Table
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

-- 2. Memory Chunks Table
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

CREATE INDEX IF NOT EXISTS idx_memory_chunks_org_perm ON memory_chunks(organization_id, permission);
CREATE INDEX IF NOT EXISTS idx_memory_chunks_fts ON memory_chunks USING GIN(fts);
CREATE INDEX IF NOT EXISTS idx_memory_chunks_embedding ON memory_chunks USING hnsw (embedding vector_cosine_ops);

-- 3. Guild Installation Store
CREATE TABLE IF NOT EXISTS guild_installations (
    guild_id TEXT PRIMARY KEY,
    organization_id TEXT NOT NULL,
    guild_name TEXT,
    installed_at TIMESTAMPTZ DEFAULT TIMEZONE('utc'::text, NOW()) NOT NULL,
    is_active BOOLEAN DEFAULT TRUE NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_guild_installations_org ON guild_installations(organization_id);

-- 4. Import Approval and Quarantine Store
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

-- 5. Discord Interaction Cache
CREATE TABLE IF NOT EXISTS processed_interactions (
    interaction_id TEXT PRIMARY KEY,
    processed_at TIMESTAMPTZ DEFAULT TIMEZONE('utc'::text, NOW()) NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_processed_interactions_expires ON processed_interactions(expires_at);
