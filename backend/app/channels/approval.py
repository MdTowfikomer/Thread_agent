import json
import os
import uuid
from pathlib import Path
from typing import Dict, List, Optional
from datetime import datetime, timezone
from app.core.canonical import (
    ImportApprovalRecord,
    PermissionLevel,
    MemoryChunk,
    SourceRecord
)
from app.memory.store import memory_store, MemoryStore
from app.memory.repository import memory_repository

class ApprovalStore:
    """
    Authoritative server-side registry for organizer approvals of imported records.
    Only active organizers can approve imports. Approval promotes quarantined PENDING_REVIEW
    chunks into INTERNAL_CORE memory and records an audit trail.

    LOCAL DEMO ONLY:
    This store maintains an in-memory index with a best-effort local append file ('approvals_audit.jsonl').
    PRODUCTION BLOCKER: This JSONL fallback is not distributed, atomic, or immutable across multi-worker
    deployments. Supabase/PostgreSQL with transactional consistency must replace it before production deployment.
    """
    def __init__(self, audit_file_path: Optional[Path] = None):
        self._approvals: Dict[str, ImportApprovalRecord] = {}
        self._hash_to_approvals: Dict[str, List[str]] = {}
        self._audit_file_path = audit_file_path or (
            Path(__file__).resolve().parent.parent / "data" / "approvals_audit.jsonl"
        )
        self._load_audit_log()

    def _load_audit_log(self):
        """Restore previous approvals from append audit log if present."""
        if not self._audit_file_path or not self._audit_file_path.exists():
            return
        with open(self._audit_file_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                data = json.loads(line)
                rec = ImportApprovalRecord(**data)
                self._approvals[rec.id] = rec
                self._hash_to_approvals.setdefault(rec.import_hash, []).append(rec.id)

    def _persist_audit_record(self, record: ImportApprovalRecord):
        """Append approval to local demo audit file with flush and sync."""
        if not self._audit_file_path:
            return
        self._audit_file_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._audit_file_path, "a", encoding="utf-8") as f:
            f.write(record.model_dump_json() + "\n")
            f.flush()
            os.fsync(f.fileno())

    def approve_import(
        self,
        organization_id: str,
        import_hash: str,
        approved_by_user_id: str,
        store: Optional[MemoryStore] = None
    ) -> ImportApprovalRecord:
        approval_id = str(uuid.uuid4())

        # 1. Multi-Worker Durable Promotion:
        # Executes database promotion in Supabase when configured, and updates local cache
        promoted_chunk_ids = memory_repository.promote_import(
            organization_id=organization_id,
            import_hash=import_hash,
            approved_by_user_id=approved_by_user_id,
            approval_id=approval_id
        )

        # 2. Persist immutable approval record
        approval = ImportApprovalRecord(
            id=approval_id,
            organization_id=organization_id,
            import_hash=import_hash,
            approved_by_user_id=approved_by_user_id,
            promoted_chunk_ids=promoted_chunk_ids
        )
        self._approvals[approval.id] = approval
        self._hash_to_approvals.setdefault(import_hash, []).append(approval.id)
        self._persist_audit_record(approval)
        return approval

    def get_approval(self, approval_id: str) -> Optional[ImportApprovalRecord]:
        return self._approvals.get(approval_id)

    def get_approvals_for_hash(self, import_hash: str) -> List[ImportApprovalRecord]:
        ids = self._hash_to_approvals.get(import_hash, [])
        return [self._approvals[aid] for aid in ids if aid in self._approvals]

    def clear(self):
        self._approvals.clear()
        self._hash_to_approvals.clear()
        if self._audit_file_path and self._audit_file_path.exists():
            try:
                self._audit_file_path.unlink()
            except Exception:
                pass

approval_store = ApprovalStore()
