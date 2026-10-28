"""BYOK API, cryptographic boundaries and provider execution without live secrets.

Provider responses are mocked at the network/SDK boundary. The shared fixture
also runs on PostgreSQL when THREAD_TEST_SERVICE_DB_URL is explicitly configured.
"""
import base64
import json
import os
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.core.crypto import encrypt_secret, decrypt_secret
from app.main import app
from app.tenancy.auth import TenantContext
from app.tenancy.credentials import credential_aad, credential_record, EMBEDDING_MODEL, EMBEDDING_DIMENSIONS
from app.tenancy.models import google_provider, create_chat_model, invoke_chat, capture_usage
from app.tenancy.repository import tenant_repository
from test_v2_identity_and_tenants import service, account, workspace, join

KEY_A = "AIza-synthetic-tenant-A-secret-1111"
KEY_B = "AIza-synthetic-tenant-B-secret-2222"
MASTER = base64.b64encode(bytes(range(32))).decode()


def test_auth_key_format_reaches_provider_without_modification(service, monkeypatch):
    client, _ = account(); org = workspace(client)
    key = "AQ.synthetic_auth-key_123456789012345678901234567890123"
    seen = []
    monkeypatch.setattr(google_provider, "validate", lambda value, model: seen.append(value))
    result = client.post(path(org), json={"api_key": key})
    assert result.status_code == 200, result.text
    assert seen == [key]
    assert decrypt_secret(credential_record(org)["encrypted_api_key"], associated_data=credential_aad(org)) == key
    assert key not in result.text
    from app.tracing.sanitize import redact_text
    assert redact_text("failure " + key) == "failure [REDACTED]"


@pytest.fixture(autouse=True)
def master_key(monkeypatch):
    monkeypatch.setenv("THREAD_MASTER_ENCRYPTION_KEY", MASTER)


def path(org):
    return f"/api/v2/organizations/{org}/credentials/model"


def configure(client, org, monkeypatch, key=KEY_A, model="gemini-3.6-flash"):
    monkeypatch.setattr(google_provider, "validate", lambda *_: None)
    result = client.post(path(org), json={"api_key": key, "model_name": model})
    assert result.status_code == 200, result.text
    return result.json()


def fake_chat(monkeypatch, *, barrier=None, error=None, reported=True):
    created = []
    invoked = []
    class Chat:
        def __init__(self, **kwargs):
            self.key = kwargs["google_api_key"].get_secret_value()
            self.model = kwargs["model"]
            created.append((self.key, self.model))
        def invoke(self, prompt, **kwargs):
            invoked.append(self.key)
            if barrier:
                barrier.wait(timeout=10)
            if error:
                raise error
            label = "Alpha" if self.key == KEY_A else "Beta"
            return SimpleNamespace(content=f"{label}: the Aurora launch is Friday.",
                                   usage_metadata={"input_tokens": 17, "output_tokens": 9} if reported else None)
    monkeypatch.setattr("langchain_google_genai.ChatGoogleGenerativeAI", Chat)
    return created, invoked


def test_aes_envelopes_are_random_authenticated_and_tenant_bound():
    first = encrypt_secret(KEY_A, associated_data="tenant-a")
    second = encrypt_secret(KEY_A, associated_data="tenant-a")
    assert first != second and KEY_A not in first
    assert len(base64.b64decode(first)) == 12 + len(KEY_A) + 16
    assert decrypt_secret(first, associated_data="tenant-a") == KEY_A
    for payload, aad in ((first, "tenant-b"), ("not-base64", "tenant-a")):
        with pytest.raises(HTTPException) as result:
            decrypt_secret(payload, associated_data=aad)
        assert result.value.status_code == 503
        assert KEY_A not in str(result.value)
    raw = bytearray(base64.b64decode(first)); raw[-1] ^= 1
    with pytest.raises(HTTPException):
        decrypt_secret(base64.b64encode(raw).decode(), associated_data="tenant-a")


@pytest.mark.parametrize("master", ["", "not-base64", base64.b64encode(b"short").decode()])
def test_master_key_configuration_is_strict(monkeypatch, master):
    monkeypatch.setenv("THREAD_MASTER_ENCRYPTION_KEY", master)
    with pytest.raises(HTTPException) as result:
        encrypt_secret(KEY_A, associated_data="test")
    assert result.value.status_code == 503
    assert KEY_A not in str(result.value)


