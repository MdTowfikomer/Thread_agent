import os
import time
import json
import asyncio
import pytest
from unittest.mock import patch, MagicMock, AsyncMock

from cryptography.hazmat.primitives.asymmetric import ed25519
from fastapi.testclient import TestClient

from app.main import app
from app.core.canonical import ChannelType, PermissionLevel
from app.channels.installation import guild_installation_store
from app.channels.policy import channel_policy_store
from app.channels.gateway import discord_gateway_bot
from app.channels.delivery import webhook_delivery_store
from app.channels.outbound import OutboundRateLimitError, DiscordOutboundAdapter
from app.graph.workflow import app_graph

# Cryptographic key for slash command signature tests
TEST_PRIVATE_KEY = ed25519.Ed25519PrivateKey.generate()
TEST_PUBLIC_KEY_HEX = TEST_PRIVATE_KEY.public_key().public_bytes_raw().hex()
os.environ["THREAD_DISCORD_PUBLIC_KEY"] = TEST_PUBLIC_KEY_HEX
os.environ["THREAD_ALLOW_OFFLINE_BINDINGS"] = "1"
os.environ["THREAD_FORCE_DETERMINISTIC_SYNTHESIS"] = "1"

client = TestClient(app, base_url="https://testserver")


@pytest.fixture(autouse=True)
def setup_discord_test_env():
    guild_installation_store.clear()
    channel_policy_store.clear()
    webhook_delivery_store._deliveries.clear()

    # Register bound test guild
    guild_installation_store.register_installation(
        guild_id="guild_discord_101",
        organization_id="gdg_mcet",
        guild_name="GDG MCET Discord"
    )

    # Register bound test channel
    channel_policy_store.register_policy(
        organization_id="gdg_mcet",
        channel_type=ChannelType.DISCORD,
        guild_id="guild_discord_101",
        channel_id="chan_general_202",
        channel_name="general",
        permission_scope=PermissionLevel.PUBLIC_COMMUNITY
    )


# 1. Mention equals one graph run and one reply
def test_discord_mention_one_graph_run_and_one_reply():
    async def run_test():
        mock_discord_client = MagicMock()
        mock_bot_user = MagicMock()
        mock_bot_user.id = 998877
        mock_discord_client.user = mock_bot_user

        mock_guild = MagicMock()
        mock_guild.id = "guild_discord_101"
        mock_guild.name = "GDG MCET Discord"

        mock_channel = MagicMock()
        mock_channel.id = "chan_general_202"
        mock_channel.typing.return_value.__aenter__ = AsyncMock()
        mock_channel.typing.return_value.__aexit__ = AsyncMock()

        mock_author = MagicMock()
        mock_author.id = 112233
        mock_author.name = "student_rohan"
        mock_author.display_name = "Rohan"
        mock_author.bot = False

        mock_message = MagicMock()
        mock_message.id = 7001
        mock_message.guild = mock_guild
        mock_message.channel = mock_channel
        mock_message.author = mock_author
        mock_message.mentions = [mock_bot_user]
        mock_message.content = "<@998877> what is GDG MCET's next workshop?"
        mock_message.reference = None

        with patch.object(app_graph, "invoke", wraps=app_graph.invoke) as mock_graph_invoke:
            with patch("app.channels.outbound.DiscordOutboundAdapter.send", return_value="msg_outbound_999") as mock_outbound_send:
                await discord_gateway_bot.handle_discord_mention_reply(mock_message, mock_discord_client)

                assert mock_graph_invoke.call_count == 1
                assert mock_outbound_send.call_count == 1

                sent_dest, sent_text, _ = mock_outbound_send.call_args[0]
                assert sent_dest["channel_id"] == "chan_general_202"
                assert sent_dest["guild_id"] == "guild_discord_101"
                assert len(sent_text) > 0

    asyncio.run(run_test())


