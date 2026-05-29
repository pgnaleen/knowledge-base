# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Python data pipeline that crawls 5 Singapore government property regulatory sites (HDB, URA, IRAS, MAS, CPF), processes content, generates embeddings, and indexes into a vector store for RAG retrieval.

## Setup

```bash
# First-time setup (builds containers, runs migrations, verifies everything)
bash setup.sh

# Start containers after a restart
docker compose up -d
```

## Common Commands

All commands run **inside the app container** — no local Python/venv needed.

```bash
# Open an interactive shell inside the container (easiest for development)
docker exec -it KB-Pipeline-App bash

# OR run individual commands directly:

# Run all unit tests with coverage
docker exec KB-Pipeline-App python -m pytest tests/unit/ -v

# Run a single test file
docker exec KB-Pipeline-App python -m pytest tests/unit/test_base_spider.py -v

# Lint and format (run before every commit)
docker exec KB-Pipeline-App ruff check .
docker exec KB-Pipeline-App black .

# Apply database migrations
docker exec KB-Pipeline-App alembic upgrade head

# Initialise MinIO buckets
docker exec KB-Pipeline-App python -c "from config.storage import StorageClient; StorageClient().ensure_buckets()"

# Run a spider
docker exec KB-Pipeline-App scrapy crawl hdb

# Stop everything
docker compose down
```

## Architecture

### Data flow (end-to-end)
```
Scrapy/Playwright crawlers
  → raw HTML/PDF → MinIO (raw-html / raw-pdf buckets)
  → raw_documents table (PostgreSQL) with SHA-256 content_hash
  → processors/ (BeautifulSoup + pdfplumber)
  → processed text → MinIO (processed bucket)
  → processed_chunks table (PostgreSQL)
  → embedders/ (OpenAI text-embedding-3-large, batch 2048)
  → Pinecone (primary) + pgvector (fallback)
  → FastAPI /retrieve endpoint
```

### Module responsibilities
- `crawlers/` — Scrapy spiders, one per source. All must extend `BaseCrawler` from `crawlers/base.py`. HDB and CPF require Playwright for JS rendering. Subclasses set `source_name` (lowercase, e.g. `"hdb"`) and implement `get_start_urls() -> list[str]` and `parse_document(response) -> Generator`. `handle_response` (base) does SHA-256 → MinIO upload → DB insert automatically. For JS pages, yield `scrapy.Request(url, meta={"playwright": True}, callback=self.handle_response)`.
- `processors/` — HTML extraction (BeautifulSoup), PDF extraction (pdfplumber → PyMuPDF fallback), semantic chunking (LangChain RecursiveCharacterTextSplitter, 512 tokens / 64 overlap), metadata extraction.
- `embedders/` — OpenAI embedding service and vector store upsert (Pinecone + pgvector).
- `storage/` — `StorageClient` wraps boto3 for MinIO. 4 buckets: `raw-html`, `raw-pdf`, `processed`, `embeddings`. Key patterns: `{source}/{date}/{id}` for content buckets, `{batch_id}/{chunk_id}` for embeddings.
- `config/migrations/` — Alembic migrations. Migration `001` creates `sources`, `raw_documents`, `processed_chunks` and pre-seeds the 5 source rows.

### Database schema (PostgreSQL + pgvector)
- `sources` — the 5 agencies (id, name, url, crawl_config JSONB)
- `raw_documents` → FK to `sources` — one row per crawled URL (content_hash SHA-256, raw_html, raw_text)
- `processed_chunks` → FK to `raw_documents` — one row per chunk (chunk_text, chunk_index, metadata_json JSONB, embedding_id)

### Infrastructure (Docker Compose)
| Service | Image | Port | Credentials |
|---------|-------|------|-------------|
| postgres | pgvector/pgvector:pg16 | 5432 | user / pass / sg_property_kb |
| redis | redis:7-alpine | 6379 | — |
| minio | minio/minio:latest | 9000 (API), 9001 (console) | minioadmin / minioadmin |
| app | Dockerfile | — | reads .env |

All backing services have health checks; the `app` container waits for all three to be healthy before starting.

## Coding Conventions

- All classes must have docstrings.
- Use `structlog` for logging — never `print()`.
- All crawlers must extend `BaseCrawler` from `crawlers/base.py`.
- Retry logic: 3 retries with exponential backoff (use `tenacity`) on all HTTP and external API calls.
- Always check `robots.txt` before crawling any new URL.
- SHA-256 hash every document for change detection.
- Catch specific exceptions — never swallow errors silently.
- Type hints required on all function signatures.

## Testing Rules

- 80% minimum coverage for `/processors` and `/embedders` (enforced by `--cov-fail-under=80` in pytest config).
- Mock all OpenAI, Pinecone, and boto3 calls in unit tests.
- Integration tests run manually against live sites — not in CI.

## Critical Implementation Notes

- JS-rendered pages: use Playwright for HDB (`/residential/*`) and CPF (`/member/home-ownership`).
- Crawler blocking: polite delays 2–5 s, rotate user agents.
- Retry backoff: exponential backoff enabled (Scrapy `RETRY_BACKOFF_ENABLED`) with 60s cap. Retries on 429, 5xx errors — prevents hammering failing servers.
- PDF extraction: pdfplumber first, PyMuPDF fallback; flag scanned PDFs for OCR queue.
- Pinecone namespaces per source: `hdb`, `ura`, `iras`, `mas`, `cpf` + `all` (unified).
- pgvector index: `HNSW ef_construction=128 m=16`, dimension 3072.
- Celery Beat schedule: full crawl weekly Sunday 02:00 SGT, change detection daily 06:00 SGT.

## Task Reference

Week 1: 1.1 repo ✓, 1.2 docker ✓, 1.3 scaffold ✓, 1.4 DB schema ✓, 1.5 S3 buckets ✓, 1.6 base crawler ✓, 1.7 HDB ✓, 1.8 URA ✓, 1.9 IRAS ✓, 1.10 MAS ✓, 1.11 CPF ✓, 1.12 integration tests ✓
Week 2: 2.1 HTML extractor, 2.2 PDF extractor, 2.3 tables, 2.4 metadata, 2.5 chunking, 2.6 validation, 2.7 embeddings, 2.8 Pinecone, 2.9 pgvector, 2.10 change detection, 2.11 pipeline, 2.12 unit tests
Week 3: 3.1 retrieval API, 3.2 hybrid retrieval, 3.3 query expansion, 3.4 filtering, 3.5 scheduling, 3.6 incremental, 3.7 monitoring, 3.8–3.10 eval, 3.11–3.13 docs/CLI/cleanup
