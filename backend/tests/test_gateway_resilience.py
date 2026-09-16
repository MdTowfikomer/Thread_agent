import asyncio
import os
import time
from datetime import datetime, timezone, timedelta
from typing import Optional
from unittest.mock import MagicMock, AsyncMock, patch

import pytest
import discord
from fastapi.testclient import TestClient

# Deterministic test environment
os.environ["THREAD_FORCE_DETERMINISTIC_EMBEDDINGS"] = "1"
os.environ["THREAD_FORCE_DETERMINISTIC_SYNTHESIS"] = "1"
os.environ["APP_ENV"] = "production"
os.environ["THREAD_DEMO_AUTH_ENABLED"] = "false"
os.environ["THREAD_ALLOW_GUEST_MODE"] = "false"
os.environ["THREAD_JWT_SECRET"] = "test-secret-cryptographically-secure-32-chars-long-abc12345"

from app.core.config import settings
from app.core.canonical import PermissionLevel, ChannelType
from app.core.auth import create_access_token
from app.core.membership import membership_store
from app.channels.gateway import (
    DiscordGatewayBot,
    DiscordThreadClient,
    extract_error_details,
    try_acquire_gateway_advisory_lock,
    release_gateway_advisory_lock,
    discord_gateway_bot,
)
from app.channels.installation import guild_installation_store
from app.channels.policy import channel_policy_store
from app.memory.store import memory_store
from app.main import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def clean_gateway_env():
    """Reset stores, channels, membership, and gateway bot state between tests."""
    memory_store.clear()
    channel_policy_store.clear()
    guild_installation_store.clear()
    guild_installation_store.register_installation("1549162455874412667", "gdg_mcet", "GDG MCET")
    membership_store.reset()

    # Register default server-owned active ChannelPolicy for test guild/channel
    channel_policy_store.register_policy(
        organization_id="gdg_mcet",
        channel_type=ChannelType.DISCORD,
        channel_id="12345",
        permission_scope=PermissionLevel.PUBLIC_COMMUNITY,
        guild_id="1549162455874412667",
        channel_name="general",
    )

    discord_gateway_bot.state = "stopped"
    discord_gateway_bot.retry_count = 0
    discord_gateway_bot.last_ready_at = None
    discord_gateway_bot.next_retry_at = None
    discord_gateway_bot._running = False
    discord_gateway_bot._client = None
    discord_gateway_bot._task = None
    discord_gateway_bot._ingestion_workers.clear()
    discord_gateway_bot._ingestion_queue = None
    discord_gateway_bot._dropped_messages_count = 0


# =====================================================================
# 1. ERROR EXTRACTION & DETECTION (HTTP 429 & CLOUDFLARE 1015)
# =====================================================================

def test_extract_error_details_429():
    """Verify HTTP 429 rate limit is detected distinctly without leaking body or token."""
    mock_resp = MagicMock()
    mock_resp.headers = {"Retry-After": "60"}

    exc = discord.HTTPException(mock_resp, "429: Too Many Requests")
    exc.status = 429

    details = extract_error_details(exc)
    assert details["http_status"] == 429
    assert details["is_429"] is True
    assert details["is_cf_1015"] is False
    assert "token" not in details
    assert "response" not in details


def test_extract_error_details_cloudflare_1015():
    """Verify Cloudflare 1015 is detected distinctly via code or CF-Ray header."""
    mock_resp = MagicMock()
    mock_resp.headers = {"CF-RAY": "91df85b738917e3a-BOM"}

    # Cloudflare returns 403 or 429 with HTML error page containing error code: 1015
    exc = discord.HTTPException(mock_resp, "Error 1015: You are being rate limited by Cloudflare edge")
    exc.status = 403

    details = extract_error_details(exc)
    assert details["is_cf_1015"] is True
    assert details["cf_ray"] == "91df85b738917e3a-BOM"
    assert "token" not in details


def test_extract_error_details_safe_zero_token_leakage():
    """Verify sensitive token strings never leak in extracted details."""
    sensitive_token = "MTA1OTIxMjM0NTY3ODkwMTIzNA.GhIJkL.mNoPqRsTuVwXyZ"
    exc = RuntimeError(f"Failed to authenticate with token {sensitive_token}")

    details = extract_error_details(exc)
    assert sensitive_token not in str(details)
    assert details["exception_class"] == "RuntimeError"


