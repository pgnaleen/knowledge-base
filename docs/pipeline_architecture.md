# KB-Pipeline Architecture — Two-Stage Design

**Last updated:** 2026-05-07  
**Overview:** Crawl + Extract → Read + Chunk + Embed

---

## Pipeline 1: Scrape + Extract + Save

### Stage 1.1 — Spider Crawling

**Entry point:** `crawlers/runner.py:run_crawlers()`

```python
# crawlers/runner.py, line 22
def run_crawlers(source_codes: list[str] | None = None, job_type: str = "full"):
    process = CrawlerProcess(get_project_settings())
```

For each source (HDB, URA, IRAS, MAS, CPF), a Scrapy spider is spawned.

**Spider classes:** `crawlers/spiders/{hdb,ura,iras,mas,cpf}.py`

Each extends `BaseCrawler` (`crawlers/base.py:23`):

```python
class BaseCrawler(scrapy.Spider):
    def start_requests(self):  # line 39
        # Read js_rendering flag from sources.yml
        js = self.source_config.get("js_rendering", False)
        for url in self.get_start_urls():
            if js and not url.lower().endswith(".pdf"):
                meta["playwright"] = True  # line 44
```

**JavaScript rendering:** If `js_rendering: true` in `config/sources.yml` (HDB, CPF, MAS), Playwright opens a real browser, waits for `domcontentloaded`, captures fully rendered HTML. Otherwise standard HTTP GET.

---

### Stage 1.2 — Response Arrival & Content Type Detection

**Callback:** `BaseCrawler.handle_response()` (line 50)

```python
def handle_response(self, response):
    yield from self.parse_document(response)  # line 51
```

Each spider's `parse_document()` implementation checks Content-Type:

**Example — HDB spider** (`crawlers/spiders/hdb.py:30`):

```python
def parse_document(self, response) -> Generator[CrawlItem, None, None]:
    content_type_header = response.headers.get("Content-Type", b"").decode("utf-8", errors="ignore").lower()
    is_pdf = self._is_pdf_url(response.url) or "application/pdf" in content_type_header
    is_html = "text/html" in content_type_header
    
    if is_pdf:
        # yield PDF item (line 34-40)
    elif is_html:
        # yield HTML item (line 42-50)
    else:
        # skip non-text responses silently (line 51)
```

**Content type routing:**
- `text/html` → HTML extraction path
- `application/pdf` → PDF extraction path  
- Any other type → skipped (logged as debug)

---

### Stage 1.3 — CrawlItem Creation

**Item class:** `crawlers/items.py:6`

```python
class CrawlItem(scrapy.Item):
    url = scrapy.Field()
    source_code = scrapy.Field()
    content_type = scrapy.Field()          # "html" or "pdf"
    raw_html = scrapy.Field()              # bytes
    raw_pdf = scrapy.Field()               # bytes
    raw_text = scrapy.Field()              # populated by S3Pipeline
    content_hash = scrapy.Field()          # populated by S3Pipeline
    s3_path = scrapy.Field()               # populated by S3Pipeline
```

Spider yields the item with raw bytes. Pipeline order in `scrapy.cfg`:
1. `S3Pipeline` (upload + extract)
2. `PostgresPipeline` (dedup + save)

---

### Stage 1.4 — S3Pipeline: Upload Raw File

**Class:** `crawlers/pipelines.py:23`

```python
class S3Pipeline:
    def process_item(self, item, spider):
        url_hash = hashlib.md5(item["url"].encode()).hexdigest()[:12]
        
        if item.get("raw_html"):
            key = upload_raw_html(  # config/storage.py
                item["source_code"], url_hash, 
                item["raw_html"].decode("utf-8", errors="replace")
            )
            item["s3_path"] = key  # e.g., "raw-html/hdb/2026-05-07/abc123.html"
```

**upload_raw_html()** (`config/storage.py`):
- Puts object to MinIO at bucket `sg-property-kb`, key `raw-html/{source}/{date}/{hash}.html`
- Returns the key
- Raw file is preserved regardless of extraction success/failure

---

### Stage 1.5 — S3Pipeline: HTMLExtractor / PDFExtractor

**For HTML:**

```python
# crawlers/pipelines.py, line 39-46
extracted = html_extractor.extract(
    item["raw_html"],
    source_url=item.get("url", ""),
    source_name=item.get("source_code", ""),
)
```

