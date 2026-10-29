"""Errors after SSE headers are sent must remain readable terminal events."""
import json
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from app.main import app
from app.core.auth import AuthenticatedPrincipal, get_current_principal
from app.core.canonical import AccessContext, PermissionLevel
from app.channels.inbound_service import inbound_agent_query_service


@pytest.mark.parametrize('expected_http_error', [True, False])
def test_stream_returns_terminal_error_without_crashing_or_logging_secrets(monkeypatch, caplog, expected_http_error):
    context=AccessContext(user_id='stream-test-user',organization_id='stream-test-org',role_id='member',
                          user_permission=PermissionLevel.PUBLIC_COMMUNITY,allowed_scopes=[PermissionLevel.PUBLIC_COMMUNITY])
    principal=AuthenticatedPrincipal(user_id=context.user_id,organization_id=context.organization_id,access_context=context)
    monkeypatch.setitem(app.dependency_overrides,get_current_principal,lambda:principal)
    secret='synthetic-private-provider-key'
    detail='Credential encryption is unavailable. Ask the operator to check THREAD_MASTER_ENCRYPTION_KEY.'
    def fail_after_first_event(**kwargs):
        yield {'type':'stage','step':'triage_router','status':'running'}
        if expected_http_error:
            raise HTTPException(503,detail)
        raise RuntimeError(secret)
    monkeypatch.setattr(inbound_agent_query_service,'process_query_stream',fail_after_first_event)
    response=TestClient(app).post('/api/chat/stream',json={'query':'What has our team decided recently?'})
    assert response.status_code==200  # Streaming headers precede the failure.
    events=[json.loads(line.removeprefix('data: ')) for line in response.text.splitlines() if line.startswith('data: ')]
    assert [event['type'] for event in events]==['stage','error']
    assert events[-1]['status']==(503 if expected_http_error else 500)
    assert events[-1]['error']==(detail if expected_http_error else 'The query could not be completed. Retry later.')
    assert secret not in response.text+caplog.text
