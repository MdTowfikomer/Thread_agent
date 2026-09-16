import os
import pytest
from unittest.mock import MagicMock, patch, AsyncMock
from types import SimpleNamespace
from app.core.canonical import ChannelType, PermissionLevel
from app.channels.installation import GuildInstallationStore
from app.channels.policy import ChannelPolicyStore
from app.channels.gateway import DiscordGatewayBot

def test_two_fresh_workers_read_same_durable_policies_without_hardcoded_defaults(monkeypatch):
    """
    Validates that two independently created worker instances load identical
    authoritative guild installations and channel policies from durable storage,
    starting from zero in-memory state and containing zero hardcoded defaults.
    """
    # Create two completely independent, fresh store instances
    worker1_guilds = GuildInstallationStore()
    worker1_policies = ChannelPolicyStore()
    worker2_guilds = GuildInstallationStore()
    worker2_policies = ChannelPolicyStore()

    # Prior to loading, stores must be completely empty (ZERO hardcoded defaults)
    assert len(worker1_guilds._installations) == 0
    assert len(worker2_guilds._installations) == 0
    assert len(worker1_policies._policies) == 0
    assert len(worker2_policies._policies) == 0

    # Ensure get_installation / get_policy return None when unpopulated
    assert worker1_guilds.get_organization_for_guild("1549162455874412667") is None
    assert worker2_guilds.get_organization_for_guild("1549162455874412667") is None
    assert worker1_policies.get_policy(organization_id="gdg_mcet", channel_type=ChannelType.DISCORD, channel_id="1549162457359065110", guild_id="1549162455874412667") is None
    assert worker2_policies.get_policy(organization_id="gdg_mcet", channel_type=ChannelType.DISCORD, channel_id="1549162457359065110", guild_id="1549162455874412667") is None

    # Simulate durable PostgreSQL records returned from Supabase
    durable_guilds = [
        ("1549162455874412667", "gdg_mcet", "GDG MCET Discord", True)
    ]
    durable_policies = [
        ("gdg_mcet", "discord", "1549162455874412667", "1549162457359065110", "general", "PUBLIC_COMMUNITY", True, {}),
        ("gdg_mcet", "discord", "1549162455874412667", "1549434796772560967", "core-team", "INTERNAL_CORE", True, {})
    ]

    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_conn.__enter__.return_value = mock_conn
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

    def mock_execute(query, params=None):
        if "FROM discord_guild_installations" in str(query):
            mock_cursor.fetchall.return_value = durable_guilds
        elif "FROM channel_policies" in str(query):
            mock_cursor.fetchall.return_value = durable_policies
        return None

    mock_cursor.execute.side_effect = mock_execute

    monkeypatch.setenv("SUPABASE_DB_URL", "postgresql://test:test@localhost:5432/testdb")

    with patch("psycopg2.connect", return_value=mock_conn):
        # Worker 1 loads from DB
        g_count1 = worker1_guilds.load_from_database(fail_on_error=True)
        p_count1 = worker1_policies.load_from_database(fail_on_error=True)

        # Worker 2 loads independently from DB
        g_count2 = worker2_guilds.load_from_database(fail_on_error=True)
        p_count2 = worker2_policies.load_from_database(fail_on_error=True)

    assert g_count1 == 1 and g_count2 == 1
    assert p_count1 == 2 and p_count2 == 2

    # Prove both workers resolve identical organizations
    org1 = worker1_guilds.get_organization_for_guild("1549162455874412667")
    org2 = worker2_guilds.get_organization_for_guild("1549162455874412667")
    assert org1 == "gdg_mcet"
    assert org2 == "gdg_mcet"

    # Prove both workers resolve identical channel policies
    pol1_pub = worker1_policies.get_policy(organization_id="gdg_mcet", channel_type=ChannelType.DISCORD, channel_id="1549162457359065110", guild_id="1549162455874412667")
    pol2_pub = worker2_policies.get_policy(organization_id="gdg_mcet", channel_type=ChannelType.DISCORD, channel_id="1549162457359065110", guild_id="1549162455874412667")
    assert pol1_pub is not None and pol2_pub is not None
    assert pol1_pub.channel_name == pol2_pub.channel_name == "general"
    assert pol1_pub.permission_scope == pol2_pub.permission_scope == PermissionLevel.PUBLIC_COMMUNITY

    pol1_priv = worker1_policies.get_policy(organization_id="gdg_mcet", channel_type=ChannelType.DISCORD, channel_id="1549434796772560967", guild_id="1549162455874412667")
    pol2_priv = worker2_policies.get_policy(organization_id="gdg_mcet", channel_type=ChannelType.DISCORD, channel_id="1549434796772560967", guild_id="1549162455874412667")
    assert pol1_priv is not None and pol2_priv is not None
    assert pol1_priv.channel_name == pol2_priv.channel_name == "core-team"
    assert pol1_priv.permission_scope == pol2_priv.permission_scope == PermissionLevel.INTERNAL_CORE

