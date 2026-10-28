# V2 demo: online and platform verification plan

Date: 2026-10-28

## Read-only checks already performed

These checks authenticated existing bot credentials and inspected schema metadata.
They did not migrate databases, post messages, alter provider webhooks, create
GitHub events, or perform billed model generation.

| Area | Observed result | What this proves |
| --- | --- | --- |
| Configured PostgreSQL | Reachable; pgvector installed | Database connection and extension work |
| Identity tables | Users, organizations and memberships present | Phase 1 schema foundation exists |
| BYOK table | `model_credentials` absent | Migration 021 is still needed in this database |
| Trace tables | `conversations` and `execution_traces` absent | Migration 022 is still needed in managed memory |
| Local encryption configuration | Master key missing or invalid | Local BYOK cannot yet be used successfully |
| Disposable test databases | Neither test database variable configured | Opt-in PostgreSQL suites remain unverified |
| Discord | Bot token authenticated | Credential works, not proof of gateway ingestion/replies |
| Slack | Bot token authenticated | Credential works, not proof of Events API delivery |
| Telegram | Bot authenticated; webhook present; no reported webhook error; zero pending updates | Credential and webhook registration look healthy |
| GitHub | Webhook secret configured; one active repository binding; PAT/OAuth/App credentials absent | Inbound webhook setup can be tested; absence of a PAT alone does not invalidate ingestion |
| Backend URL configured in frontend rewrite | `/health` and `/openapi.json` timed out after 12 seconds | Deployed availability/version is unverified; could be a cold start or an outdated target |

These are local configured-environment observations, not confirmation that the
hosted deployment has the same environment or code version.

## 1. Establish the staging deployment

- Confirm the actual public API URL and frontend rewrite target. Obtain a healthy
  `/health` response and confirm the deployed OpenAPI includes V2 account,
  credential and trace endpoints.
- Review/apply pending migrations 021/022 to the intended managed staging database.
  Check the migration checksum tracker; do not blindly rerun old migration SQL.
- Configure a valid `THREAD_MASTER_ENCRYPTION_KEY` consistently across API and
  worker processes. Keep credentials out of reports and screenshots.
- Establish legitimate owner/admin access to the workspace bound to the existing
  bots. A new user's workspace does not inherit MCET's bindings or model key.
- Save a valid BYOK connection for that bound workspace. A global Gemini key is
  not a substitute for its organization-specific model connection.
- Confirm HTTPS cookies, allowed origins, reverse-proxy routing and the intended
  gateway worker configuration. Health alone does not prove bot-worker readiness.

## 2. Real PostgreSQL and application authorization

Configure a disposable `THREAD_TEST_SERVICE_DB_URL` outside source control, then run:

```powershell
backend\.venv\Scripts\python.exe -m pytest backend/tests/test_v2_identity_and_tenants.py backend/tests/test_v2_byok_credentials.py backend/tests/test_v2_execution_traces.py backend/tests/test_v2_security_isolation.py -q
```

The PostgreSQL variants create/drop generated test schemas. Use an appropriate
backend test role; never substitute a production database for a disposable target.
Verify actual PostgreSQL constraints, ownership transfers, invitation/session
revocation, ciphertext, trace authorization and source-scope changes.

Separately verify staging memory RPCs: transactional source/chunk persistence,
hybrid/FTS search, organization/scope filtering and direct browser-role denial by
RLS. The older Supabase live suite has writes and cleanup and needs V2 review
before selecting its cases. Do not enable all historical live tests indiscriminately.

## 3. Real model and neural retrieval

- Validate a real key through settings, then generate a short answer and an actual
  768-dimensional embedding using the saved organization credential.
- Ask grounded questions about known staging records and inspect citations and
  provider-reported usage. Confirm the selected model and embedding model separately.
- Use two test organizations with separate keys and disjoint records. Confirm
  neither keys nor source evidence cross the boundary.
