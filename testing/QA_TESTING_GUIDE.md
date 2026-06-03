# QA Testing Guide — SG Property Advisory AI Agent

This guide covers the correct testing approach for every pipeline layer. Each section explains:
- Which tools to install
- The two test categories (content quality vs. behavior/robustness)
- How to write each type of test with the actual class and method from the codebase
- What to assert and what metrics to produce

**Test file location per section:**

| Section | Test file to create |
|---|---|
| PDF Extraction | `testing/kb-pipeline/pdf-extraction/test_pdf_extractor.py` |
| HTML Extraction | `testing/kb-pipeline/html-extraction/test_html_extractor.py` |
| Table Extraction | `testing/kb-pipeline/table-extraction/test_table_extractor.py` |
| Metadata Extraction | `testing/kb-pipeline/metadata-extraction/test_metadata_extractor.py` |
| Chunking | `testing/kb-pipeline/chunking/test_chunker.py` |
| Embedding | `testing/kb-pipeline/embedding/test_embedding_service.py` |
| Crawlers | `testing/kb-pipeline/crawlers/test_crawlers.py` |

---

## The Two Test Categories (applies to every section)

Every section has two fundamentally different types of tests. Do not mix them up.

| Category | What it tests | Input | How to check | Metrics |
|---|---|---|---|---|
| **Content Quality** | Does the extractor read content correctly? | Real files (HTML/PDF) + expected JSON | Compare output field-by-field against JSON | CER, WER, Table Accuracy, Precision, Recall |
| **Behavior / Robustness** | Does the system handle errors and edge cases correctly? | Crafted bytes or tiny fixtures | Assert correct exception raised, or correct warning/fallback activated | Pass/Fail only |

---

## 1. PDF Extraction

**Class:** `PDFExtractor`
**File:** `KB-Pipeline/processors/pdf_extractor.py`
**Method:** `extract(pdf_bytes: bytes, source_url: str, source_name: str) -> ExtractedDocument`
**Raises:** `PDFExtractionError`
**Fallback chain:** pdfplumber → PyMuPDF (fitz)

### Tools

```bash
pip install pytest pytest-mock jiwer editdistance fpdf2
```

| Tool | Why |
|---|---|
| `pytest` | Run tests, assert results |
| `pytest-mock` | Mock pdfplumber to simulate crashes for fallback tests |
| `jiwer` | Calculate WER (Word Error Rate) in one line |
| `editdistance` | Calculate CER (Character Error Rate) |
| `fpdf2` | Generate crafted test PDFs in code (scanned, multi-page, etc.) |

---

### Category 1 — Content Quality Tests

Uses real government PDFs from `testing/datasets/pdfs/` + expected JSON from `testing/datasets/expected/`.

**What to put in the expected JSON for a PDF:**

```json
{
  "source": "iras",
  "metadata": {
    "title": "e-Tax Guide: ABSD"
  },
  "content_must_contain": [
    "Additional Buyer's Stamp Duty",
    "Singapore Citizen",
    "20%"
  ],
  "content_must_not_contain": ["cookie", "subscribe"],
  "tables": [
    {
      "description": "ABSD rates table",
      "headers": ["Profile", "1st Property", "2nd Property"],
      "rows": [
        ["Singapore Citizen", "0%", "20%"],
        ["Singapore PR", "5%", "30%"]
      ]
    }
  ]
}
```

**Test code pattern:**

```python
import json, sys, editdistance
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parents[3]))  # project root
from KB_Pipeline.processors.pdf_extractor import PDFExtractor

extractor = PDFExtractor()

def test_pe01_text_extraction_iras():
    pdf_bytes = open("testing/datasets/pdfs/iras_absd_guide.pdf", "rb").read()
    expected  = json.load(open("testing/datasets/expected/iras_absd_guide.json"))

    result = extractor.extract(pdf_bytes, source_url="", source_name="iras")

    # Content quality checks
    for phrase in expected["content_must_contain"]:
        assert phrase in result.text, f"Missing phrase: {phrase}"
    for phrase in expected["content_must_not_contain"]:
        assert phrase not in result.text, f"Noise leaked: {phrase}"

    # Title check
    assert result.title == expected["metadata"]["title"]

    # WER (requires a reference text file alongside expected JSON)
    # reference_text = open("testing/datasets/expected/iras_absd_guide_reference.txt").read()
    # from jiwer import wer
    # assert wer(reference_text, result.text) < 0.05  # target <5% WER

def test_pe02_table_extraction_iras():
    pdf_bytes = open("testing/datasets/pdfs/iras_absd_guide.pdf", "rb").read()
    expected  = json.load(open("testing/datasets/expected/iras_absd_guide.json"))

    result = extractor.extract(pdf_bytes, source_url="", source_name="iras")

    assert len(result.tables) >= len(expected["tables"])
    for exp_table in expected["tables"]:
        matched = next((t for t in result.tables if t.headers == exp_table["headers"]), None)
        assert matched is not None, f"Table not found: {exp_table['description']}"
        assert matched.rows == exp_table["rows"]
```