def test_save_validates_fixed_models_and_returns_only_safe_metadata(service, monkeypatch, caplog, capsys):
    client, _ = account(); org = workspace(client)
    calls = []
    def request(method, url, **kwargs):
        calls.append((method, url, kwargs))
        capability = "embedContent" if "embedding" in url else "generateContent"
        return SimpleNamespace(status_code=200, json=lambda: {"supportedGenerationMethods": [capability]})
    monkeypatch.setattr("app.tenancy.models.requests.request", request)
    result = client.post(path(org), json={"provider": "google", "api_key": KEY_A})
    assert result.status_code == 200, result.text
    assert len(calls) == 2 and all(call[0] == "GET" for call in calls)
    assert all(call[2]["headers"]["x-goog-api-key"] == KEY_A and KEY_A not in call[1] and call[2]["allow_redirects"] is False for call in calls)
    row = credential_record(org)
    assert row["encrypted_api_key"] != KEY_A
    assert decrypt_secret(row["encrypted_api_key"], associated_data=credential_aad(org)) == KEY_A
    assert row["embedding_dimensions"] == 768
    assert result.json()["masked_key"] == "****…1111"
    assert "encrypted_api_key" not in result.text and KEY_A not in result.text
    assert client.get(path(org)).json() == result.json()
    assert result.headers["cache-control"] == "no-store"
    assert KEY_A not in caplog.text + capsys.readouterr().out


def test_invalid_key_and_provider_errors_are_sanitized_without_saving(service, monkeypatch, caplog, capsys):
    client, _ = account(); org = workspace(client)
    monkeypatch.setattr("app.tenancy.models.requests.request", lambda *a, **k: SimpleNamespace(status_code=401, json=lambda: {"error": KEY_A}))
    result = client.post(path(org), json={"api_key": KEY_A})
    assert result.status_code == 400
    assert credential_record(org) is None
    assert KEY_A not in result.text + caplog.text + capsys.readouterr().out
    def unavailable(*a, **kw):
        import requests
        raise requests.Timeout("provider exception echoes " + KEY_A)
    monkeypatch.setattr("app.tenancy.models.requests.request", unavailable)
    assert client.post(path(org), json={"api_key": KEY_A}).status_code == 503
    assert credential_record(org) is None
    assert KEY_A not in caplog.text + capsys.readouterr().out


def test_admin_permissions_cross_tenant_and_validation_redaction(service, monkeypatch):
    owner, _ = account(); org = workspace(owner)
    member, _, _ = join(owner, org, "reader@example.com")
    outsider, _ = account("outsider@example.com"); workspace(outsider)
    calls = []
    monkeypatch.setattr(google_provider, "validate", lambda *args: calls.append(args))
    for client in (member, outsider):
        assert client.get(path(org)).status_code == 403
        assert client.post(path(org), json={"api_key": KEY_A}).status_code == 403
        assert client.delete(path(org)).status_code == 403
    assert calls == []
    malformed = owner.post(path(org), json={"api_key": KEY_A, "embedding_model": "other-model"})
    assert malformed.status_code == 422 and KEY_A not in malformed.text
    assert owner.post(path(org), json={"api_key": KEY_A, "model_name": "../../unexpected"}).status_code == 400
    assert owner.post(path(org), json={"provider": "openai", "api_key": KEY_A}).status_code == 422
    assert owner.post(path(org), json={"api_key": "non-ascii-秘密-credential"}).status_code == 400


def test_missing_key_never_uses_global_key_or_deterministic_bypass(service, monkeypatch):
    client, _ = account(); org = workspace(client)
    monkeypatch.setenv("GEMINI_API_KEY", "global-key-must-not-be-used")
    created, invoked = fake_chat(monkeypatch)
    for query in ("Hello", "What did our team decide?", "!summary"):
        result = client.post("/api/chat", json={"query": query})
        assert result.status_code == 409 and "Workspace settings" in result.json()["detail"]
    assert created == [] and invoked == []
    assert client.get(path(org)).json()["status"] == "unconfigured"


