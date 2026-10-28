# Current Milestone: V2 Demo — Evaluations and Conversation-scoped Traces

## Deployment preparation — 2026-10-29

The current deployment gate passed 92 selected tests, with 39 opt-in checks skipped,
and the frontend production build passed. Local/user-observed live checks verified
BYOK chat, Slack and Telegram ingestion, and Telegram evidence cited in Slack.
The dedicated Discord gateway is hosted separately; its blocking first-mention
path was fixed and packaged, and the user reported a delivered Discord reply.
Full Discord ingestion-to-citation verification remains a separate check.

GitHub memory was preserved while the existing configured platform bindings were
transferred to the demo workspace. Public backend deployment and Telegram cutover
are in progress; do not claim either complete until hosted V2 checks pass.
See `specs/reports/backend_deployment_readiness.md` and
`specs/reports/discord_heartbeat_fix.md` for scope and verification details.

## Earlier implementation verification

Implementation and selected offline verification are complete for Tickets 05/06:
89 selected checks passed, 41 opt-in checks skipped, and the frontend build passed.
See `specs/EVALS_AND_TRACES_IMPLEMENTATION.md`, `specs/reports/eval_v2_report.md`,
and `CODEBASE_WALKTHROUGH.md`. Remaining live verification and the demo's known
fixture abstention failures must remain visible; do not claim production accuracy.

On 2026-10-28, the user deferred customer-owned databases (Ticket 03) and
self-service Discord onboarding (Ticket 04). Keep the existing Discord integration
and managed PostgreSQL memory. The implemented scope is Tickets 05 and 06,
original Phase 5, following implemented Phase 2. Preserve existing tenant/source/
destination permissions; do not claim deferred capabilities in the demo.

See `specs/IMPLEMENTATION_PLAN_V2.md` for the revised sequence. Live PostgreSQL,
real-provider and browser verification limitations from Phases 1/2 remain pending;
the scope reduction does not turn those checks into completed evidence.

## Previous milestone: V2 Phase 2 — Organization-specific Model Credentials

The user explicitly authorized Phase 2 on 2026-10-28. Implement Ticket 02:
AES-256-GCM credential storage, provider validation, organization-scoped chat and
embedding execution, usage attribution, and BYOK settings. Use the existing
migration runner (migration 021). Do not begin Phase 3 storage work here.

Phase 2 implementation is in place. See `specs/PHASE_2_IMPLEMENTATION.md` for
configuration, verification evidence and the remaining live acceptance checks.

Phase 1 PostgreSQL deployment proof remains pending; retain that limitation when
reporting Phase 2 validation. Never migrate live databases or use real customer
provider keys as a substitute for disposable integration verification.

## Previous milestone: V2 Phase 1 — Identity and Tenant Foundation

The user authorized V2 Phase 1 after reconciling `specs/V2_SPEC.md`, Ticket 01,
and `specs/IMPLEMENTATION_PLAN_V2.md`. This supersedes the earlier scope below.

Implementation includes persistent identity and workspace metadata, revocable
sessions, membership administration, configurable assistant roles, and the
corresponding frontend. PostgreSQL deployment proof remains pending; see
`specs/PHASE_1_IMPLEMENTATION.md` for setup and verification status.

Do not advance to BYOK or customer-owned storage under this milestone.

## Previous milestone: Slack Live Interaction (preserved)

Read this file before exploring the repository. It is the active scope.

## Goal

Complete one real Slack interaction loop in the already bound workspace:

1. A human message in `#general` is signature-verified and ingested once.
2. A human `@Thread` question is retrieval-gated and receives one grounded reply in the same channel.
3. The reply contains only evidence permitted for the destination channel.
4. Supabase contains durable inbound provenance, retrieval receipt, and outbound audit evidence.

Do not begin new connectors, OAuth work, broad frontend changes, or refactors until this proof is complete.

## Real Integration Facts

- Thread organization: `gdg_mcet`
- Slack workspace ID: `T0C21JVKS49`
- Slack public demo channel: `#general` / `C0C21QPFB6E`
- Slack Request URL: configured externally as `/api/webhooks/slack` on the current public HTTPS tunnel.
- The bot can send real Slack messages. Slack inbound Events API delivery has not yet been proven.
- Never put tokens, signing secrets, or answer text into commits, tests, logs, or reports.

## Required Slack Configuration (User-Owned)

The Slack app must be installed in the workspace, invited into `#general`, and have these bot scopes:

- `channels:read`
- `channels:history`
- `app_mentions:read`
- `chat:write`

After a scope/event change, Slack must be reinstalled. Bot event subscriptions must include:

- `message.channels`
- `app_mention`

## Relevant Code Only

- Signed inbound endpoint: `backend/app/api/webhooks.py`
- Slack parser/ingestion: `backend/app/channels/slack.py`
- Durable channel bindings: `backend/app/channels/installation.py`
- Retrieval and outbound sending: `backend/app/channels/outbound.py`
- Outbound endpoint: `backend/app/api/delivery.py`
- Delivery ledger: `backend/app/channels/delivery.py`
- Tests: `backend/tests/test_slack_connector.py`, `backend/tests/test_outbound_delivery.py`

Start by reading those files only. Use `rg` to find the named symbols before reading anything else.

## Non-Negotiable Security Rules

- Derive organization and user identity from the verified bearer token. Never trust browser or event payload organization/role claims.
- Resolve Slack destinations only from durable server-owned workspace/channel bindings.
- A public channel may receive only `PUBLIC_COMMUNITY` evidence. An internal answer must never be posted into `#general`.
- `PENDING_REVIEW` content is never retrievable or sendable.
- Ignore bot-originated Slack events and message subtypes.
- Canonically deduplicate a message observed as both `message.channels` and `app_mention` using workspace ID + channel ID + message timestamp.
- Do not blindly retry an outbound post after an ambiguous timeout: the provider may already have delivered it.

## Acceptance Evidence

For one real human message and one real `@Thread` question, report only:

- Slack event IDs and message timestamps
- Supabase source-record/chunk IDs and source URI
- Inbound replay result and unchanged chunk count
- Retrieval receipt ID and citation count
- Outbound provider response ID, outbound audit row ID/status
- A public-destination ACL check showing internal evidence is rejected before any provider call

## Current Known Gaps To Fix In This Milestone

1. Outbound sending must compare evidence/citation permissions with the destination channel policy before provider delivery.
2. Scope user-supplied idempotency keys by organization, initiating user, platform, and destination.
3. Failed sends need an explicit controlled retry state; ambiguous provider timeouts need `unknown`, not automatic duplicate posts.
4. Add tests for the above before attempting a live `@Thread` response.

## Commands

```powershell
backend/.venv/Scripts/python.exe -m pytest -q
```

```powershell
cd frontend
npm run build
```

Do not claim a live Slack proof until the Event API delivery log, FastAPI request log, and Supabase rows agree.