**Metrics produced:** CER, WER, Table Extraction Accuracy, Metadata Completeness

---

### Category 2 — Behavior / Robustness Tests

No expected JSON needed. These test that the system handles abnormal inputs correctly.

```python
import pytest
from unittest.mock import patch
from KB_Pipeline.processors.pdf_extractor import PDFExtractor, PDFExtractionError

extractor = PDFExtractor()

# PE07 — Empty bytes: must raise PDFExtractionError immediately
def test_pe07_empty_pdf_raises():
    with pytest.raises(PDFExtractionError):
        extractor.extract(b"", source_url="", source_name="test")

# PE03 — pdfplumber crash: must fall back to PyMuPDF
def test_pe03_fallback_to_pymupdf(mocker):
    # Mock pdfplumber to crash
    mocker.patch(
        "KB_Pipeline.processors.pdf_extractor.pdfplumber.open",
        side_effect=Exception("pdfplumber crashed")
    )
    pdf_bytes = open("testing/datasets/pdfs/iras_absd_guide.pdf", "rb").read()
    result = extractor.extract(pdf_bytes, source_url="", source_name="test")

    # Fallback activated — warning must mention it
    assert any("fallback" in w.lower() for w in result.extraction_warnings)

# PE05 — Scanned PDF: must be detected and flagged
def test_pe05_scanned_pdf_detected():
    # Generate a minimal image-only PDF using fpdf2
    from fpdf import FPDF
    pdf = FPDF()
    pdf.add_page()
    # A page with no text = scanned heuristic triggers
    pdf_bytes = pdf.output()

    result = extractor.extract(pdf_bytes, source_url="", source_name="test")
    assert any("scanned" in w.lower() for w in result.extraction_warnings)

# PE08 — Both parsers fail: must raise PDFExtractionError
def test_pe08_both_parsers_fail(mocker):
    mocker.patch("KB_Pipeline.processors.pdf_extractor.pdfplumber.open",
                 side_effect=Exception("pdfplumber failed"))
    mocker.patch("KB_Pipeline.processors.pdf_extractor.fitz.open",
                 side_effect=Exception("fitz failed"))
    with pytest.raises(PDFExtractionError):
        extractor.extract(b"%PDF-1.4 broken", source_url="", source_name="test")

# PE19 — Password-protected PDF
def test_pe19_password_protected_pdf():
    # Use a real encrypted PDF or create one with pypdf
    # For now: corrupted bytes simulate the encrypted state
    with pytest.raises(PDFExtractionError):
        extractor.extract(b"%PDF-1.4 encrypted content %%EOF", source_url="", source_name="test")
```

**Metrics produced:** Pass/Fail only. Fallback coverage rate.

---

## 2. HTML Extraction

**Class:** `HTMLExtractor`
**File:** `KB-Pipeline/processors/html_extractor.py`
**Method:** `extract(html, source_url, source_name, content_selectors=None) -> ExtractedDocument`
**Raises:** `ExtractionError`
**Fallback chain:** site-specific selector → `main` / `article` → `<body>`

### Tools

```bash
pip install pytest pytest-mock
```

No extra tools needed — BeautifulSoup is already a project dependency.

---

### Category 1 — Content Quality Tests

Uses real HTML files from `testing/datasets/html/` + expected JSON from `testing/datasets/expected/`.

