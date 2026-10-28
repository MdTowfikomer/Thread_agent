# Spec: Thread Agent V2 - Multi-tenant Organizational Memory

## Active demo scope — revised 2026-10-28

The user deferred customer-owned databases (Ticket 03) and self-service Discord
onboarding (Ticket 04). Use managed PostgreSQL/pgvector and the existing authorized
Discord installation and channel bindings. Continue directly from Phase 2 to
evaluations and conversation-scoped traces (Tickets 05/06). Future BYODB/OAuth
designs below are retained as roadmap material, not current requirements.

For this demo, memory and execution traces use the configured managed memory
database with organization and conversation authorization. Customer database
selection, connection pooling and SSRF validation are not prerequisites. Existing
tenant isolation, source ACLs, destination visibility and secret handling remain
mandatory. A second web workspace must not inherit MCET's Discord sources.

## Problem Statement
Organizational decisions, architectural rationales, and critical context are scattered across messaging channels (Discord, Slack, Telegram) and repositories. When core leaders graduate or senior engineers move on, vital institutional context vanishes ("institutional amnesia").

Currently, Thread Agent exists as a demonstration tied to a single hardcoded workspace (`gdg_mcet`) with static configuration files (`organizations.py`, `domains.py`), in-memory membership state (`membership.py`), community-specific intent routing keywords (`gdg`, `devfest`, etc.), and global environment variables for model API keys and database storage. A second organization cannot onboard without code changes, connect its own model credentials (BYOK), select a dedicated customer-owned PostgreSQL database with pgvector, or configure Discord channel ingestion with appropriate privacy boundaries.

## Solution
Evolve Thread Agent into a configurable, multi-tenant organizational memory portfolio demonstration. An organization owner or administrator can sign up, create an isolated workspace, invite teammates with role-based privileges (`owner`, `admin`, `member`), securely provide an encrypted model API key (BYOK), choose either managed storage or a dedicated customer-owned PostgreSQL database with pgvector, connect Discord via OAuth, select ingested channels, and ask questions through the web app or Discord. Thread returns grounded answers citing authorized evidence from the tenant's chosen memory database, governed by strict pre-retrieval scope isolation and observable execution traces.

## User Stories

### 1. Identity, Workspaces & Membership Administration
1. As an organization owner, I want to sign up and log in with persistent credentials, so that my user account is securely established.
2. As an organization owner, I want to create a new workspace with a name and description, so that my team's institutional context is managed under our own distinct organizational boundary.
3. As an organization owner, I want my workspace, memberships, and assistant configurations to persist across backend restarts in a relational database, so that state is durable and authoritative.
4. As an organization member belonging to multiple workspaces, I want to view my workspaces and switch between them in the UI, so that I can interact with the appropriate assistant context without logging out.
5. As an organization administrator, I want to invite teammates by email with an application role (`owner`, `admin`, `member`), so that our team can collaborate.
6. As an invitee, I want to accept an invitation link and join the workspace, so that my membership is established.
7. As an organization owner, I want to change member roles or remove members, so that former teammates immediately lose access to private workspace data.
8. As an organization owner, I want workspace ownership transfer rules enforced (e.g. an owner cannot leave without designating a new owner), so that workspaces are never orphaned.
9. As a user, I want the system to reject unknown or unauthorized organization IDs with an explicit HTTP 404 / 403 error, so that no fallback or default data leak occurs.

### 2. Configurable Organizational Assistant Behavior
10. As an organization administrator, I want a general organizational memory assistant configured by default without any community-specific keywords (`gdg`, `devfest`, `mcet`), so that our assistant feels native to our organization.
11. As an organization administrator, I want to optionally configure specialist roles with custom names, styles, and expertise topics, so that our assistant can route queries to domain specialists if desired.
12. As a user asking a general greeting or capability question, I want the assistant to answer conversationally without querying private organizational memory records.
13. As a user asking an organizational question, I want the query routed to memory retrieval based on general semantic relevance rather than hardcoded community keywords.

