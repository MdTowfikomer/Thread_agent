# Thread Agent: codebase walkthrough

Start with one idea: Thread gathers organizational records, retrieves only
authorized evidence, and uses an organization's model connection to answer a
question. Accounts and workspaces decide who can ask; citations and traces let
the user inspect what happened.

## 1. The repository map

| Location | Responsibility |
| --- | --- |
| `frontend/src/App.tsx` | Routes between landing, accounts, invitations and workspace views |
| `frontend/src/pages/WorkspacePage.tsx` | Chat, source timeline, connections and settings shell |
| `frontend/src/components/ChatArea.tsx` | Sends questions and renders answers, citations and execution links |
| `frontend/src/api.ts` | Browser requests and typed errors, including failed-request trace IDs |
| `backend/app/main.py` | FastAPI startup, route registration, CORS and validation handling |
| `backend/app/core/canonical.py` | Shared record, chunk, access-context, citation and receipt schemas |
| `backend/app/tenancy/` | Persistent accounts/workspaces and organization-specific model execution |
| `backend/app/memory/` | Ingestion persistence, embeddings, retrieval and conversation history |
| `backend/app/graph/` | Request state and routing/retrieval/verification/synthesis workflow |
| `backend/app/channels/` | Platform normalization, installation bindings and safe outbound delivery |
| `backend/app/tracing/` | Stage observation, redaction, managed trace persistence and ownership |
| `backend/app/evaluation/` | Offline and optional PostgreSQL benchmark implementations |
| `backend/app/data/migrations/` | Ordered, checksum-tracked database changes |
| `backend/tests/` | Behavioral, authorization, retrieval and connector checks |

## 2. Follow a question from the browser

Use “When is our Aurora launch?” as the example.

1. **The UI submits the question.** `ChatArea.tsx` calls `sendChatMessage()` in
   `api.ts`, which POSTs to `/api/chat` with the HTTP-only session cookie. A loading
   message appears while the request runs.
2. **The server establishes identity.** `core/auth.py:get_current_principal`
   resolves the V2 session through `tenancy/auth.py` and rechecks current membership.
   The active organization and allowed scopes come from the server. A caller's
   claimed user ID or role cannot grant privileges.
3. **The chat API validates the request.** `api/chat.py` rejects empty questions
   and mismatched organization assertions, then calls the shared inbound service.
4. **The inbound service constructs context.** `channels/inbound_service.py`
   builds a session key from platform, destination and user. V2 also fingerprints
   current source scopes so a downgraded user gets a fresh context window. It loads
   recent conversation turns and constructs `GraphState`.
5. **The trace wrapper creates durable ownership.** `tracing/runtime.py:ObservedGraph`
   starts a conversation/turn trace in managed memory before invoking the graph.
   It stores safe execution metadata, not the complete question or hidden thoughts.
6. **The graph executes its real stages.** Read the next section for the four
   nodes and the distinction between code decisions and model generation.
7. **The result is normalized and saved.** The wrapper redacts credential patterns
   and finalizes the trace. The inbound service validates the answer and records
   user/assistant turns through the conversation store.
8. **The UI displays the answer and evidence.** The response includes citations,
   receipt metadata, trace ID and conversation ID. “Inspect execution” opens
   `TraceInspector.tsx`, which fetches the saved trace through an authorized API.

Failures also matter: a missing BYOK connection returns an actionable error and,
when managed trace storage is available, a saved failure trace ID in response
headers. The UI can inspect that trace even though no answer was generated.

## 3. What LangGraph does here

Read `graph/state.py` first, then `graph/workflow.py` from top to bottom.

- **Triage:** distinguishes explicit tools, ordinary conversation and organizational
  questions. The general assistant is the default; configured specialists can be
  chosen by expertise matching. Tenant executions require a valid saved model
  configuration before continuing.
- **Retrieval:** conversational/tool routes can bypass vector search. Organizational
  questions call the retrieval service with a verified `AccessContext` and any
  triggering-message exclusions.
- **Evidence verification:** checks whether the returned evidence pack is sufficient.
  This is deterministic verification code. It is not a second autonomous model
  secretly consulting a peer.
- **Synthesis:** runs the selected tool, produces a direct conversational answer,
  or builds a source-grounded prompt. Missing evidence produces an explicit
  insufficient-evidence response. Source instructions do not authorize tools.