# 2. No reply to non-mentions
def test_no_reply_to_non_mentions():
    async def run_test():
        mock_discord_client = MagicMock()
        mock_bot_user = MagicMock()
        mock_bot_user.id = 998877
        mock_discord_client.user = mock_bot_user

        mock_guild = MagicMock()
        mock_guild.id = "guild_discord_101"

        mock_channel = MagicMock()
        mock_channel.id = "chan_general_202"

        mock_author = MagicMock()
        mock_author.id = 112233
        mock_author.bot = False

        mock_message = MagicMock()
        mock_message.id = 7002
        mock_message.guild = mock_guild
        mock_message.channel = mock_channel
        mock_message.author = mock_author
        mock_message.mentions = []  # No bot mention
        mock_message.content = "Just chatting with friends about coding."
        mock_message.reference = None

        with patch.object(app_graph, "invoke") as mock_graph_invoke:
            with patch("app.channels.outbound.DiscordOutboundAdapter.send") as mock_outbound_send:
                await discord_gateway_bot.handle_discord_mention_reply(mock_message, mock_discord_client)

                assert mock_graph_invoke.call_count == 0
                assert mock_outbound_send.call_count == 0

    asyncio.run(run_test())


# 3. No reply in unbound channels
def test_no_reply_in_unbound_channels():
    async def run_test():
        mock_discord_client = MagicMock()
        mock_bot_user = MagicMock()
        mock_bot_user.id = 998877
        mock_discord_client.user = mock_bot_user

        mock_guild = MagicMock()
        mock_guild.id = "guild_discord_101"

        mock_channel = MagicMock()
        mock_channel.id = "chan_unbound_999"  # Unbound channel

        mock_author = MagicMock()
        mock_author.id = 112233
        mock_author.bot = False

        mock_message = MagicMock()
        mock_message.id = 7003
        mock_message.guild = mock_guild
        mock_message.channel = mock_channel
        mock_message.author = mock_author
        mock_message.mentions = [mock_bot_user]
        mock_message.content = "<@998877> secret query in unbound channel"
        mock_message.reference = None

        with patch.object(app_graph, "invoke") as mock_graph_invoke:
            with patch("app.channels.outbound.DiscordOutboundAdapter.send") as mock_outbound_send:
                await discord_gateway_bot.handle_discord_mention_reply(mock_message, mock_discord_client)

                assert mock_graph_invoke.call_count == 0
                assert mock_outbound_send.call_count == 0

    asyncio.run(run_test())


# 4. List-shaped Gemini content becomes plain text on Discord
def test_list_shaped_gemini_content_becomes_plain_text():
    async def run_test():
        mock_discord_client = MagicMock()
        mock_bot_user = MagicMock()
        mock_bot_user.id = 998877
        mock_discord_client.user = mock_bot_user

        mock_guild = MagicMock()
        mock_guild.id = "guild_discord_101"

        mock_channel = MagicMock()
        mock_channel.id = "chan_general_202"
        mock_channel.typing.return_value.__aenter__ = AsyncMock()
        mock_channel.typing.return_value.__aexit__ = AsyncMock()

        mock_author = MagicMock()
        mock_author.id = 112233
        mock_author.bot = False

        mock_message = MagicMock()
        mock_message.id = 7004
        mock_message.guild = mock_guild
        mock_message.channel = mock_channel
        mock_message.author = mock_author
        mock_message.mentions = [mock_bot_user]
        mock_message.content = "<@998877> explain AI"
        mock_message.reference = None

        mock_llm = MagicMock()
        mock_llm.invoke.return_value = MagicMock(content=[{"type": "text", "text": "Artificial Intelligence is the simulation of human intelligence."}])

        with patch("app.graph.workflow.get_llm", return_value=mock_llm):
            with patch("app.channels.outbound.DiscordOutboundAdapter.send", return_value="msg_outbound_7004") as mock_outbound_send:
                await discord_gateway_bot.handle_discord_mention_reply(mock_message, mock_discord_client)

                assert mock_outbound_send.call_count == 1
                _, sent_text, _ = mock_outbound_send.call_args[0]
                assert isinstance(sent_text, str)
                assert "[" not in sent_text
                assert "Artificial Intelligence" in sent_text

    asyncio.run(run_test())