# =====================================================================
# 2. EXPONENTIAL BACKOFF WITH FULL JITTER FORMULA
# =====================================================================

def test_calculate_backoff_exponential_cap():
    """Verify backoff scales exponentially (60s, 120s, 240s, 480s, 900s) and caps at 15 minutes."""
    bot = DiscordGatewayBot(
        initial_backoff=60.0,
        max_backoff=900.0,
        jitter_fn=lambda low, high: high  # Deterministic maximum (ceiling)
    )

    assert bot.calculate_backoff(1) == 60.0
    assert bot.calculate_backoff(2) == 120.0
    assert bot.calculate_backoff(3) == 240.0
    assert bot.calculate_backoff(4) == 480.0
    assert bot.calculate_backoff(5) == 900.0  # Capped at 900s (15 min)
    assert bot.calculate_backoff(10) == 900.0  # Still capped at 900s


def test_calculate_backoff_full_jitter_bounds():
    """Verify full jitter produces a value between 0.01 and the exponential ceiling."""
    bot = DiscordGatewayBot(initial_backoff=60.0, max_backoff=900.0)

    for _ in range(50):
        val_1 = bot.calculate_backoff(1)
        assert 0.01 <= val_1 <= 60.0

        val_2 = bot.calculate_backoff(2)
        assert 0.01 <= val_2 <= 120.0

        val_5 = bot.calculate_backoff(5)
        assert 0.01 <= val_5 <= 900.0


# =====================================================================
# 3. SUPERVISOR RETRY LOOP: 429/1015 WITHOUT TIGHT LOOP
# =====================================================================

def test_supervisor_retries_429_and_1015_with_exponential_backoff():
    """Verify supervisor retries unexpected connection failures with backoff and avoids tight loops."""
    async def run():
        delays_slept = []

        async def mock_sleep(seconds: float):
            delays_slept.append(seconds)

        attempt_counter = 0

        def mock_create_client():
            nonlocal attempt_counter
            attempt_counter += 1
            client_mock = AsyncMock()
            client_mock.is_closed = MagicMock(return_value=False)
            created_clients.append(client_mock) if 'created_clients' in locals() else None

            if attempt_counter == 1:
                # First attempt fails with 429
                exc_resp = MagicMock()
                exc_resp.headers = {"Retry-After": "60"}
                exc = discord.HTTPException(exc_resp, "429: Too Many Requests")
                exc.status = 429
                client_mock.start.side_effect = exc
            elif attempt_counter == 2:
                # Second attempt fails with Cloudflare 1015
                exc_resp = MagicMock()
                exc_resp.headers = {"CF-RAY": "91df85b738917e3a-BOM"}
                exc = discord.HTTPException(exc_resp, "Error 1015: Rate limited")
                exc.status = 403
                client_mock.start.side_effect = exc
            else:
                # Third attempt: supervisor will stop
                async def stop_bot(token):
                    bot.state = "connected"
                    bot._running = False
                client_mock.start.side_effect = stop_bot

            return client_mock

        bot = DiscordGatewayBot(
            initial_backoff=60.0,
            max_backoff=900.0,
            jitter_fn=lambda low, high: high,  # Ceiling for deterministic delay check
            sleep_fn=mock_sleep
        )
        bot.create_client = mock_create_client

        with patch.dict(os.environ, {"DISCORD_BOT_TOKEN": "test_bot_token_123"}):
            await bot.start()

        assert len(delays_slept) == 2
        assert delays_slept[0] == 60.0   # Attempt 1 backoff
        assert delays_slept[1] == 420.0  # Attempt 2 backoff: 300s CF 1015 minimum + 120s max ceiling jitter
        assert attempt_counter == 3
        assert bot.retry_count == 2

    asyncio.run(run())


# =====================================================================
# 4. RETRY COUNTER RESET ONLY ON ON_READY
# =====================================================================

def test_retry_counter_resets_only_after_on_ready():
    """Verify retry_count persists during backing_off and resets to 0 only after on_ready succeeds."""
    async def run():
        bot = DiscordGatewayBot()
        bot.retry_count = 4
        bot.state = "backing_off"
        bot.next_retry_at = datetime.now(timezone.utc) + timedelta(minutes=5)

        assert bot.retry_count == 4
        assert bot.state == "backing_off"

        await bot.on_client_ready()

        assert bot.retry_count == 0
        assert bot.state == "connected"
        assert bot.last_ready_at is not None
        assert bot.next_retry_at is None

    asyncio.run(run())


