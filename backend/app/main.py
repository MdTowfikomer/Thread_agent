import os
from contextlib import asynccontextmanager
from typing import Optional
from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import settings
from app.core.organizations import WORKSPACES, get_workspace
from app.core.auth import AuthenticatedPrincipal, get_current_principal
from app.core.canonical import PermissionLevel
from app.data.seeds import get_seed_data
from app.memory.store import memory_store
from app.memory.repository import memory_repository
from app.channels.gateway import discord_gateway_bot, try_acquire_gateway_advisory_lock, release_gateway_advisory_lock
from app.channels.installation import guild_installation_store, telegram_binding_store, slack_binding_store, github_binding_store
from app.identity.service import identity_service
from app.api.chat import router as chat_router
from app.api.imports import router as imports_router
from app.api.webhooks import router as webhooks_router
from app.api.identity import router as identity_router
from app.api.delivery import router as delivery_router

@asynccontextmanager
async def lifespan(app: FastAPI):
    # 1. Enforce production security checks at startup
    settings.validate_production_security()

    # 2. Startup: Ingest test fixtures ONLY in local development when explicitly enabled.
    # NEVER inject synthetic/mock data in production or render demo mode.
    if settings.is_development and os.getenv("THREAD_SEED_DEV_DATA", "false").lower() in ("true", "1"):
        records, chunks, receipts = get_seed_data()
        memory_repository.save_records_and_chunks(records, chunks)
        print(f"[Thread Memory Core v0] Initialized dev fixtures with {len(chunks)} chunks from {len(records)} source records.")

    # 3. Discord Gateway Lifecycle:
    # Mode A: render_free_demo - single Uvicorn worker instance under PostgreSQL session advisory lock.
    # Mode B: local development demo - background task if THREAD_START_GATEWAY_BOT=true.
    # Mode C: standard production - dedicated worker process (run_gateway.py) enforced by validate_production_security.
    gateway_lock_conn = None
    if settings.is_render_free_demo and settings.discord_bot_token and os.getenv("THREAD_START_GATEWAY_BOT", "false").lower() in ("true", "1"):
        web_concurrency = int(os.getenv("WEB_CONCURRENCY", "1"))
        if web_concurrency > 1:
            raise RuntimeError(
                f"Configuration Error: render_free_demo requires exactly 1 worker (WEB_CONCURRENCY=1), but found {web_concurrency}."
            )
        # In render_free_demo, a database or lock failure must fail startup fast.
        # Standby mode is ONLY entered if PostgreSQL authoritatively confirms an active peer holds the lock.
        gateway_lock_conn = try_acquire_gateway_advisory_lock(fail_on_db_error=True)
        if gateway_lock_conn:
            print("[Discord Gateway] Acquired advisory lock. Launching background Gateway worker (render_free_demo leader)...")
            discord_gateway_bot.start_background()
        else:
            print("[Discord Gateway] Verified active peer holds advisory lock. Running API in standby for Discord Gateway.")
    elif settings.is_development and settings.discord_bot_token and os.getenv("THREAD_START_GATEWAY_BOT", "false").lower() in ("true", "1"):
        print("[Discord Gateway] Launching single-worker background connector task (development demo)...")
        discord_gateway_bot.start_background()

    yield

    if discord_gateway_bot._running:
        await discord_gateway_bot.stop()
    if gateway_lock_conn:
        release_gateway_advisory_lock(gateway_lock_conn)
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
app.include_router(identity_router, prefix=settings.API_PREFIX)
app.include_router(delivery_router, prefix=settings.API_PREFIX)


@app.get("/health")
def health_check():
    """Minimal liveness health probe. Zero information disclosure in production."""
    return {"status": "healthy"}

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

@app.get(f"{settings.API_PREFIX}/connections")
def list_connections(
    organization_id: Optional[str] = None,
    principal: AuthenticatedPrincipal = Depends(get_current_principal)
):
    """Expose server-owned connector bindings for the demo status screen."""
    if organization_id is not None and organization_id != principal.organization_id:
        raise HTTPException(status_code=403, detail="Cross-organization access is denied.")
    organization_id = principal.organization_id
    return {
        "organization_id": organization_id,
        "connections": {
            "github": [
                {"id": binding.repository_id, "label": binding.repository_name, "status": "bound"}
                for binding in github_binding_store._bindings_by_id.values()
                if binding.organization_id == organization_id and binding.is_active
            ],
            "discord": [
                {"id": binding.guild_id, "label": binding.guild_name or binding.guild_id, "status": "bound"}
                for binding in guild_installation_store._installations.values()
                if binding.organization_id == organization_id and binding.is_active
            ],
            "telegram": [
                {"id": binding.chat_id, "label": binding.chat_title or binding.chat_id, "status": "bound"}
                for binding in telegram_binding_store._bindings_by_id.values()
                if binding.organization_id == organization_id and binding.is_active
            ],
            "slack": [
                {
                    "id": binding.team_id,
                    "label": binding.team_domain or binding.team_id,
                    "channels": binding.metadata.get("channel_ids", []),
                    "status": "bound",
                }
                for binding in slack_binding_store._bindings_by_id.values()
                if binding.organization_id == organization_id and binding.is_active
            ],
        },
    }

@app.get(f"{settings.API_PREFIX}/review")
def list_review_items(
    organization_id: Optional[str] = None,
    principal: AuthenticatedPrincipal = Depends(get_current_principal)
):
    """Return quarantine and unresolved identity evidence for the review panel."""
    if organization_id is not None and organization_id != principal.organization_id:
        raise HTTPException(status_code=403, detail="Cross-organization access is denied.")
    if PermissionLevel.INTERNAL_CORE not in principal.access_context.allowed_scopes:
        raise HTTPException(status_code=403, detail="Organizer access is required for review.")
    organization_id = principal.organization_id
    chunks = memory_repository.get_chunks_for_organization(organization_id)
    quarantine = [
        {
            "id": chunk.id,
            "source": chunk.source_type.value,
            "title": chunk.title,
            "author": chunk.author,
            "content": chunk.content,
            "provenance": chunk.provenance,
        }
        for chunk in chunks
        if chunk.permission == PermissionLevel.PENDING_REVIEW
    ]
    links = [
        link.model_dump()
        for link in identity_service._account_links.values()
        if link.organization_id == organization_id
        if not link.is_verified and link.is_active
    ]
    return {"organization_id": organization_id, "quarantine": quarantine, "identity_links": links}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
