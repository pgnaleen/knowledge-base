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

## How to Run QA — Step by Step

This section explains the full QA process from start to finish. Any team member can follow this guide independently.

---

### The Core Pattern (applies to every layer)

Every test in this project follows the same 4-step pattern:

```
Step 1          Step 2               Step 3                  Step 4
Input files  →  Run real code    →   Compare to expected  →  Report with metrics
(datasets/)     (actual system)      (datasets/expected/)    (results/)
```

The only thing that changes between layers is what the input is and what "expected" means. The pattern is always the same.

---

### Folder Structure — What Goes Where

```
testing/
├── datasets/
│   ├── html/          ← saved HTML pages from HDB, URA, IRAS, MAS, CPF
│   ├── pdfs/          ← downloaded PDFs from same sources
│   ├── queries/       ← queries.json (real user questions)
│   └── expected/      ← one JSON per HTML/PDF + expected_answers.json
├── kb-pipeline/       ← Python test files, one subfolder per layer
│   ├── html-extraction/
│   ├── pdf-extraction/
│   ├── metadata-extraction/
│   ├── table-extraction/
│   ├── chunking/
│   ├── embedding/
│   ├── api-retrieval/
│   └── pipeline-resilience/
├── agent/             ← Python test files for agent layers
│   ├── e2e/
│   ├── graph-agents/
│   ├── mcp-tools/
│   └── performance/
├── results/           ← auto-generated metric reports (created when tests run)
├── QA_METRICS.md      ← this file
└── Testing.xlsx       ← human-readable test tracker (P0/P1 priorities, Pass/Fail status)
```

---

### Step 1 — Collect Test Data (HTML pages and PDFs)

Before any test can run, you need real sample files from the 5 government sources. Save these into `testing/datasets/html/` and `testing/datasets/pdfs/`.

**How to save an HTML page:**
Open the page in Chrome → Right-click anywhere → **Save As** → choose **"Webpage, HTML Only"** (NOT "Complete"). Name the file as shown below.

**How to save a PDF:**
Click the PDF link on the site → it opens in the browser → click the download icon in the top-right corner → save with the filename shown below.

---

#### HDB — `datasets/html/` and `datasets/pdfs/`

| What to save | URL | Filename |
|---|---|---|
| Eligibility page (has income ceiling tables) | `hdb.gov.sg/buying-a-flat/understanding-your-eligibility-and-housing-loan-options/flat-and-grant-eligibility` | `hdb_eligibility.html` |
| BTO application process | `hdb.gov.sg/buying-a-flat/buying-procedure-for-new-flats/application` | `hdb_bto_application.html` |
| Rental eligibility | `hdb.gov.sg/residential/renting-a-flat/renting-from-hdb/public-rental-scheme/eligibility` | `hdb_rental_eligibility.html` |
| Any PDF from eligibility page with income tables | Link found on eligibility page above | `hdb_income_ceiling_guide.pdf` |

> HDB uses JavaScript rendering. Wait 3–5 seconds after the page fully loads before saving.

---

#### IRAS — `datasets/html/` and `datasets/pdfs/`

| What to save | URL | Filename |
|---|---|---|
| ABSD rates page (best table test) | `iras.gov.sg/taxes/stamp-duty/for-property/buying-or-acquiring-property/additional-buyer-s-stamp-duty-(absd)` | `iras_absd.html` |
| Property tax rates page | `iras.gov.sg/taxes/property-tax/other-services/property-tax-rates` | `iras_property_tax_rates.html` |
| e-Tax Guide PDF (look for "e-Tax Guide" link on ABSD page) | Link found on ABSD page above | `iras_absd_guide.pdf` |

---

#### URA — `datasets/html/`

| What to save | URL | Filename |
|---|---|---|
| Buying private residential property | `ura.gov.sg/Corporate/Property/Residential/buying-private-residential-property` | `ura_private_residential.html` |
| Development guidelines | `ura.gov.sg/Corporate/Guidelines/Development-Control/Residential/Flats-Condominiums` | `ura_guidelines.html` |

---

#### MAS — `datasets/html/`

| What to save | URL | Filename |
|---|---|---|
| TDSR rules page | Find under `mas.gov.sg/regulations-and-financial-stability` — search "Total Debt Servicing" | `mas_tdsr.html` |
| LTV limits page | Find under same section — search "Loan-to-Value" | `mas_ltv.html` |

> MAS uses JavaScript rendering. Wait 3–5 seconds after the page fully loads before saving.

---

#### CPF — `datasets/html/`

| What to save | URL | Filename |
|---|---|---|
| Using CPF to buy a home | `cpf.gov.sg/member/home-ownership/using-your-cpf-to-buy-a-home` | `cpf_home_ownership.html` |
| CPF housing scheme | `cpf.gov.sg/member/home-ownership/housing-scheme` | `cpf_housing_scheme.html` |

> CPF is a React app. Wait for the spinner to disappear and the full page content to appear before saving.

