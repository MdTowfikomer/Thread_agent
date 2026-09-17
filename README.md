# 🧵 Thread Agent: AI Organizational Context & Multi-Platform Intelligence

> **"Thread is not a chatbot with a vector database. Thread is a context reconstruction system."**  
> *Search retrieves. Memory stores. Thread reconstructs.*  
>  
> **Thread connects the scattered knowledge of an organization and reconstructs the context behind its work — across Discord, Telegram, Slack, GitHub, documents, people, projects, and decisions.**  
>  
> **Live Deployment**: [thread-agent-xi.vercel.app](https://thread-agent-xi.vercel.app)  
> **Demonstration Environment**: GDG MCET Organization Workspace

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

## 🚀 Quickstart Guide

### Prerequisites
- **Node.js**: 20+
- **Python**: 3.11+
- **Database**: PostgreSQL / Supabase (Optional for full DB persistence)

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

# Database (Optional - Supabase / PostgreSQL)
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

You can start both backend and frontend using `run_dev.bat` on Windows, or manually:

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
   > *Result (as Community Member):* Pre-Retrieval ACL blocks the query before vector search, ensuring confidential data remains secure.

---

## 📦 Deployment Overview

- **Frontend**: Deployed on [Vercel](https://thread-agent-xi.vercel.app) using Vite production build (`npm run build`).
- **Backend API & Gateway**: Containerized FastAPI application configured for deployment on Railway / Render / Oracle Cloud with Supabase Database bindings.

---

## 📄 License

Built for organizations, developer communities, and teams. Distributed under the MIT License.
