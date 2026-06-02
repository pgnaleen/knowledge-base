# SG Property Agent

A conversational AI agent for Singapore property advisory. Combines the KB-Pipeline retrieval API with Claude's reasoning to answer questions about ABSD, HDB eligibility, stamp duty, property grants, and more.

## Architecture

```
React Frontend (http://localhost:3000)
    ↓
FastAPI Backend (http://localhost:8001)
    ↓
KB-Pipeline API (http://localhost:8000)
    ↓
PostgreSQL + pgvector + Pinecone
```

**Components:**
- **Frontend** (`sg-property-agent/frontend/`) — React + Vite UI for chat interface
- **Backend** (`sg-property-agent/backend/`) — FastAPI server with LangGraph agent orchestrator
- **MCP Server** (`sg-property-agent/mcp-server/`) — FastMCP tools for financial calculations (BSD, ABSD, CPF withdrawal, etc.)
- **KB-Pipeline** — Separate knowledge base crawl/embed/retrieval pipeline (see root [README.md](../README.md))

## Setup

**Full-stack setup is via the root README.md — start there.**

This guide covers only the SG Property Agent sub-project components. For first-time setup (cloning, environment files, Docker), go to [../README.md](../README.md#quick-start).

### Prerequisites

After completing the root [README.md Quick Start](#quick-start), you'll have:
- All Docker containers running (`docker compose ps` shows 11 services)
- KB-Pipeline database initialized (`alembic upgrade head` completed)
- All `.env` files created and filled

### Services

Once `docker compose up --build -d` is running from the root directory:

| Service | URL | Purpose |
|---|---|---|
| Frontend | http://localhost:3000 | React chat UI |
| Backend | http://localhost:8001/docs | FastAPI server (Swagger UI) |
| MCP Server | http://localhost:8002 | Internal tools server (no browser access) |
| KB-Pipeline API | http://localhost:8000/docs | Knowledge base retrieval |

## How It Works

1. **User asks a question** in the React UI (http://localhost:3000)
2. **Frontend sends** `POST /chat` to Backend with the question and a `thread_id` (conversation session ID)
3. **Backend orchestrator** (LangGraph agent) receives the question
4. **Orchestrator routes** to specialist agents based on intent:
   - **Eligibility Agent** — HDB, PR/citizen eligibility rules
   - **Financial Agent** — ABSD, BSD, stamp duty, property grants
   - **Knowledge Advisory Agent** — General property knowledge (calls KB-Pipeline `/retrieve`)
5. **Specialist agents** call MCP tools for calculations or KB-Pipeline for knowledge retrieval
6. **Pass 2**: Orchestrator synthesizes specialist outputs into a final answer
7. **Backend streams** the answer back to Frontend via Server-Sent Events (SSE)
8. **Frontend displays** tokens as they arrive in real-time

**Multi-turn support**: Each `thread_id` maintains conversation memory (via LangGraph MemorySaver). Follow-up questions use context from previous messages.

## API Endpoints

### Backend API (`http://localhost:8001`)

Full API documentation available at `http://localhost:8001/docs` (FastAPI Swagger UI).

#### POST /chat
Send a question and receive a streamed response.

**Request:**
```json
{
  "question": "What is ABSD for a PR buying a second property?",
  "thread_id": "user-session-abc123"
}
```

**Parameters:**
- `question` (str, required): User's question
- `thread_id` (str, optional): Session ID for multi-turn conversations. Auto-generated if omitted.

**Response (200, text/event-stream):**
```
data: {"type": "token", "content": "The"}
data: {"type": "token", "content": " ABSD"}
...
data: {"type": "done"}
```

---

#### POST /reset
Clear conversation memory for a session.

**Request:**
```json
{
  "thread_id": "user-session-abc123"
}
```

**Response:**
```json
{
  "status": "ok",
  "thread_id": "user-session-abc123"
}
```

---

#### GET /health
Liveness check.

**Response:**
```json
{"status": "ok"}
```

---

### KB-Pipeline API (`http://localhost:8000`)

See [../README.md#api-reference](../README.md#api-reference) for full KB-Pipeline API documentation.

Key endpoints:
- `POST /crawl` — queue a crawl task
- `GET /jobs` — view task status and logs
- `POST /retrieve` — semantic search

---

## Features

- **Multi-turn conversation** — maintains memory across messages within a `thread_id`
- **Grounded answers** — responses cite official government sources (HDB, URA, IRAS, MAS, CPF)
- **Specialist agents** — separate reasoning paths for eligibility, financial, and knowledge queries
- **Financial calculators** — ABSD, BSD, stamp duty, CPF withdrawal, HDB grants (via MCP tools)
- **Error handling** — gracefully handles KB-Pipeline unavailability
- **Reset button** — clears conversation history anytime
- **Hybrid search** — KB-Pipeline uses both vector + BM25 for retrieval

---

## Example Questions

- "What is ABSD for a PR buying a condo?"
- "What if they already own one property?"
- "Am I eligible for HDB as a PR?"
- "What is the stamp duty for HDB buyers?"
- "How much CPF can I withdraw for home purchase?"

---

## Checking Logs

### Backend logs
```bash
docker compose logs -f backend
```

### Worker logs (for KB-Pipeline tasks triggered by the agent)
```bash
docker compose logs -f kb-worker
```

### View API task history
```bash
curl "http://localhost:8000/jobs?limit=10"
```

See [../README.md#checking-logs](../README.md#checking-logs) for detailed logging instructions.

---

## Environment Variables

Backend-specific configuration (see [../README.md#sg-property-agentbackendenv--required-for-docker](../README.md#sg-property-agentbackendenv--required-for-docker) for full reference):

| Variable | Required? | Example |
|---|---|---|
| `LLM_PROVIDER` | No | `openrouter` (default) or `openai` |
| `OPENROUTER_API_KEY` | Yes (if OpenRouter) | `sk-or-...` |
| `OPENAI_API_KEY` | Yes (if OpenAI) | `sk-...` |
| `KB_PIPELINE_URL` | No | `http://localhost:8000` |
| `CORS_ORIGINS` | No | `http://localhost:5173` (for dev frontend) |

---

## Tech Stack

- **Backend**: FastAPI, LangGraph, Anthropic Claude
- **Frontend**: React 18, Vite, TypeScript
- **LLM**: OpenRouter or OpenAI API
- **Tools**: FastMCP (financial calculations)
- **Retrieval**: KB-Pipeline API (PostgreSQL + pgvector + Pinecone)
- **Message Queue**: Celery + Redis (for async KB tasks)
- **Tracing**: LangSmith (optional, via `LANGCHAIN_TRACING_V2`)

---

## License

[Add your license here]

## Support

For setup issues, see [../README.md#troubleshooting](../README.md#troubleshooting).
