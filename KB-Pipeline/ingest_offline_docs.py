"""
Ingest offline PDF and HTML documents from testing/datasets/ into an isolated
evaluation database and Pinecone index, bypassing the Scrapy crawler entirely.

This script is intentionally run with EVAL env vars so it NEVER touches the
production database or Pinecone index.

Prerequisites (run inside the KB-Pipeline Docker container):
  1. Create the eval Postgres database:
       docker exec sg-property-kb-postgres psql -U kb_user -c "CREATE DATABASE kb_pipeline_eval;"
  2. Apply migrations to the eval DB:
       export DATABASE_URL=postgresql://kb_user:kb_pass@postgres:5432/kb_pipeline_eval
       alembic upgrade head
  3. Create a new Pinecone index named "kb-pipeline-eval" (same dimension=3072, metric=cosine)

Usage (inside container with eval env vars):
  docker exec -e DATABASE_URL=postgresql://kb_user:kb_pass@postgres:5432/kb_pipeline_eval \
              -e PINECONE_INDEX=kb-pipeline-eval \
              sg-property-kb-app python ingest_offline_docs.py

On re-run, already-ingested documents are skipped (idempotent via content_hash).
"""

import hashlib
import sys
from pathlib import Path

# ── Locate testing/datasets relative to this script ──────────────────────────

_REPO_ROOT   = Path(__file__).resolve().parent
_EVAL_DOCS_DIR = _REPO_ROOT / "eval_docs"
_PDF_DIR     = _EVAL_DOCS_DIR
_HTML_DIR    = _EVAL_DOCS_DIR

# ── Source code mapping — infer from filename ─────────────────────────────────

_FILENAME_TO_SOURCE = {
    "hdb":  ["hdb", "couples", "joint singles", "smart planning"],
    "iras": ["iras", "tax"],
    "cpf":  ["cpf", "cpfb"],
    "ura":  ["ura", "urban", "proposed amendments"],
    "mas":  ["mas", "notice 1106", "residential property loans"],
}


def _detect_source(filename: str) -> str:
    """Map a filename to the best-matching source code."""
    name_lower = filename.lower()
    for code, keywords in _FILENAME_TO_SOURCE.items():
        if any(kw in name_lower for kw in keywords):
            return code
    return "hdb"  # safe default — HDB is the broadest source


# ── Ingest logic ──────────────────────────────────────────────────────────────

def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()


def ingest_all() -> None:
    # Import KB-Pipeline modules here so env vars are already set by the caller
    from config.database import SessionLocal
    from config.models import RawDocument, Source
    from embedders.pipeline import EmbeddingPipeline
    from processors.html_extractor import HTMLExtractor
    from processors.pdf_extractor import PDFExtractor
    from processors.runner import process_pending_documents

    db = SessionLocal()
    html_extractor = HTMLExtractor()
    pdf_extractor  = PDFExtractor()

    # Build source lookup
    sources: dict[str, object] = {
        s.code: s for s in db.query(Source).filter(Source.is_active == True).all()  # noqa: E712
    }
    if not sources:
        print(
            "[ingest] ERROR: No sources found in database. "
            "Did you run 'alembic upgrade head' against the eval DB?"
        )
        sys.exit(1)

    inserted = skipped = failed = 0

    # ── PDFs ────────────────────────────────────────────────────────────────
    for pdf_path in sorted(_PDF_DIR.glob("*.pdf")):
        if pdf_path.name == ".gitkeep":
            continue

        source_code = _detect_source(pdf_path.name)
        source = sources.get(source_code) or next(iter(sources.values()))
        fake_url = f"file://eval/{pdf_path.name}"

        try:
            raw_bytes = pdf_path.read_bytes()
            extracted = pdf_extractor.extract(raw_bytes, source_url=fake_url, source_name=source_code)
            content_hash = _sha256(extracted.text)

            existing = (
                db.query(RawDocument)
                .filter_by(content_hash=content_hash)
                .first()
            )
            if existing:
                print(f"[ingest] SKIP (already exists): {pdf_path.name}")
                skipped += 1
                continue

            doc = RawDocument(
                source_id=source.id,
                url=fake_url,
                content_hash=content_hash,
                content_type="pdf",
                raw_text=extracted.text,
                s3_path="",
                status="pending",
                needs_ocr=extracted.needs_ocr if hasattr(extracted, "needs_ocr") else False,
                extraction_flags={"title": extracted.title, "source": "offline_eval"},
            )
            db.add(doc)
            db.commit()
            print(f"[ingest] OK (pdf): {pdf_path.name}  →  source={source_code}")
            inserted += 1

        except Exception as exc:
            db.rollback()
            print(f"[ingest] FAIL (pdf): {pdf_path.name}: {exc}")
            failed += 1

    # ── HTMLs ────────────────────────────────────────────────────────────────
    # We use list(glob("*.html")) + list(glob("*.htm")) to catch both extensions
    html_files = list(_HTML_DIR.glob("*.html")) + list(_HTML_DIR.glob("*.htm"))
    for html_path in sorted(html_files):
        if html_path.name == ".gitkeep":
            continue

        source_code = _detect_source(html_path.name)
        source = sources.get(source_code) or next(iter(sources.values()))
        fake_url = f"file://eval/{html_path.name}"

        try:
            html_text = html_path.read_text(encoding="utf-8", errors="replace")
            extracted = html_extractor.extract(html_text, source_url=fake_url)
            content_hash = _sha256(extracted.text)

            existing = (
                db.query(RawDocument)
                .filter_by(content_hash=content_hash)
                .first()
            )
            if existing:
                print(f"[ingest] SKIP (already exists): {html_path.name}")
                skipped += 1
                continue

            doc = RawDocument(
                source_id=source.id,
                url=fake_url,
                content_hash=content_hash,
                content_type="html",
                raw_text=extracted.text,
                s3_path="",
                status="pending",
                extraction_flags={"title": extracted.title, "source": "offline_eval"},
            )
            db.add(doc)
            db.commit()
            print(f"[ingest] OK (html): {html_path.name}  →  source={source_code}")
            inserted += 1

        except Exception as exc:
            db.rollback()
            print(f"[ingest] FAIL (html): {html_path.name}: {exc}")
            failed += 1

    db.close()
    print(f"\n[ingest] Done — inserted={inserted}, skipped={skipped}, failed={failed}")

    if inserted == 0 and skipped > 0:
        print("[ingest] All documents already in eval DB. Nothing to process.")
        return

    if inserted > 0:
        print("\n[ingest] Running processor (chunk + metadata) …")
        process_pending_documents()

        print("[ingest] Running embedder (embed + upsert to Pinecone eval index) …")
        EmbeddingPipeline().embed_chunks()

        print("[ingest] Ingestion complete. Eval KB is ready.")


if __name__ == "__main__":
    ingest_all()
