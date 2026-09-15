-- Migration 010: Seed Thread_Agent Authoritative Repository Binding
-- Binds GitHub repository ID 1371393965 (MdTowfikomer/Thread_agent) to organization gdg_mcet.
-- Removes any legacy demo repository bindings from production storage.

-- 1. Upsert authoritative repository binding for Thread_Agent
INSERT INTO github_repository_bindings (
    id,
    organization_id,
    installation_id,
    repository_id,
    repository_name,
    is_active,
    bound_at,
    metadata
)
VALUES (
    'bind_thread_agent_1371393965',
    'gdg_mcet',
    'gh_inst_thread_agent',
    '1371393965',
    'mdtowfikomer/thread_agent',
    TRUE,
    TIMEZONE('utc'::text, NOW()),
    '{"full_name": "MdTowfikomer/Thread_agent"}'::jsonb
)
ON CONFLICT (repository_id) DO UPDATE SET
    organization_id = EXCLUDED.organization_id,
    repository_name = EXCLUDED.repository_name,
    installation_id = EXCLUDED.installation_id,
    is_active = EXCLUDED.is_active,
    metadata = EXCLUDED.metadata;

-- 2. Remove legacy non-existent fixture/demo repository bindings
DELETE FROM github_repository_bindings WHERE repository_id = '1029384';