**HTMLExtractor** (`processors/html_extractor.py:class HTMLExtractor`):

```python
def extract(self, html: bytes, source_url: str, source_name: str) -> ExtractedDocument:
    soup = BeautifulSoup(html, "lxml")
    
    # Strip noise tags (line ~104-107)
    for tag in soup.find_all(["script", "style", "nav", "footer", "header", ...]):
        tag.decompose()
    
    # Strip class-based noise (line ~109-115)
    for tag in soup.find_all():
        if "navbar" in tag.get("class", []):  # or sidebar, cookie, banner, etc.
            tag.decompose()
    
    # Find main content node (line ~117)
    main = soup.find("main") or soup.find("article") or soup.find(role="main")
    
    # Extract text with \n separators (line ~119)
    text = main.get_text(separator="\n", strip=True)
    
    # Extract tables (line ~additional methods)
    tables = self._extract_tables(soup)
    
    # Extract headings structure
    headings = self._extract_headings(soup)
    
    return ExtractedDocument(
        title=..., text=text, headings=headings, tables=tables, ...
    )
```

**For PDF:**

```python
# crawlers/pipelines.py, line 57-66
extracted = pdf_extractor.extract(
    item["raw_pdf"],
    source_url=item.get("url", ""),
    source_name=item.get("source_code", "")
)
```

**PDFExtractor** (`processors/pdf_extractor.py:class PDFExtractor`):

```python
def extract(self, pdf_bytes: bytes, source_url: str, source_name: str) -> ExtractedDocument:
    try:
        doc = pdfplumber.open(BytesIO(pdf_bytes))
        text = "\n\n".join(page.extract_text() or "" for page in doc.pages)
    except:
        # Fallback to PyMuPDF
        text = self._extract_with_pymupdf(pdf_bytes)
    
    # Check for scanned PDF
    is_scanned = not text.strip() or very low word count
    
    return ExtractedDocument(text=text, is_scanned=is_scanned, ...)
```

---

### Stage 1.6 — S3Pipeline: Merge Tables into raw_text

**New behavior:** Tables extracted by HTMLExtractor are converted to Markdown and merged inline into `raw_text`.

Example:
```
Buyer's Stamp Duty Rates

The following rates apply:

| Purchase Price    | BSD Rate |
|-------------------|----------|
| First $180,000    | 1%       |
| Next $180,000     | 2%       |
| Remaining         | 3%       |

Additional note: BSD applies when...
```

Tables stay at their original position in the document. The `raw_text` field is a single string containing all text + inline markdown tables.

---

### Stage 1.7 — S3Pipeline: Content Hash Computation

**Helper functions** (`crawlers/pipelines.py:16-25`):

```python
def _normalize_text(text: str) -> str:
    """Collapse whitespace for hashing — whitespace-insensitive change detection."""
    if not text:
        return ""
    return re.sub(r"\s+", " ", text).replace("\x00", "").strip()

def _sanitize_text(text: str) -> str:
    """Strip NUL bytes that PostgreSQL TEXT columns reject."""
    return text.replace("\x00", "") if text else ""
```

**Hash computation** (line 49-50):

```python
item["raw_text"] = _sanitize_text(extracted.text.strip())
item["content_hash"] = hashlib.sha256(_normalize_text(extracted.text).encode("utf-8")).hexdigest()
```

**Why two different transformations:**
- `raw_text`: preserves paragraph breaks (`\n`) for readability and chunking quality
- `content_hash`: collapses all whitespace so layout-only changes don't trigger reprocessing (e.g., HDB reformats page navigation but actual content unchanged)

---

### Stage 1.8 — PostgresPipeline: Cross-URL Dedup

**Class:** `crawlers/pipelines.py:78`

```python
class PostgresPipeline:
    def process_item(self, item, spider):
        source = self.db.query(Source).filter_by(code=item["source_code"]).first()
        content_hash = item.get("content_hash", "")
        
        # Step 1: Cross-URL duplicate detection (line 91-102)
        hash_match = self.db.query(RawDocument).filter_by(content_hash=content_hash).first()
        if hash_match and hash_match.url != item["url"]:
            logger.info("Skipped duplicate content", url=item["url"], matched_url=hash_match.url)
            return item  # Skip — identical content already stored
```

Query: `SELECT * FROM raw_documents WHERE content_hash = ?`

