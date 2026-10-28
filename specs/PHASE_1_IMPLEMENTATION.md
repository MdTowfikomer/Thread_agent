# V2 Phase 1: implementation and verification

## Delivered behavior

- Email/password signup and login using Argon2id password hashes.
- Opaque, expiring, server-revocable sessions in HTTP-only cookies. Only token hashes are persisted.
- Persistent organizations, memberships, invitations, and assistant configuration.
- Workspace creation, listing and switching; membership is checked on each protected request.
- Email-bound, seven-day, single-use invitation links; only hashes are persisted.
- Member removal and owner-controlled administrator promotion/demotion.
- Atomic ownership transfer: the former owner becomes admin, with exactly one owner retained.
- Default generic assistant and configurable specialists. Routing defaults to evidence retrieval; known greetings and explicit educational questions bypass memory.
- Lexical expertise matches take priority for specialists; optional embedding similarity uses the existing embedding path when available. Organization-scoped model credentials arrive in Phase 2.
- Existing chat, workspace and session endpoints accept V2 cookies and revalidate current membership. Legacy signed tokens also require current membership when persistent service storage is configured.
- Account, invitation, workspace creation/switching, member management and assistant settings screens in the existing React/Tailwind style.

## Repository decisions

The existing runner discovers migrations under `backend/app/data/migrations`.
The new migration is `020_v2_identity_and_tenants.sql`, registered in the existing
checksum manifest. A second migration directory was not introduced.

The user table is named `thread_users` to avoid collision with provider-owned
identity tables. IDs are stored as text: new accounts use UUID values while legacy
fixture identities retain their existing IDs for connector compatibility.

The migration explicitly provisions the MCET workspace and legacy people. These
fixture accounts have no password and cannot log in through the V2 password flow.
It does not create a default password or silently promote newly registered users
into MCET. Owner transfer or identity provisioning for an existing live operator
requires an explicit administrative migration, not matching by name or email.

In production, workspace and membership reads use PostgreSQL without an in-memory
fallback. Static MCET personas are retained solely for explicitly enabled offline
legacy tests (`THREAD_ALLOW_OFFLINE_IDENTITY=1`). V2 writes always require a database.

V2 administration uses application roles. The initial existing two-scope compatibility
mapping gives owners/admins internal scope and members public scope; specialist agent
roles never grant access. Richer source-policy configuration is part of Discord onboarding.

## Setup

1. Install the updated `backend/requirements.txt` in the existing virtual environment.
2. Configure the backend's PostgreSQL service connection. `THREAD_SERVICE_DB_URL`
   overrides `SUPABASE_DB_URL` / `DATABASE_URL` for V2 service metadata. Use a backend
   role permitted by the migration's RLS policies; browser Supabase roles are denied.
3. Review and apply the existing migration sequence to the intended database. From
   `backend`, use `python -m app.data.migrator --status` and
   `python -m app.data.migrator --up`. For a separate service database, pass its
   configured URL through the runner's `--db-url` argument in your own environment.
   Do not commit or paste database credentials into reports.
4. Start FastAPI and Vite using the documented project commands. Open `/auth`, create
   an account, and create a workspace. Account creation does not grant MCET access.
5. In Settings, create an invitation link and share it manually with a test teammate.
   Automatic invitation email delivery is outside this phase.

Hosted production requires HTTPS for secure cookies. Cookie mutations validate
browser Origin / Fetch Metadata against the service's configured origins.

## Verification

From the repository root:

```powershell
backend\.venv\Scripts\python.exe -m pytest backend/tests/test_v2_identity_and_tenants.py -q
```

The offline suite uses an explicitly injected SQLite connection factory and the
portable part of the migration. SQLite is not a supported runtime deployment mode.
It checks persistence across repository/client recreation, hashed credentials and
tokens, session expiry/logout replay, invitation email/expiry/single-use rules,
role escalation rejection, immediate membership revocation, concurrent ownership
transfers, workspace/chat isolation, configuration, and failure behavior.

For real PostgreSQL verification, set `THREAD_TEST_SERVICE_DB_URL` locally to a
disposable database accessed by a suitable backend test role. The same tests then
also run the complete migration and transactions in a generated test schema. The
fixture drops only its generated schema afterward. Do not point this at production.

If this Windows installation's configured `.pytest_tmp` directory is inaccessible,
create a writable temporary parent and pass a fresh `--basetemp` directory to pytest.

Frontend:

```powershell
cd frontend
npm run build
```

Verification on 2026-10-27:

- 53 tests passed across the V2 identity, session/frontend security, demo session,
  general routing, identity service, migration runner, memory core, and triggering
  message exclusion suites. 14 tests were skipped, including the 12 parameterized
  PostgreSQL cases and existing opt-in live checks.
- All 12 offline V2 identity cases passed, including concurrent ownership transfer
  and revocation of both V2-cookie and legacy-bearer access.
- The frontend production build passed. Vite reports the existing large-bundle
  warning (main JavaScript bundle exceeds 500 kB).
- PostgreSQL tests remain pending without a disposable test connection. Browser
  verification could not run because no browser surface is connected to this agent.

The existing `test_response_behavior_and_routing.py` suite contains three GitHub
binding expectation failures and one event-response expectation failure that also
occur with the committed workflow. These have not been changed or hidden by V2 tests.
The wider connector checks also found an existing conversation-history test that
expects recorded turns while its database is unavailable. It fails with the
committed conversation store as well, which deliberately returns empty history
when disconnected. This contract mismatch remains outside Phase 1.

## Limits and next phase

This phase does not implement BYOK, per-tenant memory databases, self-service Discord
installation, or new evaluation/trace storage. Those remain the next tickets.
Password recovery, email verification delivery, and distributed authentication
rate limiting are not provided by this portfolio identity slice; do not treat it as
a finished public authentication service.

Phase 1 requires live PostgreSQL verification before its deployment acceptance gate
can be marked complete. No live database migration has been applied by the agent.
