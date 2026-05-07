# KB-Pipeline Deep Dive: How `run_pipeline` Works

This document walks through every step from the moment a spider fetches a URL to the moment
processed chunks are written to the database. It explains **what happens, why, and exactly
which functions run** at each stage.

---

## Overview: The Two-Phase Architecture

```
Phase 1 — Scrapy Crawl (crawlers/)
  Spider fetches URL
    → S3Pipeline     (upload raw file + extract text + compute content_hash)
    → PostgresPipeline (dedup check + write raw_documents row)

Phase 2 — Processor Runner (processors/runner.py)
  process_pending_documents()
    → download from S3
    → HTMLExtractor / PDFExtractor  (full re-extraction with heading structure)
    → MetadataExtractor
    → DocumentChunker
    → ChunkValidator
    → write processed_chunks rows
```

Phase 1 runs per-crawl (Scrapy). Phase 2 runs on a schedule (or manually via
`docker exec KB-Pipeline-App python -m processors.runner`).

---

## Phase 1 — Scrapy Crawl Pipeline

### Step 1.1 — Spider Produces a CrawlItem

Each spider in `crawlers/` fetches a page and yields a `CrawlItem` dict:

```python
{
    "url":           "https://www.hdb.gov.sg/...",
    "source_code":   "hdb",
    "content_type":  "html",          # or "pdf"
    "raw_html":      b"<html>...",    # bytes of the full page (HTML only)
    # OR
    "raw_pdf":       b"%PDF-...",     # bytes of the PDF (PDF only)
    "metadata_json": {},
}
```

Scrapy routes this item through two pipelines in order: **S3Pipeline → PostgresPipeline**.

---

### Step 1.2 — S3Pipeline (`crawlers/pipelines.py` → `S3Pipeline.process_item`)

This pipeline does two things: **preserve the raw file** and **compute the content hash from text**.

#### 1.2.1 For HTML items

```python
# Upload raw HTML to MinIO (bucket: raw-html)
key = upload_raw_html(item["source_code"], url_hash, item["raw_html"].decode(...))
item["s3_html_key"] = key

# Extract text for hashing
extracted = HTMLExtractor().extract(item["raw_html"], source_url=..., source_name=...)
normalized_text = _normalize_text(extracted.text)
item["raw_text"]      = normalized_text
item["content_hash"]  = sha256(normalized_text.encode("utf-8")).hexdigest()
```

#### 1.2.2 For PDF items

Same pattern but with `PDFExtractor().extract(item["raw_pdf"], ...)`.

#### 1.2.3 Extraction failure fallback

If `HTMLExtractor` or `PDFExtractor` raises any exception, the pipeline catches it and falls
back gracefully:

```python
item["raw_text"]     = ""
item["content_hash"] = sha256(b"").hexdigest()
```

The raw file is still uploaded (never lost). The hash of empty bytes is deterministic, so
the document won't be treated as "new" on re-crawl if it continues to fail.

#### 1.2.4 `_normalize_text(text)` — what it does

```python
def _normalize_text(text: str) -> str:
    if not text:
        return ""
    normalized = re.sub(r"\s+", " ", text)  # collapse all whitespace runs to single space
    return normalized.strip()               # remove leading/trailing whitespace
```

This collapses spaces, tabs, and newlines into a single space, then strips edges.
The result is a single-line string. This is what gets hashed, so minor layout changes in the
HTML (extra newlines, different indentation) do not change the hash as long as the visible
text is the same.

**Why text-based hash, not raw bytes?**
If the government site changes its navigation bar, cookie banner, or CSS class names, the raw
HTML bytes change but the visible content doesn't. With raw-byte hashing that triggers a
re-process. With text-based hashing it doesn't.

---

### Step 1.3 — PostgresPipeline (`crawlers/pipelines.py` → `PostgresPipeline.process_item`)

Receives the item now enriched with `content_hash`, `raw_text`, and `s3_html_key` / `s3_pdf_key`.

#### 1.3.1 Source lookup

```python
source = db.query(Source).filter_by(code=item["source_code"]).first()
```

Looks up the agency row. If it doesn't exist, `DropItem` is raised — the item is discarded.

#### 1.3.2 Step 1: Cross-URL duplicate detection (new)

```python
hash_match = db.query(RawDocument).filter_by(content_hash=content_hash).first()
if hash_match and hash_match.url != item["url"]:
    # Same content text already exists under a different URL — skip
    return item
```

This is the cross-URL dedup. If the exact same extracted text is already stored from a
*different* URL (e.g. two different pages with identical content), the item is skipped.
No new `raw_documents` row is created.

#### 1.3.3 Step 2: URL-level change detection

