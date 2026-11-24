# Singapore Property Knowledge Base (KB-Pipeline)

A data pipeline that turns Singapore government property regulations into a searchable knowledge base for a property-advisory AI agent (RAG: Retrieval-Augmented Generation).

The pipeline crawls five official sources, extracts and cleans the text, splits it into chunks, generates embeddings, and serves hybrid (vector + keyword) search through a FastAPI `/retrieve` endpoint.

| Code | Source | What we extract |
|---|---|---|
| `hdb` | Housing & Development Board (hdb.gov.sg) | Flat eligibility, grants, BTO/resale rules |
| `ura` | Urban Redevelopment Authority (ura.gov.sg) | Private property and development guidelines |
| `iras` | Inland Revenue Authority (iras.gov.sg) | Stamp duties (BSD/ABSD/SSD), property tax |
| `mas` | Monetary Authority of Singapore (mas.gov.sg) | LTV limits, TDSR/MSR, mortgage rules |
| `cpf` | CPF Board (cpf.gov.sg) | CPF housing usage, withdrawal limits |

> **Consumer:** the `sg-property-agent` app (LangGraph backend, React frontend, WhatsApp channel; it lives on other branches, see [Branches](#7-branches-what-lives-where)) calls `POST /retrieve` on this service through its `retrieve_property_info` tool.

---

## Contents

1. [Architecture](#1-architecture)
2. [Libraries and why each is used](#2-libraries-and-why-each-is-used)
3. [Repository layout](#3-repository-layout)
4. [Getting started](#4-getting-started)
5. [Code flow, step by step](#5-code-flow-step-by-step)
6. [Data model and storage layout](#6-data-model-and-storage-layout)
7. [Branches: what lives where](#7-branches-what-lives-where)
8. [Known issues](#8-known-issues)
9. [Verification plan (are the results correct?)](#9-verification-plan-are-the-results-correct)
10. [Next steps and the libraries each one needs](#10-next-steps-and-the-libraries-each-one-needs)

---

## 1. Architecture

```mermaid
flowchart LR
    subgraph S1["Stage 1: Crawl (Scrapy + Playwright)"]
        SP["Spiders<br/>hdb/ura/iras/mas/cpf/generic"] --> S3P["S3Pipeline<br/>upload raw + extract text + hash"]
        S3P --> PGP["PostgresPipeline<br/>dedup + change detection"]
    end
    subgraph S2["Stage 2: Process"]
        MD["MetadataExtractor"] --> CH["DocumentChunker<br/>512 tok / 64 overlap"] --> VA["ChunkValidator"]
    end
    subgraph S3["Stage 3: Embed"]
        EM["EmbeddingService<br/>OpenRouter → OpenAI fallback"] --> PC["Pinecone<br/>(per-source + 'all' namespaces)"]
        EM -.fallback.-> PV["pgvector"]
    end
    subgraph S4["Stage 4: Retrieve (FastAPI)"]
        QE["QueryExpander (LLM)"] --> FI["Filter inference"] --> HY["Vector + BM25 → RRF"]
    end
    GOV[(Gov websites)] --> SP
    S3P --> MINIO[(MinIO / S3<br/>raw HTML/PDF)]
    PGP --> RD[(raw_documents)]
    RD --> MD
    VA --> PCH[(processed_chunks)]
    PCH --> EM
    PC --> HY
    PV --> HY
    PCH --> HY
    AGENT["sg-property-agent"] -->|POST /retrieve| QE
    BEAT["Celery Beat"] -->|schedule| WORKER["Celery worker"] --> S1
```

Every stage reads its input from PostgreSQL and writes its output back with a status flag, so stages can run together or on their own:

```
raw_documents.status:  pending ──(process)──▶ processed      (or failed / deleted)
processed_chunks.embedding_id:  NULL ──(embed)──▶ <vector id>
```

---

## 2. Libraries and why each is used

All runtime dependencies are declared in [pyproject.toml](../pyproject.toml).

### Crawling

| Library | Used in | Purpose |
|---|---|---|
| **Scrapy** ≥2.11 | [crawlers/](../crawlers/) | Crawl engine: scheduling, link following, robots.txt, retry with backoff, download delay, item pipelines, crawl stats |
| **scrapy-playwright** / **Playwright** | [crawlers/scrapy_settings.py](../crawlers/scrapy_settings.py), [crawlers/base.py](../crawlers/base.py) | Headless Chromium for JavaScript-rendered pages (HDB, CPF). Turned on per source with `js_rendering: true` |
| **Twisted** (asyncio reactor, installed with Scrapy) | `TWISTED_REACTOR` setting | Event loop that Scrapy runs on. The asyncio reactor is required by Playwright |

### Extraction and processing

| Library | Used in | Purpose |
|---|---|---|
| **BeautifulSoup4** + **lxml** | [processors/html_extractor.py](../processors/html_extractor.py), [crawlers/base.py](../crawlers/base.py) | Parse HTML, remove noise (nav/footer/cookie banners), pick the main content node via `content_selectors`, collect the h1–h6 heading hierarchy |
| **pdfplumber** | [processors/pdf_extractor.py](../processors/pdf_extractor.py), [processors/table_extractor.py](../processors/table_extractor.py) | Primary PDF text and table extraction |
| **PyMuPDF** (`fitz`) | [processors/pdf_extractor.py](../processors/pdf_extractor.py) | Fallback PDF text extraction, plus scanned-PDF detection (image coverage and text density per page) |
| **langchain-text-splitters** | [processors/chunker.py](../processors/chunker.py) | `RecursiveCharacterTextSplitter`: splits on paragraph, then line, then word |
| **tiktoken** (`cl100k_base`) | chunker, validator, embedder | Counts tokens with the same tokenizer as the OpenAI embedding model, so chunk sizes are exact |

### Embeddings, vector stores and retrieval

| Library | Used in | Purpose |
|---|---|---|
| **openai** SDK | [embedders/embedding_service.py](../embedders/embedding_service.py), [api/query_expander.py](../api/query_expander.py) | Calls `text-embedding-3-large` (3072 dims) through **OpenRouter** first (OpenAI-compatible), falling back to OpenAI directly. Also used for the query-expansion chat call (`openrouter_chat_model`, default `openai/gpt-4o-mini`) |
| **pinecone** | [embedders/pinecone_store.py](../embedders/pinecone_store.py) | Primary vector index (cosine). Each vector is written to a per-source namespace and to the shared `all` namespace |
| **pgvector** (+ `pgvector/pgvector:pg16` image) | [embedders/pgvector_store.py](../embedders/pgvector_store.py) | Fallback vector store inside PostgreSQL (`processed_chunks.embedding vector(3072)`) |
| **rank-bm25** | [embedders/bm25_store.py](../embedders/bm25_store.py) | In-memory BM25Okapi keyword index, fused with vector results by Reciprocal Rank Fusion |
| **tenacity** | embedding service, vector stores | Retry with exponential backoff for external API calls |

### Storage, API, scheduling, utilities

| Library | Used in | Purpose |
|---|---|---|
| **SQLAlchemy 2** + **psycopg2-binary** | [config/database.py](../config/database.py), [config/models.py](../config/models.py) | ORM and PostgreSQL driver |
| **Alembic** | [alembic/versions/](../alembic/versions/) | Schema migrations. Migration 001 also seeds the 5 sources |
| **boto3** | [config/storage.py](../config/storage.py) | S3 client for MinIO (locally) or AWS S3: raw HTML/PDF and embedding archives |
| **FastAPI** + **uvicorn** | [api/](../api/) | `/retrieve` plus pipeline control and monitoring endpoints (`/crawl`, `/process`, `/embed`, `/jobs`, `/stats`, `/admin/reindex-bm25`) |
| **Celery[redis]** + **Redis** | [config/celery_app.py](../config/celery_app.py), [tasks/](../tasks/) | Celery Beat triggers scheduled crawls; the worker runs the pipeline. Redis is the broker and result backend |
| **pydantic** / **pydantic-settings** | [config/settings.py](../config/settings.py), [api/schemas.py](../api/schemas.py) | Typed settings from `.env`; API request/response validation |
| **structlog** | [config/logger.py](../config/logger.py) | Structured JSON logs with per-run context (`run_id`, `source`, `url`) |
| **httpx** | [config/notifications.py](../config/notifications.py) | Slack webhook on final crawl-task failure; also used by [eval/retrieval_eval.py](../eval/retrieval_eval.py) to call `/retrieve` |
| **PyYAML** | [config/celery_app.py](../config/celery_app.py), [config/sync_sources.py](../config/sync_sources.py) | Reads [config/sources.yml](../config/sources.yml) (source definitions and cron schedules); the DB copy is authoritative at runtime |
| **python-dotenv** | settings | `.env` loading |

### Development

| Tool | Purpose |
|---|---|
| **pytest**, **pytest-cov**, **pytest-asyncio** | Unit tests. Coverage gate is 80% (`--cov-fail-under=80`) |
| **ruff**, **black**, **mypy** | Lint, format and type checks (line length 100) |
| **GitHub Actions** | [.github/workflows/ci.yml](../.github/workflows/ci.yml): ruff, black --check and unit tests on push/PR to `main`/`master` |
| **Docker Compose** | Runs the app, API, worker, beat, Postgres, Redis, MinIO and Grafana |
| **Grafana** | Dashboard over Postgres: crawl status, document/chunk counts, embedding coverage, task history |


### Libraries by file (what is actually imported)

Generated from the source imports. Standard-library and project-internal imports are omitted. Libraries that are installed but never imported directly (used by another library) are listed after the table.

| File | Third-party libraries imported |
|---|---|
| [run_pipeline.py](../run_pipeline.py) | `structlog` |
| [crawlers/base.py](../crawlers/base.py) | `scrapy`, `bs4` (BeautifulSoup), `scrapy_playwright` |
| [crawlers/items.py](../crawlers/items.py) | `scrapy` |
| [crawlers/pipelines.py](../crawlers/pipelines.py) | `scrapy` (DropItem), `sqlalchemy` (func) |
| [crawlers/runner.py](../crawlers/runner.py) | `scrapy` (CrawlerProcess, signals) |
| [crawlers/spiders/generic.py](../crawlers/spiders/generic.py) | `scrapy`, `scrapy_playwright` |
| [processors/html_extractor.py](../processors/html_extractor.py) | `bs4` |
| [processors/pdf_extractor.py](../processors/pdf_extractor.py) | `pdfplumber`, `fitz` (PyMuPDF) |
| [processors/table_extractor.py](../processors/table_extractor.py) | `bs4`, `pdfplumber` |
| [processors/chunker.py](../processors/chunker.py) | `langchain_text_splitters`, `tiktoken` |
| [processors/validator.py](../processors/validator.py) | `tiktoken` |
| [processors/runner.py](../processors/runner.py) | `sqlalchemy`, `structlog` |
| [embedders/embedding_service.py](../embedders/embedding_service.py) | `openai`, `tenacity`, `tiktoken` |
| [embedders/pinecone_store.py](../embedders/pinecone_store.py) | `pinecone`, `tenacity` |
| [embedders/pgvector_store.py](../embedders/pgvector_store.py) | `sqlalchemy`, `tenacity` |
| [embedders/bm25_store.py](../embedders/bm25_store.py) | `rank_bm25`, `sqlalchemy` |
| [embedders/pipeline.py](../embedders/pipeline.py) | `openai`, `sqlalchemy`, `tiktoken` |
| [api/app.py](../api/app.py) | `fastapi`, `sqlalchemy`, `structlog` |
| [api/schemas.py](../api/schemas.py) | `pydantic` |
| [api/dependencies.py](../api/dependencies.py), [api/query_expander.py](../api/query_expander.py) | `openai` |
| [api/retrieval.py](../api/retrieval.py) | `sqlalchemy` |
| [config/settings.py](../config/settings.py) | `pydantic_settings` |
| [config/database.py](../config/database.py) | `sqlalchemy` |
| [config/models.py](../config/models.py) | `sqlalchemy`, `pgvector` |
| [config/storage.py](../config/storage.py), [clean_data.py](../clean_data.py) | `boto3`, `botocore` |
| [config/celery_app.py](../config/celery_app.py) | `celery`, `yaml` (PyYAML), `structlog` |
| [config/sync_sources.py](../config/sync_sources.py) | `yaml` |
| [config/notifications.py](../config/notifications.py) | `httpx`, `structlog` |
| [config/logger.py](../config/logger.py) | `structlog` |
| [tasks/pipeline_tasks.py](../tasks/pipeline_tasks.py) | `sqlalchemy`, `structlog` |
| [alembic/](../alembic/) (env and versions 001–008) | `alembic`, `sqlalchemy` |
| [eval/retrieval_eval.py](../eval/retrieval_eval.py) | `httpx` |
| [backfill_pgvector.py](../backfill_pgvector.py) | `sqlalchemy` |

**Installed but not imported directly:** `lxml` (BeautifulSoup parser in `crawlers/base.py`), `playwright` (browser engine driven by `scrapy-playwright`), `psycopg2-binary` (SQLAlchemy's PostgreSQL driver), `redis` (Celery broker client, via `celery[redis]`), `uvicorn` (runs the FastAPI app), `python-dotenv` (declared; `pydantic-settings` reads `.env` itself), `Twisted` (Scrapy's engine; the asyncio reactor is set in `scrapy_settings.py`).

---

## 3. Repository layout

```
run_pipeline.py            CLI entry point: crawl → process → embed (flags below)
clean_data.py              Wipes DB tables and MinIO prefixes (dev only!)
setup.sh                   One-command local setup (Docker, migrations, source sync)
config/
  settings.py              Pydantic settings (.env)
  database.py              SQLAlchemy engine + SessionLocal
  models.py                Source, RawDocument, ProcessedChunk, CrawlJob, TaskExecution
  sources.yml              Source definitions: URLs, selectors, tag_config, schedules
  sync_sources.py          Copies sources.yml → sources.crawl_config (JSONB)
  storage.py               S3/MinIO helpers
  celery_app.py            Celery app + Beat schedule built from sources.yml
  logger.py, notifications.py
crawlers/
  base.py                  BaseCrawler: DB-driven config, link filtering, Playwright meta
  spiders/{hdb,ura,iras,mas,cpf}.py   Thin subclasses (config lives in DB)
  spiders/generic.py       Crawls any active DB source without its own spider
  pipelines.py             S3Pipeline (upload + extract + hash), PostgresPipeline (dedup/change detection)
  runner.py                Starts spiders, records crawl_jobs + summary
processors/
  html_extractor.py, pdf_extractor.py, table_extractor.py
  metadata_extractor.py    title / section / effective_date / tags
  chunker.py               Token-based chunking + heading_path breadcrumbs
  validator.py             Chunk quality gate
  runner.py                process_pending_documents()
embedders/
  embedding_service.py     OpenRouter → OpenAI embeddings, batching, token logging
  pinecone_store.py, pgvector_store.py, bm25_store.py
  pipeline.py              embed_chunks(), cleanup_deleted_documents(), purge_vectors()
api/
  app.py                   FastAPI app
  retrieval.py             RetrievalService (vector / hybrid + RRF)
  query_expander.py        LLM phrasings + entity extraction
  metadata_filter_inference.py   Rule-based filter inference from the query
tasks/pipeline_tasks.py    Celery tasks (crawl in a subprocess, process, embed) + task_executions bookkeeping
eval/                      retrieval_eval.py (hit@k, MRR, fact support, filters, latency) + testset.csv
grafana/                   Provisioned datasource + dashboard (real tables)
backfill_pgvector.py       Restore pgvector rows from the S3 embedding archive
ingest_offline_docs.py     Ingest local HTML/PDF snapshots into an isolated eval DB/index
alembic/                   Migrations 001–008 (008 = HNSW index via halfvec)
tests/unit, tests/integration
docs/                      Architecture deep-dives and the original task breakdown
```

---

## 4. Getting started

### Prerequisites
- Docker Desktop
- API keys: OpenRouter and/or OpenAI (embeddings), Pinecone (optional; pgvector is used without it)

### Setup

```bash
bash setup.sh
```

[setup.sh](../setup.sh) does the following:
1. Copies `.env.example` to `.env`.
2. Runs `docker compose up -d --build`.
3. Waits until the services are healthy.
4. Runs `alembic upgrade head` (creates the schema and seeds the 5 sources).
5. Runs `python -m config.sync_sources` (copies [config/sources.yml](../config/sources.yml) into `sources.crawl_config`).
6. Creates the MinIO bucket.

Add your keys to `.env` before crawling. All Python runs **inside** the `KB-Pipeline-App` container.

| Service | URL |
|---|---|
| Retrieval API | http://localhost:8000 (`/docs` for Swagger) |
| Grafana | http://localhost:3000 (admin / admin), dashboard "KB Pipeline Overview" |
| MinIO console | http://localhost:9001 (minioadmin / minioadmin) |
| PostgreSQL | localhost:5432 (kb_user / kb_pass, db `kb_pipeline_db`) |
| Redis | localhost:6379 |

### Running the pipeline

```bash
APP="docker exec KB-Pipeline-App"

$APP python run_pipeline.py                         # all stages, all sources
$APP python run_pipeline.py hdb iras                # only these sources
$APP python run_pipeline.py --crawl-only -S CLOSESPIDER_PAGECOUNT=10   # quick test crawl
$APP python run_pipeline.py --process-only          # chunk pending docs
$APP python run_pipeline.py --embed-only            # embed un-embedded chunks
$APP python run_pipeline.py --skip-embed            # crawl + process
$APP python run_pipeline.py --incremental           # job_type=incremental
$APP python run_pipeline.py hdb --purge-vectors     # DESTRUCTIVE: wipe Pinecone namespace(s)
```

### Querying

```bash
curl -X POST localhost:8000/retrieve -H 'Content-Type: application/json' -d '{
  "query": "What is the ABSD for a PR buying a second condo?",
  "top_k": 5,
  "search_mode": "hybrid",
  "filters": {"source": ["iras"]}
}'
```

### Tests and lint

```bash
$APP pytest                                   # unit tests, 80% coverage gate, skips "integration"
$APP pytest -m integration tests/integration  # live sites + infra
$APP ruff check . && $APP black --check .
```

### Configuration reference (`.env`)

| Variable | Purpose |
|---|---|
| `DATABASE_URL`, `REDIS_URL` | Postgres and Redis connections (use the service names `postgres`/`redis` inside Docker) |
| `S3_ENDPOINT`, `S3_ACCESS_KEY`, `S3_SECRET_KEY`, `S3_REGION`, `S3_BUCKET` | MinIO/S3 |
| `OPENROUTER_API_KEY`, `OPENROUTER_BASE_URL` | Primary provider for embeddings and query expansion |
| `OPENROUTER_CHAT_MODEL` | Query-expansion LLM (default `openai/gpt-4o-mini`) |
| `OPENAI_API_KEY` | Fallback embedding provider |
| `PINECONE_API_KEY`, `PINECONE_INDEX`, `PINECONE_ENVIRONMENT` | Vector index |
| `CRAWL_DELAY`, `CRAWL_USER_AGENT`, `CRAWL_RESPECT_ROBOTS_TXT`, `CRAWL_MAX_RETRIES` | Global crawl defaults (each source can override them in `sources.yml`) |
| `SLACK_WEBHOOK_URL` | Failure notifications (optional) |
| `CELERY_TIMEZONE` | Default `Asia/Singapore` |
| `ADMIN_API_KEY` | When set, admin endpoints require the `X-API-Key` header (empty = open, local dev only) |
| `BM25_REFRESH_SECONDS` | BM25 index auto-rebuild age (default 300, 0 = never) |
| `LOG_LEVEL` | structlog level |

---

## 5. Code flow, step by step

Entry point: `run_full_pipeline()` in [run_pipeline.py](../run_pipeline.py). It is called from the CLI or from the Celery task `run_source_pipeline_task` in [tasks/pipeline_tasks.py](../tasks/pipeline_tasks.py).

### Step 0: Source configuration
1. [config/sources.yml](../config/sources.yml) defines, for each source: `start_urls`, `allowed_domains`, `target_prefixes` / `skip_prefixes`, `blocked_subdomains`, `js_rendering`, `crawl_delay`, `content_selectors`, `content_keywords_filter`, `tag_config` (keyword → tag rules) and a `schedule` (cron).
2. [config/sync_sources.py](../config/sync_sources.py) upserts this into `sources.crawl_config` (JSONB). **The crawlers read config only from the database**, not from the YAML file.
3. [config/celery_app.py](../config/celery_app.py) builds the Celery Beat schedule from `sources.crawl_config['schedule']` in the DB (the YAML is only a fallback for a fresh, un-synced database). The default is a full crawl on Sunday at 02:00 SGT and an incremental crawl daily at 06:00 SGT.

**Libraries used in this step**

```python
import yaml                                   # config/sync_sources.py, config/celery_app.py
from celery import Celery                     # config/celery_app.py
from celery.schedules import crontab          # cron strings -> Beat schedule
from pydantic_settings import BaseSettings    # config/settings.py (reads .env)
```

### Stage 1: Crawl ([crawlers/runner.py](../crawlers/runner.py) → `run_crawlers`)
1. For each source code, create a `crawl_jobs` row (`status=running`) and schedule its spider. When no source is given, the `generic` spider is scheduled too.
2. **Spider start** ([crawlers/base.py](../crawlers/base.py) `BaseCrawler`):
   - Load `crawl_config` from the DB.
   - Apply `DOWNLOAD_DELAY`, `ROBOTSTXT_OBEY` and `USER_AGENT` from that config.
   - Yield requests for `start_urls`, adding Playwright meta when `js_rendering` is on.
3. **`handle_response` → `parse_document`**:
   - **PDF** (detected by URL or `Content-Type`): yield a `CrawlItem` with `raw_pdf`.
   - **HTML**: run a quick main-content extraction. Skip the page if it is shorter than `min_content_length` or fails `content_keywords_filter`. Otherwise yield a `CrawlItem` with `raw_html` and the source's `content_selectors`.
4. **`_follow_links`**: a link is followed only if all of these hold:
   - scheme is http/https;
   - not a static asset;
   - domain is in `allowed_domains` and not a blocked subdomain;
   - path is not in `skip_prefixes`, and is in `target_prefixes` when that list is set (PDFs always pass the path checks).
5. **`S3Pipeline`** ([crawlers/pipelines.py](../crawlers/pipelines.py)):
   - Upload the raw file to `raw-html/` or `raw-pdf/{source}/{date}/{md5(url)[:12]}`.
   - Run the full `HTMLExtractor` or `PDFExtractor` (below).
   - Use the extractor text as is: tables are already placed **inline, in document position, as Markdown** (never appended a second time).
   - Set `raw_text` and `content_hash = sha256(normalised text)`.
   - Record `extraction_flags` (warnings, word count, table count, title, headings, `needs_ocr`, `used_fallback`).
6. **`PostgresPipeline`**:
   1. **Cross-URL duplicate**: if another URL already has the same hash, skip the item and delete its S3 object.
   2. **Change detection** by `(source_id, url)`:
      - new URL → insert with `status=pending`;
      - hash changed → update the row and reset to `pending`;
      - unchanged → bump `last_seen_at` only.
   3. **On close**: URLs in the DB but not seen in this crawl are marked `status=deleted`.
7. Spider stats (`pages_new`, `pages_changed`, `pages_deleted`, errors) are written back to `crawl_jobs`, and a summary table is printed.
8. **Post-crawl cleanup** (`EmbeddingPipeline.cleanup_deleted_documents`) deletes the vectors and chunks of `deleted` documents.

**Libraries used in this stage**

```python
# crawlers/base.py
import scrapy
from bs4 import BeautifulSoup
from scrapy_playwright.page import PageMethod        # JS rendering per request

# crawlers/runner.py
from scrapy import signals
from scrapy.crawler import CrawlerProcess
from scrapy.utils.project import get_project_settings

# crawlers/pipelines.py
from scrapy.exceptions import DropItem
from sqlalchemy import func

# config/storage.py
import boto3
from botocore.config import Config                    # S3 / MinIO client

# processors/pdf_extractor.py (imported inside the methods that use them)
import pdfplumber                                     # primary PDF text + tables
import fitz                                           # PyMuPDF: fallback text + scanned-PDF detection
```

**Extractors**
- [HTMLExtractor](../processors/html_extractor.py):
  - parses with BeautifulSoup and removes noise tags and classes;
  - picks the content node via `content_selectors`, then `main`/`article`/`role=main`, then `body`;
  - walks the content in document order, emitting each table as Markdown at its position, plus h1–h6 headings, and normalises whitespace.
- [PDFExtractor](../processors/pdf_extractor.py):
  - extracts per-page text with pdfplumber, placing detected tables (Markdown) at their vertical position; falls back to PyMuPDF on error or empty text (tables are then appended at the end);
  - detects scanned PDFs (few words per page, large image coverage), which sets `needs_ocr`.

### Stage 2: Process ([processors/runner.py](../processors/runner.py) → `process_pending_documents`)
For each `raw_documents` row with `status=pending`:
1. Rebuild an `ExtractedDocument` from `raw_text` and `extraction_flags` (title, headings). No re-download is needed.
2. **[MetadataExtractor](../processors/metadata_extractor.py)** produces `title`, `source_agency`, `section` (first heading), `effective_date` (regex date patterns → ISO) and `tags` (`property_type`, `citizenship`, `topic`, matched with the source's `tag_config`).
3. **[DocumentChunker](../processors/chunker.py)** first separates inline Markdown tables from prose. Each table stays atomic as a `chunk_type="table"` chunk (tables over 512 tokens are split by row groups with the header repeated). Prose uses `RecursiveCharacterTextSplitter.from_tiktoken_encoder(chunk_size=512, chunk_overlap=64, separators=["\n\n", "\n", " "])`. Each chunk gets:
   - the document metadata plus `chunk_index` and `chunk_type`;
   - a `heading_path` breadcrumb, computed from the chunk's offset in the text;
   - an exact tiktoken count.
4. **[ChunkValidator](../processors/validator.py)** applies two levels of checks:
   - **Errors (the chunk is dropped):** empty text, NUL bytes, invalid `chunk_type`, fewer than 50 tokens (tables exempt) or more than 600 tokens, boilerplate-only, duplicate within the document (SHA-256).
   - **Warnings (logged, chunk kept):** word-count mismatch, missing URL/source/metadata keys, malformed `heading_path`, possible mid-sentence split.
   - Surviving chunks are re-indexed from 0.
5. Delete the document's old chunks, insert the new `processed_chunks` rows, and set the document to `status=processed`. On an exception the status becomes `failed` and the traceback goes into `error_message`.

**Libraries used in this stage**

```python
# processors/chunker.py
import tiktoken
from langchain_text_splitters import RecursiveCharacterTextSplitter

# processors/validator.py
import tiktoken

# processors/runner.py
import structlog
from sqlalchemy.orm import Session
```

### Stage 3: Embed ([embedders/pipeline.py](../embedders/pipeline.py) → `EmbeddingPipeline.embed_chunks`)
1. Select chunks with `embedding_id IS NULL` whose document is not `deleted`. Re-processed documents get fresh chunks, so only new or changed content is embedded.
2. **[EmbeddingService](../embedders/embedding_service.py)**:
   - batches at most 2048 texts and 250k tokens per call;
   - calls OpenRouter with tenacity retries, switching to OpenAI for the rest of the run if OpenRouter keeps failing;
   - logs token usage per batch for cost tracking.
3. **Upsert**:
   - Pinecone, into namespaces `{source}` and `all`, with metadata `source_name`, `property_types`, `citizenship_types`, `topics`, `chunk_type`, `effective_date_ts`;
   - pgvector **always** (dual-write, same `{source}-{db_id}` vector ids), so the fallback is a real backup. If one store fails the other still serves; if both fail the chunks stay un-embedded and are retried on the next run.
4. Archive each embedding as JSON to S3 at `processed/embeddings/{date}/{vector_id}.json`.
5. Write `processed_chunks.embedding_id`.

**Libraries used in this stage**

```python
# embedders/embedding_service.py
import openai
import tiktoken
from openai import OpenAI                             # OpenRouter and OpenAI share this client
from tenacity import retry, retry_if_not_exception_type, stop_after_attempt, wait_exponential

# embedders/pinecone_store.py
from pinecone import Pinecone, ServerlessSpec
from tenacity import retry, stop_after_attempt, wait_exponential

# embedders/pgvector_store.py, embedders/pipeline.py
from sqlalchemy import text
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

# config/models.py (the vector column type)
from pgvector.sqlalchemy import Vector
```

### Stage 4: Retrieve ([api/retrieval.py](../api/retrieval.py) → `RetrievalService.retrieve`)
1. **Startup** ([api/dependencies.py](../api/dependencies.py)) creates the embedding service, Pinecone, pgvector, the BM25 index (built once from all embedded chunks) and the query expander. Each one degrades gracefully if unavailable.
2. **Query expansion** ([api/query_expander.py](../api/query_expander.py)):
   - expands abbreviations (ABSD, BSD, SSD, TDSR, MSR, LTV, EC, BTO, OA/SA, SC/PR, …);
   - asks the LLM for 2 alternative phrasings plus `property_type`, `citizenship` and `topic` entities;
   - falls back to `[query]` if the LLM call fails.
3. **Filter inference** ([api/metadata_filter_inference.py](../api/metadata_filter_inference.py)): regex rules map words such as "HDB", "condo", "PR" or "IRAS" to `source`, `property_type` and `citizenship_type` filters. These are merged (as a union) with the LLM entities and the user-supplied filters.
4. **For each phrasing**: embed it, then search.
   - `vector` mode: Pinecone, using one source's namespace when a single source is filtered, otherwise `all` with a `$in` filter. Falls back to pgvector.
   - `hybrid` mode (the default): take the top `5×top_k` from vector search and from BM25 (filtered the same way), fuse them with **Reciprocal Rank Fusion** `1/(60+rank_v) + 1/(60+rank_bm25)`, then load the chunk text and metadata from Postgres.
5. Combine phrasings by `(source_url, chunk_index)`: in hybrid mode scores are summed (RRF across phrasings) and normalised to (0, 1]; in vector mode the best cosine score is kept. Return the top `top_k`.
6. The response includes `inferred_filters`, `applied_filters`, a timing `trace` and `store_used`.

**Libraries used in this stage**

```python
# api/dependencies.py: the services wired together at startup
from embedders.bm25_store import BM25Store
from embedders.embedding_service import EmbeddingService
from embedders.pgvector_store import PgVectorStore
from embedders.pinecone_store import PineconeStore
from openai import OpenAI                             # query expansion LLM (via OpenRouter)

# embedders/bm25_store.py
from rank_bm25 import BM25Okapi

# api/app.py
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from sqlalchemy import desc, text

# api/schemas.py
from pydantic import BaseModel, Field
```

---

## 6. Data model and storage layout

| Table | Key columns |
|---|---|
| `sources` | `code` (hdb/ura/iras/mas/cpf), `name`, `base_url`, `crawl_config` JSONB (GIN index), `is_active` |
| `raw_documents` | `source_id`, `url` (unique per source), `content_hash`, `content_type`, `raw_text`, `s3_path`, `status` (pending/processed/failed/deleted), `needs_ocr`, `extraction_flags`, `last_seen_at` |
| `processed_chunks` | `document_id` (cascade delete), `chunk_text`, `chunk_index`, `token_count`, `embedding_id`, `embedding vector(3072)`, `metadata_json` |
| `crawl_jobs` | per-source crawl run: `job_type`, `status`, `pages_found/new/changed/deleted/errored` |
| `task_executions` | Celery task history (migration 007), written by every Celery task and read by `GET /jobs` |

MinIO bucket `sg-property-kb`:
```
raw-html/{source}/{YYYY-MM-DD}/{url_hash}.html
raw-pdf/{source}/{YYYY-MM-DD}/{url_hash}.pdf
processed/{source}/{YYYY-MM-DD}/{url_hash}.txt
processed/embeddings/{YYYY-MM-DD}/{vector_id}.json
```

---

## 7. Branches: what lives where

Reviewed and merged on 2026-11-22. `dev` is the integration branch.

| Branch | Contents | Status |
|---|---|---|
| `dev` | This pipeline | Baseline |
| `master` | Older snapshot | Contained in `dev` |
| `features` | Improved HTML/PDF extraction (inline tables, coordinate-based PDF reading order) | **Merged** into `dev`. The conflict in `pdf_extractor.py` was resolved by keeping `dev`'s error tracking and richer scanned-PDF detection, and dropping debug prints and `[PAGE_START]` markers |
| `property-advisory-ai-advisory` | Monorepo with unrelated history (`KB-Pipeline/`, `sg-property-agent/`, `testing/`) | KB-Pipeline features **ported by hand** (below); a real merge would import the whole monorepo |
| `sg-property-agent` | Chat agent (LangGraph backend, React frontend, WhatsApp, stamp-duty calculator) | Separate application; not part of this repo |

### Ported or built from `property-advisory-ai-advisory`

| Feature | Where |
|---|---|
| Job-control API and history | `POST /crawl`, `/process`, `/embed`, `GET /jobs`, `GET /config` in [api/app.py](../api/app.py); Celery tasks writing `task_executions` in [tasks/pipeline_tasks.py](../tasks/pipeline_tasks.py); migration 007 |
| Scheduling from the DB | [config/celery_app.py](../config/celery_app.py) reads `crawl_config['schedule']`; [config/sync_sources.py](../config/sync_sources.py) now syncs it |
| Reliable repeated crawls | The crawl task runs `run_pipeline.py` in a subprocess. The monorepo's in-process `CrawlerRunner` + `reactor.run()` would still fail on the second crawl in one worker |
| Grafana | [grafana/](../grafana/) plus a compose service. The dashboard was **rewritten** against real tables (the original queried non-existent `crawl_runs` / `embedding_stats`) |
| Offline eval ingestion, QA docs, Q&A set | [ingest_offline_docs.py](../ingest_offline_docs.py), [docs/QA_METRICS.md](../docs/QA_METRICS.md), [docs/QA_TESTING_GUIDE.md](../docs/QA_TESTING_GUIDE.md), [eval/testset.csv](../eval/testset.csv) |
| Bug fixes | Missing `func` import, `content_selectors` plumbing, `open_spider(spider=None)` signature, merge of the two Alembic heads, `clean_data.py` clearing `task_executions` |

Deliberately **not** taken: `config/settings.py` (typo `redis://l ocalhost`), the verbose INFO logging additions, the rewrite of migration 001 (editing an applied migration does not update existing databases), the commented-out `test_chunker.py`, and the DeepEval / agent-routing suites (they target the chat agent, not the KB).

Also fixed on `dev` (not fixed on any other branch): `GenericSpider` used the removed Scrapy API `make_requests_from_url` and lost the source config on followed links. SQLAlchemy is now pinned `<2.1`, because 2.1 defaults `postgresql://` to psycopg3 while we ship psycopg2.

---

## 8. Known issues

### Resolved in this revision

| # | Issue | Fix |
|---|---|---|
| 1 | Tables duplicated in `raw_text` | The `features` extractors inline tables; the append step was removed from `S3Pipeline` |
| 2 | No `chunk_type="table"` chunks; tables split mid-row | The chunker keeps tables atomic and splits large ones by row groups with a repeated header; the validator exempts tables from the 50-token minimum |
| 3 | pgvector only written when Pinecone failed | Dual-write in `EmbeddingPipeline.embed_chunks`; [backfill_pgvector.py](../backfill_pgvector.py) restores older vectors from S3 |
| 4 | pgvector HNSW index missing and unused | Migration 001 created it, but auto-generated migration `9d14d2974166` dropped it, and queries cast to `vector` so they could not use it anyway. Migration 008 recreates it on `embedding::halfvec(3072)` and queries now use the same expression. Re-check `alembic revision --autogenerate` output: it may try to drop this expression index again |
| 5 | BM25 index stale until API restart | TTL auto-rebuild (`BM25_REFRESH_SECONDS`) with an atomic swap, plus `POST /admin/reindex-bm25`; deleted documents are excluded |
| 6 | Pinecone filter missing `topic` / `effective_date` | Metadata now has `topics`, `chunk_type`, `effective_date_ts`; `/retrieve` accepts `filters.topic` |
| 7 | Hybrid `score` meaningless across requests | RRF is summed across phrasings and normalised to (0, 1] |
| 8 | Housekeeping | Removed `processors/__init__ copy.py` and the committed `celerybeat-schedule*` (now git-ignored); CLAUDE.md rewritten |
| 9 | CI ignored `dev` | CI now also triggers on `dev` |
| 10 | No check that facts are backed by retrieved text | [eval/retrieval_eval.py](../eval/retrieval_eval.py) `Must_Contain` column: exact figures must appear in the retrieved chunks |

### Still open / caveats

- Pinecone vectors created before this change lack `topics` / `effective_date_ts`; re-embed (`--purge-vectors`, then `--embed-only`) to use those filters.
- Existing documents keep their old (duplicated-table) `raw_text` until re-crawled. Run a full crawl to refresh; the hash now includes table text, so those pages will register as "changed" once.
- The Beat schedule is read when Beat starts; restart `beat` after changing a schedule.
- `ADMIN_API_KEY` is optional; set it before exposing the API outside a trusted network.
- `eval/testset.csv` has no `Must_Contain` / `Topic` columns yet; add them for numeric-fact checks and per-topic reports.
- None of these changes were built or test-run in this revision (project preference). Validate by running a crawl, then `eval/retrieval_eval.py`.

---

## 9. Verification plan (are the results correct?)

Goal: each layer is measured against a **ground truth**, with a target and a command that produces the number. Targets come from the team's QA plan (`testing/QA_METRICS.md` on `property-advisory-ai-advisory`) and the original task breakdown ([docs/task-breakdown.md](../docs/task-breakdown.md)). Targets marked *(proposed)* are new suggestions; agree on them as a team.

### 9.1 Ground-truth datasets to build or adopt

| Dataset | Content | Where it comes from |
|---|---|---|
| **Expected URL list** per source | Pages that must be crawled | Manual list; `estimated_pages` in `sources.yml` as a sanity bound |
| **Extraction gold set** | ~20 HTML pages and ~10 PDFs with hand-verified clean text and tables | `testing/datasets/{html,pdfs}` and `testing/evaluation/eval_docs/{hdb,ura,iras,mas,cpf}` (offline snapshots, so tests don't depend on live sites) |
| **Retrieval Q&A set** | Question → expected source URL(s) → expected answer. Minimum 50: HDB eligibility 10, stamp duty 10, CPF 8, MAS 8, URA 7, cross-source 7 | Start from `testing/evaluation/testset.csv` (it already has `Question, Answer, Source URL`) and extend; `generate_synthetic_testset.py` can draft more, but **a human must verify every row** |
| **Edge-case set** | Abbreviation-heavy ("ABSD for PR 2nd property"), ambiguous, multi-source, Mandarin, out-of-scope | Task 3.10 |
| **Numeric facts set** | Rates and limits that must be exact (ABSD %, LTV %, BSD tiers, CPF limits), each with its official source URL | Hand-built; re-verify after every policy change |

### 9.2 Metrics, targets and how to measure

| Layer | Metric | Target | How to measure |
|---|---|---|---|
| Crawl | Recall vs expected URL list | > 95% | `SELECT url FROM raw_documents JOIN sources … WHERE code='hdb'` compared with the list |
| Crawl | Change detection rate / false-positive rate | > 98% / < 2% | Serve a page fixture twice (unchanged → expect `pages_unchanged`), modify it → expect `pages_changed` and `status=pending`. Unit-testable with mocked DB |
| Crawl | Error rate | < 1% | `crawl_jobs.pages_errored / pages_found` |
| Extraction | HTML parse success | > 99% | `extraction_flags->>'is_empty'` = false ratio |
| Extraction | Content precision (no nav/boilerplate) | > 90% | Gold-set comparison: share of extracted lines present in gold text |
| Extraction | PDF CER / WER | < 2% / < 5% | `jiwer` against gold text |
| Extraction | Table accuracy | > 90% | Cell-level exact match against gold tables |
| Processing | Metadata completeness | > 95% | % of chunks with non-empty `title`, `section`, `source_agency`, and ≥1 tag |
| Processing | Tag accuracy | > 90% *(proposed)* | Hand-labelled sample of 100 chunks (property_type / citizenship / topic) |
| Processing | Chunk size compliance | 100% in [50, 600] tokens | `SELECT … WHERE token_count NOT BETWEEN 50 AND 600` must be 0 |
| Processing | Duplicate rate | < 2% | `SELECT md5(chunk_text), count(*) … HAVING count(*)>1` |
| Embedding | Coverage | 100% *(proposed)* | `SELECT count(*) FROM processed_chunks WHERE embedding_id IS NULL` = 0 after a run |
| Embedding | Store consistency | 100% *(proposed)* | Pinecone `describe_index_stats()` namespace counts = Postgres counts per source |
| Embedding | Drift | < 5% | Re-embed a fixed 50-chunk sample; cosine similarity to the archived S3 vector should be ≥ 0.95 |
| Retrieval | **Hit rate@5** (expected URL in top 5) | > 90% *(proposed)* | Retrieval-only script against `/retrieve` (below) |
| Retrieval | **Recall@5 / Precision@5** (context) | > 0.85 / > 0.80 | Same script, URL-level or chunk-level labels |
| Retrieval | **MRR** | > 0.7 *(proposed)* | Same script |
| Retrieval | Filter correctness | 100% *(proposed)* | Every result honours `applied_filters` (assert per result) |
| Retrieval | Latency | P95 < 2 s, API only *(proposed)* | `latency_ms` in responses; `locust` for load |
| End-to-end (agent) | Faithfulness, answer relevancy, contextual precision/recall | ≥ 0.8 | DeepEval via `testing/evaluation/run_rag_eval.py` against the agent |
| End-to-end | Numeric exactness | 100% *(proposed)* | Answers to the numeric facts set must contain the exact official figure |

### 9.3 Retrieval-only evaluation ([eval/retrieval_eval.py](../eval/retrieval_eval.py))

This is the most direct check that the KB itself returns the right documents. It tests the KB without any LLM answer generation.

```
for each row in testset (question, expected_urls):
    resp = POST /retrieve {query, top_k: 5, search_mode}
    rank = first position where result.source_url ∈ expected_urls (normalise trailing slash / query)
    hit@k  += rank is not None
    mrr    += 1/rank if rank else 0
report per source, per topic, per search_mode (vector vs hybrid) → JSON + CSV
fail CI if hit@5 or MRR fall below target or drop > 5 points vs the last baseline
```

`python eval/retrieval_eval.py --k 5 --mode hybrid --min-hit 0.9 --min-mrr 0.7 --baseline eval/baseline.json` writes `eval/last_run.json` and exits non-zero on failure. Run it three times: `vector`, `hybrid`, and `hybrid` with expansion turned off. That shows whether BM25 and query expansion actually help.

### 9.4 Where each check runs

| When | What |
|---|---|
| Every PR (CI, no network) | Unit tests (≥ 80% coverage); extractor tests on offline gold HTML/PDF fixtures; chunker/validator property checks |
| Nightly / after each scheduled crawl | SQL health checks from §9.2 (coverage, size compliance, duplicates, store consistency); Slack alert on breach |
| Weekly / before release | Retrieval-only eval (§9.3) on an **isolated eval DB + Pinecone index** (`ingest_offline_docs.py` pattern: `kb_pipeline_eval` + `kb-pipeline-eval`), plus the DeepEval end-to-end run |
| After a known policy change | Re-run the numeric facts set; confirm the change was detected (`pages_changed`) and the new figure is retrieved |

---

## 10. Next steps and the libraries each one needs

Done in this revision: job API, DB-driven schedule, subprocess crawls, Grafana, table-aware chunking, dual-write + HNSW, BM25 refresh, topic filters, evaluation harness.

| # | Feature | What to do | Libraries / tools |
|---|---|---|---|
| 1 | **Grow the evaluation set** | Extend `eval/testset.csv` to 50+ human-verified rows with `Topic` and `Must_Contain`; commit `eval/baseline.json`; add a nightly job | `httpx` (present); `deepeval` or `ragas` for answer-level metrics at the agent layer |
| 2 | **Verify extraction against gold data** | Hand-verified HTML/PDF gold set; measure CER/WER, table cell accuracy, content precision | `jiwer`; offline snapshots as in `ingest_offline_docs.py` |
| 3 | **Prometheus metrics + alerts** | Export crawl/embed/retrieval metrics; alert on stale crawls, embedding backlog, hit-rate drop | `prometheus-client`, `prometheus-fastapi-instrumentator`; Grafana alerting; `flower` for Celery |
| 4 | **Reranking** | Rerank the top 20–50 RRF candidates with a cross-encoder for better precision and a meaningful score | `sentence-transformers` (`BAAI/bge-reranker-v2-m3`) or Cohere / Voyage rerank APIs |
| 5 | **OCR for scanned PDFs** | Process `raw_documents WHERE needs_ocr`, then re-hash and re-process | `ocrmypdf` or `pytesseract` + Tesseract; `pdf2image` |
| 6 | **Postgres full-text / sparse vectors** | Replace in-memory BM25 for large corpora | Postgres `tsvector` + GIN, or `pinecone-text` BM25 encoder |
| 7 | **Admin CLI** (task 3.12) | `kb crawl/process/embed/stats/search/reindex [source]` | `typer`, `rich` |
| 8 | **Security hardening** | Rate limiting on `/retrieve`, secrets out of `docker-compose.yml`, non-root containers, mandatory `ADMIN_API_KEY` outside dev | `slowapi`, Docker secrets |
| 9 | **Multilingual queries** (task 3.10) | Detect language; translate via the expansion LLM before retrieval | `langdetect` / `fasttext-langdetect` |
| 10 | **Schedule hot-reload** | Pick up schedule changes without restarting Beat | `celery-redbeat` |
| 11 | **Release** | Tag `v1.0.0` after a full crawl and an evaluation run that meets the targets | git |

---

## Further reading

- [docs/pipeline_architecture.md](../docs/pipeline_architecture.md): detailed architecture
- [docs/pipeline_deep_dive.md](../docs/pipeline_deep_dive.md): component internals
- [docs/QUICK_REFERENCE.md](../docs/QUICK_REFERENCE.md): commands and sample data
- [docs/task-breakdown.md](../docs/task-breakdown.md): original 3-week plan and quality gates
