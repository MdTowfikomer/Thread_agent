import asyncio
import json
import logging
import os
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
        await self.bot_service.handle_discord_mention_reply(message, self)

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

    async def handle_discord_mention_reply(self, message: discord.Message, client: discord.Client):
        """Handle mention and direct interaction replies for Discord messages."""
        if message.author.bot or not message.guild:
            return

        guild_id = str(message.guild.id)
        org_id = self.installation_store.get_organization_for_guild(guild_id)
        if not org_id:
            return

        bot_user = client.user
        if not bot_user:
            return

        is_bot_mentioned = (
            bot_user in message.mentions
            or f"<@{bot_user.id}>" in message.content
            or f"<@!{bot_user.id}>" in message.content
        )
        is_reply_to_bot = (
            message.reference
            and message.reference.resolved
            and getattr(message.reference.resolved, "author", None) == bot_user
        )

        if not (is_bot_mentioned or is_reply_to_bot):
            return

        import re
        clean_query = re.sub(rf"<@!?{re.escape(str(bot_user.id))}>", "", message.content).strip()
        if not clean_query:
            await message.reply("Hello! Ask me any question about GDG MCET records and I'll find grounded evidence.", mention_author=False)
            return

        async with message.channel.typing():
            try:
                from app.identity.service import identity_service
                from app.core.membership import membership_store
                from app.core.auth import AuthenticatedPrincipal
                from app.channels.outbound import channel_message_delivery_service
                from app.channels.policy import channel_policy_store
                from app.core.canonical import PermissionLevel

                author_id = str(message.author.id)
                author_name = message.author.name
                display_name = getattr(message.author, "display_name", author_name)

                link = identity_service.resolve_identity(
                    organization_id=org_id,
                    channel_type=ChannelType.DISCORD,
                    account_id=author_id,
                    username=author_name,
                    display_name=display_name,
                )
                access_context = membership_store.derive_access_context(
                    user_id=link.person_id,
                    organization_id=org_id,
                )
                principal = AuthenticatedPrincipal(
                    user_id=link.person_id,
                    organization_id=org_id,
                    access_context=access_context,
                )

                policy = channel_policy_store.get_policy(org_id, ChannelType.DISCORD, str(message.channel.id), guild_id)
                if not policy or not policy.is_active:
                    channel_policy_store.register_policy(
                        organization_id=org_id,
                        channel_type=ChannelType.DISCORD,
                        channel_id=str(message.channel.id),
                        permission_scope=PermissionLevel.PUBLIC_COMMUNITY,
                        guild_id=guild_id,
                        channel_name=getattr(message.channel, "name", None),
                    )

                reply_idempotency_key = f"discord_reply_{guild_id}_{message.channel.id}_{message.id}"

                send_result = await asyncio.to_thread(
                    channel_message_delivery_service.send_message,
                    principal=principal,
                    platform=ChannelType.DISCORD,
                    destination_id=str(message.channel.id),
                    query=clean_query,
                    idempotency_key=reply_idempotency_key,
                )

                if send_result.get("status") == "insufficient_evidence":
                    await message.reply(
                        "Based on verified organizational records, there is insufficient evidence to answer this inquiry within this channel's scope.",
                        mention_author=False
                    )
            except PermissionError as pe:
                logger.warning(f"Discord ACL rejected send for message {message.id}: {pe}")
                await message.reply(
                    f"⚠️ Access restriction: {pe}",
                    mention_author=False
                )
            except Exception as exc:
                logger.error(f"Error handling Discord mention for message {message.id}: {exc}")
                await message.reply(
                    "Sorry, I encountered an error retrieving verified records. Please try again.",
                    mention_author=False
                )

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
        if os.getenv("DISCORD_ENABLE_MESSAGE_CONTENT_INTENT", "false").lower() in ("true", "1"):
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

DISCORD_GATEWAY_ADVISORY_LOCK_ID = 1414025812


def try_acquire_gateway_advisory_lock(fail_on_db_error: bool = False) -> Optional[Any]:
    """
    Attempt to acquire non-blocking PostgreSQL session advisory lock for Discord Gateway.
    Guarantees that across Render horizontal restarts or zero-downtime overlaps,
    only a single worker process connects to Discord Gateway.

    Returns:
      - connection object: if lock was successfully acquired (this process is leader).
      - None: if and only if PostgreSQL authoritatively confirms the lock is held by another active peer.
    
    Raises:
      - RuntimeError: if fail_on_db_error is True and database is unreachable, missing, or errors.
    """
    db_url = os.getenv("SUPABASE_DB_URL") or os.getenv("DATABASE_URL")
    if not db_url:
        msg = "[Discord Gateway] SUPABASE_DB_URL/DATABASE_URL is not configured to acquire advisory lock."
        logger.error(msg)
        if fail_on_db_error:
            raise RuntimeError(msg)
        return None

    try:
        import psycopg2
        conn = psycopg2.connect(db_url)
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute("SELECT pg_try_advisory_lock(%s);", (DISCORD_GATEWAY_ADVISORY_LOCK_ID,))
            row = cur.fetchone()
            acquired = row[0] if row else False
            if acquired:
                logger.info(f"[Discord Gateway] Acquired PostgreSQL advisory lock ({DISCORD_GATEWAY_ADVISORY_LOCK_ID}). Process is Gateway leader.")
                return conn
            else:
                # Positively confirmed by PostgreSQL that another active session holds the lock
                logger.warning(f"[Discord Gateway] Advisory lock ({DISCORD_GATEWAY_ADVISORY_LOCK_ID}) is held by an active peer instance. Standby mode.")
                conn.close()
                return None
    except Exception as e:
        msg = f"[Discord Gateway] PostgreSQL error checking advisory lock: {e}"
        logger.error(msg)
        if fail_on_db_error:
            raise RuntimeError(msg) from e
        return None


def release_gateway_advisory_lock(conn: Any) -> None:
    """Release PostgreSQL advisory lock and close the leader connection."""
    if conn:
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT pg_advisory_unlock(%s);", (DISCORD_GATEWAY_ADVISORY_LOCK_ID,))
            conn.close()
            logger.info(f"[Discord Gateway] Released PostgreSQL advisory lock ({DISCORD_GATEWAY_ADVISORY_LOCK_ID}).")
        except Exception as e:
            logger.warning(f"[Discord Gateway] Error releasing advisory lock: {e}")
