# Knowledge Base - Project Context for Claude

## Project Overview
Singapore Property Regulatory Data Pipeline — crawls 5 government sources (HDB, URA, IRAS, MAS, CPF), processes content, generates vector embeddings, and indexes for RAG retrieval.

## Current Status
- **Week 1 (Crawlers):** COMPLETE — all 5 spiders built, base crawler framework, DB schema, Docker Compose, tests
- **Week 2 (Processing):** NOT STARTED — HTML/PDF extractors, chunking pipeline, embedding generation, vector store setup
- **Week 3 (Retrieval):** NOT STARTED — FastAPI retrieval API, hybrid search, scheduling, evaluation

## Project Structure
```
/crawlers/base_crawler.py    — Abstract base with rate limiting, retry, content hash, S3 storage
/crawlers/spiders/           — hdb, ura, iras, mas, cpf spiders
/crawlers/runner.py          — Orchestration, DB persistence, crawl job tracking
/processors/                 — (empty, Week 2)
/embedders/                  — (empty, Week 2)
/config/settings.py          — Pydantic settings from .env
/config/database.py          — SQLAlchemy engine + session
/config/models.py            — Source, RawDocument, ProcessedChunk, CrawlJob tables
/config/storage.py           — S3/MinIO upload helpers
/config/sources.yml          — Source definitions (URLs, domains, delays)
/tests/unit/                 — test_base_crawler.py, test_spiders.py
```

## Tech Stack
Python 3.11, httpx, BeautifulSoup4, pdfplumber, SQLAlchemy, PostgreSQL 16 + pgvector, Redis, MinIO (S3), OpenAI embeddings, Pinecone, FastAPI, Docker Compose

## Key Design Decisions
- Using httpx instead of Scrapy for simpler async control
- SHA-256 content hashing for change detection
- Raw HTML/PDF stored in S3, metadata in PostgreSQL
- 512-token chunks with 64-token overlap (LangChain RecursiveCharacterTextSplitter)
- OpenAI text-embedding-3-large (3072 dimensions)
- Pinecone primary vector store, pgvector as backup
- One namespace per source in Pinecone

## Branch
- Main branch: `master`
