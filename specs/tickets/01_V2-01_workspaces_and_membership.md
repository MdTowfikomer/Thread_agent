# Ticket: [V2-01] Persistent Identity, Workspaces, and Membership Administration

## Pillar
V2-01: Workspaces and membership

## Summary
Build the multi-tenant relational persistence foundation for users, organizations, memberships, invitations, and assistant configurations. Replace static in-memory registries (`organizations.py`, `domains.py`, `membership.py`) with persistent database models. Provide full lifecycle endpoints and frontend screens for signup/login, workspace creation/switching, member invitations, role changes, member removal, and ownership transfer. Unknown organization IDs must fail explicitly and never fall back to `gdg_mcet`.

## Detailed Work Breakdown

### Task 1.1: Database Schema & Migration (Service Database)
- Create migration script (`backend/app/data/migrations/020_v2_identity_and_tenants.sql`):
  - `users`: `id` (UUID), `email` (unique), `password_hash`, `name`, `created_at`.
  - `organizations`: `id` (text / slug, unique), `name`, `description`, `created_at`.
  - `memberships`: `id` (UUID), `user_id` (FK), `organization_id` (FK), `role` (`owner` | `admin` | `member`), `created_at`, unique `(user_id, organization_id)`.
  - `invitations`: `id` (UUID), `organization_id` (FK), `email`, `role`, `token` (unique), `expires_at`, `status` (`pending` | `accepted` | `revoked`).
  - `assistant_configurations`: `organization_id` (FK, unique), `default_agent_name`, `system_prompt`, `configured_roles` (JSONB).
- Seed `gdg_mcet` workspace and its legacy members as an explicit database fixture for demo backwards compatibility.

### Task 1.2: Identity & Authentication Endpoints
- Implement `backend/app/api/v2/auth.py`:
  - `POST /api/v2/auth/signup`: Create user account with hashed password (bcrypt / argon2).
  - `POST /api/v2/auth/login`: Authenticate and issue secure HTTP-only session cookie / JWT.
  - `GET /api/v2/auth/me`: Return authenticated user info and accessible organizations.
  - `POST /api/v2/auth/logout`: Invalidate session.

### Task 1.3: Workspace Lifecycle & Membership Administration
- Implement `backend/app/api/v2/organizations.py`:
  - `POST /api/v2/organizations`: Create a workspace; creator automatically becomes `owner`.
  - `GET /api/v2/organizations`: List current user's organizations.
  - `POST /api/v2/organizations/{org_id}/switch`: Validate membership and set active workspace context.
  - `POST /api/v2/organizations/{org_id}/invitations`: Create and return invitation link (restricted to `owner` and `admin`).
  - `POST /api/v2/invitations/{token}/accept`: Authenticated user accepts invitation, creating a `membership` record.
  - `PATCH /api/v2/organizations/{org_id}/members/{user_id}`: Update role (`owner`, `admin`, `member`). Only owner can transfer ownership. Owner cannot downgrade without designating a new owner.
  - `DELETE /api/v2/organizations/{org_id}/members/{user_id}`: Remove member. Revoked members lose access immediately on subsequent requests.
- Remove fallback logic in `backend/app/core/organizations.py` and `membership.py`. Unknown organization IDs raise `OrganizationNotFoundError` returning HTTP 404.

### Task 1.4: Configurable Assistant Behavior
- Remove hardcoded community keywords (`gdg`, `mcet`, `devfest`) from `backend/app/graph/workflow.py`.
- Implement generic routing:
  - Default organizational assistant handles general organization memory retrieval.
  - If custom `configured_roles` exist in `assistant_configurations`, match role expertise tags semantically; otherwise, use the default assistant.

### Task 1.5: Frontend Workspace & Member Management
- Implement frontend UI components:
  - `WorkspaceSwitcher`: Dropdown in navigation bar listing user's workspaces with a "+ Create Workspace" modal.
  - `WorkspaceSettingsPage`: Manage organization details, invite teammates by email, inspect members list, adjust roles, or remove members.

## Acceptance Criteria
1. Given a signed-in user, creating a new workspace persists in PostgreSQL and survives server restarts.
2. An organization owner can invite a teammate, who can accept the invitation link and immediately see the workspace.
3. An organization owner can remove a member or change their role; the removed member immediately receives HTTP 403 / 404 on subsequent requests to that workspace.
4. An owner cannot leave or delete their role without transferring ownership to another member.
5. Querying with an invalid or unknown organization ID returns HTTP 404 and never defaults to `gdg_mcet`.
6. Queries to a new workspace route to a generic organizational assistant without referencing GDG MCET roles or keywords.

## Verification Commands
```bash
# Run identity & membership unit and integration tests
backend\.venv\Scripts\python.exe -m pytest backend/tests/test_v2_identity_and_tenants.py
```

## Implementation status

Implemented for verification. See [Phase 1 implementation notes](../PHASE_1_IMPLEMENTATION.md) for migration integration, identity/storage decisions, test evidence, and the pending live PostgreSQL acceptance gate. The runtime user table is `thread_users`; new user IDs are UUIDs stored as text to preserve legacy fixture IDs.
