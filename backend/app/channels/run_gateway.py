import asyncio
import logging
import sys

from app.core.config import settings
from app.channels.gateway import (
    discord_gateway_bot,
    try_acquire_gateway_advisory_lock,
    release_gateway_advisory_lock,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("discord_gateway_worker")


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
    asyncio.run(main())