```python
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parents[3]))
from KB_Pipeline.processors.html_extractor import HTMLExtractor

extractor = HTMLExtractor()

def test_he07_iras_absd_content():
    html     = open("testing/datasets/html/iras_absd.html", encoding="utf-8").read()
    expected = json.load(open("testing/datasets/expected/iras_absd.json"))

    result = extractor.extract(html, source_url="", source_name="iras")

    # Title
    assert result.title == expected["metadata"]["title"]

    # Content phrases present
    for phrase in expected["content_must_contain"]:
        assert phrase in result.text, f"Missing: {phrase}"

    # Nav/footer noise NOT present
    for phrase in expected["content_must_not_contain"]:
        assert phrase not in result.text, f"Noise leaked: {phrase}"

    # Metadata completeness: title, source_name, content_type populated
    assert result.source_name == "iras"
    assert result.content_type == "html"
    assert result.word_count > 50

# Run for all 5 sources to catch broken selectors
import pytest
@pytest.mark.parametrize("source,filename", [
    ("hdb",  "hdb_eligibility.html"),
    ("iras", "iras_absd.html"),
    ("ura",  "ura_private_residential.html"),
    ("mas",  "mas_tdsr.html"),
    ("cpf",  "cpf_home_ownership.html"),
])
def test_all_sources_parse_without_error(source, filename):
    html   = open(f"testing/datasets/html/{filename}", encoding="utf-8").read()
    result = extractor.extract(html, source_url="", source_name=source)
    assert result is not None
    assert result.word_count > 0, f"{source} extraction returned empty content"
```

**Metrics produced:** Parsing Success Rate (per source), Metadata Completeness, Precision (noise in text = fail)

---

### Category 2 — Behavior / Robustness Tests

```python
import pytest
from KB_Pipeline.processors.html_extractor import HTMLExtractor, ExtractionError

extractor = HTMLExtractor()

# HE01 — Empty HTML must raise ExtractionError
def test_he01_empty_html_raises():
    with pytest.raises(ExtractionError):
        extractor.extract("", source_url="", source_name="test")

# HE02 — Malformed HTML still extracts (BeautifulSoup is lenient)
def test_he02_malformed_html_does_not_crash():
    malformed = "<html><body><div>Unclosed tag<p>Some content"
    result = extractor.extract(malformed, source_url="", source_name="test")
    assert "Some content" in result.text

# HE03 — Site-specific selector enforced
def test_he03_site_specific_selector():
    html = """<html><body>
        <nav>Menu item</nav>
        <div class="sfContentBlock">Real policy content here</div>
        <footer>Footer text</footer>
    </body></html>"""
    result = extractor.extract(
        html, source_url="", source_name="iras",
        content_selectors=[".sfContentBlock"]
    )
    assert "Real policy content here" in result.text
    assert "Menu item" not in result.text
    assert "Footer text" not in result.text

# HE04 — Fallback to generic selector when site selector not found
def test_he04_fallback_to_generic_selector():
    html = """<html><body>
        <main>Main content here</main>
    </body></html>"""
    # No site-specific selector matches → falls back to <main>
    result = extractor.extract(html, source_url="", source_name="test")
    assert "Main content here" in result.text

# HE10/HE11 — Noise tags stripped
def test_he10_noise_tags_stripped():
    html = """<html><body>
        <main>
            <p>Real content</p>
            <div class="cookie-banner">Accept cookies</div>
            <div class="sidebar">Related links</div>
        </main>
        <script>alert('js')</script>
        <footer>Footer</footer>
    </body></html>"""
    result = extractor.extract(html, source_url="", source_name="test")
    assert "Real content" in result.text
    assert "Accept cookies" not in result.text
    assert "alert" not in result.text
```

**Metrics produced:** Parsing Success Rate, Precision (noise removal), Fallback coverage

---

## 3. Table Extraction

**Class:** `TableExtractor`
**File:** `KB-Pipeline/processors/table_extractor.py`
**Methods:**
- `extract_from_html(node) -> list[ExtractedTable]`
- `extract_from_pdf(pdf_bytes: bytes) -> list[ExtractedTable]`

**Raises:** None — fails silently (skips bad tables, logs warnings)

### Tools

```bash
pip install pytest beautifulsoup4
```

`beautifulsoup4` is already a project dependency. No extra tools needed.

---

### Category 1 — Content Quality Tests

