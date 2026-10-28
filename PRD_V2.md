# Thread Agent V2: Multi-tenant Organizational Memory Demo

Status: Active demo pillars implemented and selected offline checks passed. Live verification gaps and fixture evaluation failures remain documented.

Date: 2026-10-27

## Demo scope revision — 2026-10-28

The user deferred customer-owned databases (V2-03) and self-service Discord onboarding
(V2-04). The active demo uses Thread-managed PostgreSQL/pgvector and the existing
Discord installation and bindings. V2-01, V2-02, V2-05 and V2-06 are the required
pillars. The original future designs remain below for later implementation; they
are not demo acceptance gates. Continue from Phase 2 directly to original Phase 5
(evaluations and traces), retaining ticket numbers for continuity.

## 1. Purpose

Evolve Thread Agent from a GDG MCET demonstration into a configurable organizational memory product. A second organization must be able to create a workspace without code changes, connect its own model API key, and receive evidence-backed answers using managed PostgreSQL storage while remaining isolated from other organizations. The demo retains the existing Discord installation; self-service installation and customer-owned storage are future scope.

V2 is an AI engineer portfolio demonstration. It must demonstrate working integrations, retrieval quality, security boundaries, and observable execution. It does not need the full commercial infrastructure of a production SaaS.

Product positioning:

> Connect your team's tools. Bring your own AI key. Ask Thread for answers grounded in your organization's knowledge.

## 2. Problem and target users

Organizational decisions and supporting evidence are scattered across conversations and repositories. Knowledge disappears during leadership changes, and a new organization currently cannot adopt Thread without developer configuration.

The initial users are developer communities and small technical teams. The data model should support different organizations without introducing industry-specific code.

| User | Primary need |
| --- | --- |
| Organization owner | Create a workspace, configure credentials and storage, and manage membership |
| Administrator | Connect sources, select channels, configure access, and diagnose synchronization problems |
| Member | Ask questions and inspect evidence they are authorized to access |
| Portfolio reviewer | Verify the architecture, measured retrieval behavior, and tenant isolation |

## 3. Existing foundation and gaps

The repository already includes organization identifiers in memory records, conversations, and connector bindings; hybrid retrieval; citations; a LangGraph workflow; multiple messaging connectors; and a trace-oriented frontend. These are reusable foundations, not proof of complete tenant isolation.

Identified gaps from the initial code inspection:

- `backend/app/core/organizations.py` holds a static MCET workspace and falls back to it for unknown IDs.
- `backend/app/core/domains.py` contains a second static configuration registry.
- `backend/app/core/membership.py` initializes predefined members and maintains authoritative memberships in process memory.
- Authentication, conversation handling, and frontend screens contain MCET/demo defaults.
- Workflow routing includes community keywords and fixed role IDs.
- Connector bindings exist, but installation, source selection, and operational status need a self-service product flow.
- Database access and some provider credentials use global configuration and need an organization-aware boundary.

The implementation plan must verify these observations and identify all affected paths before changing behavior.

## 4. Scope and priorities

Four pillars are required for the demo; two are retained as future scope.

| ID | Pillar | Required outcome |
| --- | --- | --- |
| V2-01 | Workspaces and membership | Persistent organizations, real accounts, authorized workspace switching, and member administration |
| V2-02 | Bring your own key | One supported model provider, encrypted credentials, validation, and replacement/deletion |
| V2-03 | Memory storage selection — deferred | Customer-owned PostgreSQL is future scope; the demo uses managed storage |
| V2-04 | Self-service Discord — deferred | Future installation UX; the demo retains existing server/channel bindings |
| V2-05 | Evaluation | Versioned questions, reproducible measurements, and isolation/security regression checks |
| V2-06 | Execution visibility | Authorized evidence, routing, model usage, latency, and failure traces |

Existing Slack, Telegram, and GitHub functionality should retain relevant regression coverage. Their self-service onboarding is outside the V2 acceptance gate.

## 5. Primary user journeys

### Journey A: Create and configure an organization

1. A user signs up or signs in.
2. They create a workspace with a name and description and become its owner.
3. They configure the assistant and invite a teammate.
4. They add a model API key and validate it.
5. Their workspace uses Thread-managed memory; no database connection form is required.

### Journey B: Connect knowledge and ask a question