```python
existing = db.query(RawDocument).filter_by(source_id=source.id, url=item["url"]).first()
```

Four outcomes:

| Scenario | Action |
|---|---|
| New URL, new content | `INSERT` new `raw_documents` row with `status="pending"` |
| Same URL, hash changed | `UPDATE` hash, raw_text, s3 keys, reset `status="pending"` |
| Same URL, hash unchanged | `SKIP` — log "Skipped unchanged" |
| Different URL, same hash | Already caught in Step 1 — `SKIP` |

On `INSERT`, `raw_text` is populated immediately from the item (text was extracted in S3Pipeline).

---

## Phase 2 — Processor Runner (`processors/runner.py`)

### Step 2.1 — Find Pending Documents

```python
pending_docs = db.query(RawDocument).filter(RawDocument.status == "pending").all()
```

Fetches every `raw_documents` row with `status = "pending"`.

### Step 2.2 — Skip Already-Processed Documents

```python
if doc.status == "processed":
    existing_chunks = db.query(ProcessedChunk).filter_by(document_id=doc.id).count()
    if existing_chunks > 0:
        continue  # skip — already done
```

Guard against reprocessing. In practice this only matters if the runner is interrupted
mid-batch and restarted — it won't reprocess documents that already have chunks.

### Step 2.3 — Download Raw File from S3

```python
if doc.s3_html_key:
    raw_bytes = storage.download_from_s3(doc.s3_html_key, settings.s3_bucket_raw_html)
elif doc.s3_pdf_key:
    raw_bytes = storage.download_from_s3(doc.s3_pdf_key, settings.s3_bucket_raw_pdf)
```

The original raw file is fetched from MinIO. This is needed because the chunker needs heading
structure and table layout — things that can't be derived from the flat `raw_text` string.

### Step 2.4 — Full Extraction (HTML or PDF)

This is a **second, full extraction** — more detailed than the one done in S3Pipeline.

#### For HTML: `HTMLExtractor.extract(html, source_url, source_name, content_selectors)`

**Step A: Parse with BeautifulSoup**

```python
soup = BeautifulSoup(html, "html.parser")
```

Builds a DOM tree from the raw HTML bytes.

**Step B: Extract title — `_extract_title(soup)`**

Tries in priority order:
1. `<title>` tag
2. First `<h1>` tag
3. `<meta name="og:title">` or `<meta property="og:title">`
4. Falls back to `"Untitled"`

**Step C: Remove noise — `_remove_noise(soup)`**

Destroys (`.decompose()`) the following HTML elements entirely:

*By tag name:*

| Tag | What it removes |
|---|---|
| `<script>` | JavaScript code |
| `<style>` | CSS styles |
| `<noscript>` | Fallback JS content |
| `<iframe>` | Embedded frames |
| `<nav>` | Navigation menus |
| `<header>` | Page headers |
| `<footer>` | Page footers |
| `<aside>` | Sidebars |

*By class/id/role — `_is_noise_by_class_or_id(tag)`*

Any HTML element whose `class`, `id`, or `role` attribute contains any of these patterns is also
removed:

```
cookie, breadcrumb, sidebar, social, share, print, skip,
banner, popup, modal, overlay, advertisement, advert
```

For example, a `<div class="cookie-banner">` or `<div id="sidebar-nav">` is destroyed.
This removes cookie consent banners, social share buttons, print links, modals, and ads
regardless of what tag they use.

**Step D: Find the main content node — `_find_content_node(soup, content_selectors)`**

Tries selectors in order until one matches:

1. Any selectors from the source's `crawl_config.content_selectors` (defined in `config/sources.yml` per agency)
2. `main`
3. `article`
4. `div[role='main']`
5. Falls back to `<body>`, then the full soup

The first matching node becomes the "content area" — all further extraction works only within
this node, ignoring everything outside it.

**Step E: Extract text and headings — `_extract_text_and_headings(content_node)`**

Headings are collected first:
```python
for element in node.descendants:
    if element.name in {"h1", "h2", "h3", "h4", "h5", "h6"}:
        headings.append({"level": int(element.name[1]), "text": element.get_text(strip=True)})
```

Then the full text is extracted with newlines as separators:
```python
raw_text = node.get_text(separator="\n", strip=True)
```

