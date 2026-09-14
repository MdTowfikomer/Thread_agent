import os
import pytest
from unittest.mock import MagicMock, call
from pathlib import Path
from dotenv import load_dotenv
from app.data.migrator import MigrationRunner, Migration

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "..", ".env"))

def test_migration_runner_discovers_migrations_in_order():
    runner = MigrationRunner()
    migrations = runner.get_migrations()
    assert len(migrations) >= 6, "Must discover at least 6 migration files"
    
    versions = [m.version for m in migrations]
    assert versions[0].startswith("001_initial_schema")
    assert versions[1].startswith("002_provenance_and_schema_hardening")
    assert versions[2].startswith("003_zero_direct_access_rls")
    assert versions[3].startswith("004_hybrid_search_rpc")
    assert versions[4].startswith("005_transactional_rpcs")
    assert versions[5].startswith("006_reembedding_and_status_tracking")

def test_migration_sql_idempotency_and_safe_repeatability():
    runner = MigrationRunner()
    migrations = runner.get_migrations()
    migration_map = {m.version: m.sql for m in migrations}

    # 1. 001_initial_schema has IF NOT EXISTS
    sql_001 = migration_map["001_initial_schema"]
    assert "CREATE TABLE IF NOT EXISTS schema_migrations" in sql_001
    assert "CREATE TABLE IF NOT EXISTS source_records" in sql_001
    assert "CREATE TABLE IF NOT EXISTS memory_chunks" in sql_001

    # 2. 002_provenance_and_schema_hardening uses explicit ALTER TABLE and backfills timestamps
    sql_002 = migration_map["002_provenance_and_schema_hardening"]
    assert "ALTER TABLE source_records ADD COLUMN IF NOT EXISTS source_uri TEXT;" in sql_002
    assert "ALTER TABLE memory_chunks ADD COLUMN IF NOT EXISTS source_timestamp TIMESTAMPTZ;" in sql_002
    assert "UPDATE memory_chunks mc" in sql_002
    assert "SET source_timestamp = sr.timestamp" in sql_002
    assert "CREATE TABLE IF NOT EXISTS legacy_unverifiable_chunks" in sql_002
    assert "INSERT INTO legacy_unverifiable_chunks" in sql_002
    assert "SET source_timestamp = created_at" not in sql_002, "Must NOT fabricate source_timestamp from ingestion created_at"
    assert "ALTER TABLE memory_chunks ALTER COLUMN source_timestamp SET NOT NULL;" in sql_002
    assert "fts TSVECTOR GENERATED ALWAYS AS" in sql_002
    assert "ALTER TABLE memory_chunks ADD COLUMN IF NOT EXISTS embedding_v2 VECTOR(768);" in sql_002

    # 3. 003_zero_direct_access_rls uses DROP POLICY IF EXISTS before CREATE POLICY
    sql_003 = migration_map["003_zero_direct_access_rls"]
    assert 'DROP POLICY IF EXISTS "service_role_all_source_records" ON source_records;' in sql_003
    assert 'CREATE POLICY "service_role_all_source_records" ON source_records' in sql_003
    assert 'DROP POLICY IF EXISTS "service_role_all_memory_chunks" ON memory_chunks;' in sql_003
    assert 'CREATE POLICY "service_role_all_memory_chunks" ON memory_chunks' in sql_003
    assert "ENABLE ROW LEVEL SECURITY;" in sql_003
    assert "FORCE ROW LEVEL SECURITY;" in sql_003

    # 4. 004_hybrid_search_rpc uses CREATE OR REPLACE FUNCTION with SECURITY INVOKER
    sql_004 = migration_map["004_hybrid_search_rpc"]
    assert "CREATE OR REPLACE FUNCTION hybrid_search" in sql_004
    assert "SECURITY INVOKER" in sql_004

    # 5. 005_transactional_rpcs uses CREATE OR REPLACE FUNCTION
    sql_005 = migration_map["005_transactional_rpcs"]
    assert "CREATE OR REPLACE FUNCTION persist_record_and_chunks" in sql_005
    assert "CREATE OR REPLACE FUNCTION promote_quarantined_chunks" in sql_005

    # 6. 006_reembedding_and_status_tracking (Forward migration hardening)
    assert "006_reembedding_and_status_tracking" in migration_map
    sql_006 = migration_map["006_reembedding_and_status_tracking"]
    assert "legacy_embedding_128" in sql_006
    assert "embedding_status" in sql_006
    assert "embedding_model" in sql_006
    assert "embedding_dimension" in sql_006
    assert "provenance" in sql_006
    assert "embedding_status = 'ready'" in sql_006