1. The demo operator uses the existing authorized Discord installation and configured channel policies.
2. Installation-to-workspace bindings remain server-owned; a second web workspace does not inherit the demo server's sources.
3. Synthetic test-workspace content is loaded through a documented import or evaluation fixture workflow.
4. Existing ingestion and delivery behavior is demonstrated without claiming new self-service onboarding.
5. A member asks a question through the web app or linked Discord server.
6. Thread retrieves authorized evidence and returns a grounded answer with citations.

### Journey C: Verify boundaries and recover from failure

1. A user switches to another organization they belong to.
2. The assistant uses that organization's configuration, credentials, memory, and permissions.
3. An unauthorized user is denied access to another organization's records and traces.
4. An unavailable managed database or invalid model key produces an actionable error.
5. An administrator repairs the connection and retries without duplicate ingestion or unintended duplicate replies.

## 6. Functional requirements and acceptance criteria

### V2-01: Workspaces, identity, and assistant configuration

Requirements:

- Persist users, organizations, memberships, invitations, and assistant configuration.
- Support owner, administrator, and member application roles.
- Support one user belonging to multiple organizations.
- Revalidate membership server-side when accessing a workspace or performing privileged actions.
- Keep application administration roles separate from source access permissions and agent specializations.
- Provide a general organizational assistant by default; configured specialists are optional.
- Retain MCET as an explicitly provisioned demo workspace.
- Unknown or missing organization identifiers must never select MCET implicitly.

Acceptance:

- Given a signed-in user, creating a workspace succeeds without a deployment or source-code edit.
- Workspace configuration and membership survive service restarts.
- A user belonging to two organizations can switch between them and see the correct configuration and data.
- An unrelated or removed member cannot access private workspace records or settings on subsequent requests.
- An unknown organization returns an explicit error and no other workspace's configuration.

### V2-02: Bring your own model API key

Requirements:

- Support one provider and a small documented model selection initially; choose the provider during planning.
- Store keys encrypted on the backend and restrict configuration changes to authorized administrators.
- Provide validation, replacement, deletion, and masked connection status.
- Never return stored secrets to clients or include them in logs, traces, exports, or evaluation artifacts.
- Resolve model credentials from the verified organization context.
- Declare the embedding provider/model/dimensions separately from the answer-generation model.
- Track token usage and identify whether usage/cost values are provider-reported or estimated.

Acceptance:

- Two organizations can use distinct credentials without changing global environment variables.
- Invalid or revoked keys produce a useful error and are not silently replaced with another organization's or the service's key.
- Replacing or deleting a key affects subsequent model calls, including worker execution.
- Saving a new answer-generation model does not silently change the embedding configuration.

### V2-03: Managed and customer-owned memory — deferred future design

Requirements:

- Managed mode uses Thread-operated PostgreSQL with organization-scoped records.
- Customer-owned mode supports a dedicated PostgreSQL database or schema using Thread's schema and pgvector; arbitrary existing schemas are unsupported.
- Validate connectivity, TLS policy, supported database capabilities, and required extension availability.
- Show required schema changes before an authorized administrator initializes or upgrades tables.
- Track schema versions and surface incompatible or incomplete setup.
- Encrypt connection credentials and support rotation.
- Reject database connection targets that could expose internal infrastructure; validate destinations and constrain network access.
- Resolve storage once from trusted organization configuration and propagate it through imports, workers, retrieval, citations, and conversation operations.
- Never silently fall back to managed storage when customer-owned storage fails.
- Use explicit embedding configuration compatibility checks; model/dimension changes require a controlled reindexing path or are blocked in V2.

Data ownership boundary:

| Thread service database | Selected memory database |
| --- | --- |
| Users, organizations, memberships, invitations, encrypted credential references, installation routing, and operational job status | Source records, chunks, embeddings, provenance, source access metadata, conversations, and persisted answer/evidence history |

Service operational records must avoid storing source text, answers, secrets, or other memory payloads. The implementation plan must explicitly classify remaining audit and trace fields against this boundary.

Customer-owned storage does not imply customer-only processing. Hosted Thread processes data, and relevant content is sent to the configured model provider. Explain this in setup and documentation. Customer administrators remain responsible for their database hosting and backups.

Acceptance:

- A second organization connects a genuinely separate database through the UI.
- A new source record and its embedding appear in that database and are used for a cited answer.
- Memory payloads are not duplicated into the managed memory database.
- Disconnecting that database causes an actionable failure with no writes or retrieval against another destination.
- Invalid schema, incompatible embeddings, and prohibited connection targets fail clearly.

