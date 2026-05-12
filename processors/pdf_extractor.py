"""PDF extraction module - pdfplumber primary, PyMuPDF fallback."""

import io
import re
from typing import Any

from config.logger import get_logger
from processors.models import ExtractedDocument, ExtractedTable
from processors.table_extractor import TableExtractor

_table_extractor = TableExtractor()
logger = get_logger("pdf_extractor")

_SCANNED_WORD_THRESHOLD = 20
_SCANNED_PAGE_RATIO_THRESHOLD = 0.8
_LARGE_IMAGE_COVERAGE_THRESHOLD = 0.85


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
            logger.warning(
                "pdf.pymupdf_fallback",
                source_url=source_url,
                source_name=source_name,
                reason=type(exc).__name__,
            )

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

        is_scanned, scan_signals = self._detect_scanned_pdf(pdf_bytes)
        if is_scanned:
            warnings.append(
                "Scanned PDF detected (image-only pages dominate, "
                f"text_pages={scan_signals['text_pages']}/{scan_signals['page_count']}, "
                f"image_pages={scan_signals['image_pages']}/{scan_signals['page_count']}) "
                "- flagged for OCR queue"
            )
            logger.warning(
                "pdf.ocr_detected",
                word_count=word_count,
                pages=page_count,
                text_pages=scan_signals["text_pages"],
                image_pages=scan_signals["image_pages"],
                scanned_like_pages=scan_signals["scanned_like_pages"],
                source_url=source_url,
                source_name=source_name,
            )
        elif word_count < _SCANNED_WORD_THRESHOLD:
            warnings.append(
                f"Low extracted text ({word_count} words) but text layer is present; "
                "not auto-flagged as scanned PDF"
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

    def _detect_scanned_pdf(self, pdf_bytes: bytes) -> tuple[bool, dict[str, int]]:
        """Detect scanned PDFs by checking page-level text and image layers.

        Heuristic:
        - A page is scanned-like when it has no text layer and has image content.
        - A document is scanned when image-only pages dominate (>= 80%), and
          there is at least one image page.
        """
        import fitz  # PyMuPDF

        empty_signals = {
            "page_count": 0,
            "text_pages": 0,
            "image_pages": 0,
            "scanned_like_pages": 0,
        }

        try:
            doc: Any = fitz.open(stream=pdf_bytes, filetype="pdf")
        except Exception:
            return False, empty_signals

        try:
            page_count = doc.page_count
            text_pages = 0
            image_pages = 0
            scanned_like_pages = 0

            for page in doc:
                blocks = page.get_text("dict").get("blocks", [])
                page_has_text = False
                image_area = 0.0
                page_area = float(page.rect.width * page.rect.height) or 1.0

                for block in blocks:
                    block_type = block.get("type")
                    if block_type == 0:
                        for line in block.get("lines", []):
                            for span in line.get("spans", []):
                                if (span.get("text") or "").strip():
                                    page_has_text = True
                                    break
                            if page_has_text:
                                break
                        if page_has_text:
                            break
                    elif block_type == 1:
                        bbox = block.get("bbox") or [0, 0, 0, 0]
                        width = max(0.0, float(bbox[2]) - float(bbox[0]))
                        height = max(0.0, float(bbox[3]) - float(bbox[1]))
                        image_area += width * height

                page_has_image = image_area > 0 or len(page.get_images(full=True)) > 0
                page_has_large_image = (image_area / page_area) >= _LARGE_IMAGE_COVERAGE_THRESHOLD

                if page_has_text:
                    text_pages += 1
                if page_has_image:
                    image_pages += 1
                if (not page_has_text) and (page_has_image or page_has_large_image):
                    scanned_like_pages += 1

            signals = {
                "page_count": page_count,
                "text_pages": text_pages,
                "image_pages": image_pages,
                "scanned_like_pages": scanned_like_pages,
            }

            if page_count == 0 or image_pages == 0:
                return False, signals

            scanned_ratio = scanned_like_pages / page_count
            is_scanned = scanned_ratio >= _SCANNED_PAGE_RATIO_THRESHOLD
            return is_scanned, signals
        finally:
            doc.close()

    @staticmethod
    def _clean_metadata_string(value: Any) -> str:
        if not value:
            return ""
        if isinstance(value, bytes):
            value = value.decode("utf-8", errors="replace")
        text = str(value).strip()
        text = text.lstrip("\ufeff").strip()
        return text if text else ""

    @staticmethod
    def _normalise_whitespace(text: str) -> str:
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()
