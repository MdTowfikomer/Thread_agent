from types import SimpleNamespace
import pytest
from app.channels import progress
from app.channels.inbound_service import InboundAgentQueryService
from app.channels.outbound import channel_message_delivery_service
from app.core.auth import AuthenticatedPrincipal
from app.core.canonical import AccessContext, ChannelType, PermissionLevel


@pytest.mark.parametrize('platform',[ChannelType.DISCORD,ChannelType.SLACK,ChannelType.TELEGRAM])
def test_native_progress_precedes_work_and_final_reply_and_stays_destination_scoped(monkeypatch,platform):
    monkeypatch.delenv('THREAD_PROGRESS_ENABLED',raising=False)
    clock=[0.0];monkeypatch.setattr(progress,'monotonic',lambda:clock[0])
    access=AccessContext(user_id='public-test',organization_id='org-test',role_id='member',user_permission=PermissionLevel.PUBLIC_COMMUNITY,allowed_scopes=[PermissionLevel.PUBLIC_COMMUNITY])
    principal=AuthenticatedPrincipal(user_id=access.user_id,organization_id=access.organization_id,access_context=access)
    sent=[]
    def send(**kwargs):sent.append(kwargs);return {'status':'sent'}
    monkeypatch.setattr(channel_message_delivery_service,'send_prepared_message',send)
    monkeypatch.setattr('app.channels.inbound_service.conversation_store.get_recent_turns',lambda **k:[])
    monkeypatch.setattr('app.channels.inbound_service.conversation_store.record_turn',lambda *a:True)
    service=InboundAgentQueryService()
    def query(**kwargs):
        assert sent and sent[0]['text']=='Checking records…'
        clock[0]=2.0
        progress.notify_stage('synthesis',SimpleNamespace(intent_category='ORGANIZATIONAL_FACTS'))
        return {'answer':'The review starts Monday at 11 AM.','intent_category':'ORGANIZATIONAL_FACTS','citations':[],'receipt':None}
    monkeypatch.setattr(service,'process_query',query)
    service.process_and_deliver(principal,platform,'bound-destination','When is the Aurora review?',idempotency_key='source-event-1')
    assert len(sent)==3
    assert sent[-1]['text']=='The review starts Monday at 11 AM.'
    assert all(s['principal'] is principal and s['destination_id']=='bound-destination' and s['platform']==platform for s in sent)
    assert all(s['citations']==[] for s in sent[:-1])
    assert [s['idempotency_key'] for s in sent[:2]]==['source-event-1:progress:0','source-event-1:progress:1']
    assert sent[-1]['idempotency_key']=='source-event-1'


def test_progress_failure_does_not_stop_model_work_or_leak_provider_details(monkeypatch,caplog):
    monkeypatch.delenv('THREAD_PROGRESS_ENABLED',raising=False)
    def fail(**kwargs):raise RuntimeError('synthetic-private-token')
    monkeypatch.setattr(channel_message_delivery_service,'send_prepared_message',fail)
    with progress.NativeProgress(None,ChannelType.SLACK,'bound','!github','event') as reporter:
        assert not reporter.available
    assert 'synthetic-private-token' not in caplog.text


def test_progress_never_bypasses_rejected_destination(monkeypatch):
    monkeypatch.delenv('THREAD_PROGRESS_ENABLED',raising=False)
    def deny(**kwargs):raise PermissionError('Unbound destination')
    monkeypatch.setattr(channel_message_delivery_service,'send_prepared_message',deny)
    with pytest.raises(PermissionError):
        with progress.NativeProgress(None,ChannelType.DISCORD,'unbound','!github','event'):pass


def test_progress_descriptions_use_templates_not_raw_query_text():
    assert progress.initial_message('!github latest commits')=='Checking repository activity…'
    assert progress.initial_message('Explain a mutex')=='Preparing an answer…'
    assert progress.initial_message('What is the secret project schedule?')=='Checking records…'
