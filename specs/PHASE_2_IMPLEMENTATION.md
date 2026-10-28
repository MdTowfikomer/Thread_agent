# V2 Phase 2: organization-specific model credentials

Date: 2026-10-28

Status: Implemented; live PostgreSQL/provider and browser verification remain pending.

## Delivered behavior

- Owners and administrators can validate, save, replace and remove a Google Gemini API key in workspace settings.
- API keys are stored as AES-256-GCM ciphertext, with randomized 12-byte nonces and 16-byte authentication tags. Associated data binds the secret to its organization and purpose; moving ciphertext between organizations fails authentication.
- Responses expose only masked suffixes and configuration metadata. Request validation, provider failures and decryption errors exclude rejected keys, ciphertext and raw provider response bodies.
- Chat, specialist matching, ingestion embeddings, retrieval embeddings, discussion summaries and re-embedding workers resolve credentials for the organization they are processing.
- Configured tenant execution never uses global Gemini/OpenAI keys or deterministic flags as a replacement for missing or rejected organization credentials.
- New queries fail with an actionable setup error after key removal. Platform error replies continue through destination authorization and idempotent delivery.
- Rotation and deletion use credential revisions and transactional authorization rechecks. Slow validation cannot restore a deleted key, and a client created before rotation is rejected before invocation.
- Query traces include safe model identity, operation, stage latency and token usage. The chat UI distinguishes provider-reported counts from explicitly estimated counts.

## Provider and model choices

Phase 2 supports Google Gemini only; optional OpenAI support is deferred. The server permits `gemini-3.6-flash` and `gemini-3.5-flash-lite`. The UI receives this list from the credential metadata endpoint.