Initial scope: choose storage before importing data. Moving populated workspaces between storage destinations is deferred; do not expose an unsafe storage toggle.

### V2-04: Self-service Discord integration — deferred future design

Requirements:

- Use an authorization flow that verifies both Thread workspace administration rights and Discord installation authority.
- Persist the installation-to-organization binding server-side; never trust a caller-supplied organization identifier alone.
- Select channels and explicitly assign supported access settings.
- Provide bounded historical import and ongoing ingestion with documented limits.
- Show connection, synchronization, last-success, and failure status.
- Persist job progress and deduplicate retried events and imports.
- Support disconnecting a source and an explicit delete-imported-data action.
- Handle observed source edits/deletions and permission changes; disable affected retrieval when access cannot be established safely.
- Check the answer destination as well as the requesting user's access before sending evidence into a channel.

Acceptance:

- A new organization's administrator connects a Discord server without editing environment variables, copying internal IDs, or using a backend CLI.
- Only selected channels are imported, and repeated ingestion does not duplicate a source record.
- Web and Discord answers cite authorized evidence from the same selected memory destination.
- Internal evidence is never posted into a public channel, including when an administrator asks the question.
- Disconnecting stops future synchronization; deleting imported data removes its retrievable chunks and vectors.
- An ambiguous outbound timeout is surfaced without blindly resending a potentially delivered message.

Permission scope for V2: explicitly configured public/internal channels. Arbitrary per-user source permission mirroring is deferred. Unsupported channel types must be excluded rather than treated as public. Public means the configured audience within that organization; anonymous MCET demo access must remain explicitly scoped.

### V2-05: Evaluation and regression evidence

Requirements:

- Maintain a versioned dataset with at least 30 questions across two organizations, expected evidence, access context, and answer expectations.
- Include answerable questions, missing evidence, overlapping terminology across tenants, restricted content, changed decisions, and ingested prompt injection attempts.
- Compare vector-only and hybrid retrieval using the same corpus, questions, embedding configuration, and retrieval limits.
- Report Recall@k and MRR where gold evidence exists, citation correctness, answer support, abstention behavior, latency, and model usage.
- Document scoring methods, manual judgments, model-based judging where used, and dataset limitations.
- Keep credential-dependent live evaluations separate from repeatable offline regression checks.

Acceptance:

- One documented command produces a report with configuration, dataset version, aggregate results, and failures.
- Tenant, source-permission, destination-permission, and secret-exposure checks have zero violations in the defined suite.
- Retrieval and answer-quality results are measured and reported honestly; improvements are never assumed.
- Prompt-injection fixtures cannot override authorization or authorize tools through source text.
- Changed-decision questions cite temporal evidence and acknowledge unresolved conflicts rather than inventing certainty.

Quality thresholds beyond mandatory isolation gates will be selected from the measured baseline during implementation planning/evaluation, with a documented rationale.

### V2-06: Observable execution

Requirements:

- Extend the existing trace experience with routing, tools, authorized retrieved evidence and scores, source timestamps, model identity, stage latency, usage, and error status.
- Scope trace access to organization and conversation ownership or explicit sharing rules.
- Explain insufficient evidence and filtered results without disclosing inaccessible titles, source text, or identifiers.
- Record structured execution metadata; do not expose hidden model reasoning.
- Mark unavailable provider usage and estimated cost clearly.

Acceptance:

- A reviewer can follow a successful question from routing through retrieval to final citations.
- Failed provider, database, and ingestion operations have a visible stage and actionable status.
- Trace endpoints and the UI pass the same organization and permission checks as answers and source inspection.

## 7. Non-functional requirements

- Durable configuration and job state must survive restarts; process memory is not the authoritative store for memberships or installations.
- Missing authorization or unavailable access configuration must deny access rather than select a permissive default.
- Use bounded imports, configurable timeouts, per-organization request limits, and explicit provider rate-limit handling.
- Capture latency and failures on a documented demo corpus and environment; avoid unsupported uptime or performance claims.
- Keep secrets outside source control and redact them from all diagnostics.
- Provide setup, migration, evaluation, and demo instructions that another engineer can follow.
- Keep repository changes incremental and preserve relevant existing connector and retrieval regression coverage.

## 8. Minimum data concepts