`observe_stage` captures the stages that actually execute. `trace_model_usage`
captures model operations within a node. After the graph, the wrapper performs
real output text normalization and records that operation too.

## 4. How memory and retrieval work

The useful distinction is:

- **Source record:** the original normalized message/document and its provenance.
- **Memory chunk:** retrievable text, permissions, metadata and embedding.
- **Access context:** verified organization and source scopes for this execution.
- **Retrieval receipt:** selected IDs, scores and strategy information.
- **Evidence pack:** citations plus the receipt and an evidence-sufficiency decision.

`memory/adapters.py` normalizes supported inputs. `memory/repository.py` prepares
embeddings and coordinates persistence. `memory/supabase_store.py` implements the
managed PostgreSQL/Supabase operations. `memory/store.py` supplies the local store
used by cache/offline paths.

`memory/retrieval.py` filters by organization and permissions, excludes the query's
own message and unsuitable bot content, retrieves candidates, and constructs the
evidence pack. PostgreSQL hybrid retrieval combines vector similarity with full-text
ranking using RRF. The local fallback has different scoring; the trace should not
pretend its numbers are PostgreSQL RRF scores.

Read `data/migrations/019_filter_hybrid_search_by_embedding_model.sql` alongside
the retrieval code to understand the SQL boundary. SQL predicates constrain the
authorized result set; they do not prove a particular physical query-plan order.

## 5. Where the model key enters

The key is configured through `api/v2/credentials.py` and encrypted using
`core/crypto.py`. `tenancy/credentials.py` owns metadata and transactional lifecycle
changes. `tenancy/models.py` decrypts only when needed and constructs a scoped
Google client or embedding request.

The key does **not** belong in `GraphState`, prompts, citations or traces. There is
no tenant fallback to a server key. Chat model selection and the fixed
`gemini-embedding-001` / 768-dimensional embedding configuration are separate.

Token usage comes from provider metadata when available; otherwise it is clearly
estimated. Dollar cost remains unavailable rather than invented.

## 6. How Discord joins the same pipeline

`channels/gateway.py` receives Discord events. Installation and channel policies
resolve the workspace and destination permissions. The shared inbound query service
then uses the same graph as web chat.

`channels/outbound.py` checks destination bindings and evidence permissions before
delivery, with idempotency handling. An internal user asking in a public channel
does not make internal evidence safe to post there. Existing Slack/Telegram webhook
paths live in `api/webhooks.py`.

The demo keeps the existing configured installation. It does not include a new
self-service OAuth onboarding flow or customer-owned database configuration.

## 7. Read traces and evaluations correctly

`tracing/repository.py` stores conversations and traces in managed memory.
`api/v2/traces.py` requires current membership and conversation ownership or an
owner/admin role. Evidence is filtered again for the reader's current source scopes.
`tracing/sanitize.py` allowlists trace metadata and removes credential patterns.

The default evaluation command is safe to run without model credentials:

```powershell
backend\.venv\Scripts\python.exe scripts/run_eval_v2.py --report .tmp/my_eval.json
```

Read the dataset, `evaluation/runner.py`, and the emitted failures together.
The 32-case synthetic hash-vector benchmark is a reproducibility and evaluation
harness demonstration. It is not a live Gemini accuracy result. An optional
PostgreSQL backend measures real SQL retrieval with fixture vectors in a disposable
schema. Real model behavior and production performance need separate evidence.

## 8. A practical reading order

1. `core/canonical.py`: understand the data vocabulary.
2. `api/chat.py` and `core/auth.py`: understand the request and identity boundary.
3. `channels/inbound_service.py`: see how context and responses are assembled.
4. `graph/state.py` and `graph/workflow.py`: follow one question through the nodes.
5. `memory/retrieval.py` and `memory/supabase_store.py`: inspect the evidence search.
6. `tenancy/models.py` and `core/crypto.py`: follow the model credential boundary.
7. `tracing/runtime.py`, `repository.py`, and `api/v2/traces.py`: inspect observability
   and access control.
8. Run the evaluation CLI, then read the security/trace tests to see expected behavior.

For deployment and verification limits, read `specs/PHASE_1_IMPLEMENTATION.md`,
`specs/PHASE_2_IMPLEMENTATION.md`, and `specs/EVALS_AND_TRACES_IMPLEMENTATION.md`.
No live PostgreSQL/provider proof or visual browser check should be inferred from
offline test counts alone.