```python
import sys
from pathlib import Path
from bs4 import BeautifulSoup
sys.path.insert(0, str(Path(__file__).parents[3]))
from KB_Pipeline.processors.table_extractor import TableExtractor

extractor = TableExtractor()

# TE01 — Basic HTML table extraction
def test_te01_basic_html_table():
    html = """<table>
        <thead><tr><th>Profile</th><th>Rate</th></tr></thead>
        <tbody>
            <tr><td>Citizen</td><td>0%</td></tr>
            <tr><td>PR</td><td>5%</td></tr>
        </tbody>
    </table>"""
    soup = BeautifulSoup(html, "html.parser")
    tables = extractor.extract_from_html(soup)

    assert len(tables) == 1
    assert tables[0].headers == ["Profile", "Rate"]
    assert tables[0].rows == [["Citizen", "0%"], ["PR", "5%"]]

# TE02 — Header inferred from first <th> row (no <thead>)
def test_te02_header_inferred_from_th_row():
    html = """<table>
        <tr><th>Type</th><th>Amount</th></tr>
        <tr><td>BTO</td><td>$300,000</td></tr>
    </table>"""
    soup = BeautifulSoup(html, "html.parser")
    tables = extractor.extract_from_html(soup)

    assert tables[0].headers == ["Type", "Amount"]
    assert tables[0].rows[0] == ["BTO", "$300,000"]

# TE18 — PDF table extraction
def test_te18_pdf_table_extraction():
    pdf_bytes = open("testing/datasets/pdfs/iras_absd_guide.pdf", "rb").read()
    tables = extractor.extract_from_pdf(pdf_bytes)

    assert len(tables) >= 1
    # At least one table should have percentage values
    all_cells = [cell for t in tables for row in t.rows for cell in row]
    assert any("%" in cell for cell in all_cells)

# TE22 — Financial number format preserved
def test_te22_financial_numbers_preserved():
    html = """<table>
        <thead><tr><th>Band</th><th>Rate</th></tr></thead>
        <tbody>
            <tr><td>First $8,000</td><td>0%</td></tr>
            <tr><td>Next $47,000</td><td>4%</td></tr>
        </tbody>
    </table>"""
    soup = BeautifulSoup(html, "html.parser")
    tables = extractor.extract_from_html(soup)

    assert tables[0].rows[0][0] == "First $8,000"
    assert tables[0].rows[1][1] == "4%"
```

---

### Category 2 — Behavior / Robustness Tests

```python
from bs4 import BeautifulSoup
from KB_Pipeline.processors.table_extractor import TableExtractor

extractor = TableExtractor()

# TE04 — Empty table returns empty list (no crash)
def test_te04_empty_table_ignored():
    html = "<table><thead><tr></tr></thead><tbody></tbody></table>"
    soup = BeautifulSoup(html, "html.parser")
    tables = extractor.extract_from_html(soup)
    assert tables == []

# TE05 — None input returns empty list (no crash)
def test_te05_none_input_safe():
    tables = extractor.extract_from_html(None)
    assert tables == []

# TE15 — Markdown output is valid GitHub-flavoured Markdown
def test_te15_markdown_output():
    html = """<table>
        <thead><tr><th>A</th><th>B</th></tr></thead>
        <tbody><tr><td>1</td><td>2</td></tr></tbody>
    </table>"""
    soup = BeautifulSoup(html, "html.parser")
    tables = extractor.extract_from_html(soup)
    md = TableExtractor.to_markdown(tables[0])

    assert "| A | B |" in md
    assert "| 1 | 2 |" in md
    assert "|---|" in md  # separator row

# TE16 — Pipe character in cell is escaped
def test_te16_pipe_escaped_in_markdown():
    html = """<table>
        <thead><tr><th>Rule</th></tr></thead>
        <tbody><tr><td>A | B applies</td></tr></tbody>
    </table>"""
    soup = BeautifulSoup(html, "html.parser")
    tables = extractor.extract_from_html(soup)
    md = TableExtractor.to_markdown(tables[0])

    assert r"\|" in md  # pipe was escaped
```

**Metrics produced:** Table Extraction Accuracy (headers match + rows match), Markdown correctness

---

## 4. Metadata Extraction

