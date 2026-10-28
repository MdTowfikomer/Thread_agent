"""Observe actual executed stages, including failures, without model thoughts."""
from contextvars import ContextVar
from datetime import datetime, timezone
from functools import wraps
from time import perf_counter

from fastapi import HTTPException
from app.tracing.sanitize import trace_sanitizer, redact_text

_stages = ContextVar("execution_trace_stages", default=None)


def observe_stage(name):
    def decorate(fn):
        @wraps(fn)
        def wrapped(state):
            started = perf_counter()
            try:
                result = fn(state)
            except Exception as exc:
                collector = _stages.get()
                if collector is not None:
                    status = exc.status_code if isinstance(exc, HTTPException) else 500
                    collector.append({"step": name, "status": "failed", "latency_ms": round((perf_counter()-started)*1000, 2),
                                      "message": "Check the workspace model connection or service availability; retry after resolving the failure.",
                                      "error_status": status, "timestamp": datetime.now(timezone.utc).isoformat()})
                raise
            events = [dict(event) for event in result.get("trace", [])[len(state.trace):]]
            for event in events:
                if event.get("step") != "model_usage":
                    event["latency_ms"] = round((perf_counter()-started)*1000, 2)
                    event["intent_category"] = result.get("intent_category", state.intent_category)
            pack = result.get("evidence_pack")
            if pack is not None:
                event = next((e for e in events if e.get("step") == "retrieval_service"), None)
                if event is not None:
                    event.update(strategy=pack.receipt.retrieval_strategy, embedding_model=pack.receipt.query_embedding_model,
                                 filtered_count=max(0, pack.receipt.candidates_before_acl-pack.receipt.candidates_after_acl),
                                 authorized_count=pack.receipt.candidates_after_acl, sufficient_evidence=pack.sufficient_evidence,
                                 scores=pack.receipt.score_details,
                                 evidence=[{"item_id": c.item_id, "title": c.title, "author": c.author,
                                            "permission": c.permission.value, "score": c.relevance_score,
                                            "source": c.source.value} for c in pack.citations])
            collector = _stages.get()
            if collector is not None:
                collector.extend(trace_sanitizer.stages(events))
            result["trace"] = list(state.trace) + events
            return result
        return wrapped
    return decorate


class ObservedGraph:
    def __init__(self, graph):
        self.graph = graph

    def __getattr__(self, name):
        return getattr(self.graph, name)

    def invoke(self, state, *args, **kwargs):
        from app.graph.state import GraphState
        from app.tenancy.repository import tenant_repository
        from app.tracing.repository import trace_repository
        from app.channels.formatter import coerce_model_text
        if isinstance(state, dict):
            state = GraphState(**state)
        ids = {}
        started = perf_counter()
        if tenant_repository.configured:
            if not state.access_context or state.access_context.organization_id != state.organization_id:
                raise HTTPException(403, "Verified organization access is required for trace execution.")
            ids = trace_repository.begin(state.organization_id, state.access_context.user_id,
                                         state.session_key or f"direct:{state.access_context.user_id}", state.platform)
        events = []
        token = _stages.set(events)
        try:
            result = self.graph.invoke(state, *args, **kwargs)
            format_start = perf_counter()
            result["final_answer"] = redact_text(coerce_model_text(result.get("final_answer", "")))
            pack = result.get("evidence_pack")
            if pack:
                pack.citations = [c.model_copy(update={"snippet": redact_text(c.snippet), "title": redact_text(c.title) if c.title else None,
                                                       "author": redact_text(c.author), "source_uri": redact_text(c.source_uri) if c.source_uri else None}) for c in pack.citations]
            events.append({"step": "platform_formatter", "status": "completed", "agent_name": "Output formatting",
                           "message": "Normalized response text and redacted credential patterns.",
                           "latency_ms": round((perf_counter()-format_start)*1000, 2), "timestamp": datetime.now(timezone.utc).isoformat()})
            outcome = "refused" if result.get("intent_category") == "ORGANIZATIONAL_FACTS" and (not pack or not pack.sufficient_evidence) else "completed"
            result["trace"] = trace_sanitizer.stages(events)
            if ids:
                trace_repository.finish(ids["trace_id"], state.organization_id, outcome, events, (perf_counter()-started)*1000)
            return {**result, **ids}
        except Exception as exc:
            if ids:
                try:
                    trace_repository.finish(ids["trace_id"], state.organization_id, "failed", events, (perf_counter()-started)*1000)
                except HTTPException:
                    pass  # A pre-created running trace remains inspectable after recovery.
                headers = {"X-Thread-Trace-Id": ids["trace_id"], "X-Thread-Conversation-Id": ids["conversation_id"]}
                if isinstance(exc, HTTPException):
                    exc.detail = trace_sanitizer.clean(exc.detail)
                    exc.headers = {**(exc.headers or {}), **headers}
                else:
                    raise HTTPException(500, "Query execution failed. Inspect the execution trace or retry.", headers=headers) from None
            raise
        finally:
            _stages.reset(token)