If a row with the same hash exists at a **different URL**, the current item is skipped entirely. No duplicate rows created.

---

### Stage 1.9 — PostgresPipeline: URL-Level Dedup / Update

```python
# Step 2: URL-level change detection (line 103-117)
existing = self.db.query(RawDocument).filter_by(source_id=source.id, url=item["url"]).first()

if existing:
    if existing.content_hash != content_hash:
        # Content changed
        existing.content_hash = content_hash
        existing.content_type = item.get("content_type")
        existing.raw_text = item.get("raw_text", "")
        existing.s3_path = item.get("s3_path") or existing.s3_path
        existing.status = "pending"  # Mark for reprocessing
        self.db.commit()
        logger.info("Updated document", url=item["url"])
    else:
        logger.info("Skipped unchanged", url=item["url"])
else:
    # New URL
    doc = RawDocument(
        source_id=source.id,
        url=item["url"],
        content_hash=content_hash,
        content_type=item.get("content_type"),
        raw_text=item.get("raw_text", ""),
        s3_path=item.get("s3_path"),
        status="pending"
    )
    self.db.add(doc)
    self.db.commit()
    logger.info("Created document", url=item["url"])
```

**Three scenarios:**
1. **New URL** → INSERT `raw_documents` row
2. **URL exists, same hash** → skip (unchanged content)
3. **URL exists, different hash** → UPDATE, set `status = pending` (content changed, needs reprocessing)

Session rollback on error (line 138):
```python
except Exception as e:
    self.db.rollback()  # Clear rolled-back transaction state
    logger.error("PostgresPipeline error", url=item.get("url"), error=str(e))
```

**End of Pipeline 1.** Database now contains:
- `raw_documents.raw_text` — extracted, formatted text (with inline markdown tables)
- `raw_documents.content_hash` — whitespace-insensitive fingerprint
- `raw_documents.s3_path` — pointer to MinIO raw file
- `raw_documents.status` — `pending` (waiting for processing)

---

---

## Pipeline 2: Chunk + Embed + Store

### Stage 2.1 — Fetch Pending Documents

**Entry point:** `processors/runner.py:process_pending_documents()`

```python
def process_pending_documents():
    """Find all pending raw documents, extract, chunk, validate, and save."""
    db: Session = SessionLocal()
    
    pending_docs = db.query(RawDocument).filter(RawDocument.status == "pending").all()
```

**Key change:** No S3 download, no re-extraction. `raw_text` is already populated from Pipeline 1 and stored in the database.

---

### Stage 2.2 — Chunking via RecursiveCharacterTextSplitter

**Class:** `processors/chunker.py:17`

```python
class DocumentChunker:
    def __init__(self, chunk_size: int = 512, chunk_overlap: int = 64):
        self._splitter = RecursiveCharacterTextSplitter.from_tiktoken_encoder(
            encoding_name="cl100k_base",  # Matches OpenAI embedding model
            chunk_size=chunk_size,        # 512 tokens
            chunk_overlap=chunk_overlap   # 64 tokens
        )
    
    def chunk(self, doc: ExtractedDocument, metadata: ExtractedMetadata) -> list[DocumentChunk]:
        chunks: list[DocumentChunk] = []
        
        # Split text (line 47-48)
        pieces = self._splitter.split_text(doc.text)
        
        # For each chunk (line 50-67)
        for piece, offset in zip(pieces, piece_offsets):
            chunks.append(
                DocumentChunk(
                    chunk_text=piece,
                    chunk_index=counter,
                    token_count=len(_enc.encode(piece))
                )
            )
```

**Splitting strategy (LangChain):** Tries to break on these separators in order:
1. `\n\n` (paragraph breaks) — highest priority
2. `\n` (line breaks)
3. ` ` (spaces) — last resort

This preserves paragraph and sentence boundaries where possible.

**Markdown tables:** Because tables are already inline in `raw_text` as Markdown, they're preserved as-is within chunks. A well-formatted table (e.g., 20 rows × 3 columns = ~100 tokens) will fit within a 512-token chunk.

---

### Stage 2.3 — Chunk Validation

**Class:** `processors/validator.py:class ChunkValidator`

