import asyncio
import logging
from app.core.config import settings
from app.channels.gateway import discord_gateway_bot

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("discord_gateway_worker")

async def main():
    """
    Dedicated single-worker process for Discord Gateway ingestion.
    Runs separately from uvicorn web API workers to prevent multi-worker Gateway duplications.
    """
    token = settings.discord_bot_token
    if not token:
        logger.error("Cannot start Discord Gateway Worker: DISCORD_BOT_TOKEN is not set.")
        return

    logger.info("Starting standalone Discord Gateway Connector Worker...")
    try:
        await discord_gateway_bot.start()
    except (KeyboardInterrupt, asyncio.CancelledError):
        logger.info("Stopping Discord Gateway Worker...")
        await discord_gateway_bot.stop()

if __name__ == "__main__":
    asyncio.run(main())