### 3. Bring Your Own Key (BYOK) & Credential Isolation
14. As an organization administrator, I want to configure our own model provider API key (Google Gemini initially, with OpenAI optional), so that our organization bears its own model usage costs.
15. As an organization administrator, I want our API key to be stored encrypted at rest on the backend using AES-256-GCM, so that plaintext secrets are never exposed in storage.
16. As an organization administrator, I want the system to test and validate our API key against the provider during saving, so that invalid or expired keys provide immediate feedback.
17. As an organization administrator, I want to view masked status (e.g. `AIza...4X9Q`), rotate, or delete our API key, so that we can maintain credential hygiene.
18. As an organization administrator, I want the embedding model configuration declared and locked separately from the chat/reasoning model, so that changing the answer-generation model does not silently corrupt or require re-embedding the vector store.
19. As an organization administrator, I want queries to fail with an actionable configuration error if our model key is missing or invalid, without falling back to a global server key.
20. As an organization administrator, I want token usage tracked per query, clearly indicating whether token counts are provider-reported or estimated.

### 4. Managed and Customer-Owned Memory Storage
21. As an organization owner, I want to choose between Thread-managed PostgreSQL storage or a dedicated customer-owned PostgreSQL database with pgvector, so that we retain sovereignty over our data.
22. As an organization administrator configuring customer-owned storage, I want the system to validate connection destinations, preventing connections to loopback, private IPv4/IPv6 subnets, or cloud metadata endpoints (`169.254.169.254`) both at hostname resolution and socket connect time.
23. As an organization administrator, I want the system to verify TLS, credentials, and `pgvector` extension availability before saving the storage configuration.
24. As an organization administrator, I want to review required table migrations and initialize the schema safely, so that the customer database is ready.
25. As an organization administrator, I want all memory payloads (source records, chunks, embeddings, conversations, message turns, evidence history) stored in our selected memory database, while the Thread service database retains only operational metadata (users, organizations, encrypted credential references, installation routing).
26. As an organization administrator, I want queries and ingestion to fail immediately with an actionable error if our database is unreachable, with **strict zero-fallback** to managed storage.

### 5. Self-Service Discord Onboarding & Ingestion Lifecycle
27. As an organization administrator, I want to connect our Discord server via an OAuth authorization flow that verifies both Thread admin rights and Discord guild administration rights, binding the guild to our workspace server-side.
28. As an organization administrator, I want to select specific text channels to ingest and designate their classification (`public_community` or `internal_team`), so that non-institutional or private channels are ignored.
29. As an organization administrator, I want bounded historical import with checkpointing and idempotent deduplication, so that sync jobs can pause, resume, and avoid duplicate records.
30. As an organization administrator, I want to view connection status, synchronization progress, and actionable errors in the frontend.
31. As an organization administrator, I want Discord message edits and deletions to update or deactivate the corresponding memory records, so that deleted knowledge is no longer retrievable.
32. As an organization administrator, I want channel permission changes or bot removal detected, disabling retrieval for affected channels until permissions are re-established.
33. As an organization administrator, I want to disconnect Discord and optionally purge all ingested chunks and vectors, so that our data can be deleted on demand.
34. As a community member asking a question in a public Discord channel, I want the bot to cite only public evidence, even if the person asking has internal administrative clearance.
35. As a user, if an outbound Discord reply times out ambiguously, I want the system to surface the timeout rather than blindly resending a duplicate message.

### 6. Versioned Evaluation & Isolation Regression Evidence
36. As an engineer or reviewer, I want to run an evaluation command on a versioned multi-tenant dataset (30+ questions across 2 organizations), so that retrieval quality and answer groundedness are measurable.
37. As an engineer, I want retrieval benchmarks comparing vector-only vs. hybrid retrieval (dense embedding + PostgreSQL full-text search `tsvector` with Reciprocal Rank Fusion), reporting Recall@k, MRR, citation precision, and refusal behavior.
38. As a security reviewer, I want automated regression tests verifying that Tenant A cannot retrieve, cite, or infer Tenant B's records under any query.
39. As a security reviewer, I want test fixtures with prompt-injection attempts in source records, verifying that ingested adversarial text cannot bypass ACLs or trigger unauthorized tools.

