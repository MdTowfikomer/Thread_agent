# Ticket: [V2-04] Self-Service Discord Onboarding & Ingestion Lifecycle

## Pillar

Status: Deferred to future scope by the user on 2026-10-28. The demo uses the
existing Discord installation and configured bindings/policies. This ticket is
not a prerequisite for evaluations or traces; existing permission checks remain required.
V2-04: Self-service Discord integration

## Summary
Provide an authorized OAuth onboarding flow for Discord, channel selection, explicit access scoping (public community vs. internal team), bounded historical ingestion with checkpointing, idempotent deduplication, message edit/delete synchronization, permission revocation handling, and destination visibility checks on outbound replies.

## Detailed Work Breakdown

### Task 4.1: Database Schema for Integrations & Sync Jobs
- Create migration script (`backend/app/migrations/004_v2_discord_integration.sql`):
  - `platform_installations`: `id` (UUID), `organization_id` (FK), `platform` (`discord`), `guild_id` (text, unique per platform), `guild_name` (text), `installed_by_user_id` (FK), `status` (`active` | `disconnected` | `permission_revoked`), `created_at` (timestamptz).
  - `channel_configurations`: `id` (UUID), `installation_id` (FK), `channel_id` (text), `channel_name` (text), `is_enabled` (boolean), `permission_level` (`public_community` | `internal_team`), unique `(installation_id, channel_id)`.
  - `ingestion_jobs`: `id` (UUID), `organization_id` (FK), `channel_id` (text), `status` (`pending` | `running` | `completed` | `failed`), `checkpoint_message_id` (text), `imported_count` (integer), `error_message` (text), `updated_at` (timestamptz).

### Task 4.2: OAuth Authorization Flow & Guild Binding
- Implement `backend/app/api/v2/discord.py`:
  - `GET /api/v2/organizations/{org_id}/integrations/discord/authorize`: Generates OAuth URL with state param signed with HMAC containing `org_id` and caller `user_id`.
  - `GET /api/v2/integrations/discord/callback`: Exchanges code for guild permissions, validates state signature, and binds `guild_id` to `organization_id` server-side. Never trusts client-supplied guild IDs alone.

### Task 4.3: Channel Selection & Scoping Endpoints
- Implement channel management:
  - `GET /api/v2/organizations/{org_id}/integrations/discord/channels`: Lists text channels available in the authorized guild via Discord bot API.
  - `POST /api/v2/organizations/{org_id}/integrations/discord/channels`: Selects channels to ingest and assigns `permission_level` (`public_community` or `internal_team`). Unsupported channel types (voice, stage, announcement without text) are excluded.

### Task 4.4: Bounded Historical Ingestion & Idempotent Deduplication
- Implement `DiscordIngestionService`:
  - Batched ingestion of channel history up to a bounded maximum (e.g. 1,000 messages per channel).
  - Checkpoints last processed message ID in `ingestion_jobs`.
  - Deduplication key: `(organization_id, guild_id, channel_id, message_id)` ensures repeated runs or retries never duplicate chunks or vectors.
  - Chunks inherit the channel's configured `permission_level`.

### Task 4.5: Discord Lifecycle (Edits, Deletions, Revocation)
- Process incoming Discord gateway / webhook events:
  - `MESSAGE_UPDATE`: Updates source record content, regenerates embedding chunks, and marks old chunks superseded.
  - `MESSAGE_DELETE`: Soft-deletes source record (`is_active = false`) and marks associated chunks deactivated so they cannot be retrieved.
  - `GUILD_DELETE` / Bot Kick: Flags `platform_installations.status = 'permission_revoked'` and disables retrieval for that installation.
- Implement Disconnect and Purge:
  - `DELETE /api/v2/organizations/{org_id}/integrations/discord`: Disconnects bot.
  - Optional `purge_data=true`: Hard-deletes all ingested chunks and source records from the tenant's memory database.

### Task 4.6: Destination Permission Check & Delivery Resilience
- In `backend/app/channels/outbound.py`:
  - Check destination channel classification before sending evidence.
  - If question is asked in a public Discord channel, only `public_community` evidence can be cited. Internal evidence citations are redacted from public responses even if the requester is an admin.
  - If Discord returns a 5xx / timeout, log the failure with message idempotency key; do not blindly resend without verifying delivery status.

### Task 4.7: Frontend Discord Management Screen
- Build `DiscordIntegrationCard` in `WorkspaceSettingsPage`:
  - "Connect Discord Server" button initiating OAuth flow.
  - Guild connection status badge and sync progress indicator (e.g. "Synced 450 messages across 3 channels").
  - Channel selection table with dropdowns to toggle channels and choose `Public` vs `Internal`.
  - "Sync Now", "Disconnect", and "Purge Imported Data" buttons.

## Acceptance Criteria
1. Connecting a Discord guild requires Thread admin authentication and Discord admin authorization, binding the server to the workspace server-side.
2. Only explicitly selected channels are ingested; non-selected channels are ignored.
3. Re-running ingestion on an active channel does not duplicate existing chunks or vectors.
4. Editing or deleting a message in Discord deactivates or updates the corresponding memory chunks.
5. Asking a question in a public Discord channel cites only public evidence; internal evidence is never posted publicly.
6. Disconnecting and purging data removes retrievable chunks from the tenant's memory database.

## Verification Commands
```bash
# Run Discord OAuth, channel selection, ingestion deduplication, and lifecycle tests
backend\.venv\Scripts\python.exe -m pytest backend/tests/test_v2_discord_integration.py
```
