# V2 demo: evaluations and conversation-scoped traces

Date: 2026-10-28

## Delivered scope

Tickets 05/06 use the configured managed PostgreSQL memory database and existing
Discord paths. Customer-owned databases and self-service Discord onboarding remain
deferred. No live database migration or real provider call was performed by the agent.

### Evaluation

- A versioned, explicitly synthetic corpus contains 32 questions across GDG MCET
  and a synthetic technical organization. It covers overlapping terms, restricted
  budgets, absent evidence, earlier/current decisions and source prompt injection.
- The default CLI runs entirely offline. It generates reproducible 768-dimensional
  lexical hash vectors and compares vector-only ranking with a lexical/RRF reference.
- `--backend postgres` uses real pgvector cosine distance and PostgreSQL
  `websearch_to_tsquery` / `ts_rank_cd` with RRF in an isolated generated schema.
  It still uses fixture hash vectors, not live Gemini embeddings. pgvector must
  already be installed. Only the generated evaluation schema is created/dropped;
  application memory is never imported, queried or overwritten.
- Reports include Recall@k, HitRate@k, MRR, citation precision, abstention accuracy,
  expected-fact checks, per-stage latency, individual case failures and limitations.
- Token usage and dollar cost are unavailable in the deterministic baseline. They
  are not fabricated. Real query traces separately show actual provider usage.

Run from the repository root:

```powershell
backend\.venv\Scripts\python.exe scripts/run_eval_v2.py --report specs/reports/eval_v2_report.json
```

For an explicitly configured disposable test database:

```powershell
backend\.venv\Scripts\python.exe scripts/run_eval_v2.py --backend postgres --db-url-env THREAD_EVAL_DB_URL --report .tmp/postgres_eval.json
```

The saved offline report shows both strategies at Recall@4 = 1.0 and MRR = 1.0
on this small fixture corpus. Hybrid did not improve these measurements. Citation
precision is approximately 0.9231 and abstention accuracy 0.9375: both organizations'
missing pizza-order question elicited an unrelated approved-schedule fact. These
failures are retained in the report. This is not a production accuracy benchmark
or evidence that a real model is universally resistant to prompt injection.

### Execution traces

- Migration `022_v2_execution_traces.sql` adds durable conversation ownership and
  execution metadata to managed memory. No raw prompts, answers, source excerpts
  or hidden model reasoning are persisted in these trace rows.
- Actual routing, retrieval, evidence verification, synthesis, provider usage and
  output normalization stages are captured. A deterministic evidence check is
  labelled as such, not as an independent peer-agent consultation.
- Available PostgreSQL dense/lexical ranks and RRF scores are retained for cited
  evidence. Unsupported local scores display as unavailable rather than invented.
- Success, missing-evidence refusal and failed execution are recorded. Failed API
  requests return trace IDs in response headers so the UI can inspect the saved
  failure without a successful answer.
- If trace creation cannot reach managed storage, execution fails explicitly. If
  finalization fails after creation, the durable row remains `running`; the UI
  explains that it may be incomplete. An unavailable database cannot persist its
  own final failure record, so no such guarantee is made.
- Trace inspection requires current workspace membership and conversation ownership
  or owner/admin status. Evidence metadata is filtered again against the reader's
  current source scopes. Removed members are denied; demoted members cannot see
  previously internal evidence in their own traces.
- V2 conversational context keys include a permissions fingerprint. A role downgrade
  starts a fresh history window instead of reusing prior internal answers.
- Credential patterns, connection strings and configured server secrets are redacted.
  Source text remains untrusted data, and never authorizes backend tool execution.

Endpoints:

```text
GET /api/v2/organizations/{org_id}/traces/{trace_id}
GET /api/v2/organizations/{org_id}/conversations/{conversation_id}/traces
```

The frontend's **Inspect execution** dialog loads authorized persisted traces,
shows actual stages, timing, usage and available evidence scores, and handles
denied/unavailable traces. It is available in authenticated V2 workspaces; the
legacy public demo session does not gain account-administration API access.

## Deployment and verification

Review migration 022 and apply it to managed memory using the existing migration
runner. If service metadata uses a separate connection, trace payloads still use
the managed memory connection. Runtime never falls back to the service database
for trace data. The runner's complete migration sequence and backend RLS role
requirements remain documented in the earlier implementation notes.

Primary tests:

```powershell
backend\.venv\Scripts\python.exe -m pytest backend/tests/test_v2_security_isolation.py backend/tests/test_v2_execution_traces.py
```

The identity/BYOK fixtures also apply migration 022. An explicit disposable
`THREAD_TEST_SERVICE_DB_URL` enables their PostgreSQL variants, and
`THREAD_EVAL_DB_URL` enables the optional pgvector benchmark test. Otherwise those
checks are skipped, not represented as live verification.

The security suite checks the real retrieval boundary, conversation authorization,
source-scope changes, redaction, metric formulas, CLI artifacts and source-to-tool
separation. Mocked generation verifies application boundaries without claiming
that a particular live model always follows instructions.

Final selected verification: **89 passed, 41 skipped** across trace/security,
identity/BYOK, embedding/re-embedding, routing, session security, memory core,
migrations and triggering-message exclusion. Skips include opt-in PostgreSQL/live
checks; they are not passing live evidence. The frontend production build passed
with the existing large-bundle warning, and `git diff --check` passed.

Live PostgreSQL, real-provider generation and visual browser verification remain
pending. No connected browser surface was available in this session.
