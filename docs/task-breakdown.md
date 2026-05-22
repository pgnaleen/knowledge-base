# Technical Task Breakdown
## Knowledge Base Development
## Data Pipeline: Crawling, Processing, and Indexing

**Project:** AI-Powered Property Advisory Chatbot  
**Module:** Knowledge Base — Regulatory Data Pipeline  
**Team:** Fathima, Paveesha, Gimeth  
**Mentor:** Nalin  
**Duration:** 3 Weeks (15 Working Days)  
**Date:** April 2026  

---

## 1. Overview and Objectives

Build an automated data pipeline that crawls, processes, normalizes,
chunks, embeds, and indexes Singapore property regulatory content from
five government sources into a vector knowledge base for RAG retrieval.

### 1.1 Target Government Sources

| # | Source | URL | Content Types | Est. Pages |
|---|--------|-----|---------------|------------|
| 1 | HDB | hdb.gov.sg | Eligibility, schemes, grants, resale, BTO | 200–300 |
| 2 | URA | ura.gov.sg | Property guidelines, development rules, private property | 150–250 |
| 3 | IRAS | iras.gov.sg | Stamp duties BSD/ABSD/SSD, tax rules, reliefs | 80–120 |
| 4 | MAS | mas.gov.sg | LTV limits, TDSR, mortgage regulations | 50–80 |
| 5 | CPF | cpf.gov.sg | CPF housing scheme, withdrawal limits, accrued interest | 100–150 |

### 1.2 Team Responsibilities

| Engineer | Primary Focus | Secondary Focus |
|----------|--------------|-----------------|
| JE-1 (Gimeth) | Web crawlers and data extraction | Change detection, scheduling |
| JE-2 (Fathima/Paveesha) | Data processing, cleaning, chunking | Metadata extraction |
| JE-3 (Fathima/Paveesha) | Embedding, vector store, retrieval testing | Integration testing |

### 1.3 Definition of Done
- All 5 sources crawled and content extracted successfully
- Content cleaned, normalized, structured with metadata
- Chunked using semantic boundaries (512 tokens, 64 overlap)
- All chunks embedded with text-embedding-3-large in vector DB
- Basic retrieval test passes for 20 sample queries
- Pipeline automated for incremental updates
- All code has unit tests with minimum 80% coverage
- Documentation covers setup, configuration, runbooks

---

## 2. Week 1 — Environment Setup and Web Crawlers

### Sprint 1 Tasks

| ID | Task | Assigned | Est | Dependencies |
|----|------|----------|-----|--------------|
| 1.1 | **Project Repository Setup** — Git repo, branch strategy (main/develop/feature), PR templates, .gitignore, README, folder structure: /crawlers, /processors, /embedders, /tests, /config, /docs | JE-1 | 0.5d | None |
| 1.2 | **Development Environment** — Docker Compose: Python 3.11, PostgreSQL, Redis, MinIO. Shared .env.example | JE-3 | 1d | None |
| 1.3 | **Python Project Scaffold** — Poetry/pip with all dependencies: scrapy, playwright, bs4, pdfplumber, langchain-text-splitters, openai, pinecone-client, pytest, boto3. Ruff + black config | JE-2 | 0.5d | None |
| 1.4 | **Database Schema** — PostgreSQL tables: sources, raw_documents, processed_chunks. Migration scripts | JE-3 | 1d | 1.2 |
| 1.5 | **S3 Bucket Structure** — Buckets: /raw-html/{source}/{date}/, /raw-pdf/{source}/{date}/, /processed/{source}/{date}/, /embeddings/{batch_id}/. MinIO config | JE-1 | 0.5d | 1.2 |
| 1.6 | **Base Crawler Framework** — Abstract base class: rate limiting, robots.txt, retry 3x exponential backoff, SHA-256 hash, raw HTML/PDF to S3, metadata capture, structlog logging | JE-1 | 1.5d | 1.3, 1.5 |
| 1.7 | **HDB Crawler** — Scrapy + Playwright for JS pages. Sections: /residential/buying-a-flat, /residential/selling-a-flat, /residential/living-in-an-hdb-flat | JE-1 | 2d | 1.6 |
| 1.8 | **URA Crawler** — Focus: /property-market-information, /residential, /guidelines. Handle PDF downloads | JE-1 | 1.5d | 1.6 |
| 1.9 | **IRAS Crawler** — Focus: /taxes/stamp-duty, /taxes/property-tax. Extract tax tables BSD/ABSD/SSD. Download PDF guides | JE-2 | 1.5d | 1.6 |
| 1.10 | **MAS Crawler** — Focus: /regulations-and-financial-stability, /news. PDF-heavy content. Extract TDSR and LTV rules | JE-2 | 1d | 1.6 |
| 1.11 | **CPF Crawler** — Focus: /member/home-ownership. Handle tabbed content with Playwright. Extract CPF usage rules | JE-3 | 1.5d | 1.6 |
| 1.12 | **Crawler Integration Tests** — Verify each crawler runs against live site, captures expected pages, stores to S3, handles errors. Mock tests for CI | All | 1d | 1.7–1.11 |