Then `_normalise_whitespace(text)` is applied (note: this is the extractor's internal
normalisation, different from the pipeline's `_normalize_text`):
```python
re.sub(r"[ \t]+", " ", text)    # collapse spaces/tabs but PRESERVE newlines
re.sub(r"\n{3,}", "\n\n", text) # collapse 3+ newlines to max 2
text.strip()
```

This keeps paragraph structure (newlines preserved) while removing horizontal whitespace
clutter. The result is a multi-line string with logical paragraph breaks.

**Step F: Extract tables — `TableExtractor.extract_from_html(content_node)`**

Finds all `<table>` elements within the content node and converts them to `ExtractedTable`
objects (headers + rows as lists of strings). These become separate "table" chunks later.

**Step G: Return `ExtractedDocument`**

```python
ExtractedDocument(
    title=...,
    text=...,          # multi-line cleaned text
    headings=...,      # [{level, text}, ...]
    tables=...,        # [ExtractedTable, ...]
    source_url=...,
    source_name=...,
    content_type="html",
    word_count=...,
    extraction_warnings=...,  # populated if empty or < 50 words
)
```

#### For PDF: `PDFExtractor.extract(pdf_bytes, source_url, source_name)`

**Step A: Try pdfplumber**

```python
with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
    for page in pdf.pages:
        page_text = page.extract_text()
        pages.append(page_text.strip())
return "\n\n".join(pages)
```

Extracts text page by page, joins with double newlines between pages.
Title is taken from `pdf.metadata["Title"]`.

**Step B: Fallback to PyMuPDF (fitz)**

If pdfplumber raises any exception or returns empty text:

```python
doc = fitz.open(stream=pdf_bytes, filetype="pdf")
for page in doc:
    page_text = page.get_text("text")
```

PyMuPDF handles a wider range of PDF versions and encoding issues.

**Step C: Normalise whitespace**

Same `_normalise_whitespace` as HTML: collapse horizontal whitespace, cap newlines at 2.

**Step D: Scanned PDF detection**

```python
if word_count < 20:
    warnings.append("Scanned PDF detected ... — flagged for OCR queue")
    doc.needs_ocr = True
```

If fewer than 20 words were extracted, the PDF is almost certainly a scanned image
(no selectable text). The `needs_ocr` flag is set on the `raw_documents` row so the OCR
queue can pick it up later.

---

### Step 2.5 — Metadata Extraction (`MetadataExtractor.extract`)

Takes the `ExtractedDocument` and produces `ExtractedMetadata`.

**Effective date — `_extract_effective_date(text)`**

Tries 6 regex patterns in order:

| Pattern | Example match |
|---|---|
| `with effect from DD Month YYYY` | "with effect from 1 January 2024" |
| `effective from DD Month YYYY` | "effective from 15 March 2023" |
| `as at/of/from DD Month YYYY` | "as at 1 April 2024" |
| `last updated: DD Month YYYY` | "last updated: 12 Feb 2024" |
| `DD MonthName YYYY` | "5 October 2023" |
| `YYYY-MM-DD` | "2024-01-01" |

Returns ISO format `"YYYY-MM-DD"`, or `""` if none found.

**Section — `_extract_section(headings, title)`**

Returns the text of the first `h1` or `h2` heading. Falls back to the document title.
This becomes the "section" label for all chunks from this document.

**Tags — `_extract_tags(text, heading_texts, tag_config)`**

Uses the `tag_config` from `sources.crawl_config` (set per source in `config/sources.yml`).

The config looks like:
```yaml
tag_config:
  property_type:
    HDB: ["hdb", "public housing"]
    private: ["condo", "condominium", "private residential"]
  topic:
    stamp_duty: ["stamp duty", "absd", "bsd"]
    eligibility: ["eligible", "eligibility", "qualify"]
```

For each category, it scans the full document text (lowercased) for any keyword match.
If `"stamp duty"` appears anywhere in the text, `tags["topic"] = ["stamp_duty"]`.

Returns `{"property_type": ["HDB"], "topic": ["stamp_duty", "eligibility"]}` etc.

---

### Step 2.6 — Chunking (`DocumentChunker.chunk`)

Splits the document into embeddable pieces.

**Text chunks**

```python
pieces = self._splitter.split_text(doc.text)
```

Uses `RecursiveCharacterTextSplitter` from LangChain, configured with:
- Encoding: `cl100k_base` (tiktoken — same encoder OpenAI uses)
- Chunk size: **512 tokens**
- Overlap: **64 tokens** (consecutive chunks share 64 tokens at their boundary)

The splitter tries to split at `\n\n`, then `\n`, then `. `, then ` `, then character-by-character —
trying to keep logical units (paragraphs, sentences) together.

For each piece, `_heading_path_at(offset, full_text, headings)` is called to determine the
active heading breadcrumb at the chunk's position. For example, if the chunk is under
"Eligibility Criteria → Income Ceiling", the heading path is:
```python
[{"level": 2, "text": "Eligibility Criteria"}, {"level": 3, "text": "Income Ceiling"}]
```

This is stored as `heading_path` on the chunk and serialised as `"Eligibility Criteria > Income Ceiling"` in the DB.

**Table chunks**

Each `ExtractedTable` is converted to Markdown:
```
| Header 1 | Header 2 |
|---|---|
| Row 1 Val 1 | Row 1 Val 2 |
```

Tables become separate chunks with `chunk_type = "table"`. Token count is computed the same way.

---

### Step 2.7 — Validation (`ChunkValidator.validate`)

Quality gate. Each chunk is checked and either kept or dropped (filtered).

**Hard failures (chunk is dropped):**

| Check | Rule |
|---|---|
| Empty text | `chunk_text` is empty or whitespace-only |
| Null bytes | `\x00` in text — binary corruption |
| Invalid type | `chunk_type` not in `{"text", "table"}` |
| Too few tokens | `token_count < 50` |
| Too many tokens | `token_count > 600` |
| Boilerplate | Matches patterns like `"skip to content"`, `"© 2024"`, `"share this page"`, pure separators (`---`, `•••`) |
| Duplicate text | Same sha256 hash seen in an earlier chunk of the same document |

**Soft warnings (chunk kept, issue logged):**

| Check | Rule |
|---|---|
| Word count mismatch | Stored `word_count` ≠ actual |
| Empty source_url | |
| Empty source_name | |
| Missing metadata keys | Required: `source_agency`, `chunk_type`, `chunk_index` |
| Starts lowercase | Possible mid-sentence split |
| Doesn't end with `.!?` | Possible mid-sentence split |

After filtering, surviving chunks are re-indexed from 0 sequentially.

---

### Step 2.8 — Write to Database

**Delete stale chunks:**
```python
db.query(ProcessedChunk).filter_by(document_id=doc.id).delete()
```

Removes any existing `processed_chunks` for this document (handles re-processing on content change).

**Insert valid chunks:**
```python
db.add(ProcessedChunk(
    document_id=doc.id,
    chunk_text=chunk.chunk_text,
    chunk_index=chunk.chunk_index,
    heading_path="Section > Subsection",   # " > ".join of heading_path texts
    token_count=chunk.token_count,
    metadata_json=chunk.metadata,          # full metadata dict as JSONB
))
```

**Update the raw_documents row:**
```python
doc.raw_text        = extracted_doc.text
doc.metadata_json   = metadata.to_dict()
doc.status          = "processed"
doc.error_message   = None
doc.needs_ocr       = is_scanned
doc.extraction_flags = {
    "warnings":      extracted_doc.extraction_warnings,
    "word_count":    extracted_doc.word_count,
    "is_empty":      not extracted_doc.text.strip(),
    "needs_ocr":     is_scanned,
    "content_type":  extracted_doc.content_type,
}
```

`status` is set to `"processed"` — the document won't be picked up by the runner again
unless the crawler updates it (hash change resets it to `"pending"`).

---

## Content Hash: End-to-End

This table shows exactly what the hash is computed from at each point in time:

| When | What is hashed | Function |
|---|---|---|
| S3Pipeline (crawl time) | `_normalize_text(HTMLExtractor.extract(raw_html).text)` | `sha256(normalized.encode()).hexdigest()` |
| S3Pipeline (PDF) | `_normalize_text(PDFExtractor.extract(raw_pdf).text)` | same |
| S3Pipeline (extraction failure) | empty bytes `b""` | `sha256(b"").hexdigest()` |
| PostgresPipeline dedup | looks up `content_hash` in DB | no re-computation |
| processor runner | not re-computed | uses what was stored |

`_normalize_text` (pipeline-level): `re.sub(r"\s+", " ", text).strip()` — single-line, all whitespace collapsed.

`_normalise_whitespace` (extractor-level): collapses horizontal whitespace, preserves up to 2 consecutive newlines — multi-line, paragraph structure retained.

These are two different normalisation levels:
- The extractor produces readable multi-line text (for chunking by paragraph structure).
- The pipeline then further collapses it to a single line **only for the hash** — not stored as-is.
  The `raw_text` stored in `raw_documents` is the pipeline's normalised version (single-line).
  The `raw_text` re-set by the processor runner is the extractor's version (multi-line with paragraphs).

---

## Error Handling Summary

| Where | If it fails | Result |
|---|---|---|
| S3Pipeline upload | Exception raised | `DropItem` — item discarded entirely |
| S3Pipeline text extraction | Exception caught | Hash = sha256(b""), raw_text = "", item continues |
| PostgresPipeline source lookup | Source not in DB | `DropItem` |
| PostgresPipeline DB write | Exception caught | `DropItem` |
| processor runner per-document | Exception caught | `doc.status = "failed"`, `doc.error_message = traceback`, runner continues to next doc |
| processor runner outer | DB/session error | `db.rollback()`, runner exits |
