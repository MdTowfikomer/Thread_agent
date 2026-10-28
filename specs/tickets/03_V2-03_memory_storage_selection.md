# Ticket: [V2-03] Memory Storage Selection (Managed vs. Customer PostgreSQL + pgvector)

## Pillar

Status: Deferred to future scope by the user on 2026-10-28. Retain this design for
later; customer-owned storage is not required for the current demo or Tickets 05/06.
V2-03: Memory storage selection

## Summary
Provide workspaces with the choice between Thread-managed PostgreSQL or a dedicated customer-owned PostgreSQL database with `pgvector`. Enforce strict pre-flight connection validation (DNS resolution checks, private IP / cloud metadata blocking for SSRF protection, TLS verification, extension presence), safe schema migrations, and full memory payload storage in the customer database (chunks, records, conversations, turns, traces), with a **strict zero-fallback policy** on customer database failure.

## Detailed Work Breakdown

### Task 3.1: Service Database Schema & Storage Ownership Model
- Create migration script (`backend/app/migrations/003_v2_storage_configurations.sql`):
  - `storage_configurations`: `id` (UUID), `organization_id` (FK, unique), `storage_mode` (`managed` | `customer_owned`), `encrypted_connection_uri` (text, AES-256-GCM), `schema_version` (integer), `status` (`ready` | `error` | `uninitialized`), `last_verified_at` (timestamptz).
- Formalize Storage Ownership Boundary:
  - **Thread Service DB**: `users`, `organizations`, `memberships`, `invitations`, `model_credentials`, `storage_configurations`, `platform_installations`, `ingestion_jobs`.
  - **Selected Memory DB**: `source_records`, `memory_chunks` (with pgvector embeddings), `conversations`, `conversation_turns`, `execution_traces`.

### Task 3.2: SSRF & Destination Connection Validator
- Implement `backend/app/core/network_security.py`:
  - `validate_database_uri(uri: str) -> None`:
    1. Parse scheme (must be `postgresql://` or `postgres://`) and port.
    2. Require TLS parameter (`sslmode=require` or `sslmode=verify-full`).
    3. Resolve hostname to all IP addresses (IPv4 and IPv6).
    4. Assert no resolved IP is loopback (`127.0.0.0/8`, `::1`), private RFC1918 (`10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`, `fc00::/7`), link-local / cloud metadata (`169.254.0.0/16`, `fe80::/10`), or carrier-grade NAT (`100.64.0.0/10`).
    5. Pin connection to the validated IP with SNI set to hostname to prevent DNS rebinding.

### Task 3.3: Pre-Flight Capability Check & Migration Runner
- Build `backend/app/memory/customer_db_manager.py`:
  - `test_connection(uri: str)`: Connects, verifies `SELECT 1;`.
  - `verify_extensions(uri: str)`: Confirms `vector` extension is available (`SELECT * FROM pg_extension WHERE extname = 'vector';`).
  - `initialize_schema(uri: str)`: Applies Thread's DDL to the customer database (`source_records`, `memory_chunks` with 768-dim vector column, `conversations`, `conversation_turns`, `execution_traces`, and hybrid search RPC function).

### Task 3.4: Dynamic Connection Routing & Zero-Fallback Policy
- Implement `TenantConnectionManager`:
  - Maintains an LRU pool of connection pools (`psycopg_pool.AsyncConnectionPool`) keyed by `organization_id`.
  - When `TenantContext.storage_mode == "customer_owned"`, queries run exclusively against the customer connection pool.
  - When `TenantContext.storage_mode == "managed"`, queries run against Thread's managed database with `WHERE organization_id = :org_id`.
  - **Zero-Fallback Rule**: If the customer database connection fails, raises `TenantStorageUnavailableError` immediately. It is strictly prohibited to fall back to managed storage.

### Task 3.5: Frontend Storage Selection & Migration Screen
- Build `StorageSettingsCard` in `WorkspaceSettingsPage`:
  - Radio toggle: "Thread Managed Storage" vs. "Dedicated Customer PostgreSQL Database".
  - For customer-owned: URI input field, "Validate Connection" button, schema status check, and "Initialize / Upgrade Schema" button with visible table diff summary.

## Acceptance Criteria
1. Connecting a customer database with private IPs (`127.0.0.1`, `10.0.0.1`, `169.254.169.254`, `::1`) is rejected with an explicit security validation error.
2. An organization admin can connect a valid external PostgreSQL database with pgvector, run schema initialization, and see a "Ready" status.
3. Ingesting records for this organization stores all `source_records`, `memory_chunks`, vectors, conversations, and traces in the customer database; zero memory payloads are written to the service database.
4. If the customer database is stopped or disconnected, asking a question returns an actionable error stating the customer database is unreachable; no query is sent to managed storage.
5. Incompatible vector dimensions or missing `pgvector` extension are caught during pre-flight checks before saving.

## Verification Commands
```bash
# Run SSRF, storage selection, and customer database isolation tests
backend\.venv\Scripts\python.exe -m pytest backend/tests/test_v2_storage_selection.py
```