---

### Step 2 — Create Expected Results

For each HTML/PDF file you saved, you need a matching JSON file in `testing/datasets/expected/` that describes what the correct output should be. The test compares the extractor's output against this file.

#### Option A — Using AI (recommended)

1. Open the saved HTML file in VS Code (or any text editor)
2. Select all (Ctrl+A) and copy
3. Paste it to Claude with this prompt:

> *"Here is the raw HTML of the [source] [page name] page. Generate the expected JSON test file. Include: metadata fields (title, section, source, domain_tags), content_must_contain (5–10 key policy phrases), content_must_not_contain (nav/footer/cookie text you can see in the HTML), and tables (extract all table rows and columns exactly as they appear)."*

4. Claude generates the JSON — save it as `testing/datasets/expected/<filename>.json`

Example: `iras_absd.html` → paste to Claude → save output as `expected/iras_absd.json`

#### Option B — Via Excel (for non-technical team members)

1. Open `Testing.xlsx`
2. Find the relevant test row for that page
3. Fill in the **Expected Result** column in plain English
4. A developer runs `generate_expected_json.py` once to convert Excel → JSON automatically

**Non-technical members never need to touch a JSON file.** Excel is the source of truth; JSON is auto-generated from it.

#### What the expected JSON looks like

```json
{
  "source": "iras",
  "url": "https://www.iras.gov.sg/taxes/stamp-duty/.../absd",
  "metadata": {
    "title": "Additional Buyer's Stamp Duty (ABSD)",
    "section": "Stamp Duty",
    "source": "iras",
    "domain_tags": ["stamp_duty", "residential", "absd"]
  },
  "content_must_contain": [
    "Additional Buyer's Stamp Duty",
    "Singapore Citizen",
    "Permanent Resident",
    "20%"
  ],
  "content_must_not_contain": [
    "Privacy Policy",
    "Cookie Settings",
    "© Copyright"
  ],
  "tables": [
    {
      "description": "ABSD rates by buyer profile",
      "headers": ["Profile", "1st Property", "2nd Property", "3rd & subsequent"],
      "rows": [
        ["Singapore Citizen", "0%", "20%", "30%"],
        ["Singapore PR", "5%", "30%", "35%"],
        ["Foreigner", "60%", "60%", "60%"]
      ]
    }
  ]
}
```

| Field | What the test checks |
|---|---|
| `metadata` | All required fields are present and correct |
| `content_must_contain` | These key phrases appear in extracted text |
| `content_must_not_contain` | Nav/footer noise did NOT leak into content |
| `tables` | Table rows and columns match exactly |

#### Expected files summary

```
datasets/expected/
├── hdb_eligibility.json
├── hdb_bto_application.json
├── iras_absd.json
├── iras_property_tax_rates.json
├── ura_private_residential.json
├── mas_tdsr.json
├── cpf_home_ownership.json
└── expected_answers.json     ← for retrieval/agent tests (see Step 2b)
```

#### Step 2b — Create queries and expected answers

Create `testing/datasets/queries/queries.json` with real user questions:

```json
[
  {"id": "Q01", "query": "Am I eligible to buy a BTO flat as a Singapore PR?", "source": "hdb", "topic": "eligibility"},
  {"id": "Q02", "query": "What is the ABSD rate for a second property purchase by a Singapore citizen?", "source": "iras", "topic": "stamp_duty"},
  {"id": "Q03", "query": "How much CPF can I use to pay for my HDB flat?", "source": "cpf", "topic": "withdrawal"},
  {"id": "Q04", "query": "What is the TDSR limit for a housing loan in Singapore?", "source": "mas", "topic": "loan_limits"},
  {"id": "Q05", "query": "Can foreigners buy private property in Singapore?", "source": "ura", "topic": "private_property"},
  {"id": "Q06", "query": "What is the income ceiling for a 4-room BTO flat?", "source": "hdb", "topic": "eligibility"},
  {"id": "Q07", "query": "What are the property tax rates for owner-occupied residential properties?", "source": "iras", "topic": "property_tax"},
  {"id": "Q08", "query": "What is the minimum occupation period for an HDB flat before I can sell?", "source": "hdb", "topic": "resale_rules"},
  {"id": "Q09", "query": "What is the LTV limit for a second housing loan?", "source": "mas", "topic": "ltv"},
  {"id": "Q10", "query": "How does the CPF accrued interest work when I sell my flat?", "source": "cpf", "topic": "accrued_interest"}
]
```

For `expected_answers.json` — paste each query + its source HTML page to Claude and ask for the correct answer keywords. Save the result as `testing/datasets/expected/expected_answers.json`.

---

### Step 3 — Run Tests Layer by Layer

Run tests in this order. Each layer depends on the one before it working correctly.

