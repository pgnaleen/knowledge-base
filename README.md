# Knowledge Base - Singapore Property Regulatory Data Pipeline

Automated data pipeline that crawls, processes, and indexes Singapore property regulatory content from 5 government sources into a vector knowledge base, and serves it through a retrieval API (hybrid vector + keyword search) for RAG.

> **Current code-level reference** (libraries by file, exact imports per stage, API endpoints, branches, resolved issues, verification plan, next steps): see [docs/TECHNICAL_REFERENCE.md](docs/TECHNICAL_REFERENCE.md).

---

## Table of Contents

1. [Government Sources](#government-sources)
2. [Pipeline Overview](#pipeline-overview)
3. [Key Concepts Explained](#key-concepts-explained)
4. [How the Pipeline Works (Step by Step)](#how-the-pipeline-works-step-by-step)
5. [Project Structure](#project-structure)
6. [Tech Stack](#tech-stack)
7. [API Endpoints](#api-endpoints)
8. [Configuration](#configuration)
9. [Quick Start](#quick-start)
10. [Glossary](#glossary-quick-reference)

---

## Government Sources

| # | Source | URL | Content Types | Estimated Pages |
|---|--------|-----|---------------|-----------------|
| 1 | HDB (Housing & Development Board) | hdb.gov.sg | Eligibility, schemes, grants, resale rules, BTO info | 200-300 |
| 2 | URA (Urban Redevelopment Authority) | ura.gov.sg | Property guidelines, development rules, private property regulations | 150-250 |
| 3 | IRAS (Inland Revenue Authority) | iras.gov.sg | Stamp duties (BSD, ABSD, SSD), tax rules, reliefs | 80-120 |
| 4 | MAS (Monetary Authority) | mas.gov.sg | Loan-to-value limits, TDSR, mortgage regulations | 50-80 |
| 5 | CPF Board | cpf.gov.sg | CPF housing scheme, withdrawal limits, accrued interest | 100-150 |

---

## Pipeline Overview

The knowledge base is built through a multi-stage data pipeline. Think of it like building a library from scratch: first you collect the books (crawling), then you organize and clean them (processing), then you create a catalog system so people can find what they need quickly (embedding and indexing).

```
Government Websites
        |
        v
  [1. CRAWLING]         -- Visit websites and download pages/PDFs (Scrapy + Playwright)
        |
        v
  [2. CLEANING]         -- Remove junk (menus, footers, ads), keep text and tables
        |                  (runs right after each download, inside the crawler)
        v
  [3. CHUNKING]         -- Break long documents into small pieces; tables stay whole
        |
        v
  [4. METADATA          -- Tag each piece with labels (source, topic, property type)
      EXTRACTION]
        |
        v
  [5. EMBEDDING         -- Convert text into numbers (vectors) that capture meaning
      GENERATION]
        |
        v
  [6. INDEXING]          -- Store vectors in Pinecone AND pgvector
        |
        v
  [7. RETRIEVAL]         -- When a user asks a question, find the most relevant pieces
```

Every stage reads its input from PostgreSQL and records its progress with a status flag, so each stage can run on its own:

```
raw_documents.status:          pending --(process)--> processed      (or failed / deleted)
processed_chunks.embedding_id: NULL    --(embed)----> <vector id>
```

Run it all with one command (`python run_pipeline.py`), on a schedule (Celery Beat), or from the API (`POST /crawl`).

---

## Key Concepts Explained

This section explains every technical concept used in this project. No prior knowledge of web crawling, data mining, or data analytics is assumed.

### Web Crawling

**What it is:** Web crawling (also called web scraping or spidering) is the process of automatically visiting websites and downloading their content, just like a person browsing the internet - but done by a computer program.

**How it works in this project:** Our crawlers visit 5 Singapore government websites. They start at known pages (like hdb.gov.sg/buying-a-flat), read the text on each page, then follow the links that are in scope to discover more pages. They keep going until every relevant page has been visited.

**Real-world analogy:** Imagine sending someone into a library to photocopy every book. They start at one shelf, copy the book, check the "See Also" references at the back, go find those books, copy them too, and repeat until they've covered the whole library.

**Key terms:**
- **Spider:** The program that does the crawling. Each source has a spider (HDB, URA, IRAS, MAS, CPF). They are thin: all behaviour comes from a shared `BaseCrawler` plus a per-source configuration stored in the database. A `generic` spider crawls any other active source added to the database, with no code changes.
- **Scrapy:** The crawling framework that schedules requests, follows links, retries failures and runs the item pipelines.
- **Playwright:** A headless Chromium browser used for JavaScript-rendered pages (HDB, CPF), switched on per source with `js_rendering`.
- **Seed URLs / Start URLs:** The first pages the crawler visits (`start_urls` in the source config).
- **Crawl scope rules:** A link is followed only if its domain is in `allowed_domains`, it is not under a `skip_prefixes` path or a blocked subdomain, and (when set) it is under a `target_prefixes` path. PDFs are always followed. Pages shorter than `min_content_length` or missing the `content_keywords_filter` words are skipped.
- **Rate limiting:** The crawler waits `crawl_delay` seconds between requests (default 2.0, randomised, set per source) and runs at most 4 requests at once per domain, so it does not overwhelm government sites.
- **robots.txt:** A file that website owners use to say which pages crawlers may visit. Our crawler obeys it.
- **Retry logic:** If a request fails with 429 or a 5xx error, Scrapy retries up to 3 times with exponential backoff (capped at 60 seconds).
- **Content hash (SHA-256):** A digital fingerprint of the page's cleaned text (whitespace-normalised, tables included). If we crawl the same page later and the hash differs, we know the content changed. Example: "Hello" always produces `2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824`.
- **Crawl job:** One crawl run for one source. It is recorded in the `crawl_jobs` table with counts of pages found, new, changed, deleted and errored.

### Cleaning (Content Extraction)

**What it is:** Raw web pages contain a lot of "noise" - navigation menus, footers, cookie banners, advertisements, JavaScript code, and styling information. Cleaning removes this noise and keeps only the useful content.

**How it works in this project:** Cleaning happens inside the crawler, immediately after a page is downloaded (the `S3Pipeline` step), so the cleaned text is saved with the document. For an HDB page the raw HTML might be 50KB while the useful text is 5KB. The cleaner:
1. Parses the HTML and removes noise tags (`<nav>`, `<footer>`, `<header>`, `<script>`, `<style>`, and similar) and elements whose class or id looks like noise ("sidebar", "cookie", "banner", "menu").
2. Finds the main content area: first the per-source `content_selectors`, then `<main>`, `<article>` or `role="main"`, then `<body>`.
3. Walks that content in document order, collecting the headings (h1-h6) and turning each HTML table into a Markdown table **at the position where it appears**, so a rate table stays next to the sentence that introduces it.
4. Normalises whitespace and saves the result as `raw_text`.

**Real-world analogy:** Imagine you photocopied a whole newspaper page, but you only want the article text. You would cut away the ads, the page numbers, the newspaper logo, the navigation bar, and just keep the article. That's cleaning.

**Key terms:**
- **HTML (HyperText Markup Language):** The code that web pages are written in, using tags like `<h1>Title</h1>` and `<p>Paragraph text</p>`.
- **BeautifulSoup (with lxml):** The Python library we use to read and navigate HTML.
- **Main content area:** The part of a page that holds the actual article, as opposed to navigation, sidebars and footers.
- **Heading hierarchy:** The h1-h6 structure of the page, kept so each chunk can later be labelled with where it sits in the document.

### PDF Extraction

**What it is:** Some government documents are published as PDF files rather than web pages (especially circulars, guidelines, and rate tables). PDF extraction pulls text and tables out of those files.

**How it works in this project:** When a crawler finds a PDF, it saves the file to S3 and extracts the text in the same crawl step.
- **pdfplumber (primary)** reads each page's words and detects tables. Words outside tables are put back in reading order, and each table is inserted as Markdown at its vertical position on the page.
- **PyMuPDF (fallback)** is used when pdfplumber fails or returns no text. Tables are then re-detected and appended at the end of the text, because PyMuPDF text has no table positions.
- **Scanned-PDF detection:** every PDF is checked (how much of each page is an image versus text). Scanned PDFs are flagged `needs_ocr`. The OCR step itself is not built yet.

**Challenges:**
- Multi-column layouts (text must be read in the correct order)
- Tables (cells must be associated with the correct row and column)
- Scanned PDFs (the PDF is actually an image, not selectable text - these need OCR)

### Chunking

**What it is:** After cleaning, we have long documents - some might be thousands of words. Chunking breaks these into smaller, overlapping pieces called "chunks." Each chunk is a self-contained piece of information.

**Why we chunk:** AI models have a limited amount of text they can process at once. When a user asks a question, we don't want to send the entire HDB website to the AI. Instead, we find and send only the 3-5 most relevant chunks. Smaller pieces also produce better search results because the meaning is more focused.

**How it works in this project:**
- **Target chunk size:** 512 tokens (~380 words), large enough for a complete thought but small enough for precise retrieval.
- **Chunk overlap:** 64 tokens. Adjacent chunks share some text at their boundaries so that information isn't lost when an idea spans two chunks.
- **Separators:** Prose is split at natural boundaries: paragraph breaks first, then line breaks, then spaces.
- **Tables stay whole:** A Markdown table is never cut through the middle. Each table becomes its own `table` chunk. A table larger than 512 tokens is split into groups of rows, and the header row is repeated in every group so each piece is still readable.
- **Validation:** Every chunk then passes a quality gate. It is dropped if it is empty, under 50 tokens (tables are exempt), over 600 tokens, only navigation or boilerplate, or a duplicate of another chunk in the same document. Other problems (such as a possible mid-sentence split) are logged as warnings and the chunk is kept.

**Real-world analogy:** Imagine you have a 100-page textbook. Instead of searching the whole book every time someone asks a question, you cut it into 200 index cards, each containing one key concept. Some cards overlap slightly so you don't lose context at the boundaries. A table is kept on a single card, or on several cards that each repeat the table's header.

**Key terms:**
- **Token:** A unit of text that AI models use, roughly 3/4 of a word. We count tokens with the `tiktoken` library (`cl100k_base`), the same tokenizer as the embedding model.
- **Chunk overlap:** The number of tokens shared between consecutive chunks, which keeps context across the boundary.
- **Heading path:** A breadcrumb showing where a chunk came from in the original document. Example: "Eligibility > Singapore Citizens > First Timer". It is worked out from the chunk's position in the text and the document's headings.

### Metadata Extraction

**What it is:** Metadata is "data about data." For each chunk of text, we store labels that describe what the chunk is about, where it came from, and who it applies to.

**How it works in this project:** For each document we extract the following and copy it onto every chunk:
- **Source agency:** Which government body published it (HDB, URA, IRAS, MAS, CPF)
- **Document title:** The page or document title
- **Section:** The first top-level heading (or the title if there are no headings)
- **Effective date:** A date found in the text by pattern matching, stored as `YYYY-MM-DD` (empty if none is found)
- **Tags:** `property_type` (HDB, private, EC, commercial), `citizenship` (SC, PR, foreigner) and `topic`. These are assigned by matching keywords from the source's `tag_config` against the text and headings, so they are rule-based, not AI-generated.
- **Chunk fields:** `chunk_index`, `chunk_type` (text or table), `heading_path`, `parent_doc_id`, `total_chunks`

**Why metadata matters:** When a user asks "What is the ABSD rate for a PR buying a second property?", we can use metadata to narrow the search to IRAS chunks about stamp duty that apply to Permanent Residents instead of searching every chunk from every source. The API can also filter by `topic` when the caller supplies it.

### Vector Embedding

**What it is:** This is the most important concept in the pipeline. Vector embedding is the process of converting text into a list of numbers (called a "vector") that mathematically represents the *meaning* of that text.

**Why we need it:** Computers don't understand language the way humans do. If a user asks "Can I use CPF to buy a flat?", a simple keyword search might miss a page that says "Ordinary Account funds may be utilized for HDB property acquisition" because it uses completely different words. But both sentences have similar *meaning*. Vector embeddings capture meaning, not just words.

**How it works:**
1. We send chunks of text to the `text-embedding-3-large` embedding model, through **OpenRouter** first and **OpenAI** as a fallback. Chunks are sent in batches of up to 2,048 texts and 250,000 tokens, and token usage is logged for cost tracking. Only chunks without an embedding yet are sent, so unchanged content is never re-embedded.
2. The model returns a list of 3,072 numbers (the vector). Example: `[0.023, -0.841, 0.156, ..., 0.447]`
3. Texts with similar meanings will have vectors that are mathematically close together
4. Texts with different meanings will have vectors that are far apart

**Real-world analogy:** Imagine plotting every chunk of text as a dot on a giant map. Chunks about "HDB eligibility for first-time buyers" would cluster together in one area, while chunks about "stamp duty rates" would cluster in another area. When a user asks a question, we convert their question into a dot on the same map and find the closest existing dots. Those closest dots are the most relevant chunks.

**Key terms:**
- **Vector:** An ordered list of numbers. In our case, each vector has 3,072 numbers. Think of it as coordinates in a 3,072-dimensional space (impossible to visualize, but mathematically valid).
- **Dimension:** The number of values in a vector. Our vectors have 3,072 dimensions, meaning each chunk is represented by 3,072 numbers. More dimensions generally means more nuance in capturing meaning.
- **Embedding model:** The AI model that converts text to vectors. We use OpenAI's `text-embedding-3-large`, which was trained on billions of text examples to understand meaning across languages and topics.
- **Similarity / Distance:** How close two vectors are. We use "cosine similarity" - a mathematical measure where 1.0 means identical meaning and 0.0 means completely unrelated. For example, "HDB flat eligibility" and "BTO application requirements" might have a cosine similarity of 0.85, while "HDB flat eligibility" and "income tax filing" might have 0.15.

### Embedded Vectors

**What it is:** The output of the embedding process - the actual numerical representations stored in the database. Each chunk of text has one corresponding embedded vector.

**Example:**
```
Original text: "Singapore Citizens buying their first HDB flat may be eligible
                for the Enhanced CPF Housing Grant of up to $80,000."

Embedded vector: [0.0234, -0.8412, 0.1563, 0.0891, ..., 0.4471]
                 (3,072 numbers total)

Metadata: {
  source: "hdb",
  property_type: "hdb",
  citizenship: "SC",
  topic: "grant"
}
```

When a user asks "How much grant can a first-time buyer get?", this question is also converted to a vector, and the system finds that the grant chunk's vector is very close to the question's vector.

### Indexing

**What it is:** Indexing is the process of organizing embedded vectors in a specialized database (called a vector store) so they can be searched extremely fast. Without an index, finding the most similar vector among 10,000 vectors would require comparing against every single one. With an index, the search can skip most vectors and find the answer in milliseconds.

**How it works in this project:** Every vector is written to **both** vector stores (dual-write, using the same vector id `{source}-{chunk id}` in each):
- **Pinecone (primary):** A cloud-hosted vector database built for similarity search. Each vector is stored in its source namespace and in the unified `all` namespace, with metadata for filtering (`source_name`, `property_types`, `citizenship_types`, `topics`, `chunk_type`, `effective_date_ts`).
- **pgvector (backup):** A PostgreSQL extension that stores the vector in `processed_chunks.embedding`. Searches use an HNSW index built on `embedding::halfvec(3072)`. Plain 3072-dimension vectors are too large for an HNSW index (the limit is 2000), so the index uses half-precision `halfvec`, which supports up to 4000 dimensions with negligible accuracy loss.
- If one store fails, the other still serves queries. If both fail, the chunks stay un-embedded and are retried on the next run.
- Every embedding is also archived to S3, so pgvector can be rebuilt without calling the embedding API again (`backfill_pgvector.py`).

**Key terms:**
- **Vector store / Vector database:** A specialized database designed to store vectors and find similar vectors quickly.
- **Namespace:** A logical partition within the vector store. We create one namespace per source (hdb, ura, iras, mas, cpf) plus a unified `all` namespace.
- **HNSW (Hierarchical Navigable Small World):** An algorithm for building search indexes on vectors. It creates a graph of similar vectors so the search can navigate quickly to the most relevant area.
- **halfvec:** A half-precision vector type in pgvector that makes HNSW indexing possible for 3072-dimension vectors.
- **Cosine similarity:** Measures the angle between two vectors. Close to 1.0 means similar meaning.
- **Upsert:** Insert a new record or update it if it already exists, so re-embedding does not create duplicates.

### Retrieval (RAG - Retrieval-Augmented Generation)

**What it is:** Retrieval is the final step where the knowledge base is actually used. When a user asks a question through the chatbot, the system:
1. Expands the question into alternative phrasings and works out filters (source, property type, citizenship)
2. Converts each phrasing into a vector (using the same embedding model)
3. Searches the vector store and the keyword index, and merges the results
4. Returns the best chunks (with source URLs) to the AI chatbot, which uses them to generate an accurate answer

**Key terms:**
- **RAG (Retrieval-Augmented Generation):** A technique where an AI chatbot first *retrieves* relevant documents from a knowledge base, then *generates* an answer based on those documents, so answers are grounded in real, up-to-date government data.
- **Top-k retrieval:** Returning the k most similar chunks. The default is k=5 (maximum 50).
- **Hybrid retrieval (the default mode):** Combining two search methods:
  - **Vector search:** Finds chunks with similar *meaning* (good for paraphrased questions)
  - **BM25 (keyword search):** Finds chunks containing the same *words* (good for specific terms like "ABSD" or "TDSR"). The index is held in memory and rebuilt automatically every 5 minutes, or on demand.
  - Results are merged with **Reciprocal Rank Fusion (RRF)**: each chunk scores `1/(60 + rank in vector results) + 1/(60 + rank in keyword results)`.
- **Query expansion:** An LLM (via OpenRouter) rewrites the question into the original plus two alternative phrasings and extracts entities. Abbreviations are expanded (ABSD, BSD, SSD, TDSR, MSR, LTV, EC, BTO, OA/SA, SC/PR). If the LLM is unavailable, the original question is used.
- **Metadata filter inference:** Simple rules turn words like "HDB", "condo", "PR" or "IRAS" in the question into source, property-type and citizenship filters. These are combined with any filters the caller supplies.
- **Score:** In hybrid mode the score is a normalised rank score between 0 and 1. It is comparable across requests but is not a probability.
- **Context recall / context precision:** Quality metrics for retrieval. Targets: > 0.85 and > 0.80. They are measured with `eval/retrieval_eval.py` (hit rate, MRR, filter correctness, latency).

### Change Detection

**What it is:** Government regulations change over time. Change detection identifies when a web page has been updated since our last crawl, so we only re-process and re-embed the content that actually changed.

**How it works:** Every time we crawl a page, we compute a SHA-256 hash of its cleaned text. The pipeline then checks, in order:
1. **Duplicate content:** if a *different* URL already has the same hash, the page is skipped and its stored file is removed.
2. **Same URL, same hash:** unchanged. Only the `last_seen_at` time is refreshed.
3. **Same URL, different hash:** changed. The row is updated and set back to `pending`, so it is re-chunked and re-embedded.
4. **New URL:** a new row is created as `pending`.

**Types of changes tracked:**
- **New pages:** URLs not seen in a previous crawl
- **Modified pages:** URLs whose content hash has changed
- **Deleted pages:** URLs stored in the database that were not seen in the latest crawl. They are marked `deleted`, and their vectors and chunks are removed after the crawl.

### Data Pipeline

**What it is:** A data pipeline is a series of automated processing steps that data flows through, from raw input to final output. Each step transforms the data in some way.

**Our pipeline stages:**
```
Raw HTML/PDF  -->  Clean Text  -->  Chunks  -->  Vectors  -->  Searchable Index
   (input)       (cleaning)    (chunking)   (embedding)      (indexing)
```

Each stage reads from the database, processes the data, and writes results back, so if one stage fails we can restart from that point without redoing everything.

**Automation:**
- **Celery + Redis** run the pipeline on a schedule. Celery Beat starts a full crawl every Sunday at 02:00 SGT and an incremental crawl every day at 06:00 SGT, per source. The schedule is stored in the database (`crawl_config`), with `sources.yml` as the fallback.
- Each crawl runs in its own subprocess, because Scrapy's event loop can only start once per process.
- Every task is recorded in the `task_executions` table (status, result summary, log tail) and shown by `GET /jobs`.
- A failure after all retries sends a Slack message (when `SLACK_WEBHOOK_URL` is set).
- **Grafana** shows crawl status, document and chunk counts and embedding coverage from the same database.

### Object Storage (S3 / MinIO)

**What it is:** Object storage is a system for storing files (like raw HTML pages and PDFs) in a scalable, organized way. We use it as a backup of all crawled content.

**Key terms:**
- **S3 (Simple Storage Service):** Amazon's cloud file storage service. Files are organized into "buckets" and identified by "keys" (like file paths).
- **MinIO:** An open-source S3-compatible storage system that runs locally. We use it during development so we don't need an AWS account.
- **Bucket structure:** One bucket (`sg-property-kb`) with prefixes: `raw-html/{source}/{date}/`, `raw-pdf/{source}/{date}/`, `processed/{source}/{date}/` and `processed/embeddings/{date}/` (the archive of every embedding).

---

## How the Pipeline Works (Step by Step)

Here is a concrete example walking through the entire pipeline. The entry point is `run_full_pipeline()` in `run_pipeline.py`, called from the command line or from a Celery task.

### Step 0: Source configuration
Each source's settings (start URLs, allowed domains, content selectors, tag rules, schedule) live in `config/sources.yml` and are copied into the `sources.crawl_config` column of the database by `python -m config.sync_sources`. The crawlers read their settings **from the database**, so a new source can be added as a database row with no code change.


**Libraries and main calls used in this step**

```python
# ── imports ──
import yaml                                        # PyYAML
from celery import Celery
from celery.schedules import crontab
from pydantic_settings import BaseSettings
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# ── main calls ──
yaml.safe_load(f)                                  # sync_sources.py: parse sources.yml
db.query(Source).filter_by(code=source_code).first()   # sync_sources.py: find/upsert the source row
app = Celery("knowledge_base", broker=settings.redis_url, backend=settings.redis_url, include=["tasks.pipeline_tasks"])
crontab(minute=..., hour=..., day_of_month=..., month_of_year=..., day_of_week=...)   # cron string -> Beat entry
class Settings(BaseSettings): ...                  # settings.py: values from .env
engine = create_engine(settings.database_url, pool_pre_ping=True)   # database.py
SessionLocal = sessionmaker(bind=engine)
```

### Step 1: Crawling
The HDB spider starts at its start URLs (for example `hdb.gov.sg/buying-a-flat`). It loads each page (in Playwright where JavaScript is needed), finds links, keeps only the in-scope ones, and continues until all relevant pages have been visited. A crawl job row is created for the run.


**Libraries and main calls used in this step**

```python
# ── imports ──
import scrapy
from bs4 import BeautifulSoup
from scrapy_playwright.page import PageMethod
from scrapy.crawler import CrawlerProcess

# ── main calls ──
yield scrapy.Request(url, callback=self.handle_response, meta=meta)     # base.py: start URLs
response.css("a::attr(href)").getall()             # base.py: discover links
yield response.follow(url, callback=self.handle_response, meta=meta)    # base.py: follow in-scope links
PageMethod("wait_for_load_state", wait_event)      # base.py: wait for JS pages to render
soup = BeautifulSoup(html, "lxml")                 # base.py: quick main-content check
soup.find_all(["script", "style", "nav", "footer"]) ; tag.decompose()   # remove noise
soup.select_one(selector).get_text(separator=" ", strip=True)           # per-source content_selectors
process = CrawlerProcess(settings)                 # runner.py
process.crawl("hdb") ; process.start()             # run the spiders
```

### Step 2: Cleaning
For each downloaded page, the raw HTML or PDF is uploaded to S3, and the text is extracted straight away: navigation, footers and scripts are removed, headings are collected and tables are converted to Markdown in place. The result is saved as `raw_text` with a SHA-256 hash. The change-detection rules then decide whether the document is new (`pending`), changed (back to `pending`), unchanged (only `last_seen_at` updated) or a duplicate (skipped). Documents not seen in this crawl are marked `deleted`.


**Libraries and main calls used in this step**

```python
# ── imports ──
import boto3
from bs4 import BeautifulSoup
import pdfplumber
import fitz                                        # PyMuPDF
from scrapy.exceptions import DropItem
from sqlalchemy import func

# ── main calls ──
boto3.client("s3", endpoint_url=settings.s3_endpoint, ...)              # storage.py
get_s3_client().put_object(Bucket=..., Key="raw-html/hdb/2026-11-24/<hash>.html", Body=...)   # upload raw file
soup = BeautifulSoup(html, "html.parser")          # html_extractor.py: full extraction
soup.select_one(selector) ; tag.decompose()        # content node, remove noise
node.get_text(separator="\n", strip=True)          # text and heading extraction
with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf: ...                 # pdf_extractor.py
page.extract_words() ; page.find_tables()          # reading order + table positions
doc = fitz.open(stream=pdf_bytes, filetype="pdf")  # fallback + scanned-PDF check
page.get_text("text", sort=True) ; page.get_images(full=True)
hashlib.sha256(_normalize_text(text).encode("utf-8")).hexdigest()       # pipelines.py: content hash
raise DropItem("Failed to persist to DB")          # skip a failed item
existing.last_seen_at = func.now()                 # unchanged page: refresh liveness time
```

### Step 3: Chunking
The processing stage takes every `pending` document. A 3,000-word article about "HDB Resale Eligibility" is split into roughly 8 prose chunks of about 380 words each (512 tokens, with a 64-token overlap), plus one chunk per table. Each chunk gets a heading path like "Resale > Eligibility > Singapore Citizens". The validator then drops empty, too-short, too-long, boilerplate and duplicate chunks, and the survivors are saved to `processed_chunks`. The document becomes `processed` (or `failed`, with the error saved).


**Libraries and main calls used in this step**

```python
# ── imports ──
import tiktoken
from langchain_text_splitters import RecursiveCharacterTextSplitter
import structlog
from sqlalchemy.orm import Session

# ── main calls ──
splitter = RecursiveCharacterTextSplitter.from_tiktoken_encoder(
    encoding_name="cl100k_base", chunk_size=512, chunk_overlap=64, separators=["\n\n", "\n", " "])   # chunker.py
pieces = splitter.split_text(segment_text)         # split prose into chunks
enc = tiktoken.get_encoding("cl100k_base") ; len(enc.encode(text))      # token_count (also validator.py)
structlog.contextvars.bind_contextvars(source=src_code, url=doc.url)    # runner.py: log context
db.query(ProcessedChunk).filter_by(document_id=doc.id).delete()         # replace old chunks
db.add(ProcessedChunk(...)) ; db.commit()          # save new chunks
```

### Step 4: Metadata Extraction
Each chunk is tagged: `source_agency=Housing & Development Board`, `section=Resale`, `effective_date=2026-02-06`, and tags such as `property_type=[HDB]`, `citizenship=[SC, PR]`, `topic=[eligibility, resale]`. Tags come from the source's keyword rules.


**Libraries and main calls used in this step**

```python
# ── imports ── (standard library only)
import re
from datetime import datetime

# ── main calls ──
re.search(pattern, text, re.IGNORECASE)            # metadata_extractor.py: find the effective date
datetime.strptime(m.group(2), "%B").month          # month name -> number, then ISO YYYY-MM-DD
```

### Step 5: Embedding Generation
Every chunk with no embedding yet is sent in batches to `text-embedding-3-large`, which returns a 3,072-dimensional vector for each. The batch is retried with backoff, and OpenAI is used if OpenRouter keeps failing.


**Libraries and main calls used in this step**

```python
# ── imports ──
import openai
import tiktoken
from openai import OpenAI
from tenacity import retry, retry_if_not_exception_type, stop_after_attempt, wait_exponential

# ── main calls ──
OpenAI(api_key=settings.openrouter_api_key, base_url=settings.openrouter_base_url)   # primary client
OpenAI(api_key=openai_key)                         # fallback client
response = client.embeddings.create(model="text-embedding-3-large", input=texts)    # embedding_service.py: the embedding call
vectors = [item.embedding for item in response.data] ; response.usage.total_tokens
@retry(retry=retry_if_not_exception_type(openai.AuthenticationError),
       stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=30))   # retry with backoff
len(tiktoken.get_encoding("cl100k_base").encode(chunk.chunk_text))      # batch sizing by tokens
```

### Step 6: Indexing
The vectors are written to Pinecone (source namespace and `all`, with filter metadata) and to pgvector (HNSW index), archived to S3, and the vector id is saved in `processed_chunks.embedding_id`. The search index is then up to date for that source.


**Libraries and main calls used in this step**

```python
# ── imports ──
from pinecone import Pinecone, ServerlessSpec
from sqlalchemy import text
from pgvector.sqlalchemy import Vector
import boto3
from tenacity import retry, stop_after_attempt, wait_exponential

# ── main calls ──
pc = Pinecone(api_key=...) ; pc.create_index(name=..., dimension=3072, metric="cosine", spec=ServerlessSpec(...))
index = pc.Index(index_name)                       # pinecone_store.py
index.upsert(vectors=batch, namespace="hdb")       # also namespace="all"
conn.execute(text("UPDATE processed_chunks SET embedding = CAST(:vec AS vector) WHERE id = :id"), {...})   # pgvector_store.py
embedding = Column(Vector(3072))                   # models.py: the pgvector column
get_s3_client().put_object(Bucket=..., Key="processed/embeddings/<date>/<vector_id>.json", Body=...)   # archive
conn.execute(text("UPDATE processed_chunks SET embedding_id = :eid WHERE id = :id"), {...})   # pipeline.py
```

### Step 7: Retrieval (at query time)
A user asks: "What grants are available for first-time buyers?"
1. The question is expanded into three phrasings, and filters are inferred (for example source `hdb`).
2. Each phrasing is converted to a vector.
3. Pinecone (or pgvector, if Pinecone fails) returns the closest vectors, and BM25 returns the best keyword matches. Both are filtered the same way.
4. The two rankings are merged with Reciprocal Rank Fusion, combined across the phrasings, and the top 5 chunks are loaded from PostgreSQL with their text, headings, tags and source URLs.
5. The chatbot receives the chunks and generates an answer citing specific grant amounts and eligibility criteria.


**Libraries and main calls used in this step**

```python
# ── imports ──
from embedders.bm25_store import BM25Store
from embedders.embedding_service import EmbeddingService
from embedders.pgvector_store import PgVectorStore
from embedders.pinecone_store import PineconeStore
from openai import OpenAI
from rank_bm25 import BM25Okapi
from fastapi import Depends, FastAPI
from pydantic import BaseModel, Field
from sqlalchemy import text

# ── main calls ──
client.chat.completions.create(model=self._model, messages=[...], temperature=0.1, max_tokens=80)   # query_expander.py
vector = embedding_service.embed_query(phrase)     # retrieval.py -> embeddings.create(...)
index.query(vector=vector, top_k=..., filter=..., namespace="all")      # pinecone_store.py
conn.execute(text("... ORDER BY pc.embedding::halfvec(3072) <=> CAST(:vec AS halfvec(3072)) ..."))   # pgvector_store.py
index = BM25Okapi([chunk.lower().split() for chunk in chunks]) ; index.get_scores(query_tokens)      # bm25_store.py
conn.execute(text("SELECT ... WHERE pc.embedding_id = ANY(:ids)"), {"ids": ids})   # retrieval.py: load chunk text
@app.post("/retrieve", response_model=RetrieveResponse)                  # app.py: the endpoint
class RetrieveRequest(BaseModel): query: str = Field(min_length=1)       # schemas.py: validation
```

### Step 8: Keeping it fresh
Celery Beat repeats steps 1-6 on a schedule. Pages that changed are re-processed and re-embedded; pages that disappeared have their vectors and chunks removed. Progress is visible in `GET /jobs`, `GET /stats` and Grafana.


**Libraries and main calls used in this step**

```python
# ── imports ──
import subprocess
from celery import Celery
from celery.schedules import crontab
import httpx
import structlog

# ── main calls ──
run_source_pipeline_task.delay(source_code, job_type)                    # app.py: queue from /crawl
subprocess.run([sys.executable, "run_pipeline.py", source_code, "--incremental"], capture_output=True)   # pipeline_tasks.py: one process per crawl
raise self.retry(exc=exc, countdown=300)           # Celery retry on failure
httpx.post(settings.slack_webhook_url, json=payload, timeout=10.0)       # notifications.py: Slack alert
structlog.get_logger(__name__).info("task.pipeline_started", source=source_code)   # structured logs
```

---

## Project Structure

```
knowledge-base/
|-- run_pipeline.py            # CLI entry point: crawl -> process -> embed
|-- clean_data.py              # Wipes DB tables and MinIO prefixes (development only)
|-- backfill_pgvector.py       # Restores pgvector rows from the S3 embedding archive
|-- ingest_offline_docs.py     # Ingests local HTML/PDF snapshots into an isolated eval DB/index
|-- setup.sh                   # One-command local setup
|-- crawlers/                  # Web crawlers
|   |-- base.py                # BaseCrawler: DB-driven config, link rules, Playwright
|   |-- spiders/               # hdb.py, ura.py, iras.py, mas.py, cpf.py, generic.py
|   |-- pipelines.py           # S3Pipeline (upload + extract + hash), PostgresPipeline (dedup, change detection)
|   |-- items.py               # CrawlItem fields
|   |-- scrapy_settings.py     # Delays, retries, Playwright, pipelines
|   |-- runner.py              # Starts spiders, records crawl_jobs and a summary
|-- processors/                # Extraction, chunking, validation
|   |-- html_extractor.py      # HTML cleaning, headings, inline tables
|   |-- pdf_extractor.py       # pdfplumber + PyMuPDF fallback, scanned-PDF detection
|   |-- table_extractor.py     # HTML/PDF tables -> Markdown
|   |-- metadata_extractor.py  # Title, section, effective date, tags
|   |-- chunker.py             # 512/64 token chunks, atomic tables, heading paths
|   |-- validator.py           # Chunk quality gate
|   |-- runner.py              # Processes all pending documents
|-- embedders/                 # Embedding and vector stores
|   |-- embedding_service.py   # OpenRouter -> OpenAI embeddings, batching, token logging
|   |-- pinecone_store.py      # Primary vector store (namespaces per source + all)
|   |-- pgvector_store.py      # Backup vector store (HNSW on halfvec)
|   |-- bm25_store.py          # In-memory keyword index with auto-refresh
|   |-- pipeline.py            # Embeds new chunks, dual-write, cleanup of deleted docs, purge
|-- api/                       # FastAPI service
|   |-- app.py                 # Endpoints
|   |-- retrieval.py           # Vector / hybrid search and RRF
|   |-- query_expander.py      # LLM query rewriting and entity extraction
|   |-- metadata_filter_inference.py  # Rule-based filters from the question
|   |-- schemas.py, dependencies.py
|-- tasks/pipeline_tasks.py    # Celery tasks (crawl in subprocess, process, embed)
|-- config/                    # Settings, DB, models, storage, scheduling
|   |-- settings.py            # Environment variable configuration
|   |-- database.py            # PostgreSQL connection management
|   |-- models.py              # Source, RawDocument, ProcessedChunk, CrawlJob, TaskExecution
|   |-- storage.py             # S3/MinIO client
|   |-- celery_app.py          # Celery app and Beat schedule
|   |-- notifications.py       # Slack failure alerts
|   |-- logger.py              # Structured logging setup
|   |-- sources.yml            # Source definitions and crawl schedules
|   |-- sync_sources.py        # Copies sources.yml into the database
|-- alembic/versions/          # Database migrations 001-008
|-- eval/                      # retrieval_eval.py and testset.csv
|-- grafana/                   # Provisioned datasource and dashboard
|-- tests/                     # Unit and integration tests
|-- docs/                      # Architecture notes, QA docs, TECHNICAL_REFERENCE.md
|-- docker-compose.yml         # Postgres, Redis, MinIO, app, api, worker, beat, Grafana
|-- pyproject.toml             # Python project configuration and dependencies
|-- .env.example               # Environment variable template
```

---

## Tech Stack

| Component | Technology | Purpose |
|-----------|------------|---------|
| Language | Python 3.11+ | Primary development language |
| Web Crawling | Scrapy | Crawl engine: scheduling, link following, retries, pipelines |
| JS Rendering | Playwright, scrapy-playwright | Handle JavaScript-rendered pages (HDB, CPF) |
| HTML Parsing | BeautifulSoup4, lxml | Content extraction and table parsing |
| PDF Extraction | pdfplumber, PyMuPDF | Text and table extraction, scanned-PDF detection |
| Text Chunking | langchain-text-splitters, tiktoken | Token-based chunking and token counting |
| Embeddings | OpenAI SDK, `text-embedding-3-large` (via OpenRouter, OpenAI fallback) | 3072-dimension vector generation |
| Vector Store | Pinecone (primary), pgvector (backup, HNSW on halfvec) | Vector similarity search |
| Keyword Search | rank-bm25 | In-memory BM25 for hybrid retrieval |
| Query Expansion | OpenRouter chat model (default `openai/gpt-4o-mini`) | Alternative phrasings, entity extraction |
| Database | PostgreSQL 16, SQLAlchemy 2, Alembic, psycopg2 | Metadata, raw content, crawl history, migrations |
| Cache / Broker | Redis 7 | Celery broker and result backend |
| Object Storage | S3 / MinIO (boto3) | Raw HTML/PDF files and embedding archive |
| API | FastAPI, uvicorn, pydantic | Retrieval and pipeline-control endpoints |
| Task Queue | Celery + Redis (Beat) | Scheduled crawl automation |
| Notifications | httpx | Slack webhook on final failure |
| Logging | structlog | Structured logs with run id, source and URL |
| Monitoring | Grafana | Dashboard over PostgreSQL |
| Dev Tools | pytest, ruff, black, mypy | Tests, lint, format, types |
| Containerization | Docker Compose | Local development environment |

For the exact imports in each file, see [docs/TECHNICAL_REFERENCE.md](docs/TECHNICAL_REFERENCE.md).

---

## API Endpoints

Base URL `http://localhost:8000` (Swagger UI at `/docs`).

| Method | Path | Purpose | Auth |
|--------|------|---------|------|
| GET | `/health` | Liveness check | none |
| POST | `/retrieve` | Top-k chunks for a query (`query`, `top_k`, `search_mode` = `hybrid` or `vector`, `filters`: `source`, `property_type`, `citizenship_type`, `topic`) | none |
| POST | `/crawl` | Queue crawl -> process -> embed for one source (`source_code`, `job_type`, `page_limit`) | admin |
| POST | `/process` | Queue processing of pending documents | admin |
| POST | `/embed` | Queue embedding of un-embedded chunks | admin |
| GET | `/jobs` | Task history (filter by `source`, `status`) | admin |
| GET | `/stats` | Documents, chunks, embedding coverage and last crawl per source | admin |
| GET | `/config` | Active Pinecone index | admin |
| POST | `/admin/reindex-bm25` | Rebuild the keyword index now | admin |

"admin" endpoints require the `X-API-Key` header when `ADMIN_API_KEY` is set (open when it is empty, for local development only).

---

## Configuration

Settings come from `.env` (template: `.env.example`).

| Variable | Purpose |
|----------|---------|
| `DATABASE_URL`, `REDIS_URL` | PostgreSQL and Redis connections |
| `S3_ENDPOINT`, `S3_ACCESS_KEY`, `S3_SECRET_KEY`, `S3_REGION`, `S3_BUCKET` | MinIO / S3 |
| `OPENROUTER_API_KEY`, `OPENROUTER_BASE_URL`, `OPENROUTER_CHAT_MODEL` | Primary embeddings provider and the query-expansion model |
| `OPENAI_API_KEY` | Fallback embeddings provider |
| `PINECONE_API_KEY`, `PINECONE_INDEX`, `PINECONE_ENVIRONMENT` | Vector index (without a key, only pgvector is used) |
| `CRAWL_DELAY`, `CRAWL_USER_AGENT`, `CRAWL_RESPECT_ROBOTS_TXT`, `CRAWL_MAX_RETRIES` | Global crawl defaults (each source can override them) |
| `SLACK_WEBHOOK_URL` | Failure notifications (optional) |
| `ADMIN_API_KEY` | Protects admin endpoints (optional) |
| `BM25_REFRESH_SECONDS` | BM25 auto-rebuild age (default 300) |
| `CELERY_TIMEZONE` | Schedule timezone (default `Asia/Singapore`) |

---

## Quick Start

All Python runs inside the `KB-Pipeline-App` container, so no local virtual environment is needed. Docker Desktop must be running.

```bash
# 1. First-time setup: .env, containers, migrations, source config, MinIO bucket
bash setup.sh
#    (then add your API keys to .env)

APP="docker exec KB-Pipeline-App"

# 2. Run everything for all sources (crawl -> process -> embed)
$APP python run_pipeline.py

# 3. Or run one source, or one stage
$APP python run_pipeline.py hdb
$APP python run_pipeline.py --crawl-only -S CLOSESPIDER_PAGECOUNT=10   # small test crawl
$APP python run_pipeline.py --process-only
$APP python run_pipeline.py --embed-only

# 4. Ask a question
curl -X POST localhost:8000/retrieve -H 'Content-Type: application/json' \
  -d '{"query": "What is the ABSD for a PR buying a second condo?", "top_k": 5}'

# 5. Check retrieval quality
$APP python eval/retrieval_eval.py --k 5 --mode hybrid
```

Other useful URLs: MinIO console `localhost:9001`, Grafana `localhost:3000`.

---

## Glossary (Quick Reference)

| Term | One-Line Definition |
|------|-------------------|
| **Crawling** | Automatically visiting websites and downloading their content |
| **Spider** | A program that crawls a specific website |
| **Cleaning** | Removing noise (menus, footers, scripts) from raw HTML to get pure text |
| **Chunking** | Breaking long documents into smaller overlapping pieces (~512 tokens each) |
| **Token** | A unit of text for AI models; roughly 3/4 of a word |
| **Metadata** | Labels describing a chunk (source, topic, property type, citizenship) |
| **Vector** | A list of numbers representing the meaning of a piece of text |
| **Embedding** | The process of converting text into a vector using an AI model |
| **Embedded Vector** | The output vector after embedding; stored in the vector database |
| **Vector Store** | A specialized database for storing and searching vectors by similarity |
| **Indexing** | Organizing vectors in a database for fast similarity search |
| **Cosine Similarity** | A math formula measuring how similar two vectors are (0 to 1) |
| **RAG** | Retrieval-Augmented Generation; finding relevant docs before generating an AI answer |
| **Hybrid Retrieval** | Combining vector search (meaning) with keyword search (exact words) |
| **BM25** | A keyword-based search algorithm that ranks documents by word frequency |
| **Change Detection** | Identifying which pages have been added, modified, or deleted since the last crawl |
| **Content Hash** | A digital fingerprint (SHA-256) of page content used for change detection |
| **Upsert** | Insert-or-update operation; avoids duplicates when re-indexing |
| **Namespace** | A logical partition in the vector store (one per government source) |
| **Pipeline** | A series of automated processing steps that data flows through sequentially |
| **Dual-write** | Writing every vector to both Pinecone and pgvector so either can serve queries |
| **RRF** | Reciprocal Rank Fusion; merges the vector and keyword rankings into one list |
| **halfvec** | Half-precision vector type that lets pgvector build an HNSW index on 3072-dimension vectors |
| **Query Expansion** | Rewriting a question into several phrasings (and extracting entities) before searching |
| **Celery Beat** | The scheduler that starts crawls at set times (weekly full, daily incremental) |
| **Crawl Job** | One crawl run for one source, with counts of new, changed, deleted and errored pages |
| **needs_ocr** | Flag on a scanned PDF whose text cannot be read without OCR (OCR not built yet) |