# =====================================================================
# 5. SINGLE ACTIVE CLIENT ENFORCEMENT
# =====================================================================

def test_single_active_client_enforcement():
    """Verify supervisor closes previous client before creating a new one and never creates concurrent clients."""
    async def run():
        created_clients = []

        def mock_create_client():
            m = AsyncMock()
            m.is_closed = MagicMock(return_value=False)
            created_clients.append(m)
            if len(created_clients) < 3:
                m.start.side_effect = discord.ConnectionClosed(MagicMock(), shard_id=None, code=1006)
            else:
                async def stop_after_connect(token):
                    bot._running = False
                m.start.side_effect = stop_after_connect
            return m

        bot = DiscordGatewayBot(
            jitter_fn=lambda low, high: 0.01,
            sleep_fn=AsyncMock()
        )
        bot.create_client = mock_create_client

        with patch.dict(os.environ, {"DISCORD_BOT_TOKEN": "test_bot_token_123"}):
            await bot.start()

        assert len(created_clients) == 3
        # Client 0 closed before Client 1
        assert created_clients[0].close.await_count >= 1
        # Client 1 closed before Client 2
        assert created_clients[1].close.await_count >= 1

    asyncio.run(run())


def test_start_background_does_not_duplicate_task():
    """Verify start_background() does not create multiple concurrent background tasks."""
    bot = DiscordGatewayBot()
    bot._task = MagicMock()
    bot._task.done.return_value = False

    with patch.dict(os.environ, {"DISCORD_BOT_TOKEN": "test_bot_token_123"}):
        bot.start_background()
        assert bot._task.done.call_count >= 1


# =====================================================================
# 6. SLOW INGESTION DOES NOT DELAY MENTION REPLY
# =====================================================================

def test_slow_ingestion_does_not_delay_mention_reply():
    """Verify live message ingestion is offloaded as bounded background work without blocking mention replies."""
    async def run():
        bot = DiscordGatewayBot()

        # Simulate slow synchronous database ingestion (0.4 seconds)
        ingestion_started = False
        ingestion_completed = False

        def slow_ingest(message):
            nonlocal ingestion_started, ingestion_completed
            ingestion_started = True
            time.sleep(0.4)
            ingestion_completed = True
            return None

        bot.handle_discord_message = slow_ingest

        # Fast reply handler
        reply_dispatched = False

        async def fast_reply(message, client):
            nonlocal reply_dispatched
            reply_dispatched = True

        bot.handle_discord_mention_reply = fast_reply
        bot._running = True

        client_instance = DiscordThreadClient(bot_service=bot)

        # Mock Discord message
        mock_msg = MagicMock(spec=discord.Message)
        mock_msg.author.bot = False
        mock_msg.guild.id = 1549162455874412667
        mock_msg.channel.id = 12345
        mock_msg.id = 67890
        mock_msg.content = "<@9999> question"

        t0 = time.monotonic()
        await client_instance.on_message(mock_msg)
        elapsed = time.monotonic() - t0

        # Mention reply MUST have completed immediately (< 0.15s), NOT blocked on slow 0.4s ingestion
        assert elapsed < 0.15
        assert reply_dispatched is True

        # Await background ingestion to settle and stop bot
        await asyncio.sleep(0.5)
        assert ingestion_completed is True
        await bot.stop()

    asyncio.run(run())


# =====================================================================
# 7. DATABASE LOCK ERROR FAILING STARTUP (RENDER FREE DEMO)
# =====================================================================

def test_gateway_advisory_lock_fails_closed_on_db_error():
    """Verify Render free-demo startup fails closed (RuntimeError) when lock database check itself errors."""
    with patch.dict(os.environ, {"SUPABASE_DB_URL": "postgresql://invalid_host:5432/db"}):
        with patch("psycopg2.connect", side_effect=Exception("Database connection timeout")):
            with pytest.raises(RuntimeError) as excinfo:
                try_acquire_gateway_advisory_lock(fail_on_db_error=True)
            assert "PostgreSQL error checking advisory lock" in str(excinfo.value)