**Class:** `MetadataExtractor`
**File:** `KB-Pipeline/processors/metadata_extractor.py`
**Method:** `extract(doc: ExtractedDocument, source_agency: str, tag_config: dict) -> ExtractedMetadata`
**Raises:** None — fails silently with warnings

### Tools

```bash
pip install pytest
```

No extra tools needed.

---

### Category 1 — Content Quality Tests

```python
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parents[3]))
from KB_Pipeline.processors.html_extractor import HTMLExtractor
from KB_Pipeline.processors.metadata_extractor import MetadataExtractor

html_extractor = HTMLExtractor()
meta_extractor = MetadataExtractor()

TAG_CONFIG = {
    "property_type": {"HDB": ["hdb"], "private": ["condo", "private property"]},
    "topic": {"stamp_duty": ["stamp duty", "absd", "bsd"], "eligibility": ["eligibility", "eligible"]},
}

def test_metadata_iras_absd():
    html   = open("testing/datasets/html/iras_absd.html", encoding="utf-8").read()
    doc    = html_extractor.extract(html, source_url="", source_name="iras")
    result = meta_extractor.extract(doc, source_agency="Inland Revenue Authority of Singapore",
                                    tag_config=TAG_CONFIG)

    # Required fields populated
    assert result.title != ""
    assert result.source_agency == "Inland Revenue Authority of Singapore"
    assert result.section != ""

    # Tags matched
    assert "stamp_duty" in result.tags.get("topic", [])

def test_metadata_date_extraction():
    # Page with a known effective date in the text
    from KB_Pipeline.processors.html_extractor import ExtractedDocument
    doc = ExtractedDocument(
        title="Test",
        text="With effect from 15 February 2023, the ABSD rate applies.",
        headings=[], tables=[], source_url="", source_name="iras",
        content_type="html", word_count=10, extraction_warnings=[]
    )
    result = meta_extractor.extract(doc, source_agency="IRAS", tag_config={})
    assert result.effective_date == "2023-02-15"
```

---

### Category 2 — Behavior / Robustness Tests

```python
from KB_Pipeline.processors.metadata_extractor import MetadataExtractor
from KB_Pipeline.processors.html_extractor import ExtractedDocument

meta_extractor = MetadataExtractor()

def _make_doc(text="", headings=None, title="Test"):
    return ExtractedDocument(
        title=title, text=text, headings=headings or [],
        tables=[], source_url="", source_name="test",
        content_type="html", word_count=len(text.split()),
        extraction_warnings=[]
    )

# No date in text: warning issued, effective_date is empty string
def test_metadata_no_date_warning():
    doc    = _make_doc("This document has no date anywhere.")
    result = meta_extractor.extract(doc, source_agency="TEST", tag_config={})
    assert result.effective_date == ""
    assert any("date" in w.lower() for w in result.metadata_warnings)

# No headings: section falls back to title
def test_metadata_section_fallback_to_title():
    doc    = _make_doc("Some content here.", headings=[], title="My Policy Page")
    result = meta_extractor.extract(doc, source_agency="TEST", tag_config={})
    assert result.section == "My Policy Page"

# No tag matches: tags dict is empty (no crash)
def test_metadata_no_tag_matches():
    doc    = _make_doc("Completely unrelated content.")
    result = meta_extractor.extract(doc, source_agency="TEST",
                                    tag_config={"topic": {"finance": ["finance"]}})
    assert result.tags == {} or result.tags.get("topic") is None
```

**Metrics produced:** Metadata Completeness (required fields present), Data Type Correctness (date is ISO format)

---

## 5. Chunking

**Class:** `DocumentChunker`
**File:** `KB-Pipeline/processors/chunker.py`
**Method:** `chunk(doc: ExtractedDocument, metadata: ExtractedMetadata) -> list[DocumentChunk]`
**Defaults:** chunk_size=512 tokens, overlap=64 tokens (cl100k_base tiktoken)
**Raises:** None — returns empty list for empty documents

### Tools

```bash
pip install pytest tiktoken
```

`tiktoken` is already a project dependency.

---

### Category 1 — Content Quality Tests

