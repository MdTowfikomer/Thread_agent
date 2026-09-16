import asyncio
import os
import logging
from unittest.mock import MagicMock, AsyncMock, patch
import pytest

from app.channels.run_gateway import main
from app.channels.gateway import DiscordGatewayBot


def test_run_gateway_fails_closed_on_db_error():
    """Verify run_gateway fails closed when advisory lock DB check throws an error."""
    async def run():
        with patch.dict(os.environ, {
            "DISCORD_BOT_TOKEN": "valid_mock_token_123",
            "SUPABASE_DB_URL": "postgresql://invalid:5432/db"
        }):
            with patch("app.channels.run_gateway.try_acquire_gateway_advisory_lock", side_effect=RuntimeError("PostgreSQL connection error")):
                with pytest.raises(RuntimeError) as excinfo:
                    await main()
                assert "PostgreSQL connection error" in str(excinfo.value)

    asyncio.run(run())


def test_run_gateway_acquires_lock_and_logs_started_and_connected(caplog):
    """Verify run_gateway logs 'gateway worker started', 'gateway worker connected' on ready, and releases lock."""
    async def run():
        mock_conn = MagicMock()
        with patch.dict(os.environ, {"DISCORD_BOT_TOKEN": "valid_mock_token_123"}):
            with patch("app.channels.run_gateway.try_acquire_gateway_advisory_lock", return_value=mock_conn):
                with patch("app.channels.run_gateway.release_gateway_advisory_lock") as mock_release:
                    with patch("app.channels.run_gateway.discord_gateway_bot.start", new_callable=AsyncMock) as mock_start:
                        async def simulate_start():
                            # Simulate discord.py client triggering on_ready
                            from app.channels.run_gateway import discord_gateway_bot
                            await discord_gateway_bot.on_client_ready()

                        mock_start.side_effect = simulate_start

                        with caplog.at_level(logging.INFO):
                            await main()

                        mock_release.assert_called_once_with(mock_conn)

        log_text = caplog.text
        assert "gateway worker started" in log_text
        assert "gateway worker connected" in log_text

    asyncio.run(run())


def test_run_gateway_standby_transitions_to_started(caplog):
    """Verify run_gateway handles initial standby when lock held by peer, then starts once lock is acquired."""
    async def run():
        mock_conn = MagicMock()
        # First call returns None (held by peer), second returns mock_conn
        lock_results = [None, mock_conn]

        def get_lock(fail_on_db_error=True):
            return lock_results.pop(0)

        with patch.dict(os.environ, {"DISCORD_BOT_TOKEN": "valid_mock_token_123"}):
            with patch("app.channels.run_gateway.try_acquire_gateway_advisory_lock", side_effect=get_lock):
                with patch("app.channels.run_gateway.release_gateway_advisory_lock") as mock_release:
                    with patch("app.channels.run_gateway.discord_gateway_bot.start", new_callable=AsyncMock):
                        with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
                            with caplog.at_level(logging.INFO):
                                await main()

                            mock_sleep.assert_awaited_once_with(15)
                            mock_release.assert_called_once_with(mock_conn)

        log_text = caplog.text
        assert "gateway worker standby" in log_text
        assert "gateway worker started" in log_text

    asyncio.run(run())