def test_gateway_advisory_lock_held_is_standby_not_error():
    """Verify when PostgreSQL confirms lock is held by another active peer, None is returned without raising."""
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.fetchone.return_value = (False,)  # Lock not acquired; held by peer
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

    with patch.dict(os.environ, {"SUPABASE_DB_URL": "postgresql://mock:5432/db"}):
        with patch("psycopg2.connect", return_value=mock_conn):
            result = try_acquire_gateway_advisory_lock(fail_on_db_error=True)
            assert result is None  # Standby!


def test_render_free_demo_lifespan_fails_closed_on_db_error():
    """Verify full FastAPI lifespan in render_free_demo mode fails closed on lock check DB error."""
    from app.main import lifespan

    async def run():
        with patch.dict(os.environ, {
            "THREAD_DEPLOYMENT_MODE": "render_free_demo",
            "THREAD_START_GATEWAY_BOT": "true",
            "DISCORD_BOT_TOKEN": "token_123",
            "SUPABASE_DB_URL": "postgresql://invalid_host:5432/db",
            "THREAD_JWT_SECRET": "test-secret-cryptographically-secure-32-chars-long-abc12345"
        }):
            with pytest.raises(RuntimeError) as excinfo:
                async with lifespan(app):
                    pass
            assert "PostgreSQL error checking advisory lock" in str(excinfo.value)

    asyncio.run(run())


# =====================================================================
# 8. PRESERVED BEHAVIOR (BOT MSGS, UNKNOWN GUILDS, EMPTY MENTIONS, ACL DENIAL)
# =====================================================================

def test_bot_messages_ignored():
    """Verify bot messages are completely ignored to prevent echo recursion."""
    bot = DiscordGatewayBot()
    mock_msg = MagicMock(spec=discord.Message)
    mock_msg.author.bot = True

    result = bot.handle_discord_message(mock_msg)
    assert result is None


def test_unknown_guilds_dropped():
    """Verify messages from unmapped/unknown Discord guilds are dropped."""
    bot = DiscordGatewayBot()
    mock_msg = MagicMock(spec=discord.Message)
    mock_msg.author.bot = False
    mock_msg.guild.id = 999999999999  # Unregistered guild

    result = bot.handle_discord_message(mock_msg)
    assert result is None


def test_empty_mention_returns_helpful_greeting():
    """Verify empty mention (user tags bot with no query) receives standard helpful prompt."""
    async def run():
        bot = DiscordGatewayBot()
        client_mock = MagicMock()
        bot_user = MagicMock()
        bot_user.id = 12345
        client_mock.user = bot_user

        mock_msg = MagicMock(spec=discord.Message)
        mock_msg.author.bot = False
        mock_msg.guild.id = 1549162455874412667
        mock_msg.channel.id = 12345
        mock_msg.id = 67890
        mock_msg.content = "<@12345>"
        mock_msg.mentions = [bot_user]
        mock_msg.reply = AsyncMock()

        await bot.handle_discord_mention_reply(mock_msg, client_mock)
        mock_msg.reply.assert_awaited_once_with(
            "Hello! Ask me any question about GDG MCET records and I'll find grounded evidence.",
            mention_author=False
        )

    asyncio.run(run())


def test_acl_denial_returns_access_restriction_message():
    """Verify permission rejection returns standard access restriction reply without crashing."""
    async def run():
        bot = DiscordGatewayBot()
        client_mock = MagicMock()
        bot_user = MagicMock()
        bot_user.id = 12345
        client_mock.user = bot_user

        mock_msg = MagicMock(spec=discord.Message)
        mock_msg.author.bot = False
        mock_msg.author.id = 5555
        mock_msg.author.name = "TestUser"
        mock_msg.author.display_name = "TestUser"
        mock_msg.guild.id = 1549162455874412667
        mock_msg.guild.name = "GDG MCET"
        mock_msg.channel.id = 12345
        mock_msg.channel.name = "general"
        mock_msg.id = 67890
        mock_msg.reference = None
        mock_msg.content = "<@12345> Query"
        mock_msg.mentions = [bot_user]
        mock_msg.reply = AsyncMock()

        mock_context = AsyncMock()
        mock_msg.channel.typing.return_value = mock_context

        with patch("app.channels.outbound.channel_message_delivery_service.send_message", side_effect=PermissionError("Forbidden channel")):
            await bot.handle_discord_mention_reply(mock_msg, client_mock)

        mock_msg.reply.assert_awaited_once_with(
            "⚠️ Access restriction: Forbidden channel",
            mention_author=False
        )

    asyncio.run(run())


