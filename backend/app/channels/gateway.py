import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Optional, Dict, Any, Tuple, List

import discord

from app.core.config import settings
from app.core.canonical import (
    ChannelType,
    ChannelMessage,
    SourceRecord,
    MemoryChunk,
    IngestionReceipt,
    IngestionTrustMode
)
from app.channels.installation import guild_installation_store, GuildInstallationStore
from app.channels.discord import trusted_discord_connector_service, parse_iso_datetime, _TrustedDiscordConnectorService
from app.memory.store import memory_store, MemoryStore
from app.memory.repository import memory_repository, MemoryRepository

logger = logging.getLogger(__name__)

class DiscordThreadClient(discord.Client):
    """
    Robust Discord client powered by discord.py.
    Handles Gateway protocol v10 lifecycle, heartbeat ACK detection, sequence tracking,
    reconnects, resume sessions, and intents natively.
    """
    def __init__(self, bot_service: "DiscordGatewayBot", *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.bot_service = bot_service

    async def on_ready(self):
        logger.info(f"Discord Gateway Bot logged in as {self.user} (ID: {self.user.id})")

    async def on_message(self, message: discord.Message):
        self.bot_service.handle_discord_message(message)

class DiscordGatewayBot:
    """
    Authenticated Discord Gateway Bot using DISCORD_BOT_TOKEN and Message Content Intent.
    Ingests live MESSAGE_CREATE channel events from Discord infrastructure into Thread Core Memory.

    SECURITY GUARANTEES:
    1. Authenticates against Discord Gateway using official discord.py client with full session resilience.
    2. Resolves organization_id authoritatively from server-owned GuildInstallationStore.
       Unknown or unmapped guilds are immediately dropped.
    3. Ignores bot messages to prevent echo loops.
    4. Routes verified live events into trusted_discord_connector_service with IngestionTrustMode.VERIFIED_CONNECTOR.
    """
    def __init__(
        self,
        installation_store: Optional[GuildInstallationStore] = None,
        connector_service: Optional[_TrustedDiscordConnectorService] = None,
        mem_store: Optional[MemoryStore] = None,
        mem_repo: Optional[MemoryRepository] = None
    ):
        self.installation_store = installation_store or guild_installation_store
        self.connector_service = connector_service or trusted_discord_connector_service
        self.memory_store = mem_store or memory_store
        self.repository = mem_repo or memory_repository
        self._running = False
        self._client: Optional[DiscordThreadClient] = None
        self._task: Optional[asyncio.Task] = None

    def handle_discord_message(
        self,
        message: discord.Message
    ) -> Optional[Tuple[SourceRecord, List[MemoryChunk], IngestionReceipt]]:
        """Handle incoming discord.py Message object."""
        if message.author.bot:
            return None

        if not message.guild:
            return None

        guild_id = str(message.guild.id)
        org_id = self.installation_store.get_organization_for_guild(guild_id)
        if not org_id:
            return None

        channel_msg = ChannelMessage(
            organization_id=org_id,
            channel_type=ChannelType.DISCORD,
            guild_id=guild_id,
            guild_name=message.guild.name,
            channel_id=str(message.channel.id),
            channel_name=getattr(message.channel, "name", None),
            message_id=str(message.id),
            author_external_id=str(message.author.id),
            author_name=message.author.name,
            content=message.content,
            timestamp=message.created_at,
            metadata={"source": "discord.py_gateway"}
        )

        record, chunks, receipt = self.connector_service.ingest_live_message(
            message=channel_msg,
            organization_id=org_id
        )

        self.repository.save_record_and_chunks(record, chunks)
        return record, chunks, receipt

    def handle_gateway_event(
        self,
        event_type: str,
        data: Dict[str, Any]
    ) -> Optional[Tuple[SourceRecord, List[MemoryChunk], IngestionReceipt]]:
        """
        Process a Gateway dispatch event dictionary (for testing or custom webhook dispatch).
        Supported events: MESSAGE_CREATE
        """
        if event_type != "MESSAGE_CREATE":
            return None

        # 1. Ignore bot messages to prevent loop recursion
        author_info = data.get("author") or {}
        if author_info.get("bot") is True:
            return None

        # 2. Authoritative guild installation lookup (no caller or payload override)
        guild_id = str(data.get("guild_id") or "")
        if not guild_id:
            return None

        org_id = self.installation_store.get_organization_for_guild(guild_id)
        if not org_id:
            return None

        # 3. Validate required message fields
        message_id = str(data.get("id") or "")
        content = data.get("content", "")
        author_external_id = str(author_info.get("id") or "")
        channel_id = str(data.get("channel_id") or "")
        raw_timestamp = data.get("timestamp")

        if not message_id or not author_external_id or not channel_id or not raw_timestamp:
            return None

        parsed_time = parse_iso_datetime(raw_timestamp)

        # 4. Construct canonical ChannelMessage
        channel_msg = ChannelMessage(
            organization_id=org_id,
            channel_type=ChannelType.DISCORD,
            guild_id=guild_id,
            guild_name=data.get("guild_name"),
            channel_id=channel_id,
            channel_name=data.get("channel_name"),
            message_id=message_id,
            author_external_id=author_external_id,
            author_name=author_info.get("username") or author_info.get("name") or "Discord User",
            content=content,
            timestamp=parsed_time,
            metadata=data.get("metadata") or {}
        )

        # 5. Ingest through server-internal trusted connector service
        record, chunks, receipt = self.connector_service.ingest_live_message(
            message=channel_msg,
            organization_id=org_id
        )

        # 6. Store in authoritative core memory repository (Supabase + cache)
        self.repository.save_record_and_chunks(record, chunks)

        return record, chunks, receipt

    def create_client(self) -> DiscordThreadClient:
        """Instantiate configured discord.py client with required intents."""
        intents = discord.Intents.default()
        intents.message_content = True
        intents.guilds = True
        intents.messages = True
        return DiscordThreadClient(bot_service=self, intents=intents)

    async def start(self):
        """Start the live Discord gateway client with discord.py."""
        token = settings.discord_bot_token
        if not token:
            logger.warning("DiscordGatewayBot cannot start: DISCORD_BOT_TOKEN is not configured.")
            return

        self._running = True
        self._client = self.create_client()
        try:
            await self._client.start(token)
        except asyncio.CancelledError:
            await self.stop()
        except Exception as e:
            logger.error(f"Discord Gateway client error: {e}")
            self._running = False

    def start_background(self):
        """Start Gateway connection in background asyncio task for local single-process demo."""
        token = settings.discord_bot_token
        if token and not self._running:
            try:
                loop = asyncio.get_running_loop()
                self._task = loop.create_task(self.start())
            except RuntimeError:
                pass

    async def stop(self):
        """Gracefully stop discord.py client connection."""
        self._running = False
        if self._client and not self._client.is_closed():
            await self._client.close()
        if self._task and not self._task.done():
            self._task.cancel()

discord_gateway_bot = DiscordGatewayBot()