### Week 1 Deliverables
- Working crawlers for all 5 sources
- Raw content stored in MinIO with consistent structure
- Database populated with source metadata and raw documents
- Integration tests confirming each crawler works

---

## 3. Week 2 — Processing, Chunking, and Embedding

### Sprint 2 Tasks

| ID | Task | Assigned | Est | Dependencies |
|----|------|----------|-----|--------------|
| 2.1 | **HTML Content Extractor** — BeautifulSoup: remove nav/header/footer/sidebar, extract main content, preserve heading hierarchy h1–h4, convert tables to markdown, strip scripts/styles. Output: clean markdown | JE-2 | 1.5d | 1.7–1.11 |
| 2.2 | **PDF Content Extractor** — pdfplumber + PyMuPDF fallback: extract text preserving reading order, handle multi-column, extract tables, detect scanned pages for OCR queue | JE-2 | 1.5d | 1.7–1.11 |
| 2.3 | **Table Extraction** — Handler for HTML + PDF tables (stamp duty rates, eligibility matrices, LTV tables). Convert to markdown. Store raw JSON. Tag with table_type metadata | JE-1 | 1d | 2.1, 2.2 |
| 2.4 | **Metadata Extraction Engine** — Extract: title, source agency, section, effective date, property types (HDB/EC/private/all), citizenship types (SC/PR/foreigner/all), topic tags | JE-1 | 1.5d | 2.1, 2.2 |
| 2.5 | **Semantic Chunking Pipeline** — LangChain RecursiveCharacterTextSplitter: chunk_size=512, overlap=64, separators on section boundaries. Each chunk inherits parent metadata + chunk_index, heading_path | JE-2 | 1.5d | 2.1, 2.2, 2.4 |
| 2.6 | **Chunk Quality Validation** — Rules: min 50 tokens, max 600 tokens, no nav/boilerplate chunks, no mid-sentence splits, no duplicates. Validation script with stats per source | JE-2 | 1d | 2.5 |
| 2.7 | **Embedding Generation Service** — OpenAI text-embedding-3-large, batch 2048, rate limiting + retries, cost tracking (log token count). Incremental embedding (only new/changed) | JE-3 | 1.5d | 2.5 |
| 2.8 | **Vector Store — Pinecone** — Index: dim=3072, metric=cosine, pod=s1. Namespaces per source (hdb/ura/iras/mas/cpf) + unified (all). Metadata filters: source, property_type, citizenship_type, topic, effective_date | JE-3 | 1d | 2.7 |
| 2.9 | **Vector Store — pgvector** — Enable pgvector in PostgreSQL, embeddings table vector(3072), HNSW index ef_construction=128 m=16. Benchmark vs Pinecone | JE-3 | 1d | 2.7 |
| 2.10 | **Change Detection System** — SHA-256 hash comparison between crawls. Track new/modified/deleted pages. Change report after each crawl. Only re-process changed content. Hash history for audit | JE-1 | 1d | 2.4 |
| 2.11 | **Pipeline Orchestration** — End-to-end DAG: crawl→extract→clean→chunk→embed→upsert. Logging, error handling, progress tracking. Each stage reads/writes DB with status flags | All | 1d | 2.1–2.10 |
| 2.12 | **Unit Tests for Processing** — HTML extraction, PDF extraction, chunking (sizes/overlaps/metadata), embedding (mock API). Min 80% coverage for /processors | All | 1d | 2.1–2.10 |

### Week 2 Deliverables
- Clean processed text from all 5 sources
- Metadata-tagged chunks in PostgreSQL
- Embeddings in Pinecone + pgvector
- Change detection system
- End-to-end pipeline in single command

---

## 4. Week 3 — Retrieval, Automation, and QA

### Sprint 3 Tasks

