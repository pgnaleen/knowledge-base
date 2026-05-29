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
git clone <repo-url>
cd "N\Property Advisory AI Agent"
```

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

Services will be available at:

| Service | URL | Purpose |
|---|---|---|
| Frontend | http://localhost:3000 | React UI |
| Backend API | http://localhost:8001/docs | FastAPI Swagger docs |
| KB Retrieval API | http://localhost:8000/docs | Knowledge base API |
| MinIO Console | http://localhost:9001 | Object storage admin (user: `minioadmin`, pass: `minioadmin`) |

### 5. Check Logs

```bash
docker compose logs -f backend   # Follow backend logs
docker compose logs -f kb-api    # Follow KB API logs
```

### 6. Stop Services

```bash
docker compose down
```

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

- [KB-Pipeline README](KB-Pipeline/README.md) — Data pipeline details
- [SG Property Agent README](sg-property-agent/README.md) — Architecture & API design
- [KB-Pipeline CLAUDE.md](KB-Pipeline/CLAUDE.md) — Technical reference

## License

[Add your license here]

## Support

For setup issues, check the [Troubleshooting](#troubleshooting) section or open an issue.