- In a disposable workspace, test invalid rotation, key removal, and restoration.
  Failed rotation must preserve the previous valid connection; removal must block
  subsequent calls without using a server key.
- Ask missing-information questions, including the pizza-order cases that the
  offline baseline answered incorrectly. Judge real answers against the sources.
- Confirm model/provider errors are actionable and their saved traces contain no
  credentials or raw provider exception bodies.

The optional SQL benchmark is:

```powershell
backend\.venv\Scripts\python.exe scripts/run_eval_v2.py --backend postgres --db-url-env THREAD_EVAL_DB_URL --report .tmp/live_sql_eval.json
```

It uses real pgvector/FTS but synthetic hash vectors and deterministic generation.
It is not the real-Gemini evaluation above. Keep those results separate.

## 4. Real browser journey

- Sign up/log in, create/switch workspaces, invite/accept a teammate, change a role,
  remove a member, sign out and confirm access is revoked on subsequent requests.
- Save/rotate/remove a test model connection; verify the form never retrieves the
  plaintext saved key or exposes it in browser storage.
- Ask a grounded question, a missing-evidence question and a failed-model question.
  Open their saved traces and confirm the stages, evidence, timings and usage.
- As two members, attempt to open each other's trace URLs. Expect 403/404. Confirm
  the authorized owner/admin can inspect their workspace's traces.
- Verify keyboard operation, dialog focus, mobile layout and state after refresh.

## 5. Real platform loops

Use approved, clearly labelled test channels/chats and synthetic content. A bot
authentication response or a mocked webhook payload is not an end-to-end pass.

| Platform | Required live proof |
| --- | --- |
| Discord | A human message enters a bound channel, becomes one source record, and a human mention produces one cited reply and saved trace. Verify the gateway is running, intents/permissions are correct, bot messages are ignored, triggering questions are excluded from evidence, and internal facts are not posted publicly. |
| Slack | Real URL verification and signed Events API delivery. Verify bot membership/scopes, ordinary-message ingestion, one app-mention answer, canonical deduplication across message/app-mention events, native formatting and public/internal destination restrictions. A 200 acknowledgement is not proof that background processing succeeded. |
| Telegram | Correct webhook secret and bound chat, real human text ingestion, a supported mention/DM query, one correctly escaped reply with citations, update deduplication and access isolation. Verify any intended polling mode separately from webhook registration. |
| GitHub | A real supported push/PR/comment event from the bound test repository arrives with a valid signature and delivery ID, persists provenance, appears in retrieval and safely deduplicates on redelivery. Check repository-query commands separately. OAuth account linking requires its own configured client; webhook ingestion does not inherently require a PAT. |

For each platform also test one unsupported/unbound input and one controlled retry.
An ambiguous outbound timeout must not trigger an automatic duplicate post.

## 6. Evidence to record

For each test retain: environment and deployed revision, synthetic test-run ID,
platform event/message/delivery IDs, source/chunk IDs, trace/conversation IDs,
observed result, expected result, latency and pass/fail. Store screenshots only
with synthetic content; never include tokens, passwords, private records or keys.

The main successful path is:

```text
Real human event → verified binding/signature → durable source/chunk →
authorized retrieval → organization model → one platform reply → saved trace
```

## Existing script caveats

- `test_discord_live_agent.py` and `test_platform_connectors_integration.py` contain
  simulated clients, patched verification or deterministic execution. Their names
  do not establish real platform connectivity.
- `backend/scripts/discord_live_proof.py` posts to hardcoded real channels and
  manually ingests constructed messages. It is not a proof of automatic human
  Gateway ingestion and must not be run blindly in the community.
- The old gateway preflight requires a global model key and checks only older
  tables. That is insufficient for the V2 BYOK/trace flow and can misclassify readiness.

## Recommended order

Deployment/schema configuration → isolated PostgreSQL checks → real BYOK/web flow
→ Discord → Slack/Telegram → GitHub → repeatable recorded walkthrough.

No new platform test messages or events have been sent as part of this inspection.
