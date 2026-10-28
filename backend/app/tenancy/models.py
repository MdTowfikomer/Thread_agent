"""Tenant-only provider execution. No secret values are placed in graph state.

Provider HTTP targets and supported models are server-owned. Raw provider errors,
response bodies, and request headers are never returned or logged here.
"""
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from functools import wraps
from dataclasses import dataclass, field
import math
from time import perf_counter

from fastapi import HTTPException
from pydantic import SecretStr
import requests

from app.core.crypto import decrypt_secret
from app.tenancy.credentials import (
    credential_record, credential_aad, mark_invalid,
    EMBEDDING_MODEL, EMBEDDING_DIMENSIONS, SUPPORTED_MODELS,
)
from app.tenancy.repository import tenant_repository


class TenantModelNotConfiguredError(HTTPException):
    def __init__(self):
        super().__init__(409, "Configure or reconnect your organization's model API key in Workspace settings.")


class TenantModelUnavailableError(HTTPException):
    def __init__(self, status_code=502, detail="The organization's model provider is unavailable. Retry or check the provider connection in Workspace settings."):
        super().__init__(status_code, detail)


def provider_error(status=None, *, validation=False):
    if status in (400, 401, 403):
        error = TenantModelUnavailableError(400 if validation else 409, "The provider rejected the request or this API key's permissions. Check the key, input limits and project restrictions, then reconnect if needed.")
        error.credential_rejected = status in (401, 403)
        return error
    if status == 404:
        return TenantModelUnavailableError(400 if validation else 502, "The selected model is unavailable to this API key. Select another supported model or check provider access.")
    if status == 429:
        return TenantModelUnavailableError(429, "The provider quota or rate limit was reached. Check project billing/quota and retry later.")
    return TenantModelUnavailableError(503, "Could not reach the model provider. Retry later; no replacement key or provider was used.")


class GoogleProvider:
    def request(self, key, model, *, body=None, validation=False):
        method = "GET" if body is None else "POST"
        endpoint = f"https://generativelanguage.googleapis.com/v1beta/{model}"
        try:
            response = requests.request(method, endpoint, headers={"x-goog-api-key": key},
                                        json=body, timeout=(5, 30), allow_redirects=False)
        except (requests.RequestException, UnicodeError, ValueError):
            raise provider_error(validation=validation) from None
        if response.status_code != 200:
            raise provider_error(response.status_code, validation=validation)
        try:
            data = response.json()
            if not isinstance(data, dict):
                raise ValueError()
            return data
        except (ValueError, TypeError):
            raise TenantModelUnavailableError(502, "The provider returned an invalid response. Retry later.") from None

    def validate(self, key, model):
        # Metadata checks validate authentication and advertised model capabilities;
        # they do not guarantee future inference quota or perform a billed generation.
        for model_id, capability in ((f"models/{model}", "generateContent"), (EMBEDDING_MODEL, "embedContent")):
            data = self.request(key, model_id, validation=True)
            methods = data.get("supportedGenerationMethods")
            if not isinstance(methods, list) or capability not in methods:
                raise TenantModelUnavailableError(400, "This key does not expose the required chat and embedding models. Check provider model access.")


google_provider = GoogleProvider()
_usage_collector = ContextVar("tenant_model_usage", default=None)


def record_usage(org_id, model, operation, started, input_tokens, output_tokens, is_estimated):
    event = {
        "step": "model_usage", "agent_id": "model_provider", "agent_name": "Model provider",
        "status": "completed", "message": f"{operation} completed with {'estimated' if is_estimated else 'provider-reported'} token usage.",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "organization_id": org_id, "provider": "google", "model_name": model, "operation": operation,
        "input_tokens": input_tokens, "output_tokens": output_tokens, "is_estimated": is_estimated,
        "usage_source": "character_heuristic" if is_estimated else "provider",
        "latency_ms": round((perf_counter() - started) * 1000, 2),
        "estimated_cost_usd": None, "cost_status": "not_estimated",
    }
    collector = _usage_collector.get()
    if collector is not None:
        collector.append(event)
    return event


@contextmanager
def capture_usage():
    events = []
    token = _usage_collector.set(events)
    try:
        yield events
    finally:
        _usage_collector.reset(token)


def trace_model_usage(fn):
    @wraps(fn)
    def wrapped(state):
        with capture_usage() as events:
            result = fn(state)
        result["trace"] = list(result.get("trace", state.trace)) + events
        return result
    return wrapped


def _estimated_tokens(text):
    # Explicitly labelled rough heuristic, not a provider tokenizer measurement.
    return max(1, math.ceil(len(text) / 4)) if text else 0


def _valid_count(value):
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def resolve_credential(org_id):
    row = credential_record(org_id)
    if not row or row["status"] != "active" or not row["encrypted_api_key"]:
        raise TenantModelNotConfiguredError()
    if row["provider"] != "google" or row["model_name"] not in SUPPORTED_MODELS or row["embedding_model"] != EMBEDDING_MODEL or row["embedding_dimensions"] != EMBEDDING_DIMENSIONS:
        raise TenantModelUnavailableError(409, "The saved model configuration is incompatible. Reconnect a supported model in Workspace settings.")
    try:
        key = decrypt_secret(row["encrypted_api_key"], associated_data=credential_aad(org_id))
    except HTTPException as exc:
        raise TenantModelUnavailableError(exc.status_code, exc.detail) from None
    return row, key


