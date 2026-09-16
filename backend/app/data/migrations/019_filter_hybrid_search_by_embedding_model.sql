-- Migration 019: Server-side FTS Search RPC and Homogeneous Embedding Model Filter in Hybrid Search
-- Installs fts_search RPC function and updates hybrid_search RPC to filter vector candidates strictly by embedding_model

CREATE OR REPLACE FUNCTION fts_search(
    query_text TEXT,
    match_count INT,
    filter_organization_id TEXT,
    filter_permissions TEXT[]
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
    fts_rank FLOAT
) LANGUAGE plpgsql SECURITY INVOKER AS $$
BEGIN
    RETURN QUERY
    SELECT 
        mc.id,
        mc.source_record_id,
        mc.organization_id,
        mc.source_type,
        mc.source_uri,
        mc.source_timestamp,
        mc.source_hash,
        mc.ingestion_version,
        mc.policy_version,
        mc.author,
        mc.author_role,
        mc.title,
        mc.content,
        mc.permission,
        mc.tags,
        mc.entities,
        mc.provenance,
        ts_rank_cd(mc.fts, websearch_to_tsquery('english', query_text))::FLOAT AS fts_rank
    FROM memory_chunks mc
    WHERE mc.organization_id = filter_organization_id
      AND mc.permission = ANY(filter_permissions)
      AND mc.fts @@ websearch_to_tsquery('english', query_text)
    ORDER BY fts_rank DESC
    LIMIT match_count;
END;
$$;

REVOKE EXECUTE ON FUNCTION fts_search(TEXT, INT, TEXT, TEXT[]) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION fts_search(TEXT, INT, TEXT, TEXT[]) TO service_role;


CREATE OR REPLACE FUNCTION hybrid_search(
    query_text TEXT,
    query_embedding VECTOR(768),
    match_count INT,
    filter_organization_id TEXT,
    filter_permissions TEXT[],
    rrf_k INT DEFAULT 60,
    filter_embedding_model TEXT DEFAULT 'models/gemini-embedding-001'
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
        SELECT mc.*
        FROM memory_chunks mc
        WHERE mc.organization_id = filter_organization_id
          AND mc.permission = ANY(filter_permissions)
    ),
    vector_results AS (
        SELECT 
            pfc.id,
            1.0 - (pfc.embedding <=> query_embedding) AS cos_sim,
            ROW_NUMBER() OVER (ORDER BY pfc.embedding <=> query_embedding ASC) AS rank_v
        FROM pre_filtered_chunks pfc
        WHERE pfc.embedding IS NOT NULL
          AND pfc.embedding_model = filter_embedding_model
        ORDER BY pfc.embedding <=> query_embedding ASC
        LIMIT match_count * 3
    ),
    fts_results AS (
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

REVOKE EXECUTE ON FUNCTION hybrid_search(TEXT, VECTOR(768), INT, TEXT, TEXT[], INT, TEXT) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION hybrid_search(TEXT, VECTOR(768), INT, TEXT, TEXT[], INT, TEXT) TO service_role;
