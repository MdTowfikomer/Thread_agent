-- Migration 006: Re-embedding & Status Tracking
-- Adds embedding_status and legacy_embedding_128 columns,
-- excludes pending_reembed chunks from dense vector scoring in hybrid_search,
-- and updates transactional persistence RPC with embedding_status.

-- 1. Add embedding_status and legacy_embedding_128 columns
ALTER TABLE memory_chunks ADD COLUMN IF NOT EXISTS embedding_status TEXT DEFAULT 'ready' NOT NULL;
ALTER TABLE memory_chunks ADD COLUMN IF NOT EXISTS legacy_embedding_128 VECTOR(128);

-- 2. Safe Vector Dimension Check & Migration State (for 128-to-768 upgrade)
DO $$
DECLARE
    current_dim INT;
BEGIN
    SELECT atttypmod INTO current_dim
    FROM pg_attribute 
    WHERE attrelid = 'memory_chunks'::regclass AND attname = 'embedding';

    IF current_dim IS NOT NULL AND current_dim != 768 THEN
        -- Incompatible older dimension (e.g. vector(128)):
        -- Preserve legacy vectors into legacy_embedding_128
        UPDATE memory_chunks 
        SET legacy_embedding_128 = embedding 
        WHERE embedding IS NOT NULL;

        -- Mark chunks requiring 768-dim upgrade as pending_reembed
        UPDATE memory_chunks 
        SET embedding_status = 'pending_reembed' 
        WHERE legacy_embedding_128 IS NOT NULL;

        -- Replace embedding column with clean vector(768)
        DROP INDEX IF EXISTS idx_memory_chunks_embedding;
        ALTER TABLE memory_chunks DROP COLUMN embedding;
        ALTER TABLE memory_chunks ADD COLUMN embedding VECTOR(768);
    END IF;

    -- Ensure HNSW index is configured appropriately
    IF NOT EXISTS (SELECT 1 FROM memory_chunks WHERE embedding_status = 'pending_reembed' OR embedding IS NULL) THEN
        ALTER TABLE memory_chunks ALTER COLUMN embedding SET NOT NULL;
        DROP INDEX IF EXISTS idx_memory_chunks_embedding;
        CREATE INDEX IF NOT EXISTS idx_memory_chunks_embedding ON memory_chunks USING hnsw (embedding vector_cosine_ops);
    ELSE
        DROP INDEX IF EXISTS idx_memory_chunks_embedding;
        CREATE INDEX IF NOT EXISTS idx_memory_chunks_embedding ON memory_chunks USING hnsw (embedding vector_cosine_ops)
            WHERE embedding_status = 'ready' AND embedding IS NOT NULL;
    END IF;
END $$;

-- 3. Update Pre-Retrieval ACL Hybrid Search RPC (Dense search excludes pending_reembed)
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
        -- 2. DENSE VECTOR RETRIEVAL ON AUTHORIZED CHUNKS
        -- Exclude chunks pending re-embedding from dense vector scoring
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
        -- 3. FULL-TEXT SEARCH (SPARSE) ON AUTHORIZED CHUNKS
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

REVOKE EXECUTE ON FUNCTION hybrid_search(TEXT, VECTOR(768), INT, TEXT, TEXT[], INT) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION hybrid_search(TEXT, VECTOR(768), INT, TEXT, TEXT[], INT) TO service_role;

-- 4. Update persist_record_and_chunks RPC with embedding_status
CREATE OR REPLACE FUNCTION persist_record_and_chunks(
    record_data JSONB,
    chunks_data JSONB
) RETURNS JSONB LANGUAGE plpgsql SECURITY INVOKER AS $$
DECLARE
    chunk_elem JSONB;
    inserted_chunks INT := 0;
BEGIN
    -- Upsert Source Record
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

    -- Upsert All Memory Chunks atomically
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
