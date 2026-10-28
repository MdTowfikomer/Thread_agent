"""Organization-scoped credential metadata with atomic rotation and deletion."""
from datetime import datetime, timezone
import uuid
from fastapi import HTTPException
from app.tenancy.repository import tenant_repository

EMBEDDING_MODEL = "models/gemini-embedding-001"
EMBEDDING_DIMENSIONS = 768
SUPPORTED_MODELS = ("gemini-3.5-flash-lite", "gemini-3.6-flash")
DEFAULT_MODEL = SUPPORTED_MODELS[0]


def credential_aad(org_id: str) -> str:
    return f"thread:model-key:v1:google:{org_id}"


def credential_record(org_id):
    with tenant_repository.transaction() as cur:
        return tenant_repository.one(cur, "SELECT * FROM model_credentials WHERE organization_id=%s", (org_id,))


def public_metadata(org_id, user_id):
    with tenant_repository.transaction() as cur:
        tenant_repository._admin(cur, org_id, user_id)
        row = tenant_repository.one(cur, "SELECT provider,key_suffix,model_name,embedding_model,embedding_dimensions,status,last_validated_at,updated_at FROM model_credentials WHERE organization_id=%s", (org_id,))
    return {
        "provider": "google",
        "masked_key": f"****…{row['key_suffix']}" if row and row["key_suffix"] else None,
        "model_name": row["model_name"] if row else DEFAULT_MODEL,
        "embedding_model": row["embedding_model"] if row else EMBEDDING_MODEL,
        "embedding_dimensions": row["embedding_dimensions"] if row else EMBEDDING_DIMENSIONS,
        "status": row["status"] if row else "unconfigured",
        "last_validated_at": row["last_validated_at"] if row else None,
        "updated_at": row["updated_at"] if row else None,
        "supported_models": list(SUPPORTED_MODELS),
    }


def save_credential(org_id, user_id, encrypted_key, key_suffix, model_name, expected_revision):
    now = datetime.now(timezone.utc).isoformat()
    with tenant_repository.transaction() as cur:
        tenant_repository.execute(cur, "SELECT id FROM organizations WHERE id=%s FOR UPDATE", (org_id,))
        tenant_repository._admin(cur, org_id, user_id)
        row = tenant_repository.one(cur, "SELECT revision FROM model_credentials WHERE organization_id=%s", (org_id,))
        revision = row["revision"] if row else 0
        if revision != expected_revision:
            raise HTTPException(409, "Model configuration changed during validation. Reload settings and try again.")
        tenant_repository.execute(cur, """
            INSERT INTO model_credentials(id,organization_id,provider,encrypted_api_key,key_suffix,model_name,embedding_model,embedding_dimensions,status,revision,last_validated_at,updated_at)
            VALUES (%s,%s,'google',%s,%s,%s,%s,%s,'active',%s,%s,%s)
            ON CONFLICT (organization_id) DO UPDATE SET encrypted_api_key=EXCLUDED.encrypted_api_key,
                key_suffix=EXCLUDED.key_suffix,model_name=EXCLUDED.model_name,status='active',
                revision=EXCLUDED.revision,last_validated_at=EXCLUDED.last_validated_at,updated_at=EXCLUDED.updated_at
        """, (str(uuid.uuid4()), org_id, encrypted_key, key_suffix, model_name, EMBEDDING_MODEL,
              EMBEDDING_DIMENSIONS, revision + 1, now, now))


def revoke_credential(org_id, user_id):
    now = datetime.now(timezone.utc).isoformat()
    with tenant_repository.transaction() as cur:
        tenant_repository.execute(cur, "SELECT id FROM organizations WHERE id=%s FOR UPDATE", (org_id,))
        tenant_repository._admin(cur, org_id, user_id)
        # Retain a tombstone even before first save so deletion cancels in-flight validation.
        tenant_repository.execute(cur, """
            INSERT INTO model_credentials(id,organization_id,provider,model_name,status,revision,updated_at)
            VALUES (%s,%s,'google',%s,'revoked',1,%s)
            ON CONFLICT (organization_id) DO UPDATE SET encrypted_api_key=NULL,key_suffix=NULL,
                status='revoked',revision=model_credentials.revision+1,updated_at=EXCLUDED.updated_at
        """, (str(uuid.uuid4()), org_id, DEFAULT_MODEL, now))


def mark_invalid(org_id, revision):
    with tenant_repository.transaction() as cur:
        tenant_repository.execute(cur, "UPDATE model_credentials SET status='invalid',revision=revision+1 WHERE organization_id=%s AND revision=%s AND status='active'", (org_id, revision))