def test_rotation_revocation_and_embedding_configuration_lock(service, monkeypatch):
    client, user = account(); org = workspace(client)
    configure(client, org, monkeypatch)
    created, invoked = fake_chat(monkeypatch)
    context = TenantContext(org, user, "owner")
    stale = create_chat_model(context)
    before = credential_record(org)
    configure(client, org, monkeypatch, KEY_B, "gemini-3.5-flash-lite")
    after = credential_record(org)
    assert after["revision"] > before["revision"]
    assert after["embedding_model"] == before["embedding_model"] == EMBEDDING_MODEL
    assert after["embedding_dimensions"] == before["embedding_dimensions"] == 768
    with pytest.raises(HTTPException) as changed:
        invoke_chat(stale, "hello", context)
    assert changed.value.status_code == 409 and not invoked
    result = client.post("/api/chat", json={"query": "Hello"})
    assert result.status_code == 200 and result.json()["answer"].startswith("Beta")
    assert invoked == [KEY_B]
    result = client.delete(path(org))
    assert result.status_code == 200 and result.json()["status"] == "revoked"
    row = credential_record(org)
    assert row["encrypted_api_key"] is None and row["key_suffix"] is None
    assert client.post("/api/chat", json={"query": "Hello"}).status_code == 409
    assert invoked == [KEY_B]


def test_master_missing_and_ciphertext_swap_fail_without_global_fallback(service, monkeypatch):
    first, _ = account(); org_a = workspace(first)
    second, _ = account("second@example.com"); org_b = workspace(second)
    configure(first, org_a, monkeypatch)
    configure(second, org_b, monkeypatch, KEY_B)
    copied_ciphertext = credential_record(org_a)["encrypted_api_key"]
    with tenant_repository.transaction() as cur:
        tenant_repository.execute(cur, "UPDATE model_credentials SET encrypted_api_key=%s WHERE organization_id=%s", (copied_ciphertext, org_b))
    created, invoked = fake_chat(monkeypatch)
    result = second.post("/api/chat", json={"query": "Hello"})
    assert result.status_code == 503 and KEY_A not in result.text
    monkeypatch.delenv("THREAD_MASTER_ENCRYPTION_KEY")
    assert first.post("/api/chat", json={"query": "Hello"}).status_code == 503
    assert created == [] and invoked == []


def test_two_tenants_execute_concurrently_with_isolated_clients_and_usage(service, monkeypatch):
    first, _ = account(); org_a = workspace(first)
    second, _ = account("second@example.com"); org_b = workspace(second)
    configure(first, org_a, monkeypatch); configure(second, org_b, monkeypatch, KEY_B)
    created, invoked = fake_chat(monkeypatch, barrier=Barrier(2))
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda client: client.post("/api/chat", json={"query": "Hello"}), (first, second)))
    assert all(response.status_code == 200 for response in responses), [r.text for r in responses]
    assert responses[0].json()["answer"].startswith("Alpha") and responses[1].json()["answer"].startswith("Beta")
    assert sorted(invoked) == sorted([KEY_A, KEY_B])
    for response, org in zip(responses, (org_a, org_b)):
        usage = [step for step in response.json()["trace"] if step["step"] == "model_usage"]
        assert len(usage) == 1 and usage[0]["organization_id"] == org
        assert usage[0]["input_tokens"] == 17 and usage[0]["output_tokens"] == 9
        assert usage[0]["is_estimated"] is False and usage[0]["estimated_cost_usd"] is None
        assert KEY_A not in response.text and KEY_B not in response.text and "encrypted_api_key" not in response.text


def test_provider_failure_has_no_fallback_or_secret_in_errors(service, monkeypatch, caplog, capsys):
    client, _ = account(); org = workspace(client); configure(client, org, monkeypatch)
    class Failure(RuntimeError):
        status_code = 429
    created, invoked = fake_chat(monkeypatch, error=Failure("raw request contains " + KEY_A))
    result = client.post("/api/chat", json={"query": "Hello"})
    assert result.status_code == 429 and len(invoked) == 1
    assert credential_record(org)["status"] == "active"
    assert KEY_A not in result.text + caplog.text + capsys.readouterr().out
    Failure.status_code = 403
    assert client.post("/api/chat", json={"query": "Hello"}).status_code == 409
    assert credential_record(org)["status"] == "invalid"
    assert client.post("/api/chat", json={"query": "Hello"}).status_code == 409
    assert len(invoked) == 2


