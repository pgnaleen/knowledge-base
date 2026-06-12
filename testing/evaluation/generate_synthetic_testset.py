"""
Generate a synthetic RAG evaluation test set from the offline PDF and HTML documents
in testing/datasets/. Extracts CLEAN text from each file first (strips HTML tags,
PDF binary artifacts) then passes plain text to DeepEval's Synthesizer.

Two-pass strategy:
  Pass 1 — generate_goldens_from_docs with domain-biased StylingConfig
  Pass 2 — coverage check + generate_goldens_from_scratch top-up for any
            missing Singapore property acronyms (ABSD, BSD, TDSR, etc.)

Usage:
    cd "c:\\GEEMETH\\N\\Property Advisory AI Agent"
    python testing/evaluation/generate_synthetic_testset.py

Output:
    testing/evaluation/testset.csv   — CSV with Source, input, expected_output, context

Environment (loaded from testing/evaluation/.env.eval):
    OPENAI_API_KEY   — required (DeepEval judge LLM)
    N_GOLDENS        — override question count (default: 100)

Install deps first:
    pip install -r testing/evaluation/requirements-eval.txt
"""

import csv
import csv
import json
import os
import tempfile
from pathlib import Path

import pdfplumber
from bs4 import BeautifulSoup
from deepeval.synthesizer import Synthesizer
from deepeval.synthesizer.config import ContextConstructionConfig, StylingConfig
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env.eval", override=True)

# ── Paths ─────────────────────────────────────────────────────────────────────

_REPO_ROOT   = Path(__file__).resolve().parents[2]
_DATASET_DIR = _REPO_ROOT / "testing" / "datasets"
_PDF_DIR     = _DATASET_DIR / "pdfs"
_HTML_DIR    = _DATASET_DIR / "html"
_OUT_FILE    = Path(__file__).parent / "testset.csv"

_N_GOLDENS   = int(os.getenv("N_GOLDENS", "100"))
_JUDGE_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o")

# ── Required topic coverage ───────────────────────────────────────────────────

DOMAIN_TOPICS = {
    "ABSD": "Additional Buyer's Stamp Duty",
    "BSD":  "Buyer's Stamp Duty",
    "SSD":  "Seller's Stamp Duty",
    "TDSR": "Total Debt Servicing Ratio",
    "MSR":  "Mortgage Servicing Ratio",
    "LTV":  "Loan-to-Value",
    "EC":   "Executive Condominium",
    "HDB":  "Housing Development Board",
    "CPF":  "Central Provident Fund",
    "BTO":  "Build-To-Order",
    "OA":   "Ordinary Account",
    "SA":   "Special Account",
    "SC":   "Singapore Citizen",
    "PR":   "Permanent Resident",
}

# ── StylingConfig — primes the LLM to use all 14 acronyms ────────────────────

DOMAIN_STYLING = StylingConfig(
    scenario=(
        "A Singapore property advisory AI helping clients understand: "
        "ABSD (Additional Buyer's Stamp Duty), BSD (Buyer's Stamp Duty), "
        "SSD (Seller's Stamp Duty), TDSR (Total Debt Servicing Ratio), "
        "MSR (Mortgage Servicing Ratio), LTV (Loan-to-Value), "
        "EC (Executive Condominium), HDB (Housing Development Board), "
        "CPF (Central Provident Fund), BTO (Build-To-Order), "
        "CPF OA (Ordinary Account), CPF SA (Special Account), "
        "and purchase eligibility rules for SC (Singapore Citizens) and PR (Permanent Residents)."
    ),
    task=(
        "Generate realistic questions a property buyer would ask when seeking advisory "
        "on Singapore property regulations, financing, and eligibility"
    ),
    input_format="Question from a client buying or considering buying property in Singapore",
    expected_output_format="Clear factual answer citing specific Singapore regulations or figures",
)

# ── Text extraction ───────────────────────────────────────────────────────────

def _extract_pdf_text(path: Path) -> str:
    """Extract plain text from a PDF using pdfplumber."""
    parts = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            text = page.extract_text()
            if text:
                parts.append(text.strip())
    return "\n\n".join(parts)


def _extract_html_text(path: Path) -> str:
    """Extract clean text from an HTML file — strips all tags, scripts, nav noise."""
    html = path.read_text(encoding="utf-8", errors="replace")
    soup = BeautifulSoup(html, "lxml")

    for tag in soup(["script", "style", "noscript", "nav", "header", "footer",
                     "aside", "iframe", "form", "button"]):
        tag.decompose()

    main = (
        soup.find("main")
        or soup.find("article")
        or soup.find(attrs={"role": "main"})
        or soup.find("div", id="content")
        or soup.body
    )
    if main is None:
        main = soup

    lines = []
    for element in main.stripped_strings:
        stripped = element.strip()
        if stripped:
            lines.append(stripped)

    return "\n".join(lines)


# ── Build document list ───────────────────────────────────────────────────────

