import os
from contextlib import asynccontextmanager
from typing import Optional
from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import settings
from app.core.organizations import WORKSPACES, get_workspace
from app.core.auth import AuthenticatedPrincipal, get_current_principal
from app.data.seeds import get_seed_data
from app.memory.store import memory_store
from app.memory.repository import memory_repository
from app.channels.gateway import discord_gateway_bot
from app.api.chat import router as chat_router
from app.api.imports import router as imports_router
from app.api.webhooks import router as webhooks_router

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Enforce production security checks at startup
    settings.validate_production_security()

    # Startup: Ingest initial organizational context via Source Adapters
    records, chunks, receipts = get_seed_data()
    memory_repository.save_records_and_chunks(records, chunks)
    print(f"[Thread Memory Core v0] Initialized with {len(chunks)} chunks from {len(records)} source records.")

    # Optional controlled single background gateway task for local demo mode ONLY (development)
    if settings.is_development and settings.discord_bot_token and os.getenv("THREAD_START_GATEWAY_BOT", "false").lower() in ("true", "1"):
        print("[Discord Gateway] Launching single-worker background connector task (development demo)...")
        discord_gateway_bot.start_background()

    yield
    if discord_gateway_bot._running:
        await discord_gateway_bot.stop()
    print("[Thread Core] Shutting down.")

app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    description="Thread — AI Organizational Context Agent (Authentication Boundary v0).",
    lifespan=lifespan
)

# Configured trusted origins CORS (Wildcard '*' replaced with strict allowed list)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)

# Include routers
app.include_router(chat_router, prefix=settings.API_PREFIX)
app.include_router(imports_router, prefix=settings.API_PREFIX)
app.include_router(webhooks_router, prefix=settings.API_PREFIX)

@app.get("/health")
def health_check():
    return {
        "status": "healthy",
        "service": "Thread Context Reconstruction Engine",
        "version": settings.VERSION,
        "app_env": settings.APP_ENV,
        "demo_auth_enabled": settings.demo_auth_enabled,
        "cors_origins": settings.allowed_origins,
        "providers": {
            "gemini": settings.has_gemini,
            "openai": settings.has_openai,
            "supabase": settings.has_supabase
        }
    }

@app.get(f"{settings.API_PREFIX}/workspace")
def get_current_workspace(organization_id: str = "gdg_mcet"):
    ws = get_workspace(organization_id)
    return {
        "id": ws.id,
        "name": ws.name,
        "description": ws.description,
        "default_role_id": ws.default_role_id,
        "roles": [r.model_dump() for r in ws.roles]
    }

@app.get(f"{settings.API_PREFIX}/memories")
def list_memories(
    organization_id: Optional[str] = None,
    principal: AuthenticatedPrincipal = Depends(get_current_principal)
):
    """
    ACL-filtered institutional memory endpoint.
    Derives permissions exclusively from the verified AuthenticatedPrincipal bearer token.
    Always retrieves principal.organization_id, rejecting mismatched requested organization with 403.
    """
    if organization_id is not None and organization_id != principal.organization_id:
        raise HTTPException(
            status_code=403,
            detail=f"Forbidden: Cross-organization memory access is denied. Requested '{organization_id}', principal is '{principal.organization_id}'."
        )

    effective_org = principal.organization_id
    access_context = principal.access_context

    # Production-safe: Query from persistent repository (Supabase if configured, cache fallback)
    all_chunks = memory_repository.get_chunks_for_organization(effective_org)
    # Strictly filter by allowed_scopes
    authorized_chunks = [
        c for c in all_chunks if c.permission in access_context.allowed_scopes
    ]

    items = [
        {
            "id": c.id,
            "source": c.source_type.value,
            "source_uri": c.source_uri,
            "author": c.author,
            "author_role": c.author_role,
            "title": c.title,
            "content": c.content,
            "permission": c.permission.value,
            "tags": c.tags,
            "entities": c.entities,
            "provenance": c.provenance,
            "timestamp": c.timestamp.isoformat()
        }
        for c in authorized_chunks
    ]
    return {
        "organization_id": effective_org,
        "user_id": principal.user_id,
        "allowed_scopes": [s.value for s in access_context.allowed_scopes],
        "count": len(items),
        "memories": items
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