def test_missing_usage_is_labelled_as_estimated(service, monkeypatch):
    client, _ = account(); org = workspace(client); configure(client, org, monkeypatch)
    fake_chat(monkeypatch, reported=False)
    result = client.post("/api/chat", json={"query": "Hello"})
    assert result.status_code == 200, result.text
    usage = [event for event in result.json()["trace"] if event["step"] == "model_usage"][0]
    assert usage["is_estimated"] is True and usage["usage_source"] == "character_heuristic"
    assert usage["input_tokens"] > 0 and usage["output_tokens"] > 0


def test_tenant_embeddings_and_worker_use_current_key_and_fixed_dimensions(service, monkeypatch):
    from app.memory.store import MemoryStore
    from app.data.reembedder import get_production_embedder
    client, _ = account(); org = workspace(client); configure(client, org, monkeypatch)
    calls = []
    def request(key, model, **kwargs):
        calls.append((key, model, kwargs["body"]))
        return {"embedding": {"values": [1.0] + [0.0] * 767}, "usageMetadata": {"promptTokenCount": 5}}
    monkeypatch.setattr(google_provider, "request", request)
    store = MemoryStore()
    with capture_usage() as usage:
        vector, model = store.embedding_result("organization question", org)
    assert model == EMBEDDING_MODEL and len(vector) == 768 and usage[0]["input_tokens"] == 5
    assert calls[0][0] == KEY_A and calls[0][2]["outputDimensionality"] == 768
    assert calls[0][2]["taskType"] == "RETRIEVAL_QUERY"
    worker = get_production_embedder(organization_id=org)
    configure(client, org, monkeypatch, KEY_B)
    result = worker("a source document")
    assert calls[-1][0] == KEY_B and calls[-1][2]["taskType"] == "RETRIEVAL_DOCUMENT"
    assert result[1:] == (EMBEDDING_MODEL, 768)
    with pytest.raises(HTTPException):
        store._get_embedding("unscoped")
    client.delete(path(org))
    with pytest.raises(HTTPException) as error:
        worker("after deletion")
    assert error.value.status_code == 409


def test_invalid_embedding_never_truncates_or_falls_back(service, monkeypatch):
    from app.memory.store import MemoryStore
    client, _ = account(); org = workspace(client); configure(client, org, monkeypatch)
    monkeypatch.setattr(google_provider, "request", lambda *a, **k: {"embedding": {"values": [1.0] * 3072}})
    with pytest.raises(HTTPException) as error:
        MemoryStore().embedding_result("test", org)
    assert error.value.status_code == 502


def test_summary_tool_uses_tenant_model_and_emits_usage(service, monkeypatch):
    from app.tools.summarizer import summarizer_assistant
    client, _ = account(); org = workspace(client); configure(client, org, monkeypatch)
    monkeypatch.setattr(summarizer_assistant, "fetch_channel_messages", lambda **kwargs: [
        {"author": "Team", "timestamp": "2026-10-28", "content": "The Aurora launch is Friday."},
    ])
    _, invoked = fake_chat(monkeypatch)
    result = client.post("/api/chat", json={"query": "!summary"})
    assert result.status_code == 200, result.text
    assert invoked == [KEY_A] and "Summary" in result.json()["answer"]
    assert any(step["step"] == "model_usage" for step in result.json()["trace"])


def test_ingestion_retrieval_and_generation_share_tenant_key_and_usage(service, monkeypatch):
    from app.core.canonical import MemoryChunk, SourceType, PermissionLevel
    from app.memory.store import MemoryStore
    from app.memory.repository import MemoryRepository
    from app.memory.retrieval import RetrievalService
    client, _ = account(); org = workspace(client); configure(client, org, monkeypatch)
    calls = []
    def embedding_request(key, model, **kwargs):
        calls.append((key, kwargs["body"]["taskType"]))
        return {"embedding": {"values": [1.0] + [0.0] * 767}, "usageMetadata": {"promptTokenCount": 6}}
    monkeypatch.setattr(google_provider, "request", embedding_request)
    store = MemoryStore()
    chunk = MemoryChunk(source_record_id="aurora-source", organization_id=org, source_type=SourceType.DISCORD,
                        author="Team", content="Our Aurora launch is Friday after the final launch review.",
                        permission=PermissionLevel.PUBLIC_COMMUNITY)
    repository = MemoryRepository(in_memory=store, supabase=SimpleNamespace(is_configured=False))
    assert repository.save_chunk(chunk)
    assert chunk.provenance["embedding_model"] == EMBEDDING_MODEL and len(chunk.embedding) == 768
    assert calls == [(KEY_A, "RETRIEVAL_DOCUMENT")]
    retriever = RetrievalService(store=store, supabase_store=SimpleNamespace(is_configured=False))
    monkeypatch.setattr("app.graph.workflow.retrieval_service", retriever)
    fake_chat(monkeypatch)
    response = client.post("/api/chat", json={"query": "When is our Aurora launch?"})
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["sufficient_evidence"] is True and result["citations"][0]["item_id"] == chunk.id
    assert calls[-1] == (KEY_A, "RETRIEVAL_QUERY")
    events = [step for step in result["trace"] if step["step"] == "model_usage"]
    assert [event["operation"] for event in events] == ["embedding", "chat"]
    assert all(event["organization_id"] == org for event in events)
    assert KEY_A not in response.text


