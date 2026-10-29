from contextlib import contextmanager
from datetime import datetime, timezone
import json
import os
import uuid

from fastapi import HTTPException
from app.tenancy.repository import TenantRepository
from app.tracing.sanitize import trace_sanitizer


class TraceRepository(TenantRepository):
    @contextmanager
    def transaction(self):
        if self.connection_factory:
            with super().transaction() as cur:
                yield cur
            return
        # Memory payloads use managed memory storage, never the optional separate
        # service metadata connection merely because it is available.
        url = os.getenv("SUPABASE_DB_URL") or os.getenv("DATABASE_URL")
        if not url:
            raise HTTPException(503, "Managed trace database is not configured.")
        import psycopg2
        connection = None
        try:
            from app.data.postgres import connect
            connection = connect(url)
            yield connection.cursor()
            connection.commit()
        except HTTPException:
            if connection:
                connection.rollback()
            raise
        except Exception:
            if connection:
                connection.rollback()
            raise HTTPException(503, "Managed trace storage is unavailable. Check migrations and the database connection.") from None
        finally:
            if connection:
                connection.close()

    def begin(self, organization_id, user_id, session_key, platform):
        conversation_id, trace_id, turn_id = (str(uuid.uuid4()) for _ in range(3))
        now = datetime.now(timezone.utc).isoformat()
        with self.transaction() as cur:
            self.execute(cur, "INSERT INTO conversations(id,organization_id,user_id,platform,session_key,created_at) VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT (organization_id,user_id,platform,session_key) DO NOTHING",
                         (conversation_id, organization_id, user_id, platform, session_key, now))
            conversation = self.one(cur, "SELECT id FROM conversations WHERE organization_id=%s AND user_id=%s AND platform=%s AND session_key=%s", (organization_id, user_id, platform, session_key))
            conversation_id = conversation["id"]
            self.execute(cur, "INSERT INTO execution_traces(id,organization_id,conversation_id,turn_id,user_id,outcome,stages,metrics,created_at) VALUES (%s,%s,%s,%s,%s,'running','[]','{}',%s)",
                         (trace_id, organization_id, conversation_id, turn_id, user_id, now))
        return {"trace_id": trace_id, "conversation_id": conversation_id, "turn_id": turn_id}

    def finish(self, trace_id, org_id, outcome, stages, total_latency_ms):
        stages = trace_sanitizer.stages(stages)
        usage = [stage for stage in stages if stage.get("step") == "model_usage"]
        metrics = {"total_latency_ms": round(total_latency_ms, 2),
                   "input_tokens": sum(stage.get("input_tokens", 0) for stage in usage),
                   "output_tokens": sum(stage.get("output_tokens", 0) for stage in usage),
                   "token_reporting_type": "estimated" if any(stage.get("is_estimated") for stage in usage) else "provider_reported" if usage else "not_used",
                   "estimated_cost_usd": None}
        with self.transaction() as cur:
            self.execute(cur, "UPDATE execution_traces SET outcome=%s,stages=%s,metrics=%s WHERE id=%s AND organization_id=%s", (outcome, json.dumps(stages), json.dumps(metrics), trace_id, org_id))

    def _authorize(self, cur, org_id, conversation_id, user_id, role):
        conversation = self.one(cur, "SELECT * FROM conversations WHERE id=%s AND organization_id=%s", (conversation_id, org_id))
        if not conversation or (conversation["user_id"] != user_id and role not in ("owner", "admin")):
            raise HTTPException(404, "Conversation trace not found.")

    def read(self, org_id, trace_id, user_id, role):
        with self.transaction() as cur:
            row = self.one(cur, "SELECT * FROM execution_traces WHERE id=%s AND organization_id=%s", (trace_id, org_id))
            if not row:
                raise HTTPException(404, "Conversation trace not found.")
            self._authorize(cur, org_id, row["conversation_id"], user_id, role)
        for field in ("stages", "metrics"):
            if isinstance(row[field], str):
                row[field] = json.loads(row[field])
        return row

    def list_for_conversation(self, org_id, conversation_id, user_id, role):
        with self.transaction() as cur:
            self._authorize(cur, org_id, conversation_id, user_id, role)
            return self.many(cur, "SELECT id,turn_id,outcome,created_at FROM execution_traces WHERE organization_id=%s AND conversation_id=%s ORDER BY created_at,id LIMIT 100", (org_id, conversation_id))


trace_repository = TraceRepository()