def _build_documents() -> list[dict]:
    """Return list of {name, text} dicts for all source PDFs and HTMLs."""
    docs = []

    for pdf_path in sorted(_PDF_DIR.glob("*.pdf")):
        if pdf_path.name == ".gitkeep":
            continue
        try:
            text = _extract_pdf_text(pdf_path)
            if text.strip():
                docs.append({"name": pdf_path.name, "text": text})
                print(f"  [pdf]  {pdf_path.name} — {len(text):,} chars")
            else:
                print(f"  [pdf]  SKIP (empty): {pdf_path.name}")
        except Exception as exc:
            print(f"  [pdf]  ERROR: {pdf_path.name}: {exc}")

    for html_path in sorted(_HTML_DIR.glob("*.html")):
        if html_path.name == ".gitkeep":
            continue
        try:
            text = _extract_html_text(html_path)
            if text.strip():
                docs.append({"name": html_path.name, "text": text})
                print(f"  [html] {html_path.name} — {len(text):,} chars")
            else:
                print(f"  [html] SKIP (empty): {html_path.name}")
        except Exception as exc:
            print(f"  [html] ERROR: {html_path.name}: {exc}")

    return docs


# ── Coverage check ────────────────────────────────────────────────────────────

def _check_coverage(records: list[dict]) -> list[str]:
    """Return acronyms with zero coverage across all generated questions."""
    all_text = " ".join(
        (r.get("input", "") or "") + " " + (r.get("expected_output", "") or "")
        for r in records
    ).lower()
    missing = []
    for acronym, full_name in DOMAIN_TOPICS.items():
        if acronym.lower() not in all_text and full_name.lower() not in all_text:
            missing.append(acronym)
    return missing


def _topup_topic(acronym: str, full_name: str) -> list:
    """Generate 2 targeted questions for a single uncovered topic."""
    synth = Synthesizer(
        model=_JUDGE_MODEL,
        styling_config=StylingConfig(
            scenario=(
                f"A Singapore property buyer asking specifically about {full_name} ({acronym}). "
                f"Context: Singapore property regulations governed by HDB, IRAS, MAS, and CPF Board."
            ),
            task=f"Generate a realistic client question specifically about {acronym} ({full_name})",
            input_format=f"Question specifically about {full_name} in Singapore property context",
            expected_output_format=(
                "Factual answer about Singapore regulations with specific figures or rules"
            ),
        ),
    )
    return synth.generate_goldens_from_scratch(num_goldens=2)


# ── Generate ──────────────────────────────────────────────────────────────────

def main() -> None:
    print("Extracting clean text from source documents …")
    docs = _build_documents()

    if not docs:
        raise FileNotFoundError(
            f"No usable PDF or HTML files found in:\n  {_PDF_DIR}\n  {_HTML_DIR}"
        )

    print(f"\nLoaded {len(docs)} document(s). Generating {_N_GOLDENS} QA pairs (Pass 1) …\n")

    synthesizer = Synthesizer(model=_JUDGE_MODEL, styling_config=DOMAIN_STYLING)
    goldens_per_doc = max(1, _N_GOLDENS // len(docs))
    
    tmp_dir = Path(tempfile.mkdtemp(prefix="deepeval_eval_"))
    records = []
    try:
        for doc in docs:
            tmp_file = tmp_dir / (doc["name"] + ".txt")
            tmp_file.write_text(doc["text"], encoding="utf-8")
            
            # Generate goldens just for this one document
            goldens = synthesizer.generate_goldens_from_docs(
                document_paths=[str(tmp_file)],
                include_expected_output=True,
                max_goldens_per_context=goldens_per_doc,
                context_construction_config=ContextConstructionConfig(
                    chunk_size=1024,
                    chunk_overlap=100,
                ),
            )
            
            for g in goldens:
                records.append({
                    "Source": doc["name"],
                    "input": g.input,
                    "expected_output": g.expected_output or "",
                    "context": json.dumps(g.context or [], ensure_ascii=False),
                })
    finally:
        # Clean up temp files
        import shutil
        shutil.rmtree(tmp_dir, ignore_errors=True)

    # Note: Saved intermediate results earlier...

    # ── Pass 2: coverage top-up ───────────────────────────────────────────────

    missing = _check_coverage(records)
    if missing:
        print(f"\nPass 2 — topping up {len(missing)} missing topic(s): {', '.join(missing)}")
        for acronym in missing:
            full_name = DOMAIN_TOPICS[acronym]
            try:
                extra = _topup_topic(acronym, full_name)
                for g in extra:
                    records.append({
                        "Source": "TopUp",
                        "input": g.input,
                        "expected_output": g.expected_output or "",
                        "context": json.dumps(g.context or [], ensure_ascii=False),
                    })
                print(f"  [{acronym}] +{len(extra)} question(s)")
            except Exception as exc:
                print(f"  [{acronym}] top-up failed: {exc}")
    else:
        print("\nPass 2 — all 14 topics covered. No top-up needed.")

    # ── Coverage report ───────────────────────────────────────────────────────

    # ── Coverage report ───────────────────────────────────────────────────────

    still_missing = _check_coverage(records)
    print("\n── Topic coverage ──────────────────────────────")
    for acronym, full_name in DOMAIN_TOPICS.items():
        status = "✗ MISSING" if acronym in still_missing else "✓"
        print(f"  {status}  {acronym} ({full_name})")

    # ── Save ──────────────────────────────────────────────────────────────────

    with _OUT_FILE.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["Source", "input", "expected_output", "context"])
        writer.writeheader()
        writer.writerows(records)

    print(f"\nSaved {len(records)} QA pairs → {_OUT_FILE}")
    print("Open testset.csv in Excel / Google Sheets to review before running test_rag.py.")


if __name__ == "__main__":
    main()
