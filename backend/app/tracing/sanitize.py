"""Bounded, allowlisted trace payloads; no prompts or hidden model reasoning."""
import math
import os
import re

PATTERNS = (
    re.compile(r"\bAQ\.[A-Za-z0-9_.-]{12,}"),
    re.compile(r"AIza[A-Za-z0-9_-]{12,}"),
    re.compile(r"sk-[A-Za-z0-9_-]{12,}"),
    re.compile(r"postgres(?:ql)?://[^\s\"'<>]+", re.I),
    re.compile(r"\b(?:password|api_key|access_token)\s*[=:]\s*[^\s,;]+", re.I),
    re.compile(r"\beyJ[A-Za-z0-9_-]+\.eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+"),
)
FORBIDDEN = {"api_key", "encrypted_api_key", "password", "password_hash", "token", "system_prompt",
             "prompt", "query", "answer", "content", "snippet", "reasoning", "chain_of_thought", "headers"}
STAGE_FIELDS = {"step","agent_id","agent_name","status","message","timestamp","latency_ms",
                "organization_id","provider","model_name","operation","input_tokens","output_tokens",
                "is_estimated","usage_source","estimated_cost_usd","cost_status","intent_category",
                "strategy","embedding_model","filtered_count","authorized_count","evidence","sufficient_evidence",
                "error_status","scores","outcome"}


def redact_text(text):
    for pattern in PATTERNS:
        text = pattern.sub("[REDACTED]", text)
    # Covers configured nonstandard server secrets without decrypting customer keys.
    for name, value in os.environ.items():
        if len(value) >= 12 and name.endswith(("_KEY", "_TOKEN", "_SECRET")):
            text = text.replace(value, "[REDACTED]")
    return text


class TraceSanitizer:
    def clean(self, value, depth=0):
        if depth > 8:
            return "[TRUNCATED]"
        if isinstance(value, str):
            return redact_text(value)[:2048]
        if isinstance(value, dict):
            return {redact_text(str(k))[:200]: self.clean(v, depth + 1) for k, v in list(value.items())[:80]
                    if str(k).lower() not in FORBIDDEN}
        if isinstance(value, (list, tuple)):
            return [self.clean(item, depth + 1) for item in value[:100]]
        if isinstance(value, float) and not math.isfinite(value):
            return None
        if value is None or isinstance(value, (bool, int, float)):
            return value
        return "[OMITTED]"

    def stages(self, stages):
        return [self.clean({key: value for key, value in stage.items() if key in STAGE_FIELDS})
                for stage in stages[:60] if isinstance(stage, dict)]

    def for_reader(self, trace, scopes):
        stages = self.stages(trace["stages"])
        for stage in stages:
            evidence = stage.get("evidence", [])
            stage["evidence"] = [item for item in evidence if item.get("permission") in scopes]
            # Do not leave a score map as a side channel for now-inaccessible IDs.
            if evidence:
                permitted = {item["item_id"] for item in stage["evidence"]}
                stage["scores"] = {key: value for key, value in stage.get("scores", {}).items() if key in permitted}
        return {**trace, "stages": stages, "metrics": self.clean(trace["metrics"])}


trace_sanitizer = TraceSanitizer()