def test_workers_fail_closed_on_database_read_failure(monkeypatch):
    """
    Validates that gateway startup and store binding loaders fail closed
    with a RuntimeError when a database read error occurs.
    """
    worker_guilds = GuildInstallationStore()
    worker_policies = ChannelPolicyStore()
    bot = DiscordGatewayBot()

    monkeypatch.setenv("SUPABASE_DB_URL", "postgresql://test:test@localhost:5432/testdb")

    with patch("psycopg2.connect", side_effect=RuntimeError("PostgreSQL connection timeout")):
        with pytest.raises(RuntimeError) as exc_g:
            worker_guilds.load_from_database(fail_on_error=True)
        assert "Database error reading Discord guild installations" in str(exc_g.value)

        with pytest.raises(RuntimeError) as exc_p:
            worker_policies.load_from_database(fail_on_error=True)
        assert "Database error reading channel policies" in str(exc_p.value)

        with pytest.raises(RuntimeError) as exc_bot:
            bot.load_bindings(fail_on_error=True)
        assert "Database error reading Discord guild installations" in str(exc_bot.value) or "Failed to load" in str(exc_bot.value)

def test_workers_reject_unbound_channels_and_guilds(monkeypatch):
    """
    Validates that both workers strictly reject unbound guilds and channels:
    A missing policy means do not ingest and do not reply.
    """
    import asyncio

    async def run_check():
        from app.channels.outbound import channel_message_delivery_service

        bot1 = DiscordGatewayBot()
        bot2 = DiscordGatewayBot()

        # Set up mock bot client
        bot_user = SimpleNamespace(id="1549157747495280641")
        client = SimpleNamespace(user=bot_user)

        # Unbound guild & channel
        unbound_guild = SimpleNamespace(id="999999999999999999", name="Unbound Guild")
        unbound_channel = SimpleNamespace(id="888888888888888888", name="secret-channel")
        author = SimpleNamespace(id="user_unbound_1", name="alice", display_name="Alice", bot=False)

        msg = SimpleNamespace(
            id="msg_unbound_1",
            guild=unbound_guild,
            channel=unbound_channel,
            author=author,
            content="<@1549157747495280641> hello there",
            mentions=[bot_user],
            reference=None,
            reply=AsyncMock()
        )

        send_calls = []
        def mock_send_message(principal, platform, destination_id, query, idempotency_key):
            send_calls.append(locals())
            return {"status": "sent"}

        monkeypatch.setattr(channel_message_delivery_service, "send_message", mock_send_message)

        # Both workers execute handle_discord_mention_reply on unbound channel
        await bot1.handle_discord_mention_reply(msg, client)
        await bot2.handle_discord_mention_reply(msg, client)

        # Zero outbound messages or replies sent by either worker
        assert len(send_calls) == 0
        assert msg.reply.call_count == 0

    asyncio.run(run_check())
