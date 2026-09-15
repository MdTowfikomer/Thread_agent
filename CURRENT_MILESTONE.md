# Current Milestone: Slack Live Interaction

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
