# Latency and visible progress

Implementation date: 2026-10-30. Runtime commit: `eae26ae`.

## What changed

Database access on the request path now uses bounded, process-local PostgreSQL
connection pools. Connections are leased per transaction, cursors are closed,
unfinished transactions are rolled back, and broken connections are discarded.
Different database URLs and connection options use separate pools. Membership,
session validity, workspace configuration and credential revision checks still
read current database state. Credentials and authorization decisions are not cached.
The Discord leader's dedicated advisory-lock connection remains outside the pool.

Synchronous chat work runs in a worker thread. Telegram model execution and Slack
background model execution also run off the API event loop. Discord's existing
worker-thread path remains in use.

Native Discord, Telegram and Slack responses now post a short status before model
execution, followed by the answer as a separate message. Local templates choose
phrases such as “Checking records…” or “Checking repository activity…”. A real
synthesis milestone can produce one additional status, with at most two progress
posts per request. Progress uses the same destination authorization and delivery
ledger as answers, with separate idempotency keys and no source evidence. Generic
progress delivery failures allow the query to continue; permission failures stop it.
Progress is not stored as a conversation turn or a source record.

The web activity component uses compact expandable rows, with actual tools counted
as tool calls. Pipeline stages are labeled as response activity. The UI starts a
loading state immediately, preserves tool input as completion events arrive, and
marks unfinished stages as interrupted on stream failure. Tool completion events
are emitted after execution. Synthesis/finalization events complete explicitly.
Streaming model usage is captured in a separate context for each generator step,
so SSE threadpool resumptions do not retain a ContextVar token across yields.

Complete greetings and explicit self-introduction requests use shared local
responses across streaming web chat and native channels. The first greeting
introduces ThreadAgent and the workspace; subsequent greetings stay short.
An explicit “introduce yourself” request gets an introduction even after earlier
turns. These paths do not generate a model response. They still require the normal
session, tenant and configured-credential checks. A greeting followed by an
organizational question retains evidence retrieval rather than matching this path.

## Why a second LLM is unnecessary for status messages

Status text describes known execution state. Local templates add no model tokens,
provider dependency or inference request. A second LLM could polish wording but
would add a network request and another failure/rate-limit path. It would not make
the main answer finish sooner. Groq is a provider distinct from xAI's Grok; adding
it as an optional answer provider would be a separate BYOK feature.

## Benchmark method

The comparison uses the deployed Render SSE endpoint from the same client. Each
run creates a temporary member and an opaque session in the existing demo
workspace, uses that workspace's configured model, and removes that member's
session, conversations, turns and traces afterward. Existing users, credentials
and source records are preserved. No messages are posted to connected platforms.

Two sequential samples are taken for each query:

- General: “What is a mutex? Answer in one short sentence.”
- Grounded: “When is the Aurora review? Answer in one short sentence.”

Timings start before the HTTP request. First event is the first received SSE
event; first token is the first received answer token; complete is the terminal
response after persistence. Post-token time measures last token to terminal
completion. The service is warmed with a health check first. Two samples provide
an initial comparison, not a p95, concurrency benchmark or latency guarantee.
Provider variation, network location and response length can affect the results.
The grounded response must contain the known Monday/11 AM fact and citations.
Raw answers, session tokens and API keys are excluded from saved timing reports.

## Measured results

Median seconds, two samples per case per version:

| Request | Metric | Before | After | Reduction |
| --- | --- | ---: | ---: | ---: |
| General | First SSE event | 6.07s | 2.46s | 59.5% |
| General | First answer token | 13.48s | 9.42s | 30.1% |
| General | Complete response | 18.17s | 11.03s | 39.3% |
| General | After last token | 4.62s | 1.58s | 65.8% |
| Grounded | First SSE event | 6.04s | 2.38s | 60.5% |
| Grounded | First answer token | 16.41s | 8.89s | 45.8% |
| Grounded | Complete response | 21.26s | 10.77s | 49.3% |
| Grounded | After last token | 4.80s | 1.78s | 63.0% |

Both grounded samples retained the expected fact and four citations. Both runs
cleaned up their temporary accounts and associated data. General completion
samples after deployment ranged from 7.44s to 14.63s, which illustrates why this
small sample cannot establish a latency guarantee. The first post-deployment
general request was slower than the second; this run does not isolate the cause.

The runtime comparison is `718f51c` versus `eae26ae`. The Vercel asset served after
deployment matched the verified local production bundle byte for byte. Timing
evidence is saved in [the sanitized benchmark report](benchmarks/latency-2026-10-30.json).

## Controls and limits

- `THREAD_DB_POOL_ENABLED=true` by default; set to `false` to disable pooling.
- `THREAD_DB_POOL_MAX_CONNECTIONS=4` by default, per URL/options/process pool,
  bounded to 1–16. Account for all processes when sizing database connections.
- `THREAD_DB_POOL_WAIT_SECONDS=5` bounds checkout waiting, within 0.01–30 seconds.
- Connections use a five-second connect timeout, ten-second statement timeout
  and five-second lock timeout by default.
- `THREAD_PROGRESS_ENABLED=true` by default; set to `false` to disable native
  status posts. Status delivery adds platform/database work; its real platform
  timing is not measured by the web benchmark.
- This change does not measure or eliminate Render free-instance cold starts.

## Verification and deployment

The focused backend gate passed 142 checks; 40 database-dependent variants were
skipped because a disposable PostgreSQL test database was not configured. This
includes session/membership/BYOK isolation, trace authorization, pool exhaustion,
pool cleanup, separate database boundaries, native destination scoping, tool event
ordering, stream errors and usage collection across separate SSE contexts.
The frontend production build and pending/tool/retrieval/failure markup checks
passed. Browser appearance and native end-to-end timing still require live QA.

Render and Vercel deploy from the GitHub main branch. The separate Bot-Hosting
Discord worker requires its runtime archive to be uploaded and extracted beside
`main.py`, followed by a restart. Preserve its existing environment configuration.
No new provider key, database migration or backend URL is needed for this change.