def test_late_validation_cannot_restore_deleted_key(service, monkeypatch):
    client, _ = account(); org = workspace(client)
    entered, resume = Event(), Event()
    def validate(*_):
        entered.set()
        assert resume.wait(timeout=10)
    monkeypatch.setattr(google_provider, "validate", validate)
    from app.tenancy.auth import COOKIE
    cookie = client.cookies.get(COOKIE)
    def save():
        other = TestClient(app); other.cookies.set(COOKIE, cookie)
        return other.post(path(org), json={"api_key": KEY_A})
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(save)
        assert entered.wait(timeout=10)
        assert client.delete(path(org)).status_code == 200
        resume.set()
        assert future.result().status_code == 409
    assert credential_record(org)["status"] == "revoked"
    assert credential_record(org)["encrypted_api_key"] is None


def test_missing_master_prevents_provider_validation_and_invalid_rotation_preserves_key(service, monkeypatch):
    client, _ = account(); org = workspace(client)
    calls = []
    monkeypatch.setattr(google_provider, "validate", lambda *args: calls.append(args))
    monkeypatch.delenv("THREAD_MASTER_ENCRYPTION_KEY")
    assert client.post(path(org), json={"api_key": KEY_A}).status_code == 503
    assert calls == [] and credential_record(org) is None
    monkeypatch.setenv("THREAD_MASTER_ENCRYPTION_KEY", MASTER)
    configure(client, org, monkeypatch)
    saved = credential_record(org)
    def reject(*_):
        raise HTTPException(400, "Provider rejected the replacement key.")
    monkeypatch.setattr(google_provider, "validate", reject)
    assert client.post(path(org), json={"api_key": KEY_B}).status_code == 400
    assert credential_record(org)["encrypted_api_key"] == saved["encrypted_api_key"]
    assert credential_record(org)["revision"] == saved["revision"]


def test_model_setup_error_is_actionable_in_platform_reply(service, monkeypatch):
    from app.core.auth import AuthenticatedPrincipal
    from app.core.membership import membership_store
    from app.core.canonical import ChannelType
    from app.channels.inbound_service import inbound_agent_query_service
    from app.channels.outbound import channel_message_delivery_service
    client, user_id = account(); org = workspace(client)
    principal = AuthenticatedPrincipal(user_id=user_id, organization_id=org,
                                       access_context=membership_store.derive_access_context(user_id, org))
    sent = []
    def deliver(**kwargs):
        sent.append(kwargs)
        return {"status": "sent"}
    monkeypatch.setattr(channel_message_delivery_service, "send_prepared_message", deliver)
    result = inbound_agent_query_service.process_and_deliver(principal, ChannelType.DISCORD, "selected-channel", "Hello", idempotency_key="setup-message")
    assert result["intent_category"] == "MODEL_ERROR" and "Workspace settings" in result["answer"]
    assert sent[0]["citations"] == [] and sent[0]["idempotency_key"] == "setup-message"


def test_installed_google_sdk_client_constructs_without_network(service, monkeypatch):
    client, user_id = account(); org = workspace(client); configure(client, org, monkeypatch)
    def no_network(*args, **kwargs):
        raise AssertionError("Client construction must not contact the provider.")
    monkeypatch.setattr("socket.socket.connect", no_network)
    model = create_chat_model(TenantContext(org, user_id, "owner"))
    assert type(model.client).__name__ == "ChatGoogleGenerativeAI"
    assert model.client.max_retries == 1
    assert KEY_A not in repr(model)