| ID | Task | Assigned | Est | Dependencies |
|----|------|----------|-----|--------------|
| 3.1 | **Retrieval API** — FastAPI POST /retrieve: query, top_k=5, filters (source, property_type, citizenship_type). Returns chunks with text, metadata, similarity score, source URL. Query logging | JE-3 | 1d | 2.8 |
| 3.2 | **Hybrid Retrieval** — BM25 + vector search. Reciprocal Rank Fusion: score = 1/(k+rank_vector) + 1/(k+rank_bm25) with k=60. BM25 via rank_bm25 library | JE-3 | 1.5d | 3.1 |
| 3.3 | **Query Expansion** — LLM call: generate 2–3 alternative phrasings, extract entities (property type, citizenship, topic), map abbreviations (HDB/EC/ABSD/BSD/SSD/TDSR/LTV/CPF) | JE-3 | 1d | 3.2 |
| 3.4 | **Metadata Filtering** — Pre-retrieval filter by property type, citizenship, source to narrow search space | JE-1 | 0.5d | 3.1 |
| 3.5 | **Scheduled Crawl Automation** — Cron/Celery Beat: full crawl weekly Sunday 2AM SGT, change detection daily 6AM SGT. Per-source YAML config. Slack/email on failure | JE-1 | 1d | 2.11 |
| 3.6 | **Incremental Update Pipeline** — On schedule: detect changes → re-extract → re-chunk → re-embed → upsert (replace old vectors). Delete vectors for removed pages. Audit log | JE-1 | 1d | 2.10, 3.5 |
| 3.7 | **Monitoring Dashboard** — JSON endpoint: crawl status (last_run, pages_found, pages_changed, errors), embedding stats (chunks, tokens, cost), vector store stats per namespace. Optional Grafana | JE-1 | 1d | 3.5, 3.6 |
| 3.8 | **Evaluation Dataset** — 50 Q&A pairs: HDB eligibility (10), stamp duties (10), CPF rules (8), MAS loan limits (8), URA guidelines (7), cross-source (7). Each with expected answer + source docs | JE-2 | 1.5d | 2.8 |
| 3.9 | **Retrieval Quality Eval** — Automated eval: context recall, context precision, MRR. Report per source and topic. Target: recall > 0.85, precision > 0.80 | JE-2 | 1.5d | 3.2, 3.8 |
| 3.10 | **Edge Case Testing** — Ambiguous queries, multilingual (Mandarin), abbreviation-heavy, very specific, multi-source questions. Document failures | JE-2 | 1d | 3.2 |
| 3.11 | **Technical Documentation** — README: architecture diagram, setup instructions, config reference, API docs, data schema, troubleshooting. Runbooks: manual crawl, re-index, add new source | All | 1d | All |
| 3.12 | **Admin CLI** — Commands: kb crawl [source], kb process [source], kb embed [source], kb stats, kb search "query", kb reindex [source] | JE-3 | 1d | 2.11 |
| 3.13 | **Code Cleanup** — Review all PRs, resolve TODOs, ruff + black, all tests pass in CI, tag v1.0.0 | All | 0.5d | All |

### Week 3 Deliverables
- Retrieval API with hybrid search, query expansion, metadata filtering
- Automated pipeline with scheduling and failure notifications
- Evaluation report across 50 test queries
- Admin CLI for manual operations
- Complete documentation and runbooks

---

## 5. Risks and Mitigations

| Risk | Impact | Likelihood | Mitigation |
|------|--------|------------|------------|
| Government sites block crawlers | High | Medium | Respect robots.txt, polite delays, rotate user agents. Fallback: manual downloads |
| Complex JS-rendered content missed | Medium | High | Use Playwright for JS rendering. Log failed extractions for manual review |
| PDF tables not extractable | Medium | Medium | pdfplumber → PyMuPDF → Tesseract OCR. Flag failed PDFs for manual entry |
| Junior engineers unfamiliar with stack | Medium | High | Daily standups, pair programming, pre-configured dev environment |
| Chunk quality insufficient for retrieval | High | Medium | Iterative tuning of chunk size/overlap. Evaluation dataset to measure objectively |
| OpenAI API rate limits | Low | Low | Batch 2048 per batch, retry with backoff, cost tracking alerts |

---

## 6. Quality Gates

| Gate | Criteria |
|------|----------|
| Week 1 | All 5 crawlers run against live sites. Raw content in S3. DB populated. No critical errors |
| Week 2 | Full pipeline runs end-to-end. All chunks have valid metadata. Vector store populated. Token cost logged |
| Week 3 | Retrieval API functional. Recall > 0.85, Precision > 0.80. Scheduling works. Docs complete. All tests pass |

---

## 7. Tech Stack Reference

| Component | Technology | Purpose |
|-----------|-----------|---------|
| Language | Python 3.11+ | Primary development |
| Web Crawling | Scrapy 2.11+ | HTTP crawling |
| JS Rendering | Playwright 1.40+ | JS-rendered pages |
| HTML Parsing | BeautifulSoup4 4.12+ | Content extraction |
| PDF Extraction | pdfplumber + PyMuPDF | Text from PDFs |
| Text Chunking | LangChain Text Splitters | Semantic chunking |
| Embeddings | OpenAI text-embedding-3-large | 3072-dim vectors |
| Vector Store | Pinecone + pgvector | Similarity search |
| Database | PostgreSQL 16+ | Metadata storage |
| Cache | Redis 7+ | Rate limiting, state |
| Object Storage | MinIO (S3-compatible) | Raw file storage |
| API | FastAPI 0.110+ | Retrieval endpoint |
| Scheduling | Celery + Redis | Automated crawls |
| Testing | pytest + pytest-cov | Unit + integration |
| CI/CD | GitHub Actions | Automated testing |
| Containers | Docker + Compose | Local dev |