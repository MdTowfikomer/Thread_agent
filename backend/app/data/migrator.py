"""
Thread: Supabase Versioned Idempotent Migration Runner.
Discovers, validates, and executes versioned SQL migrations in order.
Maintains schema_migrations tracking table with SHA-256 checksums,
guarantees repeatable upgrades, and prevents retroactive migration drift.
"""

import os
import sys
import argparse
import hashlib
import logging
from pathlib import Path
from typing import List, Set, Dict, Optional, Any
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("app.data.migrator")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"
ADVISORY_LOCK_ID = 849201847192

class SchemaDriftError(Exception):
    """Raised when an applied migration file has been modified retroactively."""
    pass

class Migration:
    def __init__(self, version: str, path: Path):
        self.version = version
        self.path = path
        self._sql: Optional[str] = None
        self._checksum: Optional[str] = None

    @property
    def sql(self) -> str:
        if self._sql is None:
            self._sql = self.path.read_text(encoding="utf-8")
        return self._sql

    @property
    def checksum(self) -> str:
        if self._checksum is None:
            # Normalize whitespace / line-endings so checksum is deterministic across OS environments
            normalized = "\n".join(line.rstrip() for line in self.sql.splitlines()).strip()
            self._checksum = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
        return self._checksum

    def __repr__(self) -> str:
        return f"<Migration {self.version} ({self.checksum[:8]})>"

