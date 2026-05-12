"""PDF extraction module — pdfplumber primary, PyMuPDF fallback."""

import io
import re
from typing import Any

from config.logger import get_logger
from processors.models import ExtractedDocument, ExtractedTable
from processors.table_extractor import TableExtractor

_table_extractor = TableExtractor()
logger = get_logger("pdf_extractor")

_SCANNED_WORD_THRESHOLD = 20


class PDFExtractionError(ValueError):
    """Raised when a PDF cannot be opened or parsed at all."""


class PDFExtractor:
    """Extracts text from PDF bytes using pdfplumber with PyMuPDF fallback.

    Scanned (image-only) PDFs are detected and flagged in extraction_warnings
    so callers can route them to an OCR queue.
    """

    def extract(
        self,
        pdf_bytes: bytes,
        source_url: str = "",
        source_name: str = "",
    ) -> ExtractedDocument:
        if not pdf_bytes:
            raise PDFExtractionError("pdf_bytes is empty")

        logger.info("pdf.started", source_url=source_url, source_name=source_name)

        warnings: list[str] = []
        text = ""
        title = "Untitled"
        page_count = 0
        used_fallback = False
        tables: list[ExtractedTable] = []
        interleaved_text: str | None = None

        try:
            interleaved_text, title, page_count, tables = self._extract_pdfplumber_interleaved(
                pdf_bytes
            )
        except PDFExtractionError:
            raise
        except Exception as exc:
            logger.warning(
                "pdf_extractor.pdfplumber_failed",
                error=str(exc),
                source_url=source_url,
            )
            warnings.append(
                f"pdfplumber failed ({type(exc).__name__}), using PyMuPDF fallback"
            )
            used_fallback = True
            logger.warning(
                "pdf.pymupdf_fallback",
                source_url=source_url,
                source_name=source_name,
                reason=type(exc).__name__,
            )

        if interleaved_text is not None and interleaved_text.strip():
            text = interleaved_text
        else:
            if interleaved_text is not None:
                warnings.append("pdfplumber returned no text, using PyMuPDF fallback")
            if not used_fallback:
                used_fallback = True
            try:
                fitz_text, fitz_title, fitz_page_count = self._extract_pymupdf(pdf_bytes)
                if fitz_text.strip():
                    text = fitz_text
                elif interleaved_text is not None:
                    text = interleaved_text
                if fitz_title and fitz_title != "Untitled":
                    title = fitz_title
                if fitz_page_count:
                    page_count = fitz_page_count
            except PDFExtractionError:
                raise
            except Exception as exc:
                logger.error(
                    "pdf_extractor.pymupdf_failed",
                    error=str(exc),
                    source_url=source_url,
                )
                warnings.append(f"PyMuPDF also failed ({type(exc).__name__})")

            # Re-detect tables against the fallback text stream (avoids mixing
            # partial interleaved state with PyMuPDF output).
            tables = _table_extractor.extract_from_pdf(pdf_bytes)
            if text and tables:
                text = self._remove_table_lines(text, tables)
            text = self._append_markdown_tables_end(text, tables)

        normalised = self._normalise_whitespace(text)
        word_count = len(normalised.split()) if normalised.strip() else 0

        if word_count < _SCANNED_WORD_THRESHOLD:
            warnings.append(
                f"Scanned PDF detected (only {word_count} words extracted) "
                "— flagged for OCR queue"
            )
            logger.warning(
                "pdf.ocr_detected",
                word_count=word_count,
                pages=page_count,
                source_url=source_url,
                source_name=source_name,
            )

        logger.info(
            "pdf.extracted",
            source_url=source_url,
            source_name=source_name,
            page_count=page_count,
            word_count=word_count,
            table_count=len(tables),
            used_fallback=used_fallback,
        )

        return ExtractedDocument(
            title=title,
            text=normalised,
            headings=[],
            tables=tables,
            source_url=source_url,
            source_name=source_name,
            content_type="pdf",
            word_count=word_count,
            extraction_warnings=warnings,
        )

    def _extract_pdfplumber_interleaved(
        self, pdf_bytes: bytes
    ) -> tuple[str, str, int, list[ExtractedTable]]:
        """Extract per-page text with Markdown tables at their vertical positions."""
        import pdfplumber

        all_tables: list[ExtractedTable] = []
        page_bodies: list[str] = []

        try:
            with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
                meta = pdf.metadata or {}
                title = self._clean_metadata_string(meta.get("Title", "")) or "Untitled"
                page_count = len(pdf.pages)

                for page_index, page in enumerate(pdf.pages):
                    page_number = page_index + 1
                    body, page_tables = self._interleave_page_tables(page, page_number)
                    all_tables.extend(page_tables)
                    if body.strip():
                        page_bodies.append(body.strip())
        except Exception as exc:
            if "PDF" in type(exc).__name__ or "invalid" in str(exc).lower():
                raise PDFExtractionError(f"Not a valid PDF: {exc}") from exc
            raise

        text = "\n\n".join(page_bodies)
        return text, title, page_count, all_tables

    def _interleave_page_tables(self, page: Any, page_number: int) -> tuple[str, list[ExtractedTable]]:
        """Build one page string: non-table words in reading order, tables by bbox."""
        words: list[dict[str, Any]] = page.extract_words() or []
        table_objs = list(page.find_tables() or [])
        bboxes = [t.bbox for t in table_objs]

        def word_in_any_table(w: dict[str, Any]) -> bool:
            cx = (float(w["x0"]) + float(w["x1"])) / 2
            cy = (float(w["top"]) + float(w["bottom"])) / 2
            for bbox in bboxes:
                bx0, btop, bx1, bbottom = (float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3]))
                if bx0 <= cx <= bx1 and btop <= cy <= bbottom:
                    return True
            return False

        outside_words = [w for w in words if not word_in_any_table(w)]
        lines = self._words_clustered_to_lines(outside_words)

        events: list[tuple[float, float, str]] = []
        for top, x0, line in lines:
            stripped = line.strip()
            if stripped:
                events.append((top, x0, stripped))

        page_tables: list[ExtractedTable] = []
        for tbl in table_objs:
            raw = tbl.extract()
            ext = _table_extractor._parse_pdf_table(raw, page_number)
            if ext is None:
                continue
            md = TableExtractor.to_markdown(ext)
            if not md:
                continue
            row_count = len(raw) if raw else 0
            col_count = max((len(r) for r in raw), default=0) if raw else 0
            logger.info(
                "Table detected",
                pipeline="pdf",
                page_number=page_number,
                row_count=row_count,
                col_count=col_count,
            )
            page_tables.append(ext)
            bbox = tbl.bbox
            events.append((float(bbox[1]), float(bbox[0]), md))

        events.sort(key=lambda e: (e[0], e[1]))
        body = "\n\n".join(e[2] for e in events)
        return self._normalise_whitespace(body), page_tables

    @staticmethod
    def _words_clustered_to_lines(
        words: list[dict[str, Any]],
    ) -> list[tuple[float, float, str]]:
        """Cluster pdfplumber words into lines (top, left, text) for reading order."""
        if not words:
            return []
        sorted_w = sorted(words, key=lambda w: (float(w["top"]), float(w["x0"])))
        tol = 3.0
        line_groups: list[list[dict[str, Any]]] = []
        current: list[dict[str, Any]] = []
        current_top: float | None = None
        for w in sorted_w:
            top = float(w["top"])
            if current_top is None or abs(top - current_top) <= tol:
                current.append(w)
                if current_top is None:
                    current_top = top
            else:
                line_groups.append(current)
                current = [w]
                current_top = top
        if current:
            line_groups.append(current)

        out: list[tuple[float, float, str]] = []
        for line_words in line_groups:
            line_words.sort(key=lambda w: float(w["x0"]))
            text = " ".join(str(w.get("text") or "") for w in line_words).strip()
            if not text:
                continue
            top = min(float(w["top"]) for w in line_words)
            x0 = min(float(w["x0"]) for w in line_words)
            out.append((top, x0, text))
        return out

    def _remove_table_lines(self, text: str, tables: list[ExtractedTable]) -> str:
        """Remove lines that match extracted table rows/headers.

        pdfplumber/PyMuPDF text extraction often includes table cell text as
        linearised lines. Since we append Markdown tables separately, we drop
        those lines here to prevent duplicates while keeping surrounding prose.
        """
        signatures: set[str] = set()
        for table in tables:
            for row in ([table.headers] if table.headers else []) + (table.rows or []):
                cleaned = [str(c).replace("\n", " ").strip() for c in (row or []) if str(c).strip()]
                # Only treat multi-cell rows as table signatures to avoid removing normal sentences.
                if len(cleaned) >= 2:
                    sig = self._normalise_whitespace(" ".join(cleaned))
                    if sig:
                        signatures.add(sig)

        if not signatures:
            return text

        kept: list[str] = []
        for line in text.splitlines():
            norm = self._normalise_whitespace(line)
            if norm and norm in signatures:
                continue
            kept.append(line)

        return "\n".join(kept)

    @staticmethod
    def _append_markdown_tables_end(text: str, tables: list[ExtractedTable]) -> str:
        """Append Markdown tables after body text (PyMuPDF fallback path only)."""
        parts: list[str] = []
        base = text.strip()
        if base:
            parts.append(base)
        for tbl in tables:
            md = TableExtractor.to_markdown(tbl)
            if md.strip():
                parts.append(md.strip())
        if not parts:
            return ""
        return "\n\n".join(parts)

    def _extract_pymupdf(self, pdf_bytes: bytes) -> tuple[str, str, int]:
        import fitz  # PyMuPDF

        try:
            doc: Any = fitz.open(stream=pdf_bytes, filetype="pdf")
        except Exception as exc:
            raise PDFExtractionError(f"PyMuPDF could not open PDF: {exc}") from exc

        try:
            meta = doc.metadata or {}
            title = self._clean_metadata_string(meta.get("title", "")) or "Untitled"
            page_count = doc.page_count

            pages: list[str] = []
            for page in doc:
                page_text = page.get_text("text")
                if page_text.strip():
                    pages.append(page_text.strip())

            return "\n\n".join(pages), title, page_count
        finally:
            doc.close()

    @staticmethod
    def _clean_metadata_string(value: Any) -> str:
        if not value:
            return ""
        if isinstance(value, bytes):
            value = value.decode("utf-8", errors="replace")
        text = str(value).strip()
        text = text.lstrip("﻿").strip()
        return text if text else ""

    @staticmethod
    def _normalise_whitespace(text: str) -> str:
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()