def ensure_model_configured(org_id):
    # Presence and decryptability are checked before every graph execution, even
    # for empty-evidence and tool paths. Deterministic test flags cannot bypass BYOK.
    resolve_credential(org_id)


@dataclass(frozen=True)
class ScopedChatModel:
    client: object = field(repr=False)
    organization_id: str
    revision: int
    model_name: str


def create_chat_model(context):
    row, key = resolve_credential(context.organization_id)
    try:
        from langchain_google_genai import ChatGoogleGenerativeAI
        # This integration maps retries to Google SDK attempt count: 1 means
        # initial request only; 0 would enable the SDK's default retry policy.
        client = ChatGoogleGenerativeAI(model=row["model_name"], google_api_key=SecretStr(key),
                                       temperature=0.1, timeout=30, max_retries=1)
        return ScopedChatModel(client, context.organization_id, row["revision"], row["model_name"])
    except Exception:
        raise TenantModelUnavailableError() from None


def invoke_chat(llm, prompt, context):
    # Recheck revocation before contacting a provider; never use server-key fallbacks.
    row, _ = resolve_credential(context.organization_id)
    if not isinstance(llm, ScopedChatModel) or llm.organization_id != context.organization_id or llm.revision != row["revision"]:
        raise TenantModelUnavailableError(409, "Model configuration changed before execution. Retry the query.")
    started = perf_counter()
    try:
        from langsmith import tracing_context
        with tracing_context(enabled=False):
            response = llm.client.invoke(prompt, config={"callbacks": []})
    except Exception as exc:
        status = getattr(exc, "status_code", None)
        if not isinstance(status, int):
            status = getattr(exc, "code", None)
        if status in (401, 403):
            mark_invalid(context.organization_id, row["revision"])
        raise provider_error(status) from None
    from app.channels.formatter import coerce_model_text
    text = coerce_model_text(response.content if hasattr(response, "content") else response)
    if not text.strip():
        raise TenantModelUnavailableError(502, "The provider returned no answer. Retry or check its safety and model settings.")
    usage = getattr(response, "usage_metadata", None)
    if not isinstance(usage, dict):
        usage = {}
    reported = _valid_count(usage.get("input_tokens")) and _valid_count(usage.get("output_tokens"))
    record_usage(context.organization_id, row["model_name"], "chat", started,
                 usage["input_tokens"] if reported else _estimated_tokens(prompt),
                 usage["output_tokens"] if reported else _estimated_tokens(text), not reported)
    return text


def stream_chat(llm, prompt, context):
    row, _ = resolve_credential(context.organization_id)
    if not isinstance(llm, ScopedChatModel) or llm.organization_id != context.organization_id or llm.revision != row["revision"]:
        raise TenantModelUnavailableError(409, "Model configuration changed before execution. Retry the query.")
    started = perf_counter()
    try:
        from langsmith import tracing_context
        from app.channels.formatter import coerce_model_text
        with tracing_context(enabled=False):
            accumulated = []
            for chunk in llm.client.stream(prompt, config={"callbacks": []}):
                content = chunk.content if hasattr(chunk, "content") else chunk
                piece = coerce_model_text(content)
                if piece:
                    accumulated.append(piece)
                    yield piece
            full_text = "".join(accumulated)
            if not full_text.strip():
                raise TenantModelUnavailableError(502, "The provider returned no answer. Retry or check its safety and model settings.")
            record_usage(context.organization_id, row["model_name"], "chat", started,
                         _estimated_tokens(prompt), _estimated_tokens(full_text), True)
    except Exception as exc:
        status = getattr(exc, "status_code", None)
        if not isinstance(status, int):
            status = getattr(exc, "code", None)
        if status in (401, 403):
            mark_invalid(context.organization_id, row["revision"])
        raise provider_error(status) from None


def embed(org_id, text, *, document=False):
    row, key = resolve_credential(org_id)
    started = perf_counter()
    body = {"content": {"parts": [{"text": text}]}, "outputDimensionality": EMBEDDING_DIMENSIONS,
            "taskType": "RETRIEVAL_DOCUMENT" if document else "RETRIEVAL_QUERY"}
    try:
        response = google_provider.request(key, f"{EMBEDDING_MODEL}:embedContent", body=body)
    except TenantModelUnavailableError as exc:
        if getattr(exc, "credential_rejected", False):
            mark_invalid(org_id, row["revision"])
        raise
    embedding = response.get("embedding")
    vector = embedding.get("values") if isinstance(embedding, dict) else None
    if not isinstance(vector, list) or len(vector) != EMBEDDING_DIMENSIONS or not all(isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x) for x in vector):
        raise TenantModelUnavailableError(502, "The embedding provider returned an incompatible vector. No vector was saved.")
    norm = math.sqrt(sum(float(x) ** 2 for x in vector))
    if not norm or not math.isfinite(norm):
        raise TenantModelUnavailableError(502, "The embedding provider returned an invalid vector. No vector was saved.")
    metadata = response.get("usageMetadata")
    count = metadata.get("promptTokenCount") if isinstance(metadata, dict) else None
    reported = _valid_count(count)
    record_usage(org_id, EMBEDDING_MODEL, "embedding", started,
                 count if reported else _estimated_tokens(text), 0, not reported)
    return [float(x) / norm for x in vector], EMBEDDING_MODEL
