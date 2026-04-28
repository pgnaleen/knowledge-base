"""
PDF Extractor - Extracts clean text from PDF files using pdfplumber.

Handles government PDFs which are often scanned or have complex layouts.
Falls back to page-by-page extraction with table handling.
"""

import io
from dataclasses import dataclass, field

from config.logger import get_logger
from processors.table_extractor import TableExtractor

logger = get_logger("pdf_extractor")


@dataclass
class ExtractedPDF:
    """Result of PDF extraction."""
    title: str
    plain_text: str
    page_count: int = 0
    word_count: int = 0
    pages: list[dict] = field(default_factory=list)  # [{page_num, text}]


class PDFExtractor:
    """Extract clean text from PDF binary content using pdfplumber."""

    def extract(self, pdf_bytes: bytes, filename: str = "") -> ExtractedPDF:
        """
        Extract text from a PDF file's raw bytes.

        Args:
            pdf_bytes: Raw PDF binary content.
            filename:  Original filename (used for title and logging).

        Returns:
            ExtractedPDF with plain text and per-page breakdown.
        """
        try:
            import pdfplumber
        except ImportError:
            logger.error("pdfplumber_not_installed")
            return ExtractedPDF(title=filename, plain_text="", page_count=0)

        title = filename.replace(".pdf", "").replace("-", " ").replace("_", " ").title()
        pages_data = []
        all_text_parts = []

        try:
            with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
                page_count = len(pdf.pages)

                for i, page in enumerate(pdf.pages, start=1):
                    # Extract plain text
                    text = page.extract_text(x_tolerance=3, y_tolerance=3) or ""

                    # Extract tables and format with shared TableExtractor
                    tables = page.extract_tables()
                    if tables:
                        table_texts = [TableExtractor.format_markdown_table(t) for t in tables]
                        valid_tables = [t for t in table_texts if t.strip()]
                        if valid_tables:
                            text = text + "\n\n" + "\n\n".join(valid_tables)

                    text = text.strip()
                    if text:
                        pages_data.append({"page_num": i, "text": text})
                        all_text_parts.append(f"[Page {i}]\n{text}")

            plain_text = "\n\n".join(all_text_parts)
            word_count = len(plain_text.split())

            logger.debug(
                "pdf_extracted",
                filename=filename,
                page_count=page_count,
                word_count=word_count,
            )

            return ExtractedPDF(
                title=title,
                plain_text=plain_text,
                page_count=page_count,
                word_count=word_count,
                pages=pages_data,
            )

        except Exception as e:
            logger.warning("pdf_extraction_failed", filename=filename, error=str(e))
            return ExtractedPDF(title=title, plain_text="", page_count=0)
