# SG Property Advisory AI Agent

A full-stack AI agent for property advisory in Singapore, combining a knowledge base pipeline with an interactive chat interface.

## Tech Stack

- **Backend**: FastAPI (Python)
- **Frontend**: React + Vite (TypeScript)
- **LLM**: Anthropic Claude via OpenRouter or OpenAI
- **KB Pipeline**: Python data pipeline (crawlers, processors, embedders)
- **DB**: PostgreSQL + pgvector
- **Cache**: Redis
- **Storage**: MinIO (S3-compatible)
- **Message Queue**: Celery + Redis
- **Integration**: WhatsApp Business API, LangSmith tracing

## Prerequisites

- **Docker Desktop** (Windows/Mac) or Docker Engine + Docker Compose (Linux)
- **Git**
- **API Keys** (see [Environment Variables](#environment-variables) section)

## Quick Start

### 1. Clone the Repository

```bash
git clone https://github.com/pgnaleen/knowledge-base.git
cd knowledge-base
git checkout property-advisory-ai-advisory
```

⚠️ **Important**: Open the `knowledge-base` **root folder** in VS Code, not any subfolder. You should see `KB-Pipeline/`, `sg-property-agent/`, `docker-compose.yml`, and other files at the top level.

### 2. Set Up Environment Files

Run the setup script to automatically create `.env` files from `.env.example`:

**Windows (PowerShell):**
```powershell
.\setup.ps1
```

**Mac/Linux (Bash):**
```bash
bash setup.sh
```

This script copies all `.env.example` files → `.env` in their respective directories. If an `.env` already exists, it skips it (safe to re-run).

### 3. Fill in API Keys

Open and edit these files with your actual credentials:

- **`sg-property-agent/backend/.env`** — **required**, fill in at least one LLM key
- `KB-Pipeline/.env` — optional for Docker, required for local KB development
- `sg-property-agent/frontend/.env` — usually ok with defaults
- `sg-property-agent/mcp-server/.env` — usually ok with defaults

Minimum to get started:
```
# In sg-property-agent/backend/.env, set ONE of:
OPENROUTER_API_KEY=sk-or-...
# OR
OPENAI_API_KEY=sk-...
```

### 4. Start All Services

From the root directory:

```bash
docker compose up --build -d
```

**⚠️ Important**: After starting, run the KB-Pipeline database setup:

```bash
# Apply database migrations (creates tables + seeds all 5 sources)
docker exec sg-property-kb-app alembic upgrade head
```

(This is automatic if you ran the setup script, but required if you started with `docker compose up`.)

Services will be available at:

| Service | URL | Purpose |
|---|---|---|
| Frontend | http://localhost:3000 | React UI |
| Backend API | http://localhost:8001/docs | FastAPI Swagger docs |
| KB Retrieval API | http://localhost:8000/docs | Knowledge base API |
| MinIO Console | http://localhost:9001 | Object storage admin (user: `minioadmin`, pass: `minioadmin`) |

### 5. Verify Setup

Check all services are running:

```bash
docker compose ps
```

You should see 11 services: postgres, redis, minio, minio-init, kb-app, kb-api, kb-worker, kb-beat, mcp-server, backend, frontend.

### 6. Check Logs

See [Checking Logs](#checking-logs) section below for detailed logging instructions.

### 7. Stop Services

```bash
docker compose down
```

## API Reference

### KB-Pipeline API — Knowledge Base Retrieval & Crawl Management

**Base URL**: `http://localhost:8000`  
**Swagger UI**: `http://localhost:8000/docs`

#### GET /health
Liveness check.

```bash
curl http://localhost:8000/health
```

Response: `{"status": "ok"}`

---

#### POST /crawl
Queue a crawl task for a source (async — returns immediately with task_id).

**Example Request (Postman):**
```json
POST http://localhost:8000/crawl
Content-Type: application/json

{
  "source_code": "hdb",
  "job_type": "incremental",
  "page_limit": 10
}
```

**Parameters:**
- `source_code` (str): `hdb`, `ura`, `iras`, `mas`, or `cpf`
- `job_type` (str, optional): `"full"` or `"incremental"` (default: `"incremental"`)
- `page_limit` (int, optional): Max pages to crawl (useful for testing)

**Response (202 Accepted):**
```json
{
  "task_id": "crawl-hdb-1234567890",
  "status": "pending",
  "source_code": "hdb",
  "job_type": "incremental"
}
```

---

#### GET /jobs
Get task execution history with optional filters.

**Example Request (Postman):**
```
GET http://localhost:8000/jobs?source=hdb&status=running&limit=5&offset=0
```

**Query Parameters:**
- `source` (str, optional): Filter by source code (`hdb`, `ura`, `iras`, `mas`, `cpf`)
- `status` (str, optional): Filter by status (`pending`, `started`, `success`, `failed`, `retry`)
- `limit` (int, optional): Results per page (default: 20)
- `offset` (int, optional): Pagination offset (default: 0)

**Response (200 OK):**
```json
{
  "jobs": [
    {
      "task_id": "crawl-hdb-1234567890",
      "task_name": "crawl",
      "source_code": "hdb",
      "status": "success",
      "started_at": "2026-06-02T10:15:30Z",
      "completed_at": "2026-06-02T10:25:45Z",
      "result_summary": {
        "pages_found": 45,
        "pages_new": 12,
        "pages_changed": 5,
        "documents_created": 12,
        "documents_updated": 5
      },
      "logs": "[2026-06-02 10:15:30] Starting crawl for hdb...\n[2026-06-02 10:25:45] Crawl completed.",
      "error_message": null
    }
  ],
  "total": 1
}
```

**Key Fields:**
- `task_id`: Unique task identifier (reference in logs)
- `status`: Current task status
- `result_summary`: Statistics from the completed task (crawl counts, pages found, etc.)
- `logs`: Full structured log output captured during task execution
- `error_message`: Error details if status is `failed`

---

#### POST /process
Queue a task to extract and chunk all raw documents pending processing.

**Example Request:**
```bash
curl -X POST http://localhost:8000/process
```

**Response (202 Accepted):**
```json
{
  "task_id": "process-1234567890",
  "status": "pending"
}
```

---

#### POST /embed
Queue a task to embed all unembedded chunks into Pinecone and pgvector.

**Example Request:**
```bash
curl -X POST http://localhost:8000/embed
```

**Response (202 Accepted):**
```json
{
  "task_id": "embed-1234567890",
  "status": "pending"
}
```

---

#### POST /retrieve
Semantic search across the knowledge base (hybrid vector + BM25).

**Example Request (Postman):**
```json
POST http://localhost:8000/retrieve
Content-Type: application/json

{
  "query": "What is ABSD for a PR buying a condo?",
  "top_k": 5,
  "search_mode": "hybrid",
  "filters": {
    "source": ["iras"],
    "property_type": ["condo"],
    "citizenship_type": ["PR"]
  }
}
```

**Parameters:**
- `query` (str, required): Search query
- `top_k` (int, optional): Number of results (default: 5, max: 50)
- `search_mode` (str, optional): `"vector"` or `"hybrid"` (default: `"hybrid"`)
- `filters` (object, optional): Filter results by source, property_type, citizenship_type (all arrays)

**Response (200 OK):**
```json
{
  "query": "What is ABSD for a PR buying a condo?",
  "results": [
    {
      "text": "The Additional Buyer's Stamp Duty (ABSD) is levied on buyers who acquire residential properties in Singapore. For permanent residents (PRs), the ABSD rate is 5% of the property value...",
      "score": 0.92,
      "source_name": "iras",
      "source_url": "https://iras.gov.sg/...",
      "title": "ABSD Rates for PRs",
      "section": "Residential Properties",
      "chunk_index": 3,
      "property_types": ["condo", "hdb"],
      "citizenship_types": ["PR"]
    }
  ],
  "total": 1,
  "latency_ms": 45,
  "store_used": "pinecone"
}
```

---

### SG Property Agent API — Conversational AI Backend

**Base URL**: `http://localhost:8001`  
**Swagger UI**: `http://localhost:8001/docs`

#### GET /health
Liveness check.

```bash
curl http://localhost:8001/health
```

Response: `{"status": "ok"}`

---

#### POST /chat
Send a question and receive a streamed answer (Server-Sent Events).

**Example Request (Postman):**
```json
POST http://localhost:8001/chat
Content-Type: application/json

{
  "question": "What is ABSD for a PR buying a condo?",
  "thread_id": "user-session-123"
}
```

**Parameters:**
- `question` (str, required): User's question (1–2000 characters)
- `thread_id` (str, optional): Conversation session ID. If omitted, a new UUID is generated. Use the same `thread_id` for multi-turn conversations.

**Response (200 OK, text/event-stream):**
```
data: {"type": "token", "content": "The"}
data: {"type": "token", "content": " ABSD"}
data: {"type": "token", "content": " for"}
...
data: {"type": "done"}
```

Each line is a JSON object:
- `{"type": "token", "content": "..."}` — a chunk of the response
- `{"type": "done"}` — end of stream
- `{"type": "error", "text": "..."}` — error occurred

**Note**: Use `text/event-stream` content-type when consuming in client code.

---

#### POST /reset
Clear conversation memory for a session.

**Example Request (Postman):**
```json
POST http://localhost:8001/reset
Content-Type: application/json

{
  "thread_id": "user-session-123"
}
```

**Response (200 OK):**
```json
{
  "status": "ok",
  "thread_id": "user-session-123"
}
```

---

## Checking Logs

All logs are streamed to stdout via structlog. Docker captures them with its default json-file logging driver.

### View Logs for All Services

```bash
# Follow all services in real-time
docker compose logs -f

# View last 50 lines of all services
docker compose logs --tail=50
```

### View Logs for Specific Services

```bash
# KB-Pipeline API (REST endpoints)
docker compose logs -f kb-api

# Celery Worker (runs crawl, process, embed tasks)
docker compose logs -f kb-worker

# Celery Beat Scheduler (runs scheduled jobs)
docker compose logs -f kb-beat

# SG Property Agent Backend (chat API)
docker compose logs -f backend

# React Frontend
docker compose logs -f frontend

# View last 100 lines only
docker compose logs --tail=100 kb-worker
```

### How to Check Logs for API-Triggered Tasks

**Scenario**: You triggered a crawl via Postman (`POST /crawl`) and got back a `task_id`. Where are the logs?

1. **Real-time task logs** — Task execution runs on the **Celery worker**, not the API:
   ```bash
   docker compose logs -f kb-worker
   ```
   Watch this terminal while the task is running. You'll see structured logs with the task name, source, pages found, etc.

2. **Task history** — After the task completes, retrieve its full log via the API:
   ```bash
   curl "http://localhost:8000/jobs?source=hdb&limit=5"
   ```
   Each job record contains:
   - `logs` field — full structured log output captured during execution
   - `result_summary` — statistics (pages found, documents created, etc.)
   - `error_message` — error details if the task failed

3. **Comparison: CLI vs API**
   - **CLI method** (direct, logs in your terminal):
     ```bash
     docker exec sg-property-kb-worker python run_pipeline.py --crawl-only hdb -S CLOSESPIDER_PAGECOUNT=10
     ```
   - **API/Postman method** (async, check logs via `/jobs`):
     ```bash
     # 1. Trigger crawl
     curl -X POST http://localhost:8000/crawl \
       -H "Content-Type: application/json" \
       -d '{"source_code": "hdb", "page_limit": 10}'
     
     # 2. Watch worker logs
     docker compose logs -f kb-worker
     
     # 3. Check final status + logs
     curl "http://localhost:8000/jobs?source=hdb&limit=1"
     ```

---

## Environment Variables Reference

### `sg-property-agent/backend/.env` ⭐ (Required for Docker)

| Variable | Required? | Example | Notes |
|---|---|---|---|
| `LLM_PROVIDER` | No | `openrouter` | Defaults to `openrouter` |
| `OPENROUTER_API_KEY` | Yes (if using OpenRouter) | `sk-or-...` | Get from https://openrouter.ai |
| `OPENROUTER_BASE_URL` | No | `https://openrouter.ai/api/v1` | Default should work |
| `OPENROUTER_MODEL` | No | `meta-llama/llama-3.3-70b-instruct:free` | Free tier model |
| `OPENAI_API_KEY` | Yes (if using OpenAI) | `sk-...` | Alternative to OpenRouter |
| `OPENAI_MODEL` | No | `gpt-4o` | If using OpenAI |
| `KB_PIPELINE_URL` | No | `http://localhost:8000` | Internal KB API |
| `CORS_ORIGINS` | No | `http://localhost:5173` | Frontend URL for local dev |
| `WHATSAPP_TOKEN` | No | `...` | For WhatsApp integration |
| `WHATSAPP_PHONE_NUMBER_ID` | No | `...` | For WhatsApp |
| `WHATSAPP_WABA_ID` | No | `...` | For WhatsApp |
| `WHATSAPP_VERIFY_TOKEN` | No | `...` | For WhatsApp |
| `WHATSAPP_APP_SECRET` | No | `...` | For WhatsApp |
| `LANGCHAIN_TRACING_V2` | No | `true` / `false` | Enable LangSmith tracing |
| `LANGCHAIN_ENDPOINT` | No | `https://api.smith.langchain.com` | LangSmith URL |
| `LANGCHAIN_API_KEY` | No | `ls__...` | LangSmith API key |
| `LANGCHAIN_PROJECT` | No | `sg-property-advisor` | LangSmith project name |

### `KB-Pipeline/.env`

| Variable | Required? | Example | Notes |
|---|---|---|---|
| `DATABASE_URL` | No | `postgresql://kb_user:kb_pass@localhost:5432/kb_pipeline_db` | Docker defaults work |
| `REDIS_URL` | No | `redis://localhost:6379/0` | Docker defaults work |
| `S3_ENDPOINT` | No | `http://localhost:9000` | MinIO (Docker) |
| `S3_ACCESS_KEY` | No | `minioadmin` | MinIO default |
| `S3_SECRET_KEY` | No | `minioadmin` | MinIO default |
| `S3_BUCKET` | No | `sg-property-kb` | Default is fine |
| `OPENROUTER_API_KEY` | Yes (for crawling) | `sk-or-...` | Embedding API |
| `OPENAI_API_KEY` | Yes (if not OpenRouter) | `sk-...` | Alternative |
| `CRAWL_DELAY` | No | `2.0` | Seconds between requests |
| `CRAWL_USER_AGENT` | No | `Mozilla/5.0 ...` | Web scraper UA |

### `sg-property-agent/frontend/.env`

| Variable | Default | Notes |
|---|---|---|
| `VITE_API_BASE_URL` | `http://localhost:8001` | Backend API URL |
| `VITE_WHATSAPP_NUMBER` | — | WhatsApp number for UI display |

### `sg-property-agent/mcp-server/.env`

| Variable | Default | Notes |
|---|---|---|
| `KB_PIPELINE_URL` | `http://localhost:8000` | KB API endpoint |

## Troubleshooting

### Error: I only see `KB-Pipeline` in VS Code

**Problem**: After cloning, you opened `KB-Pipeline/` as the workspace folder instead of the project root.

**Solution**: 
1. In VS Code, go to `File > Open Folder`
2. Select the **`knowledge-base`** root folder (not `knowledge-base/KB-Pipeline/`)
3. Verify the Explorer sidebar shows `KB-Pipeline/`, `sg-property-agent/`, `docker-compose.yml`, and `README.md` at the top level

### Error: `.env not found`

```
env file ... .env not found: GetFileAttributesEx ...
```

**Solution**: Run the setup script to create `.env` files:
```bash
.\setup.ps1          # Windows
bash setup.sh        # Mac/Linux
```

### Error: `Port already in use`

If port 3000, 8000, or 8001 is already in use:

**Option 1**: Stop the conflicting service
```bash
# Find what's using port 3000 (example)
netstat -ano | findstr :3000    # Windows
lsof -i :3000                    # Mac/Linux
```

**Option 2**: Modify port in `docker-compose.yml`
```yaml
services:
  frontend:
    ports:
      - "3001:80"  # Change 3000 → 3001
```

### Error: `docker: command not found`

Install Docker Desktop from https://www.docker.com/products/docker-desktop

### Backend won't connect to KB-Pipeline

Check that both are running:
```bash
docker compose ps
```

If KB-Pipeline is missing, ensure the root `docker-compose.yml` includes it (it should).

### Crawl returns 0 pages found

If you start the containers with `docker compose up -d` without running setup, the database hasn't been seeded. Run:

```bash
# Apply database migrations (creates tables + seeds 5 sources)
docker exec sg-property-kb-app alembic upgrade head

# Sync sources config from sources.yml to database
docker exec sg-property-kb-app python -m config.sync_sources
```

Then try crawling again:
```bash
docker exec sg-property-kb-app python run_pipeline.py --crawl-only hdb -S CLOSESPIDER_PAGECOUNT=10
```

## Development

### Local Frontend Dev (with hot reload)

```bash
cd sg-property-agent/frontend
npm install
npm run dev    # Runs on http://localhost:5173 with hot reload
```

Then update `CORS_ORIGINS` in `sg-property-agent/backend/.env` to match your frontend port.

### Local Backend Dev

```bash
cd sg-property-agent/backend
pip install -r requirements.txt
# Fill in sg-property-agent/backend/.env with your keys
python -m uvicorn main:app --reload
```

### KB-Pipeline Local Dev

See [KB-Pipeline CLAUDE.md](KB-Pipeline/CLAUDE.md) for detailed docs.

## Docker Compose Profiles

The root `docker-compose.yml` includes all services by default. If you want to run subsets:

```bash
# Start only the full stack (default)
docker compose up -d

# Start only KB-Pipeline + frontend (backend as local dev)
docker compose --profile kb-only up -d

# Start only frontend (everything else local)
docker compose --profile frontend-only up -d
```

(Note: profiles are defined in the compose file; check `docker-compose.yml` for exact profile names.)

## Documentation

- [KB-Pipeline CLAUDE.md](KB-Pipeline/CLAUDE.md) — Data pipeline setup, commands, architecture & technical reference
- [SG Property Agent README](sg-property-agent/README.md) — Architecture & API design

## License

[Add your license here]

## Support

For setup issues, check the [Troubleshooting](#troubleshooting) section or open an issue.