### 7. Observable Execution & Trace Access Control
40. As a user, I want to inspect execution traces for my queries showing routing decisions, retrieved evidence scores, model identity, token count, and stage latencies.
41. As an organization member, I want trace access strictly restricted to conversation participants or authorized workspace administrators, so that members cannot inspect private conversations of other members.
42. As a user receiving an "insufficient evidence" response, I want the trace to explain the refusal reason without leaking titles, authors, or text of inaccessible records.

## Implementation Decisions

### 1. Data Models and Boundaries
- **Service Database (Thread Operational DB)**:
  - Stores: `users` (id, email, password_hash, created_at), `organizations` (id, name, slug, description, created_at), `memberships` (user_id, organization_id, role, created_at), `invitations` (id, organization_id, email, role, token, expires_at, status), `model_credentials` (id, organization_id, provider, encrypted_api_key, model_name, embedding_model, status, updated_at), `storage_configurations` (id, organization_id, storage_mode, encrypted_connection_uri, status, schema_version), `platform_installations` (id, organization_id, platform, guild_id, status, permissions_checkpoint), `ingestion_jobs` (id, organization_id, installation_id, channel_id, status, checkpoint_message_id, imported_count, error_message).
  - Explicit rule: **No source text, memory chunks, embeddings, conversation history, or trace payloads are stored in the service database for customer-owned workspaces.**
- **Memory Database (Managed or Customer-Owned PostgreSQL + pgvector)**:
  - Stores: `source_records` (id, organization_id, source_type, external_id, title, author, content, permission, metadata, timestamp, is_active), `memory_chunks` (id, source_record_id, organization_id, content, embedding [768-dim vector], permission, fts_tokens [tsvector], provenance), `conversations` (id, organization_id, user_id, title, created_at), `conversation_turns` (id, conversation_id, role, content, evidence_pack, citations, created_at), `execution_traces` (id, organization_id, conversation_id, turn_id, stages, metrics, created_at).

### 2. Encryption Design: AES-256-GCM
- Use standard authenticated symmetric encryption: **AES-256-GCM** via the Python `cryptography` library.
- Each secret payload stores `nonce (12 bytes) + ciphertext + tag (16 bytes)`, base64-encoded.
- Master encryption key is supplied via `THREAD_MASTER_ENCRYPTION_KEY` (32 bytes base64).
- Stored secrets include model API keys and customer PostgreSQL connection URIs.
- Plaintext secrets are decrypted in memory only at the immediate point of outbound client instantiation and never logged, emitted in traces, or returned over APIs.

### 3. SSRF Protection for Customer PostgreSQL Connection URIs
- Validating connection destinations occurs in two steps:
  1. **DNS Resolution Verification**: Resolve the hostname to all IPv4 and IPv6 addresses. Ensure no resolved IP belongs to loopback (`127.0.0.0/8`, `::1`), private networks (`10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`, `fc00::/7`), link-local / cloud metadata (`169.254.0.0/16`, `fe80::/10`), or carrier-grade NAT (`100.64.0.0/10`).
  2. **Socket Connect Pinning / Hook**: Connect directly to the verified resolved IP address with the TLS SNI and server name set to the original hostname, preventing DNS rebinding attacks.
- Require TLS (`sslmode=require` or `sslmode=verify-full`).

### 4. Dynamic Execution & Storage Routing
- Replace `get_llm()` and `get_workspace()` singletons with a request-scoped `TenantContext` containing:
  - `organization_id`, `user_id`, `role`, `model_config`, `storage_config`.
- Create a `TenantConnectionManager` that pools async PostgreSQL connections (`psycopg_pool` or `asyncpg`) per customer database URI, tagged by `organization_id`.
- If customer DB is unreachable, raise `TenantStorageUnavailableError` immediately. Do not query managed storage.

### 5. Retrieval & Hybrid Search Architecture
- Dense similarity: `pgvector` cosine distance `<=>` against 768-dim embeddings (`gemini-embedding-001`).
- Lexical search: PostgreSQL full-text search using `tsvector` with `websearch_to_tsquery('english', :query)` and `ts_rank_cd`.
- Fusion: Reciprocal Rank Fusion (RRF) combining dense and lexical ranks:
  $$\text{RRF Score} = \frac{1}{60 + \text{rank}_{\text{dense}}} + \frac{1}{60 + \text{rank}_{\text{lexical}}}$$
