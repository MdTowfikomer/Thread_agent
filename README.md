# 🧵 Thread Agent: AI Organizational Context & Multi-Platform Intelligence

> **"Thread is not a chatbot with a vector database. Thread is a context reconstruction system."**  
> *Search retrieves. Memory stores. Thread reconstructs.*  
>  
> **Thread connects the scattered knowledge of an organization and reconstructs the context behind its work — across Discord, Telegram, Slack, GitHub, documents, people, projects, and decisions.**  
>  
> 🌐 **Live Web App**: [thread-agent-xi.vercel.app](https://thread-agent-xi.vercel.app)  
> 📺 **Demo Video**: [YouTube Walkthrough (8 mins)](https://youtu.be/rPY4Qk7pzkg) *(Features live web app, multi-platform bots, and PostgreSQL pgvector database)*  
> 📝 **Medium Article**: [Why Naive RAG Fails at Organizational Memory](https://medium.com/@mdtowfikomer/why-naive-rag-fails-at-organizational-memory-and-how-we-built-a-context-reconstruction-agent-4cbb0c69a378)  
> 🏢 **Demonstration Environment**: GDG MCET Organization Workspace

---

## 🎬 Demo Video, Live Walkthrough & Article

> 📺 **Watch Full Video Demo**: **[https://youtu.be/rPY4Qk7pzkg](https://youtu.be/rPY4Qk7pzkg)**  
> 📝 **Read the Medium Article**: **[Why Naive RAG Fails at Organizational Memory](https://medium.com/@mdtowfikomer/why-naive-rag-fails-at-organizational-memory-and-how-we-built-a-context-reconstruction-agent-4cbb0c69a378)**  
> 
> *The video & article demonstrate:*
> 1. **Live Web Dashboard** on Vercel with real-time agent state indicators and source citation inspection.
> 2. **Multi-Channel Integrations**: Interactive queries across Discord and Telegram bots.
> 3. **PostgreSQL & Supabase Database**: Live demonstration of PostgreSQL tables, `pgvector` embeddings (`vector(768)`), pre-retrieval ACL SQL filters, and audit logs.

---

## ⚡ Why Context Reconstruction Matters

Developer communities and fast-moving teams suffer from **institutional amnesia**:
- **Lost Context**: When core leads graduate or team members step down, vital context—past sponsor agreements, speaker rolodexes, workshop codelab repos, and venue approvals—vanishes into disconnected Discord/Telegram channels and forgotten Google Drive folders.
- **Static Wikis**: Traditional wikis (Notion, Drive) are static cemeteries that nobody maintains or reads.
- **Naïve RAG**: Traditional vector chatbots simply retrieve disjointed text snippets without understanding *who decided what*, *why a path was taken*, or *what security permissions apply*.

### How Thread Solves This
- **Multi-Platform Ingestion**: Ingests real-time events, discussions, and documents from **Discord, Telegram, Slack, GitHub, Google Drive, Notion**, and local files into a normalized **Canonical Context Schema**.
- **Pre-Retrieval ACL Enforcement**: Security permissions (`PUBLIC_COMMUNITY` vs `INTERNAL_CORE`) are strictly enforced **before vector retrieval**, guaranteeing zero data leakage to unauthorized members.
- **Deterministic & Agentic Pipeline**: Queries flow through a **LangGraph Multi-Agent Engine** with triage routing, role-based specialization, peer consultation, and evidence-backed synthesis.
- **Multi-Channel Delivery**: Responds seamlessly across **Web Dashboard**, **Discord Bot Gateway**, **Telegram Bot Webhook**, and **Slack Integration** with platform-native text coercion and markdown formatting.

---

## 🏛️ System Architecture

```
                                  THREAD AGENT
                                       │
                  ┌────────────────────┼────────────────────┐
                  │                    │                    │
              🌐 Web App          🤖 Discord Bot      💬 Telegram / Slack
         (React 19 + Vercel)     (Gateway Bot)          (Webhooks)
                  │                    │                    │
                  └────────────────────┼────────────────────┘
                                       │
                                Universal API
                                       │
                               ┌───────▼───────┐
                               │ Pre-Retrieval │
                               │  ACL & Scopes │
                               └───────┬───────┘
                                       │
                               LangGraph Engine
                                       │
                               ┌───────▼───────┐
                               │ Triage Router │
                               └───────┬───────┘
                                       │
                    ┌──────────────────┼──────────────────┐
                    │                  │                  │
               Role Agent          Role Agent         Role Agent
               (Organizer)         (Tech Lead)       (Sponsorship)
                    │                  │                  │
                    └──────────────────┼──────────────────┘
                                       │
                              Peer Consultation
                                       │
                              Evidence Checker
                                       │
                           Platform Text Formatter
                     (Telegram HTML / Slack Mrkdwn / Web)
                                       │
                         Answer + Verified Citations
```

---

## 🗄️ PostgreSQL & `pgvector` Engine

Thread uses **PostgreSQL** hosted on **Supabase** with the **`pgvector`** extension as its core storage and retrieval backbone.

```
                  ┌──────────────────────────────────────────────┐
                  │         User Query & Active User Scope       │
                  └──────────────────────┬───────────────────────┘
                                         │
                         ┌───────────────▼───────────────┐
                         │  Generate 768-Dim Embedding   │
                         │   (Google Gemini / OpenAI)    │
                         └───────────────┬───────────────┘
                                         │
              ┌──────────────────────────▼──────────────────────────┐
              │             PostgreSQL `hybrid_search()`            │
              │                                                     │
              │   1. Pre-Retrieval SQL ACL Filter:                  │
              │      WHERE organization_id = %s                     │
              │        AND permission = ANY(scope_array)            │
              │                                                     │
              │   2. Dense Vector Match (pgvector Cosine <=>):        │
              │      ORDER BY embedding <=> query_vector            │
              │                                                     │
              │   3. Sparse Lexical Match (tsvector & FTS):         │
              │      WHERE fts @@ websearch_to_tsquery(%s)          │
              │                                                     │
              │   4. Reciprocal Rank Fusion (RRF):                  │
              │      RRF_Score = 1/(k + Rank_dense) + 1/(k + Rank_lexical) │
              └──────────────────────────┬──────────────────────────┘
                                         │
                         ┌───────────────▼───────────────┐
                         │   Ranked Verified Candidates  │
                         │  (Zero Leaked Candidate Rows) │
                         └───────────────────────────────┘
```

### Key Highlights of `pgvector` Implementation:

1. **768-Dimensional Embedding Indexing**:
   Dense vector representations are generated via Google Gemini (`embedding-001`) or OpenAI (`text-embedding-3-small`) and stored directly in the `memory_chunks.embedding` column typed as `vector(768)`. Indexing via **HNSW** (Hierarchical Navigable Small World) provides sub-50ms vector distance lookup.

2. **Pre-Retrieval Scope Isolation**:
   Unlike standard RAG architectures that run vector nearest-neighbor search first and filter afterwards, Thread executes SQL filtering **before similarity calculation**:
   ```sql
   SELECT id, content, provenance, 
          1 - (embedding <=> query_vector) AS similarity
   FROM memory_chunks
   WHERE organization_id = %s 
     AND permission = ANY(%s) -- Strict Pre-Retrieval ACL Scope
   ORDER BY embedding <=> query_vector ASC
   LIMIT %s;
   ```
   If a user lacks permission for internal core records, PostgreSQL excludes those rows prior to vector comparison. The query fails-closed and confidential data never enters the LLM context.

3. **Hybrid Search with Reciprocal Rank Fusion (RRF)**:
   Thread combines dense semantic similarity (`pgvector`) with sparse keyword matching (`tsvector` full-text search) via a custom SQL function `hybrid_search()`. Results are fused using Reciprocal Rank Fusion:
   $$\text{RRF Score} = \frac{1}{k + \text{Rank}_{\text{dense}}} + \frac{1}{k + \text{Rank}_{\text{lexical}}}$$
   This ensures precision on exact terminology (e.g., repository names, invoice numbers) while retaining high-level semantic retrieval.

4. **Normalized Schema Architecture**:
   - `memory_chunks`: Stores text chunks, vector embeddings (`vector(768)`), FTS vectors (`tsvector`), metadata, and ACL permissions.
   - `source_records`: Tracks source provenance (Discord message ID, Telegram post ID, GitHub PR URL).
   - `conversations` & `audit_logs`: Maintains execution history, turn records, and delivery receipts.

---

## ✨ Key Capabilities & Modules

### 1. 🤖 Multi-Platform Bot Gateway
- **Discord Bot**: Real-time message ingestion, `!summary`, `!ask`, `!github`, `!ingest`, `!identity`, and `!help`.
- **Telegram Bot**: Long-polling & webhook support with native Telegram HTML text formatting (`convert_markdown_to_telegram_html`).
- **Slack Connector**: Custom Slack mrkdwn parser and webhook handler.
- **Model Output Text Coercion**: Automatically strips raw LLM provider structures, signatures, and extra metadata to ensure clean output across all channels.

### 2. 📝 Executive Discussion Summarizer (`!summary`)
- Summarizes channel discussions from the past 24–48 hours based strictly on ingested messages.
- Applies pre-retrieval ACL filtering so public users only summarize public discussion threads.
- Formats structured bullet points for Main Topics, Key Decisions, and Action Items.

### 3. 🔐 Pre-Retrieval ACL & Identity Management
- **Role-Based Access Control**: Distinguishes between `PUBLIC_COMMUNITY` and confidential `INTERNAL_CORE` records before running vector searches.
- **Account Binding (`!link` / `!unlink`)**: Connects platform user IDs (Discord, Telegram, Slack) with Thread Workspace user accounts.

### 4. 🌐 React 19 + Vite Modern Frontend
- Fully responsive dark-mode UI powered by **React 19**, **Vite**, **Tailwind CSS v4**, **Framer Motion**, and **Lucide Icons**.
- Live workspace switcher, AI agent status indicators, interactive trace stepper, and instant citation inspector.

---

## 🚀 Quickstart & Setup Guide

### Prerequisites
- **Node.js**: 20+
- **Python**: 3.11+
- **Database**: PostgreSQL with `pgvector` extension enabled (Supabase recommended)

---

### 1. Setup Backend

```bash
cd backend

# Create virtual environment
python -m venv .venv

# Activate virtual environment
# Windows:
.venv\Scripts\activate
# macOS/Linux:
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

#### Configure Environment (`backend/.env`)
Copy `.env.example` to `.env` and fill in your keys:

```ini
# LLM Providers (Provides Gemini or OpenAI fallback)
GEMINI_API_KEY=your-gemini-api-key
OPENAI_API_KEY=your-openai-api-key

# Database (Supabase / PostgreSQL with pgvector)
SUPABASE_DB_URL=postgresql://postgres:password@db.supabase.co:5432/postgres

# Bot Integration Tokens (Optional)
DISCORD_BOT_TOKEN=your-discord-bot-token
TELEGRAM_BOT_TOKEN=your-telegram-bot-token
SLACK_BOT_TOKEN=your-slack-bot-token
```

---

### 2. Setup Frontend

```bash
cd frontend
npm install
```

---

### 3. Run Development Environment

Start backend and frontend services:

```bash
# Terminal 1 — Backend API Server (Port 8000)
cd backend
.venv\Scripts\python.exe -m uvicorn app.main:app --port 8000 --reload

# Terminal 2 — Frontend Dev Server (Port 5173)
cd frontend
npm run dev
```

Visit the application at: **`http://localhost:5173`**

---

### 4. Run Multi-Platform Bots

```bash
# Run Discord Gateway Bot:
cd backend
.venv\Scripts\python.exe -m app.channels.run_gateway
```

---

## 🧪 Verification & Demonstration Queries

Try these queries in the **GDG MCET Workspace**:

1. **DevFest Venue Approval (Public Scope)**:
   > *"Where is DevFest taking place and has it been approved?"*  
   > *Result:* Triage routes to Lead Organizer Arjun Sharma $\rightarrow$ retrieves official college approval memo from ingested Discord records.

2. **GenAI Workshop Prerequisites (Public Scope)**:
   > *"What are the prerequisites for the GenAI workshop and where is the repo?"*  
   > *Result:* Triage routes to Tech Lead Priya Ramesh $\rightarrow$ retrieves GitHub starter-kit repository and Python requirements.

3. **Swag Vendor Budget (Internal Core Scope)**:
   > *"What is our internal budget for attendee t-shirts and swag?"*  
   > *Result (as Organizer):* Routes to Finance Lead Karthik Verma $\rightarrow$ retrieves internal budget notes.  
   > *Result (as Community Member):* Pre-Retrieval ACL blocks the query in SQL before `pgvector` similarity calculation, ensuring confidential data remains completely safe.

---

## 📦 Deployment Overview

- **Frontend**: Deployed on [Vercel](https://thread-agent-xi.vercel.app) using Vite production build (`npm run build`).
- **Backend API & Gateway**: Containerized FastAPI application configured for deployment on Railway / Render with Supabase PostgreSQL & `pgvector` bindings.

---

## 📄 License

Built for organizations, developer communities, and teams. Distributed under the MIT License.