- User, organization, membership, invitation, and application role.
- Organization assistant configuration and tool capabilities.
- Model credential reference and embedding configuration.
- Memory destination and schema version.
- Platform installation, selected source/channel, and source access policy.
- Ingestion job, synchronization checkpoint, source record, and memory chunk.
- Conversation, turn, evidence reference, and execution trace.
- Usage record and evaluation dataset/run.

Tenant-owned entities require explicit organization association. Foreign keys, uniqueness constraints, caches, and idempotency keys must preserve the relevant tenant and installation boundaries.

## 9. Out of scope

- Billing, subscriptions, pricing pages, and payment collection.
- Customer-owned database connection/setup and storage switching (deferred V2-03).
- Self-service Discord installation and channel-configuration UX (deferred V2-04).
- Enterprise SSO/SCIM and compliance certifications.
- Every model provider or arbitrary model compatibility.
- Self-service onboarding for every existing connector.
- Arbitrary database engines or customer table layouts.
- Seamless migration of populated memory between storage destinations.
- Full self-hosted packaging or a claim that hosted processing stays inside customer infrastructure.
- Complete per-user permission mirroring for all external platforms.
- Automatic discovery of an organization's entire structure or employee impersonation.
- Large-scale ingestion and production enterprise availability guarantees.

## 10. Milestones and exit evidence

| Milestone | Outcome | Exit evidence |
| --- | --- | --- |
| M1: Tenant foundation | Persistent identity, membership, configuration, and strict organization resolution | Two organizations survive restart; authorized switching works; cross-tenant requests fail |
| M2: Provider configuration | Organization-scoped BYOK and explicit embedding configuration | Distinct validated credentials, safe error behavior, and redacted diagnostics |
| M3: Storage boundary — deferred | Future customer-owned memory paths | Outside the active demo gate |
| M4: Connector onboarding — deferred | Future self-service Discord installation | Existing configured Discord is sufficient for this demo |
| M5: Evaluation and demonstration | Reproducible report and inspectable execution | Recorded walkthrough, measured baseline comparison, passing isolation suite, and updated docs |

Evaluation fixtures and security regression checks start in M1 and expand throughout. These milestones define delivery outcomes; the implementation plan will define migrations, components, tasks, and exact dependency order.

## 11. Demo script and definition of done

Use synthetic or explicitly authorized demonstration content and disposable credentials. Do not reveal API keys or database connection strings in recordings.

1. Show the existing MCET demo as an explicitly identified workspace.
2. Create a second organization without code edits.
3. Add and validate its own model key.
4. Load authorized synthetic content into the second workspace's managed memory through the documented fixture/import workflow.
5. Show the existing Discord connection and its explicitly configured source/destination scopes.
6. Ask an organizational question in the web workspace and another in the existing Discord-bound workspace; inspect citations and traces.
7. Show managed source records, embeddings and tenant-scoped evidence. Do not present managed storage as customer-owned.
8. Switch organizations and demonstrate isolation with overlapping subject matter.
9. Demonstrate a restricted-source request and an insufficient-evidence response.
10. Show controlled behavior for an invalid key or unavailable database.
11. Present the reproducible evaluation report, including failures and limitations.

The demo is complete when V2-01, V2-02, V2-05 and V2-06 satisfy their applicable acceptance criteria, relevant existing checks pass, the walkthrough is repeatable, and no tenant-isolation or secret-exposure failures remain in the defined suite. V2-03 and V2-04 do not block this demo. Existing source/destination permission controls remain required.

## 12. Decisions for implementation planning

Resolve these through code inspection and a concrete technical proposal before implementation:

- Authentication provider and invitation/session design.
- First supported model provider and embedding ownership/configuration.
- Canonical workspace configuration model replacing duplicate static registries.
- Database credential encryption, destination validation, pooling, and migration permissions.
- Exact audit/trace placement under the stated storage ownership boundary.
- Discord authorization, supported channel types, historical import limits, and permission-change handling.
- Worker execution, durable job storage, retry semantics, and operational limits.
- Evaluation fixtures, reproducible commands, baseline measurements, and quality gates.

The existing `CURRENT_MILESTONE.md` describes earlier Slack integration work. This PRD records the requested V2 scope without claiming that earlier live proof is complete or changing its implementation status. Reconcile milestone tracking explicitly when preparing the V2 implementation plan.
