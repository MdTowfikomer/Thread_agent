# Ticket: [V2-02] Bring Your Own Model Key (BYOK) & Credential Encryption

## Pillar
V2-02: Bring your own key

## Summary
Enable organization administrators to supply their own model provider API key (Google Gemini initially, with OpenAI optional). Securely store keys encrypted at rest using AES-256-GCM, validate them against provider ping endpoints, provide rotation/deletion, track query token usage, and resolve model clients dynamically per tenant turn with zero secret leakage in logs, traces, or client responses.

## Detailed Work Breakdown

### Task 2.1: Encryption Utility & Database Schema
- Create migration script (`backend/app/data/migrations/021_v2_model_credentials.sql`):
  - `model_credentials`: `id` (UUID), `organization_id` (FK, unique), `provider` (`google` | `openai`), `encrypted_api_key` (text), `model_name` (text), `embedding_model` (text), `status` (`active` | `invalid` | `revoked`), `last_validated_at` (timestamptz), `updated_at` (timestamptz).
- Implement authenticated symmetric encryption module `backend/app/core/crypto.py`:
  - Uses AES-256-GCM via `cryptography.hazmat.primitives.ciphers.aead.AESGCM`.
  - Format: base64-encoded `nonce (12 bytes) + ciphertext + tag (16 bytes)`.
  - Reads `THREAD_MASTER_ENCRYPTION_KEY` from backend environment (32 bytes base64).

### Task 2.2: BYOK Endpoints & Provider Validation
- Implement `backend/app/api/v2/credentials.py`:
  - `POST /api/v2/organizations/{org_id}/credentials/model`:
    - Validates caller is `owner` or `admin`.
    - Tests API key by making a lightweight ping to the provider (e.g. `client.models.list()` or 1-token test prompt).
    - If valid, encrypts key and stores record; if invalid, returns HTTP 400 with actionable provider error message.
  - `GET /api/v2/organizations/{org_id}/credentials/model`:
    - Returns masked credential information (e.g. `provider`, `masked_key`: `AIza...4X9Q`, `model_name`, `embedding_model`, `status`, `last_validated_at`). Never returns plaintext key.
  - `DELETE /api/v2/organizations/{org_id}/credentials/model`:
    - Revokes and deletes stored key. Subsequent queries fail with actionable setup prompt.

### Task 2.3: Dynamic Model Factory & Separate Embedding Config
- Refactor `get_llm()` in `backend/app/graph/workflow.py` to accept `tenant_context: TenantContext`:
  - Decrypts the tenant's API key into memory only for the duration of client instantiation.
  - Returns request-scoped `ChatGoogleGenerativeAI` or `ChatOpenAI`.
  - If no key is configured or decryption fails, raises `TenantModelNotConfiguredError`.
  - Embedding configuration (`gemini-embedding-001`, 768 dimensions) is locked separately from the reasoning model to prevent vector store dimension mismatch.

### Task 2.4: Token Usage & Cost Attribution
- In graph synthesis nodes, extract token usage metadata from the LLM response:
  - Track `input_tokens`, `output_tokens`, and `is_estimated` (boolean indicating if reported by provider or counted via tokenizer).
  - Store token metrics in the query's execution trace.

### Task 2.5: Frontend BYOK Settings Interface
- Build `BYOKSettingsCard` component in `WorkspaceSettingsPage`:
  - Select provider (Google Gemini default).
  - Password input field for API key with "Test & Save" button.
  - Masked key status display, status indicator badge (Active / Revoked), and "Rotate Key" / "Remove Key" actions.

## Acceptance Criteria
1. An organization admin can save a valid Google Gemini API key; the key is validated via provider ping and stored encrypted in PostgreSQL.
2. An invalid or expired API key returns an immediate, actionable error without saving.
3. Plaintext API keys never appear in HTTP response payloads, log files, execution traces, or evaluation outputs.
4. Two organizations querying the system simultaneously execute their prompts against their respective distinct API keys.
5. Deleting an API key causes subsequent queries for that workspace to return an actionable error instructing the user to configure a model key.
6. Changing the chat model does not alter the embedding model configuration.

## Verification Commands
```bash
# Run BYOK encryption, validation, and dynamic resolution tests
backend\.venv\Scripts\python.exe -m pytest backend/tests/test_v2_byok_credentials.py
```

## Implementation status

Implemented for verification. See [Phase 2 implementation notes](../PHASE_2_IMPLEMENTATION.md) for the existing-runner migration (021), Gemini-only scope, fixed embedding model, credential lifecycle, usage reporting and pending live verification.
