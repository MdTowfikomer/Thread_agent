-- Migration 005: Transactional Persistence & Promotion RPCs
-- Installs atomic persist_record_and_chunks and promote_quarantined_chunks RPCs

-- 1. Atomic Record and Chunks Persistence
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
            tags, entities, embedding, embedding_model, embedding_dimension,
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

-- 2. Durable Promotion RPC
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