```python
def validate(self, chunks: list[DocumentChunk]) -> ValidationResult:
    valid = []
    issues = []
    
    for chunk in chunks:
        token_count = len(_enc.encode(chunk.chunk_text))
        
        if token_count < 50:
            issues.append(Issue("too_short", severity="error"))
        elif token_count > 512:
            issues.append(Issue("too_long", severity="warning"))
        else:
            valid.append(chunk)
    
    return ValidationResult(valid_chunks=valid, issues=issues)
```

**Filtering:**
- Too short (< 50 tokens) → filtered out (likely navigation fragment)
- Too long (> 512 tokens) → filtered out or flagged
- Valid chunks → saved to `processed_chunks` table

---

### Stage 2.4 — Save Processed Chunks

**In processors/runner.py:process_pending_documents()** (line 86-97):

```python
db.query(ProcessedChunk).filter_by(document_id=doc.id).delete()  # Clear old chunks

for chunk in result.valid_chunks:
    heading_str = " > ".join(h["text"] for h in chunk.heading_path) or None  # line 89
    db.add(ProcessedChunk(
        document_id=doc.id,
        chunk_text=chunk.chunk_text,
        chunk_index=chunk.chunk_index,
        heading_path=heading_str,
        token_count=chunk.token_count,
        metadata_json=chunk.metadata
    ))

db.commit()
```

**Model** (`config/models.py:ProcessedChunk`):
- `document_id` — FK to `raw_documents`
- `chunk_text` — the actual text (up to 512 tokens)
- `chunk_index` — position in document (0, 1, 2, ...)
- `heading_path` — breadcrumb (e.g., "Buying > Eligibility > Income") or NULL
- `token_count` — for monitoring
- `metadata_json` — source, tags, chunk_type ("text" or "table")
- `embedding_id` — NULL until embedding is computed

---

### Stage 2.5 — Mark Document Processed

**In runner.py** (line 108-110):

```python
doc.raw_text = extracted_doc.text.strip().replace("\x00", "")
doc.status = "processed"
doc.error_message = None
```

Update `raw_documents.status` → `processed`. Document is now ready for embedding.

---

### Stage 2.6 — Embedding via EmbeddingPipeline

**Entry point:** `run_pipeline.py` Stage 3 (line 68-75)

```python
if do_embed:
    from embedders.pipeline import EmbeddingPipeline
    
    pipeline = EmbeddingPipeline(
        openai_api_key=settings.openai_api_key or None,
        pinecone_api_key=settings.pinecone_api_key or None,
        pinecone_index=settings.pinecone_index or None
    )
    for code in (source_codes or [None]):
        stats = pipeline.embed_chunks(source_code=code)
```

**EmbeddingPipeline.embed_chunks()** (`embedders/pipeline.py:146`):

```python
def embed_chunks(self, source_code: str | None = None) -> int:
    """Embed unembedded processed_chunks and upsert to vector store."""
    sql = _UNEMBEDDED_CHUNKS_SQL.format(source_filter=source_filter)
    
    with self._engine.connect() as conn:
        rows = conn.execute(text(sql), params).fetchall()
    
    if not rows:
        return 0
    
    # Batch chunks and embed
    chunks: list[DocumentChunk] = []
    for row in rows:
        chunk_id, chunk_text, chunk_index, ..., source_url, src_code = row
        chunks.append(DocumentChunk(chunk_text=chunk_text, ...))
    
    # Call OpenAI (line 182)
    results = self._embedding_service.embed_chunks(chunks)
```

**EmbeddingService** (`embedders/embedding_service.py`):

```python
def embed_chunks(self, chunks: list[DocumentChunk]) -> list[EmbeddingResult]:
    """Batch embed chunks via OpenAI text-embedding-3-large."""
    texts = [chunk.chunk_text for chunk in chunks]
    
    # Batch size: up to 2048 texts per API call
    for batch in batch_iter(texts, 2048):
        response = self.client.embeddings.create(
            input=batch,
            model="text-embedding-3-large"  # 3072-dimension vectors
        )
        # Extract embedding vectors
```

**Upsert to vector stores** (line 185-192):

```python
id_map: dict = {}
if self._pinecone_store is not None:
    try:
        id_map = self._pinecone_store.upsert(results, db_ids)
    except Exception as exc:
        logger.warning("pipeline.pinecone_upsert_failed", error=str(exc))
        id_map = self._pgvector_store.upsert(results, db_ids)  # Fallback
else:
    id_map = self._pgvector_store.upsert(results, db_ids)
```

