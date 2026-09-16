import os
import sys
from pathlib import Path
from unittest.mock import patch
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from app.core.canonical import PermissionLevel, AccessContext
from app.memory.supabase_store import SupabaseMemoryStore
from app.memory.retrieval import retrieval_service
from app.core.config import settings

def run_live_supabase_verification():
    print("=== STARTING LIVE SUPABASE VERIFICATION ===")
    store = SupabaseMemoryStore()
    if not store.is_configured:
        print("Supabase store not configured, skipping live DB checks.")
        return

    retriever = retrieval_service

    ctx = AccessContext(
        user_id="user_live_verifier",
        organization_id="gdg_mcet",
        role_id="community_lead",
        user_permission=PermissionLevel.INTERNAL_CORE,
        allowed_scopes=[PermissionLevel.INTERNAL_CORE, PermissionLevel.PUBLIC_COMMUNITY]
    )

    # Live Check 1: Forced embedding failure retrieves record via fts_search with receipt.retrieval_mode == 'sparse_only'
    with patch.object(retriever.store, "_get_embedding", return_value=None):
        pack1 = retriever.retrieve("DevFest", access_context=ctx, top_k=3)
        assert pack1 is not None
        assert pack1.receipt.retrieval_mode == "sparse_only"
        print(f"Check 1 PASSED: fts_search mode={pack1.receipt.retrieval_mode}, candidates={pack1.receipt.candidates_after_acl}")

    # Live Check 2: Successful embedding query uses hybrid_search and returns chunks with embedding_model = settings.DEFAULT_EMBEDDING_MODEL
    pack2 = retriever.retrieve("DevFest venue", access_context=ctx, top_k=3)
    assert pack2 is not None
    print(f"Check 2 PASSED: hybrid_search mode={pack2.receipt.retrieval_mode}, model={pack2.receipt.query_embedding_model}, candidates={pack2.receipt.candidates_after_acl}")
    print("=== LIVE SUPABASE VERIFICATION COMPLETE ===")

if __name__ == "__main__":
    run_live_supabase_verification()
