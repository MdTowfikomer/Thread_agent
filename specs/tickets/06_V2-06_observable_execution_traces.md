# Ticket: [V2-06] Observable Multi-Tenant Tracing & Conversation-Scoped Access Control

## Pillar

Active next demo work, revised 2026-10-28. Dependencies: Tickets 01 and 02 plus the
managed memory database. Ticket 03 and Ticket 04 are deferred. Traces must work
with the existing web and Discord paths without customer-database routing or a
new installation flow.
V2-06: Execution visibility

## Summary
Extend Thread's trace experience to be multi-tenant and conversation-scoped. Record structured execution telemetry (routing decisions, retrieved evidence scores, model identity, token counts, per-stage latency, and refusal reasons) without leaking hidden model thoughts, raw credentials, or titles of inaccessible documents. Enforce strict authorization ensuring users can only inspect traces for conversations they own or administer.

## Detailed Work Breakdown

### Task 6.1: Database Schema & Telemetry Capture
- Extend the existing migration sequence with `backend/app/data/migrations/022_v2_execution_traces.sql` (confirm the next available number before implementation):
  - `execution_traces`:
    - `id` (UUID), `organization_id` (FK), `conversation_id` (FK), `turn_id` (text), `user_id` (FK).
    - `stages`: JSONB recording:
      - `triage`: classified intent (`TOOL_EXECUTION`, `GENERAL_KNOWLEDGE`, `ORGANIZATIONAL_FACTS`), selected role.
      - `retrieval`: candidate count, dense scores, lexical ranks, RRF fused scores, chunks filtered out by scope.
      - `verification`: peer consultation verdict, evidence sufficiency check.
      - `formatter`: platform coercion result.
    - `metrics`: JSONB recording `latency_ms` per stage, `total_latency_ms`, `input_tokens`, `output_tokens`, `token_reporting_type` (`provider_reported` | `estimated`).
    - `created_at` (timestamptz).
- Storage location for this demo: the configured managed memory database, with strict organization and conversation scoping. Customer-owned storage routing is future scope.
- Inspect the existing conversation/turn schema first. Add durable conversation identity and ownership mapping if the current session-key representation cannot enforce the endpoints' authorization rules.
- Record and display only stages actually executed. Evidence verification must not be labelled as a real peer-agent consultation unless such a call occurred.

### Task 6.2: Trace Redaction & Safe Refusal Summaries
- Implement `TraceSanitizer`:
  - Automatically scrubs any string matching API key or connection string patterns before saving.
  - When evidence is insufficient or filtered out by ACL permissions, the trace notes `Filtered N candidate chunks due to access scope restrictions` without recording the document titles, authors, or text content.
  - Does not log raw hidden chain-of-thought tokens.

### Task 6.3: Conversation-Scoped Trace Authorization Endpoints
- Implement `backend/app/api/v2/traces.py`:
  - `GET /api/v2/organizations/{org_id}/traces/{trace_id}`:
    - **Authorization Rule**: User must belong to the workspace AND must either be:
      1. The creator of the conversation (`user_id == conversation.user_id`), OR
      2. An organization `owner` or `admin`.
    - If a regular member attempts to view another member's trace, return HTTP 404 (or 403).
  - `GET /api/v2/organizations/{org_id}/conversations/{conversation_id}/traces`:
    - Lists traces for turns within an authorized conversation.

### Task 6.4: Frontend Trace Inspector Integration
- Update frontend `TraceDrawer` / `TraceInspector`:
  - Displays interactive timeline showing stages: Triage Router -> Hybrid Retrieval -> Peer Verification -> Platform Formatter.
  - Visualizes dense vs lexical vs RRF retrieval scores for cited chunks.
  - Displays stage latency breakdown and token consumption badge.
  - Handles forbidden traces cleanly without crashing.

## Acceptance Criteria
1. An authorized user can inspect the full step-by-step trace of their question from routing through retrieval to citations.
2. An organization member attempting to access another member's conversation trace receives HTTP 404 / 403.
3. Organization owners and admins can inspect conversation traces across their workspace for audit purposes.
4. Failed model calls, database timeouts, or insufficient-evidence refusals display actionable stage error reasons in the trace.
5. Inaccessible document titles, authors, and text snippets are completely absent from traces of permission-filtered queries.
6. Plaintext model keys and database credentials never appear in trace payloads.

## Verification Commands
```bash
# Run trace authorization, redaction, and telemetry tests
backend\.venv\Scripts\python.exe -m pytest backend/tests/test_v2_execution_traces.py
```

## Implementation status

Implemented with selected offline verification. See [implementation notes](../EVALS_AND_TRACES_IMPLEMENTATION.md) for measured results, known fixture failures, migration 022 and pending live checks. See the root [codebase walkthrough](../../CODEBASE_WALKTHROUGH.md) for the request flow and reading order.
