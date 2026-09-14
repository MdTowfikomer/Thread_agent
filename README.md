# 🧵 Thread: AI Organizational Context Agent

> **"Thread is not a chatbot with a vector database. Thread is a context reconstruction system."**  
> *Search retrieves. Memory stores. Thread reconstructs.*  
>  
> **Thread connects the scattered knowledge of an organization and reconstructs the context behind its work — across conversations, documents, code, people, projects, and decisions.**  
>  
> **GDG MCET is our first real-world deployment and demonstration environment.**

---

## ⚡ Why Context Reconstruction Matters

Developer communities and fast-moving teams suffer from **institutional amnesia**:
- When core leads graduate or team members move on, vital context—past sponsor agreements, speaker rolodexes, workshop codelab repos, and venue approvals—vanishes into disconnected Slack channels and forgotten Google Drive folders.
- Traditional wikis (Notion, Drive) are static cemeteries that nobody maintains or reads.
- Traditional vector chatbots simply retrieve disjointed text snippets without understanding *who decided what*, *why a path was taken*, or *what permissions apply*.
- **Thread** acts as an **Organization-Agnostic Context Reconstruction System**:
  - Any organization creates its own **Workspace**, defines its own **Role Agents**, and connects its sources.
  - Context is normalized into a **Canonical Schema**.
  - Permissions are strictly enforced **before retrieval**, not filtered after the LLM generates text.
  - Queries flow through a deterministic **LangGraph Multi-Agent Pipeline** to reconstruct the full context with verified citations.

---

## 🏛️ System Architecture

```
                         THREAD
                           │
                    ┌──────▼──────┐
                    │ Organization │
                    │   Workspace  │ (e.g. GDG MCET, Acme, Open Source)
                    └──────┬──────┘
                           │
              ┌────────────┼────────────┐
              │            │            │
           People       Projects     Sources
              │            │            │
              └────────────┼────────────┘
                           │
                    Canonical Schema
                           │
                  ┌────────▼────────┐
                  │   Thread Core   │
                  ├─────────────────┤
                  │ Memory          │
                  │ Vector Search   │
                  │ Knowledge Graph │
                  │ Identity        │
                  │ Permissions     │
                  └────────┬────────┘
                           │
                    Agent Orchestrator
                           │
                    ┌──────▼──────┐
                    │ Triage Router│
                    └──────┬──────┘
                           │
                ┌──────────┼──────────┐
                │          │          │
            Role Agent  Role Agent  Role Agent
            (Organizer)  (Tech Lead) (Sponsorship)
                │          │          │
                └──────────┼──────────┘
                           │
                   Peer Consultation
                           │
                   Evidence Checker
                           │
                       Synthesis
                           │
                        Answer + Verified Sources
```

### The 4 Architectural Layers
1. **Connectors**: GitHub, Google Drive, Discord, Slack, Notion, Gmail, Local Files.
2. **Universal Ingestion**: Normalizes heterogeneous events, entities, timestamps, and permissions into a single Canonical Context Schema.
3. **Thread Core**:
   - **LangGraph Multi-Agent Engine**:  
     `User Query` $\rightarrow$ `Pre-Retrieval ACL` $\rightarrow$ `Triage Router` $\rightarrow$ `Role Agent` $\rightarrow$ `Peer Consultation` $\rightarrow$ `Evidence Checker` $\rightarrow$ `Synthesis`.
   - **Pre-Retrieval Permissions**: Role-Based Access Control (`PUBLIC_COMMUNITY` vs `INTERNAL_CORE`) enforces security before vector search, ensuring zero data leakage.
   - **Memory & Vector Store**: Cosine similarity + lexical keyword boosting + multi-provider embedding (Gemini / OpenAI).
4. **Interfaces**:
   - **React 19 + Vite Frontend**: Workspace dashboard, interactive role agents, LangGraph trace stepper, and citation cards.
   - **Context Handover Generator**: 1-click transition dossier when leads or contributors step down.
   - **Bot Ingress API**: Ready for Discord, Telegram, and Slack webhooks.

---

## 🚀 Quickstart

### Prerequisites
- Node.js 20+
- Python 3.11+

### 1. Setup Backend
```bash
cd backend
python -m venv .venv

# On Windows:
.venv\Scripts\activate
# On macOS/Linux:
source .venv/bin/activate

pip install -r requirements.txt
```

### 2. Configure Environment (Optional)
Copy `.env.example` to `.env`:
```bash
# Provide either Gemini or OpenAI API key (falls back gracefully to deterministic synthesis if omitted)
GEMINI_API_KEY=your-gemini-key
OPENAI_API_KEY=your-openai-key
```

### 3. Setup Frontend
```bash
cd ../frontend
npm install
```

### 4. Run Both Servers
Double-click `run_dev.bat` in Windows or run:
```bash
# Terminal 1 (Backend):
cd backend
.venv\Scripts\python.exe -m uvicorn app.main:app --port 8000 --reload

# Terminal 2 (Frontend):
cd frontend
npm run dev
```

Visit: **http://localhost:5173**

---

## 🎯 Verification Queries in GDG MCET Workspace

1. **DevFest Venue Approval (Community Member Profile)**:
   > *"Where is DevFest taking place and has it been approved?"*  
   > *Result:* Triage routes to Lead Organizer Arjun Sharma $\rightarrow$ retrieves official college approval memo from Discord.

2. **GenAI Workshop Prerequisites (Community Member Profile)**:
   > *"What are the prerequisites for the GenAI workshop and where is the repo?"*  
   > *Result:* Triage routes to Tech Lead Priya Ramesh $\rightarrow$ retrieves GitHub starter-kit repo and Python 3.10 requirements.

3. **Swag & Swag Vendor Budget (Organizer Core Profile)**:
   > *"What is our internal budget for attendee t-shirts and swag?"*  
   > *Result:* Triage routes to Finance Lead Karthik Verma $\rightarrow$ retrieves confidential Google Spreadsheet budget notes (₹22,000 for t-shirts from PrintWear Co).  
   > *(Switch to Community Member to watch Pre-Retrieval ACL completely filter this from the search space!)*
