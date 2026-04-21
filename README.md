# Knowledge Base - Singapore Property Regulatory Data Pipeline

Automated data pipeline that crawls, processes, and indexes Singapore property regulatory content from 5 government sources into a vector knowledge base for RAG retrieval.

---

## Table of Contents

1. [Government Sources](#government-sources)
2. [Pipeline Overview](#pipeline-overview)
3. [Key Concepts Explained](#key-concepts-explained)
4. [How the Pipeline Works (Step by Step)](#how-the-pipeline-works-step-by-step)
5. [Project Structure](#project-structure)
6. [Tech Stack](#tech-stack)
7. [Quick Start](#quick-start)

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
  [1. CRAWLING]         -- Visit websites and download pages/PDFs
        |
        v
  [2. CLEANING]         -- Remove junk (menus, footers, ads) and keep only useful text
        |
        v
  [3. CHUNKING]         -- Break long documents into small, digestible pieces
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
  [6. INDEXING]          -- Store vectors in a searchable database
        |
        v
  [7. RETRIEVAL]         -- When a user asks a question, find the most relevant pieces
```

---

## Key Concepts Explained

This section explains every technical concept used in this project. No prior knowledge of web crawling, data mining, or data analytics is assumed.

### Web Crawling

**What it is:** Web crawling (also called web scraping or spidering) is the process of automatically visiting websites and downloading their content, just like a person browsing the internet - but done by a computer program.

**How it works in this project:** Our crawlers visit 5 Singapore government websites. They start at a known page (like hdb.gov.sg/residential/buying-a-flat), read all the text on that page, then follow every link on that page to discover more pages. They keep doing this until they have visited every relevant page on the site.

**Real-world analogy:** Imagine sending someone into a library to photocopy every book. They start at one shelf, copy the book, check the "See Also" references at the back, go find those books, copy them too, and repeat until they've covered the whole library.

**Key terms:**
- **Spider:** The program that does the crawling. Each government source has its own spider (HDB spider, URA spider, etc.) because each website has a different structure.
- **Seed URLs / Start URLs:** The first pages the crawler visits. These are manually chosen pages that serve as entry points into the website.
- **Rate limiting:** Deliberately slowing down the crawler so it doesn't overwhelm the government website with too many requests. Our crawler waits 2 seconds between each page visit.
- **robots.txt:** A file that website owners place on their server to tell crawlers which pages they are allowed or not allowed to visit. Our crawler respects these rules.
- **Retry logic:** If a page fails to load (server is busy, network error), the crawler tries again. We use "exponential backoff" - waiting 2 seconds after the first failure, 4 seconds after the second, 8 seconds after the third.
- **Content hash (SHA-256):** A unique digital fingerprint of each page's content. If we crawl the same page again later and the hash is different, we know the content changed. SHA-256 is a mathematical function that turns any text into a fixed-length string of characters. Example: "Hello" always produces `2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824`.

### Cleaning (Content Extraction)

**What it is:** Raw web pages contain a lot of "noise" - navigation menus, footers, cookie banners, advertisements, JavaScript code, and styling information. Cleaning is the process of removing all this noise and keeping only the actual useful content.

**How it works in this project:** When we download an HDB page, the raw HTML file might be 50KB, but the actual informational content (the text a human would read) might only be 5KB. Our cleaner:
1. Removes all `<nav>`, `<footer>`, `<header>`, `<script>`, and `<style>` tags
2. Removes elements with CSS classes containing words like "sidebar", "cookie", "banner", "menu"
3. Finds the `<main>` content area (where the actual article text lives)
4. Converts the remaining HTML into clean plain text

**Real-world analogy:** Imagine you photocopied a whole newspaper page, but you only want the article text. You would cut away the ads, the page numbers, the newspaper logo, the navigation bar, and just keep the article. That's cleaning.

**Key terms:**
- **HTML (HyperText Markup Language):** The code that web pages are written in. It uses tags like `<h1>Title</h1>` and `<p>Paragraph text</p>` to structure content. Our cleaner parses this code to extract text.
- **BeautifulSoup:** A Python library we use to read and navigate HTML code, like a tool that understands the structure of a web page.
- **Main content area:** The part of a web page that contains the actual article or information, as opposed to the navigation, sidebars, and footers.

### PDF Extraction

**What it is:** Some government documents are published as PDF files rather than web pages (especially circulars, guidelines, and rate tables). PDF extraction is the process of pulling text and tables out of PDF files.

**How it works in this project:** When a crawler finds a link to a PDF file, it downloads the file and uses specialized tools (pdfplumber, PyMuPDF) to extract the text. This is more complex than HTML extraction because PDFs don't have a simple structure - text can be placed anywhere on the page, in any order.

**Challenges:**
- Multi-column layouts (text must be read in the correct order)
- Tables (cells must be associated with the correct row and column)
- Scanned PDFs (the PDF is actually an image, not selectable text - these need OCR)

### Chunking

**What it is:** After cleaning, we have long documents - some might be thousands of words. Chunking is the process of breaking these long documents into smaller, overlapping pieces called "chunks." Each chunk is a self-contained piece of information.

**Why we chunk:** AI models have a limited amount of text they can process at once. When a user asks a question, we don't want to send the entire HDB website to the AI. Instead, we find and send only the 3-5 most relevant chunks. Smaller pieces also produce better search results because the meaning is more focused.

**How it works in this project:**
- **Target chunk size:** 512 tokens (~380 words). This is large enough to contain a complete thought but small enough for precise retrieval.
- **Chunk overlap:** 64 tokens. Adjacent chunks share some text at their boundaries so that information isn't lost when a sentence spans two chunks.
- **Separators:** We split at natural boundaries - section headings first, then paragraph breaks, then sentence endings. We never split in the middle of a sentence.

**Real-world analogy:** Imagine you have a 100-page textbook. Instead of searching the whole book every time someone asks a question, you cut it into 200 index cards, each containing one key concept. Some cards overlap slightly so you don't lose context at the boundaries.

**Key terms:**
- **Token:** A unit of text that AI models use. A token is roughly 3/4 of a word. "Singapore Citizens" is about 3 tokens. We use the `tiktoken` library to count tokens accurately.
- **Chunk overlap:** The number of tokens shared between consecutive chunks. If Chunk 1 ends with "...eligible for the grant" and Chunk 2 starts with "eligible for the grant, applicants must...", the overlap ensures continuity.
- **Heading path:** A breadcrumb trail showing where a chunk came from in the original document. Example: "Eligibility > Singapore Citizens > First Timer". This helps the AI understand context.

### Metadata Extraction

**What it is:** Metadata is "data about data." For each chunk of text, we extract and store additional labels and tags that describe what the chunk is about, where it came from, and who it applies to.

**How it works in this project:** For each processed chunk, we extract:
- **Source agency:** Which government body published it (HDB, URA, IRAS, MAS, CPF)
- **Document title:** The page or document title
- **Section/category:** What topic it falls under (eligibility, stamp duty, housing scheme, etc.)
- **Property type:** What kind of property it applies to (HDB flat, private property, executive condominium, or all)
- **Citizenship type:** Who it applies to (Singapore Citizen, Permanent Resident, Foreigner, or all)
- **Topic tags:** Auto-classified keywords (e.g., "resale", "grant", "ABSD", "TDSR")
- **Effective date:** When the regulation was last updated, if available

**Why metadata matters:** When a user asks "What is the ABSD rate for a PR buying a second property?", we can use metadata to immediately narrow our search to IRAS chunks about stamp duty that apply to Permanent Residents. Without metadata, we would search all 2,000+ chunks from all 5 sources.

### Vector Embedding

**What it is:** This is the most important concept in the pipeline. Vector embedding is the process of converting text into a list of numbers (called a "vector") that mathematically represents the *meaning* of that text.

**Why we need it:** Computers don't understand language the way humans do. If a user asks "Can I use CPF to buy a flat?", a simple keyword search might miss a page that says "Ordinary Account funds may be utilized for HDB property acquisition" because it uses completely different words. But both sentences have similar *meaning*. Vector embeddings capture meaning, not just words.

**How it works:**
1. We send a chunk of text to OpenAI's embedding model (text-embedding-3-large)
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

**How it works in this project:** We use two vector stores:
- **Pinecone (primary):** A cloud-hosted vector database specifically designed for similarity search. It uses advanced algorithms to build an index that allows searching millions of vectors in under 100 milliseconds.
- **pgvector (backup):** A PostgreSQL extension that adds vector search capabilities to our existing database. Uses the HNSW algorithm (Hierarchical Navigable Small World) for efficient approximate nearest neighbor search.

**Key terms:**
- **Vector store / Vector database:** A specialized database designed to store vectors and find similar vectors quickly. Regular databases are great at finding exact matches (e.g., "find all rows where city = 'Singapore'"), but vector databases are designed for finding the *closest* matches in high-dimensional space.
- **Namespace:** A logical partition within the vector store. We create one namespace per source (hdb, ura, iras, mas, cpf) plus a unified namespace containing everything. This allows searching within one source or across all sources.
- **HNSW (Hierarchical Navigable Small World):** An algorithm for building search indexes on vectors. It creates a graph structure where similar vectors are connected, allowing the search to navigate quickly to the most relevant area.
- **Cosine similarity:** The mathematical method used to measure how similar two vectors are. It measures the angle between two vectors - if they point in the same direction, they are similar (score close to 1.0).
- **Upsert:** A database operation that inserts a new record or updates it if it already exists. When we re-crawl a page and the content has changed, we upsert the new vector rather than creating a duplicate.

### Retrieval (RAG - Retrieval-Augmented Generation)

**What it is:** Retrieval is the final step where the knowledge base is actually used. When a user asks a question through the chatbot, the system:
1. Converts the question into a vector (using the same embedding model)
2. Searches the vector store for the most similar chunks
3. Returns those chunks to the AI chatbot, which uses them to generate an accurate answer

**Key terms:**
- **RAG (Retrieval-Augmented Generation):** A technique where an AI chatbot first *retrieves* relevant documents from a knowledge base, then *generates* an answer based on those documents. This ensures the AI's answers are grounded in real, up-to-date government data rather than relying on its training data (which may be outdated).
- **Top-k retrieval:** Returning the k most similar chunks. We typically use k=5, meaning we retrieve the 5 most relevant chunks for each question.
- **Hybrid retrieval:** Combining two search methods for better results:
  - **Vector search:** Finds chunks with similar *meaning* (good for paraphrased questions)
  - **BM25 (keyword search):** Finds chunks containing the same *words* (good for specific terms like "ABSD" or "TDSR")
  - Results are merged using Reciprocal Rank Fusion (RRF), which combines rankings from both methods.
- **Query expansion:** Before searching, the system generates alternative phrasings of the user's question to improve recall. For example, "Can I use CPF for housing?" might be expanded to also search for "Ordinary Account withdrawal for property purchase" and "CPF housing scheme eligibility."
- **Context recall:** A quality metric measuring whether the retrieved chunks contain the information needed to answer the question. Target: > 0.85 (85%).
- **Context precision:** A quality metric measuring whether the retrieved chunks are actually relevant (not noise). Target: > 0.80 (80%).

### Change Detection

**What it is:** Government regulations change over time. Change detection is the system that identifies when a web page has been updated since our last crawl, so we only re-process and re-embed the content that actually changed.

**How it works:** Every time we crawl a page, we compute a SHA-256 hash of its content. On the next crawl, we compare the new hash with the stored hash. If they differ, the page has changed and needs re-processing.

**Types of changes tracked:**
- **New pages:** Pages that didn't exist in our previous crawl
- **Modified pages:** Pages where the content hash has changed
- **Deleted pages:** Pages that existed before but now return 404 errors

### Data Pipeline

**What it is:** A data pipeline is a series of automated processing steps that data flows through, from raw input to final output. Each step transforms the data in some way.

**Our pipeline stages:**
```
Raw HTML/PDF  -->  Clean Text  -->  Chunks  -->  Vectors  -->  Searchable Index
   (input)       (cleaning)    (chunking)   (embedding)      (indexing)
```

Each stage reads from the database, processes the data, and writes results back. This modular design means if one stage fails, we can restart from that point without redoing everything.

### Object Storage (S3 / MinIO)

**What it is:** Object storage is a system for storing files (like raw HTML pages and PDFs) in a scalable, organized way. We use it as a backup of all crawled content.

**Key terms:**
- **S3 (Simple Storage Service):** Amazon's cloud file storage service. Files are organized into "buckets" and identified by "keys" (like file paths).
- **MinIO:** An open-source S3-compatible storage system that runs locally on your computer. We use it during development so we don't need an AWS account.
- **Bucket structure:** Our files are organized as: `/raw-html/{source}/{date}/`, `/raw-pdf/{source}/{date}/`, `/processed/{source}/{date}/`

---

## How the Pipeline Works (Step by Step)

Here is a concrete example walking through the entire pipeline:

### Step 1: Crawling
The HDB spider starts at `hdb.gov.sg/residential/buying-a-flat`. It downloads the page, finds 15 links to other pages (eligibility, schemes, grants, etc.), visits each one, finds more links, and continues until it has visited all ~300 relevant pages. Each page's raw HTML is saved to S3 and recorded in the database.

### Step 2: Cleaning
The processor takes each raw HTML file and strips away navigation bars, footers, cookie consent banners, JavaScript, and CSS styling. For example, a 50KB HTML file becomes 3KB of clean text preserving headings and paragraph structure.

### Step 3: Chunking
A 3,000-word article about "HDB Resale Eligibility" is split into ~8 chunks of ~380 words each, with 50-word overlaps between consecutive chunks. Each chunk inherits the document's metadata and gets a heading path like "Resale > Eligibility > Singapore Citizens."

### Step 4: Metadata Extraction
Each chunk is tagged: `source=hdb`, `property_type=hdb`, `section=resale`, `citizenship=SC,PR`, `topics=[eligibility, resale, income_ceiling]`.

### Step 5: Embedding Generation
Each chunk is sent to OpenAI's API, which returns a 3,072-dimensional vector. All ~2,000 chunks across all 5 sources are embedded in batches of 2,048.

### Step 6: Indexing
All vectors are uploaded to Pinecone with their metadata. The index is organized by namespace (one per source) for efficient filtered searching.

### Step 7: Retrieval (at query time)
A user asks: "What grants are available for first-time buyers?"
1. The question is converted to a vector
2. Pinecone finds the 5 closest vectors (filtered to relevant sources)
3. The corresponding text chunks are returned to the chatbot
4. The chatbot generates an answer citing specific grant amounts and eligibility criteria

---

## Project Structure

```
knowledge-base/
|-- crawlers/                  # Web crawlers for each government source
|   |-- spiders/               # Individual spider implementations
|   |   |-- hdb_spider.py      # HDB (Housing & Development Board)
|   |   |-- ura_spider.py      # URA (Urban Redevelopment Authority)
|   |   |-- iras_spider.py     # IRAS (Inland Revenue Authority)
|   |   |-- mas_spider.py      # MAS (Monetary Authority)
|   |   |-- cpf_spider.py      # CPF Board
|   |-- base_crawler.py        # Abstract base class with shared functionality
|   |-- runner.py              # Crawler orchestration and DB persistence
|-- processors/                # Content extraction, cleaning, chunking (Week 2)
|-- embedders/                 # Embedding generation and vector store (Week 2)
|-- tests/                     # Unit and integration tests
|   |-- unit/                  # Fast tests using mocked data
|   |-- integration/           # Tests against live sites
|-- config/                    # Settings, DB models, storage, source definitions
|   |-- settings.py            # Environment variable configuration
|   |-- database.py            # PostgreSQL connection management
|   |-- models.py              # Database table definitions (Source, RawDocument, ProcessedChunk, CrawlJob)
|   |-- storage.py             # S3/MinIO file storage client
|   |-- logger.py              # Structured logging setup
|   |-- sources.yml            # Government source definitions and crawl configs
|-- docs/                      # Documentation and runbooks
|-- scripts/                   # Utility scripts
|-- docker-compose.yml         # Local infrastructure (PostgreSQL, Redis, MinIO)
|-- pyproject.toml             # Python project configuration and dependencies
|-- .env.example               # Environment variable template
|-- .gitignore                 # Git ignore rules
```

---

## Tech Stack

| Component | Technology | Purpose |
|-----------|------------|---------|
| Language | Python 3.11+ | Primary development language |
| Web Crawling | httpx, BeautifulSoup4 | HTTP requests and HTML parsing |
| JS Rendering | Playwright | Handle JavaScript-rendered pages (HDB, CPF) |
| PDF Extraction | pdfplumber, PyMuPDF | Text and table extraction from PDFs |
| Text Chunking | LangChain Text Splitters | Semantic document chunking |
| Embeddings | OpenAI text-embedding-3-large | 3072-dimension vector generation |
| Vector Store | Pinecone (primary), pgvector (backup) | Vector similarity search |
| Database | PostgreSQL 16 | Metadata, raw content, crawl history |
| Cache | Redis 7 | Crawl state, rate limiting |
| Object Storage | S3 / MinIO (local) | Raw HTML/PDF file storage |
| API | FastAPI | Retrieval API endpoint |
| Task Queue | Celery + Redis | Scheduled crawl automation |
| Testing | pytest | Unit and integration tests |
| Containerization | Docker Compose | Local development environment |

---

## Quick Start

```bash
# 1. Start infrastructure (PostgreSQL, Redis, MinIO)
docker compose up -d

# 2. Install Python dependencies
pip install -e ".[dev]"

# 3. Copy environment config and add your API keys
cp .env.example .env

# 4. Run a single crawler (e.g., HDB)
python -m crawlers.runner hdb

# 5. Run all 5 crawlers
python -m crawlers.runner

# 6. Run tests
pytest
```

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
