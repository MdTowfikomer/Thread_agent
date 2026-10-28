# Novaflow demo workspace transition

Applied 2026-10-28 to the database configured in the local backend environment.
The user authorized moving existing configured platforms to Novaflow and deleting
old GDG MCET memory, then clarified that GitHub information must be preserved.

Target workspace: `my-dev-team-bf8d40e051bc` (Novaflow Autonomous Systems).

## Applied in one database transaction

- Moved the configured Discord guild, Slack workspace/channel binding, Telegram
  group, and `mdtowfikomer/thread_agent` GitHub repository to Novaflow.
- Moved 19 associated channel policy rows, preserving their visibility scopes.
- Preserved and transferred all 49 GitHub source records and 49 memory chunks.
- Transferred 41 GitHub webhook delivery markers to retain replay protection.
- Deleted 108 non-GitHub source records and 108 corresponding chunks from GDG MCET.
- Deleted GDG MCET's 294 conversation turns and 116 outbound delivery records.
- No GDG MCET V2 conversations or execution traces existed to delete.
- Novaflow's existing account, membership, BYOK credentials and chat history were
  retained. Existing GDG MCET user accounts and memberships were not transferred.
- Unconfigured legacy fixture bindings were not promoted into Novaflow.

## Runtime corrections and verification

- Removed GitHub's hardcoded startup registration that could overwrite repository
  ownership back to GDG MCET. Startup now reads persisted bindings.
- The connections endpoint refreshes its binding snapshots from the database.
- Two focused GitHub regression tests passed, including read-only startup loading
  of a repository rebound to a different workspace.
- Fresh-process connections endpoint check reported one binding per platform.
- Fresh-process authorized memory endpoint check returned 49 records for the
  Novaflow owner. These checks used a test authentication dependency override;
  they do not substitute for verification of the browser session.
- Local API health returned HTTP 200.
- Live retrieval for "Thread Agent repository changes" returned four GitHub
  citations with sufficient evidence through PostgreSQL vector/FTS/RRF retrieval,
  all within the Novaflow workspace.

No platform messages were sent. Provider-side event delivery, Discord gateway
readiness, and hosted deployment updates are separate live verification steps.

## Preserved embedding provenance

The retained GitHub chunks comprise 14 Gemini embedding vectors and 35 legacy
`deterministic-v1` vectors, all 768-dimensional. Their provenance was preserved;
the transition did not relabel synthetic vectors as real provider embeddings.