```python
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parents[3]))
from KB_Pipeline.processors.html_extractor import HTMLExtractor
from KB_Pipeline.processors.metadata_extractor import MetadataExtractor, ExtractedMetadata
from KB_Pipeline.processors.chunker import DocumentChunker
import tiktoken

html_extractor = HTMLExtractor()
meta_extractor = MetadataExtractor()
chunker = DocumentChunker(chunk_size=512, chunk_overlap=64)
enc = tiktoken.get_encoding("cl100k_base")

def test_chunk_size_within_limit():
    html = open("testing/datasets/html/iras_absd.html", encoding="utf-8").read()
    doc  = html_extractor.extract(html, source_url="", source_name="iras")
    meta = meta_extractor.extract(doc, source_agency="IRAS", tag_config={})

    chunks = chunker.chunk(doc, meta)

    assert len(chunks) > 0
    for chunk in chunks:
        token_count = len(enc.encode(chunk.chunk_text))
        assert token_count <= 512, f"Chunk exceeds 512 tokens: {token_count}"

def test_chunk_metadata_completeness():
    html = open("testing/datasets/html/iras_absd.html", encoding="utf-8").read()
    doc  = html_extractor.extract(html, source_url="", source_name="iras")
    meta = meta_extractor.extract(doc, source_agency="IRAS", tag_config={})

    chunks = chunker.chunk(doc, meta)

    for chunk in chunks:
        assert chunk.source_name == "iras"
        assert chunk.content_type == "html"
        assert chunk.token_count > 0
        assert chunk.chunk_index >= 0
        assert chunk.chunk_type in ("text", "table")

def test_table_chunks_created():
    # A page with tables must produce at least one table-type chunk
    html = open("testing/datasets/html/iras_absd.html", encoding="utf-8").read()
    doc  = html_extractor.extract(html, source_url="", source_name="iras")
    meta = meta_extractor.extract(doc, source_agency="IRAS", tag_config={})

    chunks = chunker.chunk(doc, meta)
    table_chunks = [c for c in chunks if c.chunk_type == "table"]
    assert len(table_chunks) >= 1
```

---

### Category 2 — Behavior / Robustness Tests

```python
from KB_Pipeline.processors.chunker import DocumentChunker
from KB_Pipeline.processors.html_extractor import ExtractedDocument
from KB_Pipeline.processors.metadata_extractor import ExtractedMetadata

chunker = DocumentChunker()

def _make_doc(text="", tables=None):
    from KB_Pipeline.processors.html_extractor import ExtractedDocument
    return ExtractedDocument(
        title="Test", text=text, headings=[], tables=tables or [],
        source_url="", source_name="test", content_type="html",
        word_count=len(text.split()), extraction_warnings=[]
    )

def _make_meta():
    return ExtractedMetadata(
        title="Test", source_agency="TEST", section="", effective_date="",
        tags={}, metadata_warnings=[]
    )

# Empty document returns empty list (no crash)
def test_chunker_empty_document():
    doc    = _make_doc(text="")
    chunks = chunker.chunk(doc, _make_meta())
    assert chunks == []

# Heading breadcrumb is populated for text chunks
def test_chunker_heading_breadcrumb():
    text = "## Eligibility\n\nYou must be a Singapore Citizen.\n\n### Income Ceiling\n\nMaximum $14,000 per month."
    doc  = _make_doc(text=text)
    chunks = chunker.chunk(doc, _make_meta())
    # At least one chunk should have a heading path
    assert any(len(c.heading_path) > 0 for c in chunks)
```

**Metrics produced:** Exact Match Rate, Token count compliance, Metadata Completeness per chunk

---

## 6. Embedding

**Class:** `EmbeddingService`
**File:** `KB-Pipeline/embedders/embedding_service.py`
**Method:** `embed_chunks(chunks: list[DocumentChunk]) -> list[EmbeddingResult]`
**Raises:** `RuntimeError` (when both OpenRouter and OpenAI fail)
**Fallback chain:** OpenRouter → OpenAI (on `AuthenticationError`)

> **Important:** Embedding tests check process quality only — you cannot write expected JSON for a 3072-dimensional vector. There is no `expected/embedding.json`.

### Tools

```bash
pip install pytest pytest-mock numpy
```

| Tool | Why |
|---|---|
| `pytest-mock` | Mock OpenRouter to trigger the OpenAI fallback |
| `numpy` | Verify vector dimension and basic vector properties |