- **Pre-Retrieval Scope Filtering**:
  - The SQL query structure enforces `WHERE organization_id = :org_id AND permission = ANY(:allowed_scopes) AND is_active = true AND id != ALL(:exclude_chunk_ids)`.
  - In addition, the application layer re-validates the returned candidate chunks before passing them to the evidence checker to ensure no scope leakage occurs regardless of PostgreSQL index query plan optimizations.

### 6. Generic Intent Routing
- Remove all community-specific keywords (`gdg`, `devfest`, `mcet`) from `backend/app/graph/workflow.py`.
- Queries route based on general intent:
  - Explicit utility commands (`!events`, `!faq`, etc.) route to tools if enabled.
  - Conversational greetings and general conceptual queries route to direct conversational generation without memory retrieval.
  - Organizational inquiries route to memory retrieval using semantic embeddings and keyword matching.
  - Optional specialist roles configured in the workspace are selected via semantic match against their configured expertise tags; if none are configured, the default organization assistant handles the response.

### 7. Discord Synchronization Lifecycle
- Webhook events (`MESSAGE_UPDATE`, `MESSAGE_DELETE`) are processed by `DiscordIngestionService`:
  - `MESSAGE_DELETE`: Sets `is_active = false` on the matching `source_records` and associated `memory_chunks`.
  - `MESSAGE_UPDATE`: Updates source content, regenerates chunks, re-indexes tokens, and flags superseded versions.
- If Discord API returns a 5xx timeout during outbound message delivery, log the ambiguous state with the unique turn idempotency token; do not blindly resend without checking message delivery.

### 8. Observable Execution & Trace Authorization
- Every user query generates a structured `execution_trace` recording:
  - Query timestamp, user ID, routing decision, candidate chunks retrieved with similarity & lexical scores, chunks filtered out by ACL, LLM model identifier, token counts (provider-reported or estimated), and per-stage latency (ms).
- **Access Rule**: `GET /api/v2/organizations/{org_id}/traces/{trace_id}` requires that the requesting user is either:
  1. The author of the conversation, OR
  2. An organization `owner` / `admin`.
- Other members receive HTTP 404 (or 403), preventing eavesdropping on colleagues' private conversations.

## Testing Decisions

- **Testing Philosophy**: Tests must verify observable system behavior, security boundaries, and failure handling at public API and execution seams. Tests provide empirical verification within their specified scenario coverage.
- **Seams**:
  1. *FastAPI HTTP API Seam (`/api/v2/...`)*: Verified via `httpx.AsyncClient` / `TestClient`. Covers authentication, tenant switching, role administration, BYOK encryption/validation, and customer DB connection checks.
  2. *LangGraph Graph Execution Seam (`app_graph.invoke`)*: Verified with dynamic tenant contexts, testing multi-agent peer verification, citation generation, and prompt-injection resistance.
  3. *Memory Database Seam*: Verified against real PostgreSQL instances with pgvector, asserting strict isolation across distinct database targets.
  4. *Ingestion & Delivery Seam*: Verified with simulated Discord events, testing idempotency, message deletion sync, and outbound channel visibility enforcement.
- **Prior Art in Repository**:
  - `backend/tests/test_triggering_message_exclusion.py` (citation exclusion).
  - `backend/tests/test_session_and_frontend_security.py` (auth & session cookies).
  - `backend/tests/test_durable_policies_integration.py` (connector policy enforcement).

## Out of Scope
- Commercial billing, subscriptions, credit card payments.
- Enterprise SSO (SAML/SCIM) protocols.
- Live automated migration of populated memory data between managed and customer storage.
- Arbitrary database engines (only PostgreSQL with pgvector is supported).
- Desktop electron / local device packaging.

## Further Notes
- Backwards compatibility: The demo organization `gdg_mcet` is retained as a seeded fixture in the database so existing demonstration tests remain operable.
