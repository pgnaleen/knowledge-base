# QA Metrics Reference — SG Property Advisory AI Agent

## Purpose

This document defines every quality metric used across the 4 pipeline layers of this system. For each metric you will find:

- What it is (plain English)
- Why we use it (the specific risk it guards against)
- The formula
- The agreed target threshold
- How to compute it using this system's data

Use this document before writing any test code so all team members measure the same things the same way.

---

## Glossary

| Term | Meaning |
|---|---|
| **TP** (True Positive) | Correctly identified / extracted item |
| **FP** (False Positive) | Incorrectly flagged item (reported as good/changed when it isn't) |
| **FN** (False Negative) | Missed item (should have been caught but wasn't) |
| **TN** (True Negative) | Correctly ignored item |
| **K** | The number of results returned (e.g. top-5 retrieved chunks) |
| **Ground truth** | A manually verified dataset used as the reference for comparison |
| **P95** | 95th percentile — 95% of requests are faster than this value |

---

## Layer 1 — Crawlers (Scrapy + Playwright)

Crawlers fetch raw HTML and PDFs from 5 Singapore government sources (HDB, URA, IRAS, MAS, CPF) and store them in MinIO and PostgreSQL `raw_documents`.

---

### Recall

**What it is:** Of all the pages/documents that *should* have been crawled for a source, what fraction were actually fetched.

**Why we use it:** If a page exists on the government website but was never crawled, that knowledge is completely absent from the system. Users asking about it will get wrong answers.

**Formula:**
```
Recall = TP / (TP + FN)

TP = pages crawled that are in the expected URL list
FN = pages in the expected URL list that were NOT crawled
```

**Target:** > 95%

**How to compute it:** Maintain an expected URL list per source (in your Excel sheet). After a crawl run, query `SELECT url FROM raw_documents WHERE source = 'hdb'` and compare against the expected list.

---

### Change Detection Rate

**What it is:** Of all the pages that actually changed content since the last crawl, what fraction were detected and re-processed.

**Why we use it:** Government policy pages change (new HDB schemes, updated IRAS rates). If a change is missed, the knowledge base becomes stale and users get outdated advice.

**Formula:**
```
Change Detection Rate = TP / (TP + FN)

TP = pages that changed AND were flagged as changed
FN = pages that changed but were NOT flagged (missed changes)
```

**Target:** > 98%

**How to compute it:** For test pages, deliberately modify the HTML content, re-run the crawler, and verify the hash changed and a new `raw_document` record was created with `status = 'pending'`.

---

### False Positive Rate

**What it is:** Of all pages flagged as "changed", what fraction had not actually changed.

**Why we use it:** False positives waste re-processing time (the page goes through the full pipeline again for no reason). At scale this increases cost and queue backlog.

**Formula:**
```
False Positive Rate = FP / (FP + TN)

FP = pages flagged as changed but content was identical
TN = pages correctly identified as unchanged
```

**Target:** < 2%

**How to compute it:** Re-crawl a set of unchanged pages and count how many trigger a new `raw_document` record vs. returning a "no change" result.

---

### False Negative Rate

**What it is:** Of all pages that actually changed, what fraction were missed (not detected).

**Why we use it:** This is the most dangerous failure mode — a real policy change that is never picked up means users receive incorrect guidance. False negatives directly cause incorrect AI responses.

**Formula:**
```
False Negative Rate = FN / (FN + TP)
```

**Target:** < 1%

**How to compute it:** Same test setup as Change Detection Rate — FNR = 1 - Change Detection Rate.

---

### Error Rate (Crawlers)

**What it is:** Percentage of crawl requests that fail (timeout, 4xx, 5xx, connection error).

**Why we use it:** Persistent errors on a source mean that source's knowledge base stops updating. Also distinguishes site-down events from crawler bugs.

**Formula:**
```
Error Rate = Failed Requests / Total Requests × 100
```

**Target:** < 1%

**How to compute it:** Query `SELECT COUNT(*) FROM task_executions WHERE status = 'failed'` vs. total task executions for a crawl job. Or parse structured logs for error-level events.

---

### Latency (Crawlers)

**What it is:** Wall-clock time from sending the HTTP request to storing the raw document.

**Why we use it:** Playwright pages (HDB, CPF) are significantly slower than static pages. Unusually high latency often indicates a broken Playwright session, a rate-limit, or a page structural change.

**Formula:**
```
Latency = end_time - start_time  (per page)
```

**Target:** < 5 seconds per page (P95)

**How to compute it:** Add timing to the Scrapy pipeline or read from `task_executions.result_summary` which logs pages found and duration.

---

## Layer 2 — Processors (HTML + PDF + Chunker + Validator)

Processors transform raw content into validated, chunked text stored in PostgreSQL `processed_chunks`.

---

### HTML Parsing Success Rate

**What it is:** Percentage of HTML documents that BeautifulSoup parsed without raising an exception.

**Why we use it:** A parsing failure means zero content extracted from that page — it silently disappears from the knowledge base with no user-visible error.

**Formula:**
```
Parsing Success Rate = Successful Parses / Total HTML Documents × 100
```

**Target:** > 99%

**How to compute it:** Run the HTML extractor over `testing/datasets/html/` samples. Count documents where extraction completes without exception vs. total documents.

---

### Metadata Completeness

**What it is:** Percentage of processed chunks that contain all required metadata fields (title, section, effective_date, source, domain tags).

**Why we use it:** Metadata drives filtering in the retrieval API (e.g. `property_type`, `citizenship_type`). Missing metadata means a chunk may never be retrieved for the query it was written for.

**Formula:**
```
Metadata Completeness = Chunks with all required fields / Total Chunks × 100
```

**Target:** > 95% for processors; 100% for chunker (chunker must carry all fields forward)

**How to compute it:** Query `processed_chunks` and check JSONB fields: `SELECT COUNT(*) WHERE metadata->>'title' IS NULL OR metadata->>'section' IS NULL ...`

---

### Data Type Correctness

**What it is:** Percentage of extracted values where the data type is correct (prices are numeric, dates are valid ISO 8601, URLs are valid, etc.).

**Why we use it:** Type errors cause silent failures downstream — a price stored as `"$450,000"` (string with comma) will fail numeric comparisons in the financial agent.

**Formula:**
```
Data Type Correctness = Correctly Typed Values / Total Extracted Values × 100
```

**Target:** > 99%

**How to compute it:** Use the existing `Validator` component in the processor pipeline. Check `processed_chunks.metadata` for type violations using a schema check script against `testing/datasets/expected/`.

---

### Precision (HTML Content Extraction)

**What it is:** Of all text blocks extracted from a page, what percentage are actual content (policy text, tables, headings) vs. noise (navigation menus, footers, cookie banners, ads).

**Why we use it:** Noise in chunks degrades retrieval relevance — the LLM may retrieve a footer string instead of the actual policy text for a query.

**Formula:**
```
Precision = TP / (TP + FP)

TP = extracted blocks that are genuine content (verified against ground truth)
FP = extracted blocks that are noise/irrelevant
```

**Target:** > 90%

**How to compute it:** Compare extracted content blocks from `testing/datasets/html/` against manually verified expected output in `testing/datasets/expected/`.

---

### Character Error Rate (CER) — PDF Extraction

**What it is:** Percentage of individual characters in the extracted text that are wrong compared to the ground truth.

**Why we use it:** pdfplumber can garble text on complex PDFs (overlapping elements, unusual fonts). CER catches character-level corruption that WER might miss (e.g. `$4S0,000` instead of `$450,000`).

**Formula:**
```
CER = (Substitutions + Insertions + Deletions) / Total Characters in Ground Truth × 100
```

**Target:** < 2%

**How to compute it:** Run the PDF extractor on `testing/datasets/pdfs/` files. Compare extracted text to manually transcribed ground truth using a CER library (e.g. `jiwer`).

---

### Word Error Rate (WER) — PDF Extraction

**What it is:** Percentage of words in the extracted text that are wrong compared to ground truth. More human-readable than CER.

**Why we use it:** A single character error can corrupt an entire key term (e.g. `"eligib1e"` → not matched in search). WER gives a more realistic view of how usable the extracted text is.

**Formula:**
```
WER = (Substitutions + Insertions + Deletions) / Total Words in Ground Truth × 100
```

**Target:** < 5%

**How to compute it:** Same setup as CER — use `jiwer.wer(ground_truth, extracted_text)` on the PDF test dataset.

---

### Table Extraction Accuracy — PDF

**What it is:** Percentage of table cells (rows × columns) correctly extracted from PDFs that contain structured tables (HDB flat price tables, IRAS tax brackets, etc.).

**Why we use it:** Tables in government PDFs contain the most precise data (exact dollar thresholds, percentage rates). Cell-level errors directly produce wrong financial calculations.

**Formula:**
```
Table Extraction Accuracy = Correct Cells / Total Expected Cells × 100
```

**Target:** > 90%

**How to compute it:** Run the Table Extractor on PDFs in `testing/datasets/pdfs/` that contain known tables. Compare extracted rows/columns against ground truth tables in `testing/datasets/expected/`.

---

### Exact Match Rate (Chunker)

**What it is:** Percentage of chunks produced by the chunker that exactly match the expected chunks from a reference document split.

**Why we use it:** Chunk boundaries matter for retrieval — if a chunk splits mid-sentence or merges two distinct policy sections, retrieval quality degrades even if the text is correct.

**Formula:**
```
Exact Match Rate = Exactly Matching Chunks / Total Expected Chunks × 100
```

**Target:** > 95%

**How to compute it:** Run the chunker on fixed test documents in `testing/datasets/`. Compare produced chunks against pre-verified expected chunks stored in `testing/datasets/expected/`.

---

### Deduplication Rate (Processor)

**What it is:** Percentage of duplicate chunks that are correctly identified and suppressed (not inserted into `processed_chunks` twice).

**Why we use it:** Duplicate chunks inflate retrieval scores — the same text may appear multiple times in top-K results, crowding out other relevant chunks and giving users a false impression of consensus.

**Formula:**
```
False Duplicate Rate = Duplicate Chunks Incorrectly Stored / Total Chunks × 100
(Target: this stays below 2%)
```

**Target:** < 2% false duplicates stored

**How to compute it:** Submit the same document twice through the processor pipeline. Query `processed_chunks` and count records with duplicate `(source, url, chunk_index)`.

---

## Layer 3 — Embedders (OpenRouter / OpenAI → Pinecone + pgvector)

Embedders convert chunks to 3072-dimensional vectors and upsert to the vector stores.

---

### Error Rate (Embedders)

**What it is:** Percentage of embedding API calls or Pinecone upsert calls that fail.

**Why we use it:** A failed embedding means that chunk is never searchable. Unlike crawler errors, embedding errors are silent — the chunk exists in `processed_chunks` but is invisible to the retrieval API.

**Formula:**
```
Error Rate = Failed Calls / Total Calls × 100
```

**Target:** < 1%

**How to compute it:** Check structured logs for `embedding_error` or `upsert_error` events. Can also query `processed_chunks WHERE embedding_status = 'failed'` if that field is tracked.

---

### Latency (Embedders)

**What it is:** End-to-end time from receiving a chunk to confirming it is indexed in Pinecone.

**Why we use it:** Slow embedding creates a growing backlog. If the embedder can't keep up with the crawler, the knowledge base falls behind real-time. Also helps detect API rate-limit throttling.

**Formula:**
```
Latency = upsert_confirmed_time - chunk_received_time  (per chunk)
```

**Target:** < 2 seconds per chunk (P95)

**How to compute it:** Add timing instrumentation in the embedder worker. Log per-chunk duration. Check batch timing from `task_executions.result_summary`.

---

### Drift Detection (Embedders)

**What it is:** Measure of how much the embedding distribution changes when the model switches (e.g. OpenRouter primary → OpenAI fallback). Computed as cosine similarity between embeddings of the same text from both models.

**Why we use it:** If the fallback model produces significantly different embeddings, old indexed vectors become incompatible with new query vectors. Search quality silently degrades.

**Formula:**
```
Drift = 1 - avg(cosine_similarity(embed_model_A(text), embed_model_B(text)))
         over a sample of N representative chunks

Variance threshold: < 5%
```

**Target:** < 5% variance

**How to compute it:** Run the same 100 reference chunks through both embedding models. Compute cosine similarity for each pair. Flag if average similarity drops below 0.95.

> **Note:** Only run this check when changing embedding models. It is not part of the routine test suite.

---

## Layer 4 — AI Agent (LangGraph + `/retrieve` API)

The retrieval `/retrieve` endpoint and multi-agent LangGraph orchestrator (Eligibility, Financial, Knowledge Advisory, Orchestrator agents).

---

### Relevance Score

**What it is:** A score (0–1) indicating whether a retrieved chunk is actually relevant to the query that retrieved it. Scored by an LLM judge or human annotator.

**Why we use it:** Vector similarity finds semantically close text, but "close" does not always mean "useful". A chunk about HDB lease renewal might score highly for a CPF query but be irrelevant to the user's actual question.

**Formula:**
```
Relevance Score = Relevant Retrieved Chunks / Total Retrieved Chunks × 100
```

**Target:** > 95%

**How to compute it:** For each query in `testing/datasets/queries/`, retrieve top-K chunks from `/retrieve`. Compare against expected relevant chunks in `testing/datasets/expected/`. Score relevance per chunk (binary: relevant / not relevant).

---

### Precision@K

**What it is:** Of the top-K chunks returned for a query, what fraction are relevant.

**Why we use it:** The LLM agent only sees the top-K chunks. If most of them are irrelevant, the agent generates answers from wrong context — this is the direct cause of hallucination in RAG systems.

**Formula:**
```
Precision@K = Relevant chunks in top-K / K
```

**Target:** > 90% at K=5

**How to compute it:** Run each test query against `/retrieve?top_k=5`. For each result set, count relevant chunks using ground truth from `testing/datasets/expected/`.

---

### Recall@K

**What it is:** Of all the chunks that are relevant to a query, what fraction appear in the top-K results.

**Why we use it:** High Precision@K with low Recall@K means the agent is confident but incomplete — it answers accurately about what it sees but misses important policy details. This causes partially correct answers (dangerous in financial/eligibility contexts).

**Formula:**
```
Recall@K = Relevant chunks retrieved in top-K / Total relevant chunks for query
```

**Target:** > 80% at K=5

**How to compute it:** Same test setup as Precision@K — you need the full set of relevant chunks per query in your ground truth.

---

### F1-Score (Retrieval)

**What it is:** The harmonic mean of Precision@K and Recall@K. Gives a single balanced score.

**Why we use it:** Optimizing for only Precision or only Recall produces a skewed system. F1 forces a balance — you can't game it by returning everything (high recall, low precision) or only the safest result (high precision, low recall).

**Formula:**
```
F1 = 2 × (Precision × Recall) / (Precision + Recall)
```

**Target:** > 85%

**How to compute it:** Derived from Precision@K and Recall@K calculations above.

---

### Latency (Agent)

**What it is:** End-to-end wall-clock time from a user sending a `/chat` message to receiving the first SSE token.

**Why we use it:** Users abandon slow systems. For property advisory queries (complex, multi-turn), latency directly affects whether the product is usable. Also detects retrieval bottlenecks vs. LLM generation bottlenecks.

**Formula:**
```
Latency = first_token_time - request_received_time  (per request)
```

**Target:** < 5 seconds P95

**How to compute it:** Run test queries from `testing/datasets/queries/` against the live agent. Measure time-to-first-token. Log percentiles.

---

### Error Rate (Agent)

**What it is:** Percentage of chat requests that result in an agent failure (exception, empty response, tool call error, routing failure).

**Why we use it:** An agent error produces either a blank response or a generic error message — both are unacceptable for a user seeking property advice. Unlike silent pipeline errors, these are directly user-visible.

**Formula:**
```
Error Rate = Failed Requests / Total Requests × 100
```

**Target:** < 1%

**How to compute it:** Monitor `/chat` endpoint responses for HTTP 5xx, empty `content` fields, or `error` keys in the SSE stream. Parse structured agent logs for `agent_error` events.

---

## Metrics Deferred (Not in Routine Tests)

| Metric | Why Deferred |
|---|---|
| **Hash Collision Rate** | Near-zero for SHA-256 on page-sized content. Only investigate if you see phantom "no change" results. |
| **OCR Flag Rate** | Informational only — tells you how many PDFs are scanned. No action threshold needed until you add an OCR engine. |
| **Drift Detection** | Only run when you change embedding models. Not a routine check. |

---

## How to Use This Document

1. **Ground truth first** — Before writing test code for any layer, prepare an Excel sheet with: Test Case ID | Input | Expected Output | Layer | Metric
2. **One layer at a time** — Start with Layer 1 (Crawlers), get it green, then move to Layer 2, etc.
3. **Automate the formula** — Each metric above has a "How to compute it" section. Implement that as a Python function in the relevant test file under `testing/kb-pipeline/` or `testing/agent/`
4. **Red before green** — Write a failing test first (confirm the metric calculation works), then verify it passes against known-good data
5. **Track in Excel** — Use the `generate_test_cases.py` tool to produce the tracking workbook with P0/P1 priorities and Pass/Fail/Partial status columns
