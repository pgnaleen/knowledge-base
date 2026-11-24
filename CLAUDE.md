# CLAUDE.md

Guidance for Claude Code when working in this repository. See [README.md](README.md) and [docs/TECHNICAL_REFERENCE.md](docs/TECHNICAL_REFERENCE.md) for the full architecture, library list, code flow and verification plan.

## Project Overview

Python data pipeline that crawls 5 Singapore government property sites (HDB, URA, IRAS, MAS, CPF), extracts and chunks the content, embeds it, and serves hybrid (vector + BM25) retrieval over FastAPI for a RAG advisory agent. Main branch: `master`; active development branch: `dev`.

## Working Preferences (from the user)

- **Do not run or write unit tests, and do not build the product** (no pytest, docker build/compose, setup.sh). Just develop: edit code and docs. At most, a cheap `python -m py_compile` syntax check.

## Status

All three planned phases are implemented on `dev`: crawlers, processing, embedding, retrieval API, Celery scheduling, job/monitoring endpoints, Grafana dashboard, retrieval evaluation script.
Open work is listed in README §10 (OCR, reranking, Prometheus metrics, admin CLI, multilingual queries).
The `sg-property-agent` chat app and the `testing/` QA suite live on other branches (`sg-property-agent`, `property-advisory-ai-advisory`) and are intentionally not part of this repo.

## Commands

All Python runs **inside the app container** (`KB-Pipeline-App`), no local venv.

```bash
bash setup.sh                                   # first-time setup: containers, migrations, source sync, bucket
docker compose up -d                            # start after a restart
APP="docker exec KB-Pipeline-App"
$APP python run_pipeline.py [sources...]        # crawl -> process -> embed
$APP python run_pipeline.py --crawl-only -S CLOSESPIDER_PAGECOUNT=10
$APP python run_pipeline.py --process-only | --embed-only | --skip-embed | --incremental
$APP python run_pipeline.py <source> --purge-vectors      # DESTRUCTIVE
$APP alembic upgrade head                       # migrations 001-008
$APP python -m config.sync_sources              # sources.yml -> sources.crawl_config (incl. schedule)
$APP python backfill_pgvector.py                # restore pgvector rows from the S3 embedding archive
$APP python eval/retrieval_eval.py --k 5        # retrieval quality (hit@k, MRR, facts, filters)
$APP ruff check . && $APP black .
```

## Architecture

```
Scrapy (+Playwright)  ->  S3Pipeline: upload raw, extract text (tables inline as Markdown), sha256
                      ->  PostgresPipeline: dedup, change detection, mark deleted  -> raw_documents (pending)
processors/runner     ->  metadata -> chunker (512/64 tokens, tables atomic) -> validator -> processed_chunks
embedders/pipeline    ->  OpenRouter/OpenAI embeddings -> Pinecone (source + "all" namespaces) AND pgvector (dual-write)
api/ (FastAPI)        ->  query expansion -> filter inference -> vector + BM25 -> RRF -> /retrieve
Celery Beat + worker  ->  scheduled crawls (cron from sources.crawl_config, YAML fallback); crawl runs in a subprocess
```

### Modules
- `crawlers/` — `BaseCrawler` (config read from DB `sources.crawl_config`, never from YAML at crawl time); spiders `hdb/ura/iras/mas/cpf` are thin subclasses; `generic` crawls any other active source. Pipelines in `crawlers/pipelines.py`. The extractors already inline tables, so **do not append tables to text again**.
- `processors/` — `html_extractor`, `pdf_extractor` (pdfplumber interleaving tables by position, PyMuPDF fallback, scanned-PDF detection), `table_extractor`, `metadata_extractor`, `chunker`, `validator`, `runner`.
- `embedders/` — `embedding_service`, `pinecone_store`, `pgvector_store`, `bm25_store`, `pipeline`.
- `api/` — `app.py` (endpoints), `retrieval.py`, `query_expander.py`, `metadata_filter_inference.py`, `schemas.py`.
- `tasks/pipeline_tasks.py` — Celery tasks that record `task_executions`. `config/` — settings, DB, models, storage, Celery app, notifications. `eval/` — retrieval evaluation. `grafana/` — provisioned dashboard.

### API
`POST /retrieve` (public). Admin endpoints, protected by `X-API-Key` when `ADMIN_API_KEY` is set: `POST /crawl|/process|/embed`, `GET /jobs|/stats|/config`, `POST /admin/reindex-bm25`.

### Database
`sources` (crawl_config JSONB incl. `schedule`), `raw_documents` (status pending/processed/failed/deleted), `processed_chunks` (`embedding vector(3072)`, `embedding_id`, `metadata_json`), `crawl_jobs`, `task_executions`. Alembic is linear: 001 -> ... -> 006 -> 007 (merges the old two heads) -> 008 (HNSW on `embedding::halfvec(3072)`). Add new migrations; never edit applied ones.

### Infrastructure (docker-compose.yml)
postgres (pgvector 0.8, pg16) :5432, redis :6379, minio :9000/:9001, app, api :8000, worker, beat, grafana :3000.

## Coding Conventions

- Use `structlog` (via `config.logger.get_logger`), never `print()`.
- Docstrings on classes; type hints on function signatures.
- Retries with exponential backoff (tenacity / Scrapy retry) on HTTP and external API calls.
- SHA-256 content hash for change detection; respect robots.txt.
- Catch specific exceptions; never swallow errors silently.
- pgvector similarity queries must use `embedding::halfvec(3072) <=> CAST(:vec AS halfvec(3072))` to hit the HNSW index.
- `config/settings.py`: do not copy the `redis://l ocalhost` typo that exists on `property-advisory-ai-advisory`.
- Pin `sqlalchemy<2.1` (2.1 defaults `postgresql://` to psycopg3; we ship psycopg2).

## Critical Notes

- JS-rendered sources (HDB, CPF) need Playwright; set per source via `js_rendering`.
- Celery workers must not run Scrapy in-process (Twisted reactor is not restartable); tasks shell out to `run_pipeline.py`.
- Pinecone vector metadata: `source_name`, `property_types`, `citizenship_types`, `topics`, `chunk_type`, `effective_date_ts`. Vectors embedded before this change lack `topics`/`effective_date_ts` until re-embedded.
- Hybrid `score` is a normalised RRF rank score in (0, 1], comparable across requests but not a probability. `topic` is a user-supplied filter only (never auto-inferred).
- BM25 index auto-refreshes every `BM25_REFRESH_SECONDS` (default 300) and via `POST /admin/reindex-bm25`.