def test_migration_runner_state_tracking_and_idempotent_execution():
    runner = MigrationRunner()
    
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

    # Simulate: No migrations applied yet
    mock_cursor.fetchall.return_value = []

    applied = runner.run_all(mock_conn)
    assert len(applied) >= 7
    assert "001_initial_schema" in applied
    assert "005_transactional_rpcs" in applied
    assert "006_reembedding_and_status_tracking" in applied
    assert "007_reembedding_leases_and_deadletter" in applied

    # Verify advisory lock acquired and released
    lock_calls = [
        c for c in mock_cursor.execute.call_args_list 
        if "pg_advisory_lock" in str(c) or "pg_advisory_unlock" in str(c)
    ]
    assert len(lock_calls) >= 2, "Must execute pg_advisory_lock and pg_advisory_unlock"
    assert "pg_advisory_lock" in str(lock_calls[0])
    assert "pg_advisory_unlock" in str(lock_calls[-1])

    # Verify commit called for each migration
    assert mock_conn.commit.call_count >= len(applied)

    # Second run: All migrations already applied
    mock_cursor.fetchall.return_value = [(v,) for v in applied]
    applied_second_run = runner.run_all(mock_conn)
    assert len(applied_second_run) == 0, "Second run must be idempotent and apply 0 migrations"

def test_migration_runner_releases_advisory_lock_on_failure():
    runner = MigrationRunner()
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

    # Simulate error on first migration execution
    mock_cursor.fetchall.return_value = []
    
    def fail_on_migration(sql, *args):
        if "001_initial_schema" in str(sql) or "CREATE TABLE" in str(sql):
            raise RuntimeError("Database DDL execution failure")
        return None

    mock_cursor.execute.side_effect = fail_on_migration

    with pytest.raises(RuntimeError) as exc_info:
        runner.run_all(mock_conn)
    assert "Database DDL execution failure" in str(exc_info.value)

    # CRITICAL P2 CHECK: Rollback called and unlock executed despite failure
    assert mock_conn.rollback.called, "Must roll back transaction on failure"
    unlock_calls = [
        c for c in mock_cursor.execute.call_args_list 
        if "pg_advisory_unlock" in str(c)
    ]
    assert len(unlock_calls) >= 1, "Advisory lock MUST be released even if migration fails"

def test_dump_all_sql_produces_valid_consolidated_script():
    runner = MigrationRunner()
    dump = runner.dump_all_sql()
    assert "-- Thread AI: Consolidated Supabase Migrations" in dump
    assert "CREATE TABLE IF NOT EXISTS source_records" in dump
    assert "CREATE OR REPLACE FUNCTION persist_record_and_chunks" in dump
    assert 'DROP POLICY IF EXISTS "service_role_all_source_records"' in dump

def test_manifest_validation_and_drift_detection():
    from app.data.migrator import SchemaDriftError, Migration
    runner = MigrationRunner()
    manifest = runner.load_manifest()
    assert len(manifest) >= 7, "Manifest must contain all frozen historical migrations 001-007"
    assert "001_initial_schema" in manifest
    assert "002_provenance_and_schema_hardening" in manifest
    assert "007_reembedding_leases_and_deadletter" in manifest

    mock_cursor = MagicMock()
    # Case 1: Tampered local migration file differing from reviewed historical manifest
    tampered_migration = Migration("001_initial_schema", runner.migrations_dir / "001_initial_schema.sql")
    tampered_migration._sql = "-- TAMPERED SQL"

    with pytest.raises(SchemaDriftError) as exc_info:
        runner.validate_and_sync_checksums(mock_cursor, [tampered_migration])
    assert "does not match the reviewed historical manifest" in str(exc_info.value)

    # Case 2: Database record with tampered checksum
    valid_migrations = runner.get_migrations()
    mock_cursor.fetchall.return_value = [("001_initial_schema", "deadbeef_tampered_checksum")]

    with pytest.raises(SchemaDriftError) as exc_info2:
        runner.validate_and_sync_checksums(mock_cursor, valid_migrations)
    assert "checksum mismatch" in str(exc_info2.value)

    # Case 3: Legacy DB record missing checksum is backfilled strictly from manifest
    mock_cursor.fetchall.return_value = [("001_initial_schema", None)]
    runner.validate_and_sync_checksums(mock_cursor, valid_migrations)
    backfill_calls = [c for c in mock_cursor.execute.call_args_list if "UPDATE schema_migrations" in str(c)]
    assert len(backfill_calls) == 1
    assert manifest["001_initial_schema"]["sha256"] in str(backfill_calls[0])

def test_live_migration_smoke_test():
    """
    Live migration smoke test:
    When a live PostgreSQL instance is configured (via SUPABASE_DB_URL or DATABASE_URL)
    and THREAD_RUN_LIVE_SUPABASE_TESTS=1, executes full migration run and confirms idempotence.
    """
    if os.getenv("THREAD_RUN_LIVE_SUPABASE_TESTS") != "1":
        pytest.skip("Set THREAD_RUN_LIVE_SUPABASE_TESTS=1 to run live database migration tests.")

    db_url = os.getenv("SUPABASE_DB_URL") or os.getenv("DATABASE_URL")
    if not db_url:
        pytest.skip("No SUPABASE_DB_URL or DATABASE_URL provided for live migration smoke test.")

    import psycopg2
    conn = psycopg2.connect(db_url)
    runner = MigrationRunner()

    try:
        # Run 1: Apply all pending migrations
        first_run = runner.run_all(conn)
        # Run 2: Idempotent repeat run must apply 0 migrations without error
        second_run = runner.run_all(conn)
        assert len(second_run) == 0, "Live rerun must detect all migrations already applied"

        # Verify status
        status = runner.get_status(conn)
        for version, is_applied in status.items():
            assert is_applied is True, f"Migration {version} must be recorded as applied"
    finally:
        conn.close()
