import json
from types import SimpleNamespace
import pytest
from fastapi import HTTPException
from app.tracing.repository import trace_repository
from app.tenancy.repository import tenant_repository
from app.tracing.sanitize import trace_sanitizer
from test_v2_identity_and_tenants import service, account, workspace, join
from test_v2_byok_credentials import configure, fake_chat, MASTER, KEY_A


@pytest.fixture(autouse=True)
def trace_master(monkeypatch):
    monkeypatch.setenv('THREAD_MASTER_ENCRYPTION_KEY',MASTER)


def ask(client,question='Hello'):
    result=client.post('/api/chat',json={'query':question})
    assert result.status_code==200,result.text
    return result.json()


def test_trace_persists_real_stages_and_usage_and_conversation_history(service,monkeypatch):
    client,_=account(); org=workspace(client); configure(client,org,monkeypatch); fake_chat(monkeypatch)
    first=ask(client); second=ask(client)
    assert first['conversation_id']==second['conversation_id']
    assert first['trace_id']!=second['trace_id'] and first['turn_id']!=second['turn_id']
    trace=client.get(f"/api/v2/organizations/{org}/traces/{first['trace_id']}")
    assert trace.status_code==200,trace.text
    row=trace.json()
    assert row['outcome']=='completed' and row['metrics']['input_tokens']==17
    names=[stage['step'] for stage in row['stages']]
    assert names==['triage_router','retrieval_service','role_agent_verification','synthesis','model_usage','platform_formatter']
    assert all(stage['latency_ms']>=0 for stage in row['stages'])
    assert KEY_A not in trace.text and 'chain_of_thought' not in trace.text
    listed=client.get(f"/api/v2/organizations/{org}/conversations/{first['conversation_id']}/traces")
    assert len(listed.json())==2
    assert trace.headers['cache-control']=='no-store'


def test_trace_owner_admin_and_cross_tenant_authorization(service,monkeypatch):
    owner,_=account(); org=workspace(owner); configure(owner,org,monkeypatch); fake_chat(monkeypatch)
    first,first_id,_=join(owner,org,'first@example.com')
    second,_,_=join(owner,org,'second@example.com')
    created=ask(first)
    target=f"/api/v2/organizations/{org}/traces/{created['trace_id']}"
    assert first.get(target).status_code==200
    assert second.get(target).status_code==404
    assert second.get(f"/api/v2/organizations/{org}/conversations/{created['conversation_id']}/traces").status_code==404
    assert owner.get(target).status_code==200
    outsider,_=account('other@example.com'); other_org=workspace(outsider)
    assert outsider.get(target).status_code==403
    assert outsider.get(f"/api/v2/organizations/{other_org}/traces/{created['trace_id']}").status_code==404
    owner.delete(f'/api/v2/organizations/{org}/members/{first_id}')
    assert first.get(target).status_code==403


def test_failures_are_persisted_with_safe_details_and_response_trace_header(service,monkeypatch):
    client,_=account(); org=workspace(client)
    failed=client.post('/api/chat',json={'query':'Hello'})
    assert failed.status_code==409
    trace_id=failed.headers['X-Thread-Trace-Id']
    trace=client.get(f'/api/v2/organizations/{org}/traces/{trace_id}').json()
    assert trace['outcome']=='failed' and trace['stages'][0]['error_status']==409
    configure(client,org,monkeypatch)
    fake_chat(monkeypatch,error=RuntimeError('raw password '+KEY_A))
    failed=client.post('/api/chat',json={'query':'Hello'})
    trace=client.get(f"/api/v2/organizations/{org}/traces/{failed.headers['X-Thread-Trace-Id']}")
    assert trace.status_code==200 and trace.json()['outcome']=='failed'
    assert KEY_A not in trace.text and 'raw password' not in trace.text
    assert any(stage['step']=='synthesis' and stage['status']=='failed' for stage in trace.json()['stages'])


def test_insufficient_evidence_trace_has_counts_without_restricted_titles(service,monkeypatch):
    from app.memory.store import MemoryStore
    from app.memory.retrieval import RetrievalService
    from app.core.canonical import MemoryChunk,PermissionLevel,SourceType
    owner,_=account(); org=workspace(owner); configure(owner,org,monkeypatch)
    member,_,_=join(owner,org,'reader@example.com')
    store=MemoryStore()
    store.add_chunk(MemoryChunk(source_record_id='private',organization_id=org,source_type=SourceType.DISCORD,
                               author='SECRET AUTHOR',title='SECRET TITLE',content='SECRET PAYLOAD',
                               permission=PermissionLevel.INTERNAL_CORE,embedding=[1.0]+[0.0]*767))
    monkeypatch.setattr('app.graph.workflow.retrieval_service',RetrievalService(store=store,supabase_store=SimpleNamespace(is_configured=False)))
    response=ask(member,'What is our internal decision?')
    assert response['sufficient_evidence'] is False
    trace=member.get(f"/api/v2/organizations/{org}/traces/{response['trace_id']}")
    assert trace.json()['outcome']=='refused'
    assert all(value not in trace.text for value in ('SECRET AUTHOR','SECRET TITLE','SECRET PAYLOAD'))


def test_read_rechecks_source_scope_after_admin_demotion(service,monkeypatch):
    owner,_=account(); org=workspace(owner)
    admin,admin_id,_=join(owner,org,'admin@example.com','admin')
    ids=trace_repository.begin(org,admin_id,'private-session','web_chat')
    trace_repository.finish(ids['trace_id'],org,'completed',[{'step':'retrieval_service','status':'completed',
        'evidence':[{'item_id':'private-id','permission':'INTERNAL_CORE','title':'Hidden finance','author':'Hidden author'}],
        'scores':{'private-id':{'dense_similarity':.9}}}],1)
    target=f"/api/v2/organizations/{org}/traces/{ids['trace_id']}"
    assert 'Hidden finance' in admin.get(target).text
    owner.patch(f'/api/v2/organizations/{org}/members/{admin_id}',json={'role':'member'})
    response=admin.get(target)
    assert response.status_code==200
    assert all(value not in response.text for value in ('private-id','Hidden finance','Hidden author'))


def test_sanitizer_removes_secrets_and_nontelemetry_fields():
    value=trace_sanitizer.stages([{'step':'synthesis','message':f'failure {KEY_A} postgresql://user:password@db/private',
                                 'prompt':'hidden','chain_of_thought':'hidden','api_key':KEY_A,
                                 'scores':{KEY_A:{'dense_similarity':.5}}}])
    encoded=json.dumps(value)
    assert KEY_A not in encoded and 'postgresql://' not in encoded and 'hidden' not in encoded


def test_storage_failure_does_not_fall_back_to_service_db(service,monkeypatch):
    client,_=account(); workspace(client)
    def unavailable():
        raise OSError('postgresql://user:secret@db')
    monkeypatch.setattr(trace_repository,'connection_factory',unavailable)
    response=client.post('/api/chat',json={'query':'Hello'})
    assert response.status_code==503 and 'user:secret' not in response.text


def test_role_downgrade_uses_a_new_history_context(service,monkeypatch):
    owner,_=account(); org=workspace(owner); configure(owner,org,monkeypatch); fake_chat(monkeypatch)
    admin,admin_id,_=join(owner,org,'context-admin@example.com','admin')
    before=ask(admin)
    owner.patch(f'/api/v2/organizations/{org}/members/{admin_id}',json={'role':'member'})
    after=ask(admin)
    assert before['conversation_id']!=after['conversation_id']