# =====================================================================
# 9. OPERATOR-ONLY READINESS SIGNAL ENDPOINT
# =====================================================================

def test_readiness_signal_unauthenticated_rejected():
    """Verify unauthenticated requests to readiness endpoints are rejected with 401."""
    res = client.get("/api/gateway/readiness")
    assert res.status_code == 401

    res_alias = client.get("/api/channels/discord/readiness")
    assert res_alias.status_code == 401


def test_readiness_signal_non_operator_rejected():
    """Verify community member without INTERNAL_CORE scope is rejected with 403."""
    # Create valid JWT token for community member (usr_student_rohan)
    token = create_access_token(user_id="usr_student_rohan", organization_id="gdg_mcet")
    headers = {"Authorization": f"Bearer {token}"}

    res = client.get("/api/gateway/readiness", headers=headers)
    assert res.status_code == 403


def test_readiness_signal_operator_success_and_zero_leakage():
    """Verify operator (usr_arjun) can inspect readiness with zero leakage of tokens or guilds."""
    token = create_access_token(user_id="usr_arjun", organization_id="gdg_mcet")
    headers = {"Authorization": f"Bearer {token}"}

    discord_gateway_bot.state = "connected"
    discord_gateway_bot.last_ready_at = datetime(2026, 9, 16, 12, 0, 0, tzinfo=timezone.utc)
    discord_gateway_bot.next_retry_at = None

    res = client.get("/api/gateway/readiness", headers=headers)
    assert res.status_code == 200
    data = res.json()

    assert data["state"] == "connected"
    assert data["last_ready_at"] == "2026-09-16T12:00:00+00:00"
    assert data["next_retry_at"] is None

    # Strict zero-leakage assertions:
    assert "token" not in data
    assert "guild" not in data
    assert "exception" not in data
    assert "html" not in data
    assert set(data.keys()) == {"state", "last_ready_at", "next_retry_at"}


# =====================================================================
# 10. REVIEW FINDINGS: RETRY-AFTER, CF 1015, UNBOUND CHANNELS, QUEUE SATURATION
# =====================================================================

def test_429_retry_after_never_sleeps_less_than_retry_after():
    """Verify HTTP 429 backoff sleeps for at least Retry-After and never a shorter delay."""
    bot = DiscordGatewayBot(initial_backoff=60.0, max_backoff=900.0)

    # 1. 100 trials with default jitter: delay MUST always be >= 60.0s
    for attempt in range(1, 6):
        for _ in range(20):
            delay = bot.calculate_backoff(attempt, {"is_429": True, "retry_after": 60.0})
            assert delay >= 60.0, f"Delay {delay} was less than 60-second Retry-After at attempt {attempt}"

    # 2. Zero-jitter test: delay must equal exactly Retry-After
    bot_zero_jitter = DiscordGatewayBot(
        initial_backoff=60.0,
        max_backoff=900.0,
        jitter_fn=lambda low, high: 0.0
    )
    delay_zero = bot_zero_jitter.calculate_backoff(1, {"is_429": True, "retry_after": 60.0})
    assert delay_zero == 60.0

    # 3. 120s Retry-After test
    delay_120 = bot_zero_jitter.calculate_backoff(1, {"is_429": True, "retry_after": 120.0})
    assert delay_120 == 120.0


