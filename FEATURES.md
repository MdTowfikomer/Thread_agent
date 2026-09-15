# 🧵 Thread Agent — Complete System Features & Capabilities

> **Thread is an Organization-Agnostic Context Reconstruction & Multi-Agent Intelligence System.**  
> *Search retrieves. Memory stores. Thread reconstructs.*

---

## 📑 Table of Contents
1. [Core Philosophy & Architecture](#1-core-philosophy--architecture)
2. [Multi-Platform Channels & Integrations](#2-multi-platform-channels--integrations)
3. [Hybrid Intent Triage & Routing](#3-hybrid-intent-triage--routing)
4. [Two-Tier Persistent Memory System](#4-two-tier-persistent-memory-system)
5. [Security, Zero-Trust Permissions & ACLs](#5-security-zero-trust-permissions--acls)
6. [Cross-Platform Identity Resolution & Account Linking](#6-cross-platform-identity-resolution--account-linking)
7. [Community Convenience Tools](#7-community-convenience-tools)
8. [LangGraph Multi-Agent Team Pipeline](#8-langgraph-multi-agent-team-pipeline)
9. [Outbound Delivery Ledger & Reliability](#9-outbound-delivery-ledger--reliability)
10. [Database Schema & Migration Integrity](#10-database-schema--migration-integrity)
11. [Developer Experience & Test Infrastructure](#11-developer-experience--test-infrastructure)

---

## 1. Core Philosophy & Architecture

### ⚡ Context Reconstruction vs. Simple Chatbots
Traditional AI chatbots simply vectorize raw text snippets and query an LLM without understanding institutional relationships, historical chronology, access boundaries, or authority.

**Thread Agent solves institutional amnesia** by reconstructing context:
- **Who decided what?** Tracks author identity, roles, and timestamps across platforms.
- **Why was this path taken?** Connects scattered discussions across Slack, Discord, Telegram, and GitHub into coherent provenance trails.
- **What permissions apply?** Enforces strict Access Control Lists (ACLs) *before* vector candidate retrieval.
- **Zero Bluffing Guarantee**: If no authorized evidence exists in team records, the agent explicitly reports insufficient evidence rather than hallucinating answers.

### 🏛️ Multi-Tenant Workspace Model
- Fully organization-agnostic (`OrganizationWorkspace`).
- **GDG MCET** acts as the primary demonstration and production deployment tenant.
- Isolated role configs, channel policies, repository bindings, and database namespaces per tenant.

---

## 2. Multi-Platform Channels & Integrations

Thread Agent provides interactive, bi-directional connectivity across all major developer and community messaging platforms:

```
                  ┌─────────────────────────────────────────┐
                  │              THREAD AGENT               │
                  └────┬───────────────┬───────────────┬────┘
                       │               │               │
             ┌─────────▼──────┐ ┌──────▼──────┐ ┌──────▼──────┐
             │    Discord     │ │   Telegram   │ │    Slack     │
             │ Gateway / REST │ │   Webhooks   │ │ Events API │
             └────────────────┘ └──────────────┘ └────────────┘
```

### 🎮 Discord
- **Real-Time Gateway Worker Client**: Dedicated background WebSocket process (`python -m app.channels.run_gateway`) connected to Discord Gateway v10.
- **Interactive Mention Replies**: Responds instantly when `@mentioned` (`<@bot_id>`) or when users reply directly to previous bot messages.
- **Native Slash Commands**: `/ask-thread` interactive command endpoint.
- **Interaction Deadline Compliance**: Immediate Type 5 Deferred Channel Message (`DEFERRED_CHANNEL_MESSAGE_WITH_SOURCE`) returned within Discord's 3-second timeout, with asynchronous background patch to the follow-up webhook.
- **Ed25519 Cryptographic Verification**: Validates all incoming interaction HTTP request signatures.
- **Message Safety**: Automatic 1,950-character truncation protection to prevent Discord API payload rejection.
- **Typing Indicator**: Real-time typing status emitted during synthesis.

### ✈️ Telegram
- **Signed Inbound Webhook**: Authenticated via `X-Telegram-Bot-Api-Secret-Token`.
- **Flexible Mention Detection**: Triggers on Direct Messages (DMs), bot commands (`/ask`, `/events`, `/github`), `@GDGCThreadBot` mentions, and direct replies to bot messages.
- **Outbound HTTP Adapter**: Posts grounded answers and tool responses using the Telegram Bot API (`sendMessage`) with delivery tracking.

### 💬 Slack
- **Signed Events API Ingestion**: Authenticated using HMAC-SHA256 signatures (`X-Slack-Signature`, `X-Slack-Request-Timestamp`) with strict 300-second timestamp freshness.
- **Authoritative Channel Ingestion**: Ingests human conversations from bound public channels (`message.channels`).
- **Dedicated App Mentions**: Responds to `@Thread` queries in Slack channels and threads.
- **Canonical Message Deduplication**: Prevents duplicate ingestion when Slack dispatches both `message.channels` and `app_mention` events.
- **Thread Awareness**: Respects Slack thread timestamps (`thread_ts`) for focused in-thread discussion.

### 🐙 GitHub
- **Webhook Replay-Protected Ingestion**: Verifies HMAC-SHA256 signatures (`X-Hub-Signature-256`) and audits deliveries in `github_webhook_deliveries`.
- **Repository Bindings**: Server-owned table `github_repository_bindings` binding authoritative repositories (e.g. `MdTowfikomer/Thread_agent`) to organizational workspaces.
- **Granular Event Parsing**: Ingests commits, pull request lifecycles, issues, and review comments.

---

## 3. Hybrid Intent Triage & Routing

Thread Agent uses a deterministic hybrid intent classifier that separates requests into three distinct execution paths:

```
                            User Query
                                │
                      ┌─────────▼─────────┐
                      │ Intent Classifier │
                      └─────────┬─────────┘
                                │
        ┌───────────────────────┼───────────────────────┐
        │                       │                       │
┌───────▼───────┐       ┌───────▼───────┐       ┌───────▼───────┐
│     TOOL      │       │    GENERAL    │       │ORGANIZATIONAL │
│   EXECUTION   │       │   KNOWLEDGE   │       │     FACTS     │
├───────────────┤       ├───────────────┤       ├───────────────┤
│ • !events     │       │ • Greetings   │       │ • Vector RAG  │
│ • !faq        │       │ • Small talk  │       │ • Pre-ACL SQL │
│ • !github     │       │ • Tech Q&A    │       │ • Verified    │
│ • !summary    │       │ • Persona LLM │       │   Citations   │
│ • !link       │       │ • Multi-turn  │       │ • No-Bluffing │
└───────────────┘       └───────────────┘       └───────────────┘
```

1. **`TOOL_EXECUTION`**:
   - Triggers on commands (`!events`, `!faq`, `!summary`, `!github`, `!link`) or natural language inquiries ("when is the next workshop?", "show me the github repo").
   - Bypasses vector database retrieval entirely for sub-second responses.
   - Formats structured tool outputs directly for the invoking platform.

2. **`GENERAL_KNOWLEDGE`**:
   - Identifies conversational greetings, programming help, architectural advice, and dialogue.
   - Directly synthesizes a friendly, intelligent response using the assigned Role Agent persona and recent conversation history.
   - **No false "insufficient evidence" errors**: The agent converses naturally without demanding organizational citations for general discussion.

3. **`ORGANIZATIONAL_FACTS`**:
   - Queries concerning decisions, budgets, DevFest, meeting minutes, internal policies, or team history.
   - Strictly executes hybrid pgvector + full-text search with pre-retrieval ACL filtering.
   - Backed by immutable evidence citations and no-bluffing verification.

---

## 4. Two-Tier Persistent Memory System

Thread Agent operates with two levels of persistent memory:

### Tier 1: Sliding-Window Multi-Turn Conversation Turns
- **Durable Storage**: Backed by the `conversation_turns` PostgreSQL table with composite index `(session_key, created_at DESC)`.
- **Deterministic Session Keys**: `{platform}:{channel_id}:{user_id_or_thread}`
- **Dual-Layer Caching**: In-memory LRU cache ensures instant context access even during database reconnection spikes.
- **Sliding Window**: Injects the last 10 conversation turns into LLM context, allowing users to ask follow-up questions ("What was the first thing I asked you?", "Elaborate on that last event").

### Tier 2: Long-Term Hybrid Vector & Full-Text Search (RAG)
- **Dense Vector Search**: PostgreSQL `pgvector` with 768-dimensional embeddings generated via Gemini 2.5 (`text-embedding-004`) or OpenAI.
- **Sparse Lexical Search**: Native PostgreSQL Full-Text Search (`tsvector`) matching specific codes, IDs, usernames, and acronyms.
- **Reciprocal Rank Fusion (RRF)**: Implemented in SQL RPC `hybrid_search` to merge dense semantic similarity and sparse keyword scores into a single ranked candidate pool.

---

## 5. Security, Zero-Trust Permissions & ACLs

Thread Agent is built on zero-trust principles:

| Layer | Guarantee | Enforcement Mechanism |
| :--- | :--- | :--- |
| **Identity** | No spoofing via untrusted payloads | Identity resolved from cryptographically verified bearer tokens or signed webhook payloads. |
| **Pre-Retrieval ACL** | Zero data leakage in vector search | ACLs evaluated directly inside PostgreSQL SQL queries *before* candidate scoring. |
| **Destination ACL** | Confidential data never posted to public | Channel policy store checks evidence permission against destination scope (`PUBLIC_COMMUNITY` vs `INTERNAL_CORE`). |
| **Quarantine** | Unverified imports cannot leak | New/external imports enter `PENDING_REVIEW` quarantine; can only be promoted via signed admin RPC. |
| **Database RLS** | Zero direct table access | Row Level Security (RLS) enabled on all tables; restricted to `service_role`. |
| **Replay Protection** | Prevent webhook replay attacks | Idempotent delivery ledgers (`webhook_deliveries`, `processed_interactions`). |

---

## 6. Cross-Platform Identity Resolution & Account Linking

### 👤 Unified Canonical Person Mapping
- External identifiers (Discord snowflake `15491...`, Telegram chat `5865...`, Slack ID `U0C...`) are mapped to an internal immutable `person_id`.
- **Strict Anti-Spoofing Rule**: Never automatically merges accounts based solely on matching usernames or display names. An unlinked user with a name matching an organizer receives an isolated public identity.

### 🔗 Self-Service Linking (`!link`)
Community members can link their accounts across platforms in seconds:
1. Run `!link` on Discord/Slack/Telegram $\rightarrow$ receives temporary token (`LINK-XXXXXX`, valid 30 min).
2. Run `!link <TOKEN>` on another platform $\rightarrow$ accounts are merged under the same canonical `person_id`.
3. Memory, authorized access scopes, and roles synchronize immediately across both platforms.

---

## 7. Community Convenience Tools

Thread Agent includes built-in community utility tools callable via commands or natural language:

### 📅 Event Assistant (`!events`)
- **Database**: Table `community_events`.
- **Capabilities**:
  - Lists upcoming workshops, hackathons, and speaker sessions in chronological order.
  - Formats event titles, schedules in UTC, physical/virtual venues, speaker rosters, and direct RSVP links.
  - Allows organizers to add new scheduled events.

### 📚 Resource & FAQ Assistant (`!faq`, `!resources [keyword]`)
- **Database**: Table `community_resources`.
- **Capabilities**:
  - Fast search over community guidelines, discord rules, tutorials, and setup guides.
  - Filters by category (`Contribution`, `Community`, `AI & Learning`, `FAQ`).
  - Returns markdown cards with descriptions and official documentation URLs.

### 📝 Channel Summarizer (`!summary`)
- **Capabilities**:
  - Analyzes the recent conversation history in the channel/thread.
  - Produces an executive structured summary:
    - 📌 **Main Topics Discussed**
    - 💡 **Key Decisions & Takeaways**
    - 🚀 **Next Steps & Action Items**
  - Uses LLM synthesis when online, with deterministic fallback.

### 🐙 GitHub Helper (`!github`)
- **Database**: Table `github_repository_bindings`.
- **Capabilities**:
  - Returns the official repository link (`MdTowfikomer/Thread_agent`).
  - Provides a 5-step open-source contribution walkthrough:
    `git clone` $\rightarrow$ `git checkout -b` $\rightarrow$ `.venv setup` $\rightarrow$ `pytest` $\rightarrow$ `PR`.

### 🔗 Account Link Tool (`!link [token]`)
- **Database**: Table `account_link_tokens`.
- **Capabilities**:
  - Generates secure, single-use 30-minute linking codes.
  - Validates and redeems tokens across disparate chat platforms.

---

## 8. LangGraph Multi-Agent Team Pipeline

Queries flow through a stateful multi-agent DAG compiled with LangGraph:

```
[Entry: triage] ──► [retrieval] ──► [role_agent] ──► [synthesis] ──► [END]
```

### Specialized GDG MCET Role Personas
Each role agent brings domain expertise, behavioral tone, and context:

1. **Arjun Sharma — Lead Organizer (`organizer_lead`)**
   - *Domain*: Event planning, speaker relations, college permissions, DevFest schedules, venue approvals.
   - *Style*: Strategic, community-first, organized, authoritative.

2. **Priya Ramesh — Tech Lead (`tech_lead`)**
   - *Domain*: GenAI workshops, cloud labs, GitHub repositories, codelabs, tech stack, mentorship.
   - *Style*: Technical, precise, hands-on, code-oriented.

3. **Karthik Verma — Sponsorship & Finance Lead (`sponsorship_lead`)**
   - *Domain*: Budgeting, swag vendor procurement, pitch decks, reimbursements, catering costs.
   - *Style*: Pragmatic, metrics-driven, guarded with internal figures.

4. **Sneha Nair — Community & PR Lead (`community_lead`)**
   - *Domain*: Social media, RSVP tracking, volunteer onboarding, certificates, student FAQ.
   - *Style*: Warm, engaging, transparent, student-centric.

---

## 9. Outbound Delivery Ledger & Reliability

Outbound messaging is backed by a transactional audit ledger (`outbound_message_deliveries`):

- **Scoped Idempotency Keys**: Keys are hashed deterministically:
  $$\text{SHA-256}(\text{org\_id} : \text{user\_id} : \text{platform} : \text{destination\_id} : \text{raw\_key})$$
- **Delivery Lifecycle State Machine**:
  - `processing`: Lease acquired; outbound send in flight.
  - `sent`: Successfully delivered; provider message ID recorded.
  - `failed`: Provider error; eligible for controlled retry.
  - `unknown`: Ambiguous provider timeout; automatic re-post blocked to prevent duplicate channel spam.
- **Provider Resilience**: Exponential backoff and retry for transient network drops (429, 500, 502, 503, 504).

---

## 10. Database Schema & Migration Integrity

All database changes are tracked and enforced via Python migrator (`app.data.migrator`):

- **Advisory Locks**: PostgreSQL session-level locks (`849201847192`) prevent concurrent deployment race conditions.
- **Historical Manifest (`manifest.json`)**: Immutable SHA-256 hashes of all applied migrations (001 through 015). Any retroactive tampering raises `SchemaDriftError`.

### Core Tables Summary
| Table | Description |
| :--- | :--- |
| `source_records` | Authoritative source messages and documents with provenance hashes. |
| `memory_chunks` | Chunked text embeddings (768-dim) with ACL permissions. |
| `conversation_turns` | Multi-turn session history for continuous chat context. |
| `community_events` | Structured events schedule, speaker lists, and RSVP links. |
| `community_resources` | Curated documentation, rules, and FAQ database. |
| `account_link_tokens` | Single-use cross-platform identity linking tokens. |
| `channel_account_links` | Immutable mappings between external accounts and canonical persons. |
| `outbound_message_deliveries` | Audit ledger tracking sent, duplicate, and timeout states. |
| `github_repository_bindings` | Server-owned organization repository bindings. |
| `telegram_chat_bindings` | Server-owned authorized Telegram chats. |
| `slack_workspace_bindings` | Server-owned authorized Slack teams and channels. |
| `import_approvals` | Audit trail for promoting quarantined chunks to internal core. |

---

## 11. Developer Experience & Test Infrastructure

- **Zero-Latency Test Suite**: Deterministic mock synthesis toggle (`THREAD_FORCE_DETERMINISTIC_SYNTHESIS=1`) allows the entire test suite to execute in under 4 seconds without external network dependencies.
- **Test Coverage**: 139 automated tests covering:
  - Memory core, pgvector retrieval, and pre-retrieval ACLs.
  - Discord Gateway mention replies, slash commands, and Ed25519 authentication.
  - Telegram webhook ingestion, mention parsing, and outbound delivery.
  - Slack Events API ingestion, channel deduplication, and app mentions.
  - Cross-platform identity resolution, token generation, and redemption.
  - Community tools (`!events`, `!faq`, `!github`, `!summary`, `!link`).
  - Outbound idempotency, destination permission checking, and delivery ledger states.