class MigrationRunner:
    def __init__(self, migrations_dir: Optional[Path] = None):
        self.migrations_dir = migrations_dir or MIGRATIONS_DIR

    def get_migrations(self) -> List[Migration]:
        """Discovers all .sql migration files in the migrations directory, sorted by filename."""
        if not self.migrations_dir.exists():
            return []
        files = sorted(self.migrations_dir.glob("*.sql"), key=lambda p: p.name)
        return [Migration(version=f.stem, path=f) for f in files]

    def init_tracker_table(self, cursor) -> None:
        """Ensures the schema_migrations tracker table exists with checksum tracking."""
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version TEXT PRIMARY KEY,
                checksum TEXT,
                applied_at TIMESTAMPTZ DEFAULT TIMEZONE('utc'::text, NOW()) NOT NULL
            );
            ALTER TABLE schema_migrations ADD COLUMN IF NOT EXISTS checksum TEXT;
        """)

    def validate_and_sync_checksums(self, cursor, migrations: List[Migration]) -> None:
        """
        Validates SHA-256 checksums of all applied migrations against file contents.
        If an applied migration was modified retroactively, raises SchemaDriftError.
        Backfills checksums for any legacy records missing them.
        """
        self.init_tracker_table(cursor)
        cursor.execute("SELECT version, checksum FROM schema_migrations;")
        db_records = {}
        for row in cursor.fetchall():
            if len(row) >= 2:
                db_records[row[0]] = row[1]
            elif len(row) == 1:
                db_records[row[0]] = None
        migration_map = {m.version: m for m in migrations}

        for version, recorded_checksum in db_records.items():
            if version in migration_map:
                current_checksum = migration_map[version].checksum
                if recorded_checksum:
                    if recorded_checksum != current_checksum:
                        raise SchemaDriftError(
                            f"CRITICAL: Applied migration '{version}' was modified retroactively! "
                            f"Recorded checksum: {recorded_checksum}, Current file checksum: {current_checksum}. "
                            "Applied migrations are permanently immutable. Put all changes into a new migration file."
                        )
                else:
                    # Backfill checksum from frozen file
                    cursor.execute(
                        "UPDATE schema_migrations SET checksum = %s WHERE version = %s AND checksum IS NULL;",
                        (current_checksum, version)
                    )

    def get_applied_migrations(self, cursor) -> Set[str]:
        """Retrieves set of already applied migration versions."""
        self.init_tracker_table(cursor)
        cursor.execute("SELECT version FROM schema_migrations;")
        return {row[0] for row in cursor.fetchall()}

    def record_applied_migration(self, cursor, migration: Migration) -> None:
        """Records a migration and its checksum as successfully applied."""
        cursor.execute(
            """
            INSERT INTO schema_migrations (version, checksum, applied_at)
            VALUES (%s, %s, TIMEZONE('utc'::text, NOW()))
            ON CONFLICT (version) DO UPDATE SET
                checksum = COALESCE(schema_migrations.checksum, EXCLUDED.checksum);
            """,
            (migration.version, migration.checksum)
        )

    def acquire_advisory_lock(self, cursor) -> None:
        """Acquires a PostgreSQL advisory lock to serialize concurrent migration workers."""
        logger.info(f"Acquiring PostgreSQL advisory lock ({ADVISORY_LOCK_ID})...")
        cursor.execute("SELECT pg_advisory_lock(%s);", (ADVISORY_LOCK_ID,))
        logger.info("PostgreSQL advisory lock acquired.")

    def release_advisory_lock(self, conn, cursor) -> None:
        """
        Releases the PostgreSQL advisory lock safely.
        Ensures any aborted transaction is rolled back before issuing the unlock query,
        preventing lock leaks on migration failures.
        """
        try:
            conn.rollback()
        except Exception:
            pass
        try:
            cursor.execute("SELECT pg_advisory_unlock(%s);", (ADVISORY_LOCK_ID,))
            logger.info("PostgreSQL advisory lock released.")
        except Exception as e:
            logger.warning(f"Error releasing advisory lock: {e}")
        try:
            conn.commit()
        except Exception:
            pass

    def apply_migration(self, conn, migration: Migration) -> bool:
        """Executes a single migration within a database transaction."""
        logger.info(f"Applying migration: {migration.version} (checksum: {migration.checksum[:8]})")
        try:
            with conn.cursor() as cur:
                cur.execute(migration.sql)
                self.record_applied_migration(cur, migration)
            conn.commit()
            logger.info(f"Successfully applied: {migration.version}")
            return True
        except Exception as e:
            conn.rollback()
            logger.error(f"Failed to apply migration {migration.version}: {e}")
            raise

    def run_all(self, conn) -> List[str]:
        """
        Runs all pending migrations in order against the provided psycopg2 connection.
        Acquires a PostgreSQL advisory lock, validates checksums of applied migrations
        to prevent retroactive drift, and applies pending migrations sequentially.
        """
        migrations = self.get_migrations()
        if not migrations:
            logger.warning("No migration files found.")
            return []

        with conn.cursor() as cur:
            self.acquire_advisory_lock(cur)
            try:
                self.validate_and_sync_checksums(cur, migrations)
                conn.commit()
                applied = self.get_applied_migrations(cur)
                pending = [m for m in migrations if m.version not in applied]
                if not pending:
                    logger.info("All migrations are already up to date.")
                    return []

                logger.info(f"Found {len(pending)} pending migrations: {[m.version for m in pending]}")
                applied_now = []
                for migration in pending:
                    self.apply_migration(conn, migration)
                    applied_now.append(migration.version)

                return applied_now
            finally:
                self.release_advisory_lock(conn, cur)

    def get_status(self, conn) -> Dict[str, bool]:
        """Returns map of migration versions to their applied status."""
        migrations = self.get_migrations()
        with conn.cursor() as cur:
            self.init_tracker_table(cur)
            applied = self.get_applied_migrations(cur)
        return {m.version: (m.version in applied) for m in migrations}

    def get_status_details(self, conn) -> Dict[str, Dict[str, Any]]:
        """Returns detailed map of migration versions including checksums and applied dates."""
        migrations = self.get_migrations()
        with conn.cursor() as cur:
            self.init_tracker_table(cur)
            cur.execute("SELECT version, checksum, applied_at FROM schema_migrations;")
            applied_map = {row[0]: {"checksum": row[1], "applied_at": row[2]} for row in cur.fetchall()}

        details = {}
        for m in migrations:
            is_applied = m.version in applied_map
            details[m.version] = {
                "applied": is_applied,
                "file_checksum": m.checksum,
                "db_checksum": applied_map.get(m.version, {}).get("checksum"),
                "applied_at": applied_map.get(m.version, {}).get("applied_at")
            }
        return details

    def dump_all_sql(self) -> str:
        """Concatenates all migrations into a single consolidated script."""
        migrations = self.get_migrations()
        chunks = [
            "-- Thread AI: Consolidated Supabase Migrations\n"
            "-- Autogenerated from versioned migrations\n"
        ] + [
            f"-- ============================================================================\n"
            f"-- Migration: {m.version} (SHA256: {m.checksum})\n"
            f"-- ============================================================================\n\n"
            f"{m.sql.strip()}\n"
            for m in migrations
        ]
        return "\n\n".join(chunks)

def get_connection(db_url: Optional[str] = None):
    """Creates a psycopg2 database connection from environment or argument."""
    url = db_url or os.getenv("SUPABASE_DB_URL") or os.getenv("DATABASE_URL")
    if not url:
        raise ValueError("Database connection URL not specified. Set SUPABASE_DB_URL or DATABASE_URL.")
    
    import psycopg2
    return psycopg2.connect(url)

def main():
    parser = argparse.ArgumentParser(description="Thread Supabase Migration Runner")
    parser.add_argument("--up", action="store_true", help="Apply all pending migrations")
    parser.add_argument("--status", action="store_true", help="Print migration status and checksums")
    parser.add_argument("--dump", action="store_true", help="Dump consolidated SQL from all migrations")
    parser.add_argument("--check", action="store_true", help="Validate checksums of applied migrations")
    parser.add_argument("--db-url", type=str, default=None, help="Explicit database URL override")

    args = parser.parse_args()

    runner = MigrationRunner()

    if args.dump:
        print(runner.dump_all_sql())
        return

    try:
        conn = get_connection(args.db_url)
    except Exception as e:
        logger.error(f"Failed to connect to database: {e}")
        sys.exit(1)

    try:
        if args.check:
            with conn.cursor() as cur:
                runner.validate_and_sync_checksums(cur, runner.get_migrations())
            conn.commit()
            print("Migration checksums validated and synchronized successfully.")

        if args.status or args.check:
            details = runner.get_status_details(conn)
            print("\nMigration Status & Checksums:")
            drift_detected = False
            for version, info in details.items():
                mark = "[X]" if info["applied"] else "[ ]"
                state = "Applied" if info["applied"] else "Pending"
                file_cs = info["file_checksum"][:8]
                db_cs = info["db_checksum"][:8] if info["db_checksum"] else "none"
                print(f"  {mark} {state} - {version} (file: {file_cs}, db: {db_cs})")
                if info["applied"] and info["db_checksum"] and info["db_checksum"] != info["file_checksum"]:
                    print(f"      WARNING: Checksum drift detected on {version}!")
                    drift_detected = True
            print()
            if args.check and drift_detected:
                logger.error("Schema drift check failed: one or more applied migrations were modified.")
                sys.exit(1)
            return

        if args.up:
            applied = runner.run_all(conn)
            print(f"\nApplied {len(applied)} migrations.")
            return

        parser.print_help()
    finally:
        conn.close()

if __name__ == "__main__":
    main()