# 5. Duplicate event does not duplicate reply
def test_duplicate_event_does_not_duplicate_reply():
    async def run_test():
        mock_discord_client = MagicMock()
        mock_bot_user = MagicMock()
        mock_bot_user.id = 998877
        mock_discord_client.user = mock_bot_user

        mock_guild = MagicMock()
        mock_guild.id = "guild_discord_101"

        mock_channel = MagicMock()
        mock_channel.id = "chan_general_202"
        mock_channel.typing.return_value.__aenter__ = AsyncMock()
        mock_channel.typing.return_value.__aexit__ = AsyncMock()

        mock_author = MagicMock()
        mock_author.id = 112233
        mock_author.bot = False

        # Message with identical ID 7005 dispatched twice
        mock_message = MagicMock()
        mock_message.id = 7005
        mock_message.guild = mock_guild
        mock_message.channel = mock_channel
        mock_message.author = mock_author
        mock_message.mentions = [mock_bot_user]
        mock_message.content = "<@998877> hello"
        mock_message.reference = None

        with patch("app.channels.outbound.DiscordOutboundAdapter.send", return_value="msg_outbound_7005") as mock_outbound_send:
            # Event 1
            await discord_gateway_bot.handle_discord_mention_reply(mock_message, mock_discord_client)
            assert mock_outbound_send.call_count == 1

            # Event 2 (duplicate delivery attempt)
            await discord_gateway_bot.handle_discord_mention_reply(mock_message, mock_discord_client)
            # Call count remains 1 because of idempotency audit store claim
            assert mock_outbound_send.call_count == 1

    asyncio.run(run_test())


# 6. HTTP 429 honors Retry-After
def test_outbound_429_honors_retry_after():
    adapter = DiscordOutboundAdapter()
    destination = {"channel_id": "chan_general_202"}

    mock_429_resp = MagicMock()
    mock_429_resp.status_code = 429
    mock_429_resp.headers = {"Retry-After": "0.05"}
    mock_429_resp.json.return_value = {"retry_after": 0.05}

    with patch("httpx.post", return_value=mock_429_resp) as mock_post:
        with pytest.raises(OutboundRateLimitError) as exc_info:
            adapter.send(destination, "Test rate limit", "key_429_test")

        assert exc_info.value.retry_after == 0.05
        # Attempted twice (initial + 1 retry) before raising OutboundRateLimitError
        assert mock_post.call_count == 2


# 7. Slash command isolation: one deferred response, one follow-up patch, idempotency
def test_slash_command_isolation_and_idempotency():
    timestamp = str(int(time.time()))
    payload = {
        "id": "interaction_slash_9001",
        "type": 2,
        "guild_id": "guild_discord_101",
        "application_id": "app_discord_123",
        "token": "tok_interaction_9001",
        "data": {"name": "ask-thread", "options": [{"name": "query", "value": "what is GDG MCET?"}]},
        "member": {"user": {"id": "usr_discord_555", "username": "rohan_codes"}}
    }
    body_bytes = json.dumps(payload).encode("utf-8")
    sig = TEST_PRIVATE_KEY.sign(timestamp.encode("utf-8") + body_bytes).hex()

    headers = {
        "Content-Type": "application/json",
        "X-Signature-Ed25519": sig,
        "X-Signature-Timestamp": timestamp
    }

    with patch("httpx.AsyncClient.patch", new_callable=AsyncMock) as mock_patch:
        mock_patch.return_value = MagicMock(is_success=True)

        # 1. Dispatch slash command -> Deferred Type 5 response immediately
        res = client.post("/api/webhooks/discord", content=body_bytes, headers=headers)
        assert res.status_code == 200
        data = res.json()
        assert data["type"] == 5  # DEFERRED_CHANNEL_MESSAGE_WITH_SOURCE
        assert data["data"]["flags"] == 64  # EPHEMERAL

        time.sleep(0.3)

        # 2. Verify background follow-up patch was called exactly once on @original endpoint
        assert mock_patch.call_count == 1
        url = mock_patch.call_args[0][0]
        assert "messages/@original" in url
        patch_json = mock_patch.call_args[1]["json"]
        assert "content" in patch_json

        # 3. Replay protection: repeat interaction ID -> 409 Conflict
        res_dup = client.post("/api/webhooks/discord", content=body_bytes, headers=headers)
        assert res_dup.status_code == 409