---

### Category 1 — Process Quality Tests

These replace "content quality" for embedding since output vectors cannot be compared to expected values.

```python
import sys, numpy as np
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parents[3]))
from KB_Pipeline.embedders.embedding_service import EmbeddingService
from KB_Pipeline.processors.chunker import DocumentChunk

service = EmbeddingService()

def _make_chunk(text="Singapore property rules apply here."):
    return DocumentChunk(
        chunk_text=text, chunk_index=0, chunk_type="text",
        heading_path=[], metadata={}, source_url="", source_name="iras",
        content_type="html", word_count=5, token_count=8
    )

# Vector dimension must be 3072
def test_vector_dimension():
    results = service.embed_chunks([_make_chunk()])
    assert len(results) == 1
    assert len(results[0].embedding) == 3072, "Expected 3072-dim vector (text-embedding-3-large)"

# Same input produces same vector (deterministic)
def test_embedding_deterministic():
    chunk   = _make_chunk()
    result1 = service.embed_chunks([chunk])
    result2 = service.embed_chunks([chunk])
    np.testing.assert_array_almost_equal(result1[0].embedding, result2[0].embedding, decimal=4)

# Token count is captured
def test_token_count_captured():
    results = service.embed_chunks([_make_chunk()])
    assert results[0].token_count > 0
```

---

### Category 2 — Behavior / Robustness Tests

```python
import pytest
from unittest.mock import patch, MagicMock
from openai import AuthenticationError
from KB_Pipeline.embedders.embedding_service import EmbeddingService

service = EmbeddingService()

# OpenRouter AuthenticationError → permanent switch to OpenAI fallback
def test_openrouter_auth_failure_falls_back_to_openai(mocker):
    # Mock OpenRouter to raise AuthenticationError
    mock_openrouter = mocker.patch.object(service, "_openrouter_client")
    mock_openrouter.embeddings.create.side_effect = AuthenticationError(
        "Invalid API key", response=MagicMock(), body={}
    )

    # Mock OpenAI to succeed
    mock_openai = mocker.patch.object(service, "_openai_client")
    mock_openai.embeddings.create.return_value = MagicMock(
        data=[MagicMock(embedding=[0.1] * 3072)],
        usage=MagicMock(total_tokens=8)
    )

    from KB_Pipeline.processors.chunker import DocumentChunk
    chunk = DocumentChunk(
        chunk_text="test", chunk_index=0, chunk_type="text",
        heading_path=[], metadata={}, source_url="", source_name="test",
        content_type="html", word_count=1, token_count=1
    )
    results = service.embed_chunks([chunk])
    assert len(results) == 1
    mock_openai.embeddings.create.assert_called_once()  # OpenAI was used

# Both providers fail → RuntimeError
def test_both_providers_fail_raises_runtime_error(mocker):
    mocker.patch.object(service, "_openrouter_client").embeddings.create.side_effect = \
        Exception("OpenRouter down")
    mocker.patch.object(service, "_openai_client").embeddings.create.side_effect = \
        Exception("OpenAI down")

    from KB_Pipeline.processors.chunker import DocumentChunk
    chunk = DocumentChunk(
        chunk_text="test", chunk_index=0, chunk_type="text",
        heading_path=[], metadata={}, source_url="", source_name="test",
        content_type="html", word_count=1, token_count=1
    )
    with pytest.raises(RuntimeError):
        service.embed_chunks([chunk])
```

**Metrics produced:** Error Rate, Latency (add `time.time()` wrappers), Vector dimension correctness, Fallback activation rate

---

## 7. Crawlers

**Class:** `BaseCrawler` (Scrapy spider base)
**Files:** `KB-Pipeline/crawlers/base.py`, `pipelines.py`, `runner.py`
**Change detection:** SHA-256 hash of content — stored in `raw_documents.content_hash`
**Storage:** MinIO (S3) + PostgreSQL `raw_documents` table

> **Note:** Crawlers are harder to test in isolation because they require network access and a running database. The recommended approach is to test the **change detection logic** and **pipeline logic** in isolation, and test full crawl behavior in a staging environment.

### Tools

```bash
pip install pytest pytest-mock scrapy
```

---

### Category 1 — Change Detection Logic Tests

