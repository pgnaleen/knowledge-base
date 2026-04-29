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

        warnings: list[str] = []
        text = ""
        title = "Untitled"
        page_count = 0
        used_fallback = False
        tables: list[ExtractedTable] = []

        try:
            text, title, page_count = self._extract_pdfplumber(pdf_bytes)
            tables = _table_extractor.extract_from_pdf(pdf_bytes)
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

        if used_fallback or not text.strip():
            if not used_fallback:
                warnings.append("pdfplumber returned no text, using PyMuPDF fallback")
                used_fallback = True
            try:
                fitz_text, fitz_title, fitz_page_count = self._extract_pymupdf(pdf_bytes)
                if fitz_text.strip():
                    text = fitz_text
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

        normalised = self._normalise_whitespace(text)
        word_count = len(normalised.split()) if normalised.strip() else 0

        if word_count < _SCANNED_WORD_THRESHOLD:
            warnings.append(
                f"Scanned PDF detected (only {word_count} words extracted) "
                "— flagged for OCR queue"
            )
            logger.warning(
                "pdf_extractor.scanned_pdf",
                word_count=word_count,
                source_url=source_url,
                source_name=source_name,
            )

        logger.debug(
            "pdf_extractor.extracted",
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

    def _extract_pdfplumber(self, pdf_bytes: bytes) -> tuple[str, str, int]:
        import pdfplumber

        try:
            with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
                meta = pdf.metadata or {}
                title = self._clean_metadata_string(meta.get("Title", "")) or "Untitled"
                page_count = len(pdf.pages)

                pages: list[str] = []
                for page in pdf.pages:
                    page_text = page.extract_text() or ""
                    if page_text.strip():
                        pages.append(page_text.strip())

                return "\n\n".join(pages), title, page_count
        except Exception as exc:
            if "PDF" in type(exc).__name__ or "invalid" in str(exc).lower():
                raise PDFExtractionError(f"Not a valid PDF: {exc}") from exc
            raise

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
