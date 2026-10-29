from types import SimpleNamespace
from app.channels.inbound_service import InboundAgentQueryService
from app.core.auth import AuthenticatedPrincipal
from app.core.canonical import AccessContext,ChannelType,PermissionLevel


def test_tool_is_not_reported_finished_before_execution(monkeypatch):
    from app.graph import workflow
    from app.channels import inbound_service
    access=AccessContext(user_id='sample',organization_id='sample-org',role_id='member',user_permission=PermissionLevel.PUBLIC_COMMUNITY,allowed_scopes=[PermissionLevel.PUBLIC_COMMUNITY])
    principal=AuthenticatedPrincipal(user_id=access.user_id,organization_id=access.organization_id,access_context=access)
    monkeypatch.setattr(workflow,'triage_node',lambda state:{'intent_category':'TOOL_EXECUTION','tool_name':'github'})
    monkeypatch.setattr(workflow,'retrieval_node',lambda state:{})
    monkeypatch.setattr(workflow,'role_agent_node',lambda state:{})
    executed=[]
    def prepare(state):executed.append(True);return None,'The repository lookup is complete.',None
    monkeypatch.setattr(workflow,'prepare_synthesis',prepare)
    monkeypatch.setattr(inbound_service,'get_workspace',lambda org:SimpleNamespace(default_role_id='general'))
    monkeypatch.setattr(inbound_service,'get_role_agent',lambda *a:None)
    monkeypatch.setattr(inbound_service.conversation_store,'get_recent_turns',lambda **k:[])
    monkeypatch.setattr(inbound_service.conversation_store,'record_turn',lambda *a:True)
    events=InboundAgentQueryService().process_query_stream('!github',access.organization_id,principal,ChannelType.WEB_CHAT)
    finished=0
    for event in events:
        if event.get('type')=='tool_call' and event.get('status')=='completed':
            assert executed,'Tool completion was emitted before the tool ran'
            finished+=1
    assert finished==1


def test_stream_usage_scope_does_not_cross_sse_yields(monkeypatch):
    from contextvars import copy_context
    from time import perf_counter
    from app.graph import workflow
    from app.channels import inbound_service
    from app.tenancy.models import record_usage, _usage_collector

    access=AccessContext(user_id='sample',organization_id='sample-org',role_id='member',user_permission=PermissionLevel.PUBLIC_COMMUNITY,allowed_scopes=[PermissionLevel.PUBLIC_COMMUNITY])
    principal=AuthenticatedPrincipal(user_id=access.user_id,organization_id=access.organization_id,access_context=access)
    monkeypatch.setattr(workflow,'triage_node',lambda state:{'intent_category':'GENERAL_KNOWLEDGE'})
    monkeypatch.setattr(workflow,'retrieval_node',lambda state:{})
    monkeypatch.setattr(workflow,'role_agent_node',lambda state:{})
    monkeypatch.setattr(workflow,'prepare_synthesis',lambda state:('prompt',None,None))
    def stream(state, prompt):
        yield 'A mutex '
        yield 'protects shared state.'
        record_usage(state.organization_id,'synthetic-model','chat',perf_counter(),3,5,True)
    monkeypatch.setattr(workflow,'stream_for_state',stream)
    monkeypatch.setattr(inbound_service,'get_workspace',lambda org:SimpleNamespace(default_role_id='general'))
    monkeypatch.setattr(inbound_service,'get_role_agent',lambda *a:None)
    monkeypatch.setattr(inbound_service.conversation_store,'get_recent_turns',lambda **k:[])
    monkeypatch.setattr(inbound_service.conversation_store,'record_turn',lambda *a:True)
    events=InboundAgentQueryService().process_query_stream('Explain mutex',access.organization_id,principal,ChannelType.WEB_CHAT)
    emitted=[]
    while True:
        try:
            emitted.append(copy_context().run(next,events))
        except StopIteration:
            break
        assert _usage_collector.get() is None
    result=next(event['response'] for event in emitted if event['type']=='complete')
    usage=[event for event in result['trace'] if event['step']=='model_usage']
    assert len(usage)==1
    assert usage[0]['output_tokens']==5
    assert emitted[-2]['step']=='finalizing' and emitted[-2]['status']=='completed'