These test the hash-based change detection without running a live crawl.

```python
import hashlib, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parents[3]))

# Test the hash function used for change detection
def test_sha256_same_content_same_hash():
    content = "HDB eligibility rules for BTO flats."
    hash1   = hashlib.sha256(content.encode()).hexdigest()
    hash2   = hashlib.sha256(content.encode()).hexdigest()
    assert hash1 == hash2

def test_sha256_changed_content_different_hash():
    old_content = "ABSD rate for citizens: 0% on first property."
    new_content = "ABSD rate for citizens: 0% on first property. Updated 2024."
    assert hashlib.sha256(old_content.encode()).hexdigest() != \
           hashlib.sha256(new_content.encode()).hexdigest()
```

---

### Category 2 — Behavior / Robustness Tests

```python
import pytest
from unittest.mock import patch, MagicMock

# Test that unchanged content is NOT re-processed (False Positive = 0)
def test_unchanged_page_not_reprocessed(mocker):
    from KB_Pipeline.crawlers.pipelines import PostgresPipeline
    pipeline = PostgresPipeline()

    existing_hash = "abc123"
    new_content   = "Same content as before"
    new_hash      = __import__("hashlib").sha256(new_content.encode()).hexdigest()

    # Simulate: DB returns same hash for this URL
    mocker.patch.object(pipeline, "_get_existing_hash", return_value=new_hash)
    mock_update = mocker.patch.object(pipeline, "_update_last_seen")

    result = pipeline.process_item({"url": "https://test.com", "content": new_content}, None)

    mock_update.assert_called_once()           # only last_seen_at updated
    # No re-processing triggered (status not set to 'pending')

# Test that changed content IS re-processed (False Negative = 0)
def test_changed_page_triggers_reprocess(mocker):
    from KB_Pipeline.crawlers.pipelines import PostgresPipeline
    pipeline = PostgresPipeline()

    old_hash    = "abc123"
    new_content = "Updated ABSD rates: Citizen 2nd property now 25%"
    new_hash    = __import__("hashlib").sha256(new_content.encode()).hexdigest()

    mocker.patch.object(pipeline, "_get_existing_hash", return_value=old_hash)
    mock_reprocess = mocker.patch.object(pipeline, "_mark_for_reprocessing")

    pipeline.process_item({"url": "https://test.com", "content": new_content}, None)

    mock_reprocess.assert_called_once()  # re-processing was triggered
```

**Metrics produced:** Change Detection Rate, False Positive Rate, False Negative Rate, Error Rate, Latency

---

## Running All Tests

### Install all dependencies at once

```bash
pip install pytest pytest-mock pytest-cov jiwer editdistance fpdf2 numpy tiktoken
```

### Run one section

```bash
# PDF extraction only
pytest testing/kb-pipeline/pdf-extraction/ -v

# HTML extraction only
pytest testing/kb-pipeline/html-extraction/ -v
```

### Run all sections with coverage report

```bash
pytest testing/kb-pipeline/ -v --cov=KB_Pipeline --cov-report=term-missing
```

### Run only P0 (critical) tests

```bash
pytest testing/kb-pipeline/ -v -k "pe01 or pe02 or pe07 or he01 or he07 or te01"
```

### Generate HTML report

```bash
pip install pytest-html
pytest testing/kb-pipeline/ --html=testing/results/report.html --self-contained-html
```

---

## Quick Reference — What Each Section Needs

| Section | Real files needed | Crafted fixtures | Key assertion |
|---|---|---|---|
| PDF Extraction | 4–6 government PDFs | scanned PDF, empty bytes, corrupted bytes | CER <2%, WER <5%, fallback activates |
| HTML Extraction | 10 HTML pages (2 per source) | empty HTML, noise-only HTML | noise stripped, all 5 sources parse |
| Table Extraction | Same HTML + PDF files | empty table, None input | headers + rows match expected |
| Metadata | Same HTML files | text without dates, text without headings | all fields populated, ISO date format |
| Chunking | Output from HTML/PDF | empty document | token count ≤512, metadata on each chunk |
| Embedding | Any chunks (from above) | none needed | dim=3072, fallback to OpenAI works |
| Crawlers | None (uses mocks) | none needed | changed content triggers reprocess |
