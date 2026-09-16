import asyncio
import logging
import os
import sys
import urllib.parse
from typing import List

from app.core.config import settings
from app.channels.gateway import (
    discord_gateway_bot,
    try_acquire_gateway_advisory_lock,
    release_gateway_advisory_lock,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("discord_gateway_worker")


def run_preflight() -> int:
    """
    Preflight deployment validation for the dedicated Discord Gateway worker.
    Validates only required worker environment variables and database connectivity.
    Strictly prints NO secrets, tokens, or passwords.
    Returns: 0 on success, 1 on failure.
    """
    print("================================================================")
    print("Thread Discord Gateway Worker - Deployment Preflight Validation")
    print("================================================================")
    errors: List[str] = []

    # 1. DISCORD_BOT_TOKEN
    token = os.getenv("DISCORD_BOT_TOKEN", "").strip()
    if not token:
        errors.append("DISCORD_BOT_TOKEN is missing or empty.")
        print("[FAIL] DISCORD_BOT_TOKEN: MISSING")
    else:
        print(f"[OK]   DISCORD_BOT_TOKEN: Present (length: {len(token)} chars)")

    # 2. SUPABASE_DB_URL
    db_url = (os.getenv("SUPABASE_DB_URL") or os.getenv("DATABASE_URL") or "").strip()
    if not db_url:
        errors.append("SUPABASE_DB_URL (or DATABASE_URL) is missing or empty.")
        print("[FAIL] SUPABASE_DB_URL: MISSING")
    else:
        try:
            parsed = urllib.parse.urlparse(db_url)
            host = parsed.hostname or "configured"
            port = parsed.port or 5432
            database = parsed.path.lstrip("/") or "postgres"
            print(f"[OK]   SUPABASE_DB_URL: Present (host: {host}, port: {port}, db: {database})")
        except Exception:
            print("[OK]   SUPABASE_DB_URL: Present")

    # 3. LLM API Key (GEMINI_API_KEY or OPENAI_API_KEY)
    gemini_key = os.getenv("GEMINI_API_KEY", "").strip()
    openai_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not (gemini_key or openai_key):
        errors.append("Neither GEMINI_API_KEY nor OPENAI_API_KEY is configured.")
        print("[FAIL] LLM API Key: MISSING (neither GEMINI_API_KEY nor OPENAI_API_KEY set)")
    else:
        active_llm = "GEMINI_API_KEY" if gemini_key else "OPENAI_API_KEY"
        print(f"[OK]   LLM API Key: Present ({active_llm} configured)")

    # 4. Verification that unnecessary secrets are NOT required
    if not os.getenv("THREAD_JWT_SECRET"):
        print("[OK]   THREAD_JWT_SECRET: Omitted (correctly excluded from gateway worker)")
    else:
        print("[INFO] THREAD_JWT_SECRET: Present in environment (ignored by gateway worker)")

    if not os.getenv("SUPABASE_SERVICE_ROLE_KEY"):
        print("[OK]   SUPABASE_SERVICE_ROLE_KEY: Omitted (gateway uses direct PostgreSQL)")
    else:
        print("[INFO] SUPABASE_SERVICE_ROLE_KEY: Present in environment")

    # 5. Database connectivity and table existence test
    if db_url and os.getenv("THREAD_MOCK_DB_PREFLIGHT") != "1":
        try:
            import psycopg2
            with psycopg2.connect(db_url, connect_timeout=8) as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT 1;")
                    cur.fetchone()
                    print("[OK]   PostgreSQL connectivity: Successful (ping OK)")

                    # Check for required tables
                    cur.execute("""
                        SELECT table_name FROM information_schema.tables 
                        WHERE table_schema = 'public' 
                          AND table_name IN ('discord_guild_installations', 'channel_policies');
                    """)
                    found_tables = {row[0] for row in cur.fetchall()}
                    if "discord_guild_installations" in found_tables and "channel_policies" in found_tables:
                        print("[OK]   Authoritative Schema: discord_guild_installations and channel_policies verified")
                    else:
                        missing = {"discord_guild_installations", "channel_policies"} - found_tables
                        errors.append(f"Missing required database tables: {missing}. Run migrations first.")
                        print(f"[FAIL] Authoritative Schema: Missing tables {missing}")
        except Exception as exc:
            errors.append(f"PostgreSQL connectivity failure: {type(exc).__name__}: {exc}")
            print(f"[FAIL] PostgreSQL connectivity: {type(exc).__name__}: {exc}")
    elif os.getenv("THREAD_MOCK_DB_PREFLIGHT") == "1":
        print("[OK]   PostgreSQL connectivity: Mocked for preflight smoke test")
        print("[OK]   Authoritative Schema: Mocked for preflight smoke test")

    print("----------------------------------------------------------------")
    if errors:
        print(f"[RESULT] PREFLIGHT FAILED: {len(errors)} error(s) detected.")
        for err in errors:
            print(f"  [ERROR] {err}")
        print("================================================================")
        return 1

    print("[RESULT] PREFLIGHT PASSED: Gateway worker configuration is valid.")
    print("================================================================")
    return 0


async def main():
    """
    Dedicated single-worker process for Discord Gateway ingestion (Discloud / Production worker).
    Runs separately from uvicorn web API workers to prevent multi-worker Gateway duplications.
    Acquires PostgreSQL advisory lock with fail_on_db_error=True before starting.
    """
    token = settings.discord_bot_token
    if not token:
        logger.error("Cannot start Discord Gateway Worker: DISCORD_BOT_TOKEN is not set.")
        sys.exit(1)

    # 1. Acquire PostgreSQL advisory lock with fail_on_db_error=True
    # If the database check itself errors, fail closed (RuntimeError is raised).
    lock_conn = None
    try:
        lock_conn = try_acquire_gateway_advisory_lock(fail_on_db_error=True)
    except Exception as exc:
        logger.error(f"Failed to acquire advisory lock due to database error: {exc}")
        raise

    # 2. A held lock is standby. If another active peer holds the lock, remain in standby.
    while lock_conn is None:
        logger.info("gateway worker standby")
        discord_gateway_bot.set_standby()
        await asyncio.sleep(15)
        try:
            lock_conn = try_acquire_gateway_advisory_lock(fail_on_db_error=True)
        except Exception as exc:
            logger.error(f"Failed to check advisory lock in standby: {exc}")
            raise

    # 3. Once lock is acquired, this instance is the active gateway leader
    logger.info("gateway worker started")

    # Hook on_client_ready to log 'gateway worker connected'
    orig_on_client_ready = discord_gateway_bot.on_client_ready

    async def hooked_on_client_ready():
        await orig_on_client_ready()
        logger.info("gateway worker connected")

    discord_gateway_bot.on_client_ready = hooked_on_client_ready

    try:
        await discord_gateway_bot.start()
    except (KeyboardInterrupt, asyncio.CancelledError):
        logger.info("Stopping Discord Gateway Worker...")
    finally:
        await discord_gateway_bot.stop()
        if lock_conn:
            release_gateway_advisory_lock(lock_conn)


if __name__ == "__main__":
    if "--preflight" in sys.argv or "-p" in sys.argv:
        sys.exit(run_preflight())
    asyncio.run(main())
