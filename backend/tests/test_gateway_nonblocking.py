"""Gateway callbacks must leave synchronous imports and I/O off the event loop."""
import asyncio
import builtins
import threading
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from app.channels.gateway import DiscordGatewayBot, DiscordThreadClient
from app.channels.inbound_service import inbound_agent_query_service
from app.channels.policy import channel_policy_store
from app.core.membership import membership_store
from app.identity.service import identity_service, CrossChannelIdentityService
from app.memory.supabase_store import SupabaseMemoryStore


def message():
    return SimpleNamespace(
        author=SimpleNamespace(bot=False, id=55, name='Synthetic member', display_name='Synthetic member'),
        guild=SimpleNamespace(id=11223344),
        channel=SimpleNamespace(id=12345, typing=MagicMock(return_value=AsyncMock())),
        id=67890, content='<@123> When is the review?', mentions=[], reference=None,
        reply=AsyncMock(),
    )


def test_mention_cold_import_and_identity_resolution_run_off_loop(monkeypatch):
    async def run():
        loop_thread=threading.get_ident()
        called=[]
        original_import=builtins.__import__
        def guarded_import(name, *args, **kwargs):
            if name in {'app.channels.inbound_service', 'app.identity.service'}:
                called.append(('import', threading.get_ident()))
            return original_import(name, *args, **kwargs)
        def resolve(**kwargs):
            called.append(('identity', threading.get_ident()))
            return SimpleNamespace(person_id='usr_arjun')
        def process(**kwargs):
            called.append(('process', threading.get_ident()))
            return {'status':'delivered'}
        monkeypatch.setattr(identity_service,'resolve_identity',resolve)
        monkeypatch.setattr(inbound_agent_query_service,'process_and_deliver',process)
        monkeypatch.setattr(builtins,'__import__',guarded_import)
        monkeypatch.setattr(channel_policy_store,'get_policy',lambda *a:SimpleNamespace(is_active=True))
        bot=DiscordGatewayBot(num_workers=0, installation_store=SimpleNamespace(get_organization_for_guild=lambda *_:'gdg_mcet'))
        await bot.handle_discord_mention_reply(message(),SimpleNamespace(user=SimpleNamespace(id=123)))
        assert any(kind=='process' for kind,_ in called)
        assert all(thread != loop_thread for _,thread in called), called
    asyncio.run(run())


def test_queue_binding_lookup_runs_off_loop(monkeypatch):
    async def run():
        loop_thread=threading.get_ident()
        called=[]
        def lookup(*args):
            called.append(threading.get_ident())
            return 'gdg_mcet'
        bot=DiscordGatewayBot(num_workers=0)
        monkeypatch.setattr(bot.installation_store,'get_organization_for_guild',lookup)
        monkeypatch.setattr(channel_policy_store,'get_policy',lambda *a:SimpleNamespace(is_active=True))
        bot.handle_discord_mention_reply=AsyncMock()
        client=DiscordThreadClient(bot_service=bot)
        await client.on_message(message())
        assert called and all(thread != loop_thread for thread in called)
        assert bot.ingestion_queue.qsize()==1
    asyncio.run(run())


def test_configured_identity_service_never_bootstraps_demo_links(monkeypatch):
    monkeypatch.setenv('THREAD_SERVICE_DB_URL','synthetic-configured-service')
    monkeypatch.setenv('THREAD_ALLOW_OFFLINE_IDENTITY','1')
    link=MagicMock()
    monkeypatch.setattr(CrossChannelIdentityService,'link_account',link)
    service=CrossChannelIdentityService()
    service.reset()
    link.assert_not_called()


def test_direct_postgres_does_not_initialize_optional_rest_client(monkeypatch):
    from app.core.config import settings
    monkeypatch.setenv('SUPABASE_DB_URL','synthetic-direct-postgres')
    monkeypatch.setattr(settings,'SUPABASE_URL','')
    monkeypatch.setattr(settings,'SUPABASE_SERVICE_ROLE_KEY','')
    create=MagicMock()
    monkeypatch.setattr('supabase.create_client',create)
    store=SupabaseMemoryStore()
    assert store.is_configured
    assert store.client is None
    create.assert_not_called()