def test_cloudflare_1015_minimum_delay_5_minutes():
    """Verify Cloudflare 1015 without Retry-After enforces a conservative 5-minute (300s) minimum, capped at 15m (900s)."""
    bot = DiscordGatewayBot(initial_backoff=60.0, max_backoff=900.0)

    # 1. 100 trials: delay MUST always be in [300.0, 900.0]
    for attempt in range(1, 6):
        for _ in range(20):
            delay = bot.calculate_backoff(attempt, {"is_cf_1015": True, "retry_after": None})
            assert 300.0 <= delay <= 900.0, f"Delay {delay} not within [300s, 900s] at attempt {attempt}"

    # 2. Zero-jitter test: exactly 300.0s minimum
    bot_zero = DiscordGatewayBot(
        initial_backoff=60.0,
        max_backoff=900.0,
        jitter_fn=lambda low, high: 0.0
    )
    delay_min = bot_zero.calculate_backoff(1, {"is_cf_1015": True, "retry_after": None})
    assert delay_min == 300.0

    # 3. Max-jitter test: capped at 900.0s (15 minutes)
    bot_max = DiscordGatewayBot(
        initial_backoff=60.0,
        max_backoff=900.0,
        jitter_fn=lambda low, high: high
    )
    delay_max = bot_max.calculate_backoff(5, {"is_cf_1015": True, "retry_after": None})
    assert delay_max == 900.0


def test_unbound_channel_no_reply_and_no_ingest():
    """Verify that an unbound channel (no server-owned active ChannelPolicy) is neither ingested nor replied to."""
    async def run():
        bot = DiscordGatewayBot()
        client_mock = MagicMock()
        bot_user = MagicMock()
        bot_user.id = 12345
        client_mock.user = bot_user

        mock_msg = MagicMock(spec=discord.Message)
        mock_msg.author.bot = False
        mock_msg.guild.id = 1549162455874412667
        mock_msg.guild.name = "GDG MCET"
        # Channel 99999 has NO policy registered in channel_policy_store
        mock_msg.channel.id = 99999
        mock_msg.id = 88888
        mock_msg.content = "<@12345> Hello unbound channel"
        mock_msg.mentions = [bot_user]
        mock_msg.reply = AsyncMock()

        # 1. Verification of queue_message_for_ingestion: must return False and drop
        queued = bot.queue_message_for_ingestion(mock_msg)
        assert queued is False

        # 2. Verification of handle_discord_message: must return None
        ingested = bot.handle_discord_message(mock_msg)
        assert ingested is None

        # 3. Verification of handle_discord_mention_reply: must not reply
        await bot.handle_discord_mention_reply(mock_msg, client_mock)
        assert mock_msg.reply.call_count == 0

    asyncio.run(run())


def test_queue_saturation_drops_excess_and_keeps_mention_responsive():
    """Verify queue saturation safely drops excess non-mention messages while mention replies remain responsive."""
    async def run():
        # Initialize bot with small queue capacity of 2 and 0 background workers (to prevent draining)
        bot = DiscordGatewayBot(max_queue_size=2, num_workers=0)

        # Mock client
        client_mock = MagicMock()
        bot_user = MagicMock()
        bot_user.id = 12345
        client_mock.user = bot_user

        # Create 3 messages for channel 12345 (which has active policy registered in clean_gateway_env)
        def create_msg(msg_id: int, content: str):
            m = MagicMock(spec=discord.Message)
            m.author.bot = False
            m.guild.id = 1549162455874412667
            m.guild.name = "GDG MCET"
            m.channel.id = 12345
            m.id = msg_id
            m.content = content
            m.mentions = [bot_user] if "<@12345>" in content else []
            m.reply = AsyncMock()
            return m

        msg1 = create_msg(101, "First background message")
        msg2 = create_msg(102, "Second background message")
        msg3 = create_msg(103, "<@12345>")  # Empty mention asking for prompt

        # Enqueue 2 messages to saturate the queue (size 2)
        assert bot.queue_message_for_ingestion(msg1) is True
        assert bot.queue_message_for_ingestion(msg2) is True
        assert bot.ingestion_queue.full() is True

        # Now dispatch msg3 via DiscordThreadClient
        client_instance = DiscordThreadClient(bot_service=bot)
        client_instance._connection.user = bot_user

        t0 = time.monotonic()
        await client_instance.on_message(msg3)
        elapsed = time.monotonic() - t0

        # Ingestion queue was full: msg3 ingestion was safely dropped
        assert bot._dropped_messages_count >= 1

        # Mention reply MUST have completed immediately (< 0.15s) and replied
        assert elapsed < 0.15
        msg3.reply.assert_awaited_once_with(
            "Hello! Ask me any question about GDG MCET records and I'll find grounded evidence.",
            mention_author=False
        )

        await bot.stop()

    asyncio.run(run())