**Pinecone upsert** (`embedders/pinecone_store.py`):
- Namespace per source (e.g., `hdb`, `iras`, `cpf`)
- Vector ID = UUID (returned by Pinecone)
- Metadata includes: source_url, chunk_index, heading_path

**pgvector upsert** (`embedders/pgvector_store.py`):
- Inserts embedding vectors into `processed_chunks.embedding` (pgvector HNSW index)

---

### Stage 2.7 — Update processed_chunks with embedding_id

```python
# embedders/pipeline.py, line 217-224
with self._engine.begin() as conn:
    for chunk_id, vector_id in id_map.items():
        conn.execute(
            text("UPDATE processed_chunks SET embedding_id = :eid WHERE id = :id"),
            {"eid": vector_id, "id": chunk_id}
        )
```

---

## Summary: Data Flow

```
Raw HTML/PDF (MinIO)
    ↓
[Pipeline 1: S3Pipeline + PostgresPipeline]
    - Extract text + tables (inline markdown)
    - Compute content_hash (whitespace-insensitive)
    - Dedup by hash (cross-URL)
    - Dedup by URL (same-URL change detection)
    ↓
raw_documents table
    raw_text (already formatted with tables)
    content_hash
    s3_path
    status = "pending"
    ↓
[Pipeline 2: processors/runner.py]
    - No S3 download
    - No re-extraction
    - Chunk raw_text via RecursiveCharacterTextSplitter (512 tokens, 64 overlap)
    - Validate chunks
    ↓
processed_chunks table
    chunk_text (up to 512 tokens)
    chunk_index
    token_count
    metadata_json (tags, source, chunk_type)
    status = "processed"
    ↓
[Pipeline 2: embedders/pipeline.py]
    - Batch embed chunks (OpenAI text-embedding-3-large)
    - Upsert to Pinecone (primary) + pgvector (fallback)
    - Update embedding_id
    ↓
Pinecone + pgvector
    Vectors searchable for RAG retrieval
    Metadata: source_url, chunk_index, heading_path
```

---

## Configuration: sources.yml

Located at `config/sources.yml`. Example HDB entry:

```yaml
sources:
  hdb:
    name: "Housing & Development Board"
    base_url: "https://www.hdb.gov.sg"
    start_urls:
      - "https://www.hdb.gov.sg/buying-a-flat"
    allowed_domains:
      - "www.hdb.gov.sg"
    js_rendering: true                  # Use Playwright for JS rendering
    crawl_delay: 2.0
    content_selectors:
      - "div.hdb-main"                  # Target only this div for content extraction
      - "main"
    tag_config:
      property_type: ["hdb", "residential"]
```

**Fields:**
- `start_urls` — seed URLs for the spider
- `allowed_domains` — domain whitelist for link following
- `js_rendering` — if true, use Playwright; else standard HTTP
- `content_selectors` — optional targeted extraction (e.g., `div.mas-content` for MAS)
- `tag_config` — metadata tags to attach to chunks

---

## Running the Pipeline

```bash
# Full pipeline: crawl → process → embed
docker exec KB-Pipeline-App python run_pipeline.py

# Specific sources only
docker exec KB-Pipeline-App python run_pipeline.py hdb iras

# Crawl only
docker exec KB-Pipeline-App python run_pipeline.py --crawl-only

# Process + embed (skip crawl)
docker exec KB-Pipeline-App python run_pipeline.py --process-only

# Embed only (skip crawl and process)
docker exec KB-Pipeline-App python run_pipeline.py --embed-only

# Crawl + process (skip embed)
docker exec KB-Pipeline-App python run_pipeline.py --skip-embed
```

---

## Monitoring & Logs

All pipeline stages use structured logging via `structlog`:

```
2026-05-07 10:15:45 [info] stage_crawl_start sources="all"
2026-05-07 10:16:02 [info] Skipped duplicate content url="..." matched_url="..."
2026-05-07 10:16:15 [info] Created document url="..." source="hdb"
2026-05-07 10:17:30 [info] stage_process_start
2026-05-07 10:18:45 [info] Successfully processed document chunks_created=12
2026-05-07 10:19:00 [info] stage_embed_complete embedded=48
2026-05-07 10:19:05 [info] pipeline_complete
```

---

**End of Architecture Document.**