| Order | Layer | Test folder | Command |
|---|---|---|---|
| 1 | HTML Extraction | `kb-pipeline/html-extraction/` | `python test_html_extractor.py` |
| 2 | PDF Extraction | `kb-pipeline/pdf-extraction/` | `python test_pdf_extractor.py` |
| 3 | Metadata Extraction | `kb-pipeline/metadata-extraction/` | `python test_metadata_extractor.py` |
| 4 | Table Extraction | `kb-pipeline/table-extraction/` | `python test_table_extractor.py` |
| 5 | Chunking | `kb-pipeline/chunking/` | `python test_chunker.py` |
| 6 | Embedding | `kb-pipeline/embedding/` | `python test_embedder.py` |
| 7 | API Retrieval | `kb-pipeline/api-retrieval/` | `python test_retrieval.py` |
| 8 | Agent E2E | `agent/e2e/` | `python test_agent_e2e.py` |

Each test writes its report to `testing/results/`. For example, after running HTML extraction tests you will see `testing/results/html_extraction_report.json`.

> **Note:** Steps 6–8 require the system to be running (Pinecone configured, API keys set, KB-Pipeline and Agent services up). Steps 1–5 run fully offline against local files only.

---

### Step 4 — Read the Results

Each test produces console output AND a JSON report in `testing/results/`.

**Console output looks like this:**

```
HTML Extraction — IRAS
  ✅ Parsing Success:        1/1    (100%) — target >99%   PASS
  ✅ Metadata Completeness:  19/20  (95%)  — target >95%   PASS
  ✅ Data Type Correctness:  20/20  (100%) — target >99%   PASS
  ❌ Precision:              17/20  (85%)  — target >90%   FAILED

HTML Extraction — CPF
  ✅ Parsing Success:        1/1    (100%) — target >99%   PASS
  ❌ Metadata Completeness:  14/20  (70%)  — target >95%   FAILED
```

**A red line tells you exactly:**
- Which source failed (IRAS, HDB, CPF, etc.)
- Which metric failed (Precision, Metadata Completeness, etc.)
- The actual score vs. the target

**What to do when a test fails:**
1. Note the source name and metric name from the red line
2. Find that metric's "How to compute it" section in this document
3. Check the extractor code for that source in `KB-Pipeline/processors/`
4. Fix the code, re-run the test, confirm it goes green

**Summary report:**
After running all layers, open `testing/results/summary_report.json` — it shows every metric for every layer in one place with pass/fail status. This is what gets reviewed in team standups.

---

### Embedding Layer — Special Case (no expected file needed)

Embedding tests work differently from all other layers. You cannot write down what a 3072-dimensional vector "should" look like — it is meaningless to a human. So embedding tests check **process quality only**:

| What is checked | Why | Target |
|---|---|---|
| Did the API call succeed? | A failed call = chunk invisible in search | < 1% error rate |
| Was it under 2 seconds? | Slow embedding = growing backlog | < 2s per chunk (P95) |
| Was the vector stored in Pinecone? | Upsert failure = chunk never retrievable | 100% upsert success |
| Is the vector 3072 dimensions? | Wrong dimension = wrong model used | Exactly 3072 |
| Same chunk → same vector each time? | Inconsistency = non-deterministic search | Cosine similarity > 0.999 |

No `expected/embedding.json` file is needed. The test passes if the process completes correctly within the latency target.

---

### Ground Truth Maintenance

Government policy pages change. When IRAS updates ABSD rates or HDB changes income ceilings, the expected JSON files must be updated to match.

**When you see test failures after a known policy change:**

1. Re-save the HTML page from the live site (same filename, overwrite the old one)
2. Paste the new HTML to Claude and regenerate the expected JSON
3. Save over the old `expected/<source>_<page>.json`
4. Update the "Expected Result" column in `Testing.xlsx` for the affected rows
5. Re-run the tests — they should go green with the updated ground truth

**When you see unexpected failures (no known policy change):**
The website likely changed its HTML structure (CSS class renamed, new layout). Check the extractor's CSS selectors in `KB-Pipeline/processors/html_extractor.py` and update them to match the new structure.

---

### Quick Reference — What Each Layer Needs

| Layer | Needs files in datasets/? | Needs expected JSON? | Needs system running? |
|---|---|---|---|
| HTML Extraction | Yes — `datasets/html/` | Yes — per HTML file | No — offline |
| PDF Extraction | Yes — `datasets/pdfs/` | Yes — per PDF file | No — offline |
| Metadata Extraction | Yes — same HTML/PDF files | Yes — same JSON (metadata section) | No — offline |
| Table Extraction | Yes — same HTML/PDF files | Yes — same JSON (tables section) | No — offline |
| Chunking | No — chains from HTML/PDF step | Yes — expected_chunks in JSON | No — offline |
| Embedding | No — chains from chunking | No — process checks only | Yes — API keys + Pinecone |
| API Retrieval | Yes — `datasets/queries/queries.json` | Yes — `expected_answers.json` | Yes — KB-Pipeline API running |
| Agent E2E | Yes — same `queries.json` | Yes — same `expected_answers.json` | Yes — full stack running |