Embedding configuration is fixed independently at `models/gemini-embedding-001`, 768 dimensions. This corrects the ticket's earlier `text-embedding-001` name and matches the existing repository's intended embedding model. The Google [embedding documentation](https://ai.google.dev/gemini-api/docs/embeddings) documents the model and supported dimensions. Changing the chat model does not change the embedding configuration or reindex existing vectors.

Validation uses authenticated metadata requests for the selected chat model and the embedding model, checking their advertised capabilities. These [model metadata endpoints](https://ai.google.dev/api/models) validate access without a generation call. They do not guarantee future inference quota, billing availability, content acceptance or successful generation.

Keys are transmitted in the provider header, never in URLs. Requests use fixed provider destinations, TLS verification, explicit timeouts and no redirects. Chat execution uses the installed LangChain Google integration with a single SDK attempt (`max_retries=1` in this version; `0` enables SDK defaults). There is no tenant model/provider failover.

## Encryption and setup

1. Install the updated `backend/requirements.txt` in the project environment.
2. Supply `THREAD_MASTER_ENCRYPTION_KEY` as standard base64 encoding of exactly 32 cryptographically random bytes. There is no default.
3. Use the same master key in API and worker processes. Keep it outside source control. Replacing it without re-encrypting existing records makes saved keys unreadable.
4. Review and apply migration `backend/app/data/migrations/021_v2_model_credentials.sql` through the existing migration runner, after migration 020. The migration is recorded in the checksum manifest.
5. Start the application, sign in, create/select a workspace, and open Settings → Your model connection → Test & save.

Generate a master key locally, in a terminal you control:

```powershell
backend\.venv\Scripts\python.exe -c "import base64,secrets; print(base64.b64encode(secrets.token_bytes(32)).decode())"
```

Do not put its output in screenshots, recordings, commits or reports. The agent has not generated or installed a real deployment master key, migrated a live database, or used a real customer API key.

The envelope uses the standard [Cryptography AESGCM API](https://cryptography.io/en/stable/hazmat/primitives/aead/). Plaintext exists in process memory while the SDK/HTTP request needs it; Python strings and SDK internals do not provide a reliable memory-zeroization guarantee. Clients and plaintext credentials are not cached in global tenant registries, serialized into graph state or stored in trace records. Removing a key clears active-row ciphertext and suffixes, but does not revoke the API key at Google or cancel requests already sent.

## Storage and API

Migration 021 adds service-metadata table `model_credentials`, protected against direct access by browser Supabase roles. New IDs are UUID values stored as text, consistent with the Phase 1 service repository. Timestamps use PostgreSQL `TIMESTAMPTZ`.

| Endpoint | Authorization | Behavior |
| --- | --- | --- |
| `GET /api/v2/organizations/{org_id}/credentials/model` | Owner/admin | Masked metadata and supported chat models |
| `POST /api/v2/organizations/{org_id}/credentials/model` | Owner/admin | Validate and save/replace a key and selected chat model |
| `DELETE /api/v2/organizations/{org_id}/credentials/model` | Owner/admin | Remove ciphertext/suffix and retain a revision tombstone |

The POST body accepts `provider`, `api_key` and `model_name`. Extra fields, including attempted embedding changes, are rejected without echoing their values. A failed validation leaves the previous credential intact.

Unconfigured, invalid and revoked keys block new tenant queries. Missing/wrong master keys and corrupt ciphertext fail explicitly. A transient provider outage or quota error does not select another organization's key or a server key.

## Usage and attribution

Each successful provider operation emits a `model_usage` trace event containing organization, provider, model, operation, token counts, reporting source and latency. Provider counts are used when available. Otherwise counts use an explicitly labelled character-based heuristic, not an exact tokenizer count.

Cost remains `null` / `not_estimated`; no dollar estimate is fabricated. Provider dashboards remain the billing reference. Durable trace storage, historical usage reporting and billing features are outside Phase 2.

Per-node context-local collectors isolate simultaneous query telemetry. Embedding vectors and their model labels travel together rather than reading a shared mutable model-name field on tenant paths.

`TenantContext` carries organization, user and role identifiers. Current credential
metadata is resolved server-side for each operation so revocation is not hidden by
a stale context snapshot; plaintext keys are not context fields.

## Verification

Primary checks from the repository root:

```powershell
backend\.venv\Scripts\python.exe -m pytest backend/tests/test_v2_byok_credentials.py backend/tests/test_v2_identity_and_tenants.py -q
```

The shared fixture applies migrations 020 and 021 to an explicit offline DB-API test seam. Set `THREAD_TEST_SERVICE_DB_URL` locally to a disposable PostgreSQL database to also run the complete migrations and transaction tests in isolated generated schemas. Do not use a production database.

Tests cover encryption randomness/authentication, cross-organization ciphertext swaps, master-key failures, provider validation, error redaction, role boundaries, concurrent organization queries, credential rotation/deletion races, fixed embeddings, ingestion/retrieval/generation, summaries, worker key refresh, SDK construction, usage and platform setup errors. Re-embedding workers initialize a provider only when processing a row; schema-only maintenance does not require a model key. Provider calls use synthetic credentials and mocked network/SDK responses; the real installed SDK construction check disables sockets.

Frontend check:

```powershell
cd frontend
npm run build
```

The completed BYOK/identity suite passed 33 checks, with 29 PostgreSQL cases skipped because no disposable database was configured. The final combined acceptance/regression run passed **76 checks**, with **32 opt-in PostgreSQL/live checks skipped**. It included BYOK, identity, embedding reliability, re-embedding, routing, session security, memory core, migrations and summary ACL behavior. The isolated legacy model-fallback suite also passed all three checks.

The frontend production build passed; the main JavaScript bundle still produces the existing >500 kB warning. `git diff --check` passed. No live database migration or real-provider generation was performed.

The broader regression batch found an existing retrieval-strategy-label assertion in `test_supabase_hybrid.py`: committed code already emits `deterministic_offline_test_pre_acl`, while the test expects an older label. The legacy model-default test also requires deterministic flags disabled; its isolated run passed all three checks. Neither result is evidence of a tenant credential fallback.

No connected browser surface is available for visual verification. Live PostgreSQL and real provider inference are not claimed as verified.

## Next scope

Phase 3 remains managed/customer-owned memory storage selection. Phase 2 does not introduce customer database connection settings, new platform installations, billing, or durable execution-trace storage.
