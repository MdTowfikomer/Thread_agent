# GitHub Webhook E2E Verification

This commit tests end-to-end webhook ingestion for repository `MdTowfikomer/Thread_agent` (ID: `1371393965`) into Thread organization `gdg_mcet`.

### Verification Targets
1. Pull request event delivery signed via HMAC-SHA256.
2. Webhook delivery ledger state transition: `processing` -> `completed`.
3. Authoritative organization binding resolution to `gdg_mcet`.
4. Transactional persistence into `memory_repository` and Supabase PostgreSQL.
