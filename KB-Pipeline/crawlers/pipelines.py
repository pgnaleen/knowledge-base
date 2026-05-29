import hashlib
import re

from scrapy.exceptions import DropItem

from config.database import SessionLocal
from config.logger import get_logger
from config.models import RawDocument, Source
from config.storage import delete_s3_object, upload_raw_html, upload_raw_pdf
from processors.html_extractor import HTMLExtractor
from processors.pdf_extractor import PDFExtractor
from processors.table_extractor import TableExtractor

logger = get_logger(__name__)


def _normalize_text(text: str) -> str:
    """Collapse all whitespace to single spaces, strip NUL bytes, and strip edges — used for content hashing."""
    if not text:
        return ""
    return re.sub(r"\s+", " ", text).replace("\x00", "").strip()


def _sanitize_text(text: str) -> str:
    """Strip NUL bytes that PostgreSQL TEXT columns reject."""
    return text.replace("\x00", "") if text else ""


def _merge_tables_into_text(text: str, tables: list) -> str:
    """Append tables as markdown to the end of extracted text.

    Tables are converted to GitHub-flavored markdown and appended after the main text
    to preserve structure for downstream chunking and embedding.
    """
    if not tables:
        return text

    table_extractor = TableExtractor()
    markdown_tables = []
    for table in tables:
        md = table_extractor.to_markdown(table)
        if md:
            # Wrap table in structural markers
            markdown_tables.append(f"[TABLE_START]\n{md}\n[TABLE_END]")

    if not markdown_tables:
        return text

    return text + "\n\n" + "\n\n".join(markdown_tables)


class S3Pipeline:
    @classmethod
    def from_crawler(cls, crawler):
        return cls(stats=crawler.stats)

    def __init__(self, stats=None):
        self.stats = stats

    def process_item(self, item):
        try:
            url_hash = hashlib.md5(item["url"].encode()).hexdigest()[:12]
            html_extractor = HTMLExtractor()
            pdf_extractor = PDFExtractor()

            if item.get("raw_html"):
                key = upload_raw_html(
                    item["source_code"],
                    url_hash,
                    item["raw_html"].decode("utf-8", errors="replace"),
                )
                item["s3_path"] = key

                try:
                    extracted = html_extractor.extract(
                        item["raw_html"],
                        source_url=item.get("url", ""),
                        source_name=item.get("source_code", ""),
                    )
                    text_with_tables = _merge_tables_into_text(extracted.text, extracted.tables)
                    item["raw_text"] = _sanitize_text(text_with_tables.strip())
                    item["content_hash"] = hashlib.sha256(_normalize_text(extracted.text).encode("utf-8")).hexdigest()
                    logger.info("hash.created", url=item.get("url"), source=item["source_code"], hash=item["content_hash"][:12])
                    is_empty = not extracted.text.strip()
                    item["needs_ocr"] = False
                    item["extraction_flags"] = {
                        "warnings": extracted.extraction_warnings,
                        "word_count": extracted.word_count,
                        "is_empty": is_empty,
                        "needs_ocr": False,
                        "content_type": "html",
                        "table_count": len(extracted.tables),
                        "title": extracted.title,
                        "headings": extracted.headings,
                    }
                    logger.info("page.html_extracted", url=item.get("url"), source=item["source_code"], hash=item["content_hash"][:12], text_length=len(item["raw_text"]), table_count=len(extracted.tables))
                except Exception as e:
                    logger.warning("html.extract_failed", url=item.get("url"), source=item["source_code"], error=str(e))
                    item["raw_text"] = ""
                    item["content_hash"] = hashlib.sha256(b"").hexdigest()
                    item["needs_ocr"] = False
                    item["extraction_flags"] = {"warnings": [str(e)], "word_count": 0, "is_empty": True, "needs_ocr": False, "content_type": "html", "table_count": 0}

            if item.get("raw_pdf"):
                key = upload_raw_pdf(item["source_code"], url_hash, item["raw_pdf"])
                item["s3_path"] = key

                try:
                    extracted = pdf_extractor.extract(
                        item["raw_pdf"],
                        source_url=item.get("url", ""),
                        source_name=item.get("source_code", ""),
                    )
                    text_with_tables = _merge_tables_into_text(extracted.text, extracted.tables)
                    item["raw_text"] = _sanitize_text(text_with_tables.strip())
                    item["content_hash"] = hashlib.sha256(_normalize_text(extracted.text).encode("utf-8")).hexdigest()
                    logger.info("hash.created", url=item.get("url"), source=item["source_code"], hash=item["content_hash"][:12])
                    is_empty = not extracted.text.strip()
                    extraction_errors = [w for w in extracted.extraction_warnings if w.startswith("ERROR:")]
                    extraction_warnings = [w for w in extracted.extraction_warnings if not w.startswith("ERROR:")]
                    is_scanned = any("Scanned PDF" in w for w in extracted.extraction_warnings)
                    item["needs_ocr"] = is_scanned
                    item["extraction_flags"] = {
                        "warnings": extraction_warnings,
                        "errors": extraction_errors,
                        "word_count": extracted.word_count,
                        "is_empty": is_empty,
                        "needs_ocr": is_scanned,
                        "content_type": "pdf",
                        "table_count": len(extracted.tables),
                        "title": extracted.title,
                        "headings": extracted.headings,
                    }
                    logger.info("page.pdf_extracted", url=item.get("url"), source=item["source_code"], hash=item["content_hash"][:12], text_length=len(item["raw_text"]), table_count=len(extracted.tables), needs_ocr=is_scanned)
                    is_fallback = any(
                        "PyMuPDF" in w or "fallback" in w
                        for w in extracted.extraction_warnings
                    )
                    item["extraction_flags"]["used_fallback"] = is_fallback
                    if is_fallback and self.stats:
                        self.stats.inc_value("pages_pymupdf_fallback")
                    if item.get("needs_ocr") and self.stats:
                        self.stats.inc_value("pages_needs_ocr")
                except Exception as e:
                    logger.warning("pdf.extract_failed", url=item.get("url"), source=item["source_code"], error=str(e))
                    item["raw_text"] = ""
                    item["content_hash"] = hashlib.sha256(b"").hexdigest()
                    item["needs_ocr"] = False
                    item["extraction_flags"] = {
                        "warnings": [],
                        "errors": [f"ERROR: pdf.extract_failed: {str(e)}"],
                        "word_count": 0,
                        "is_empty": True,
                        "needs_ocr": False,
                        "content_type": "pdf",
                        "table_count": 0,
                    }

            return item
        except Exception as e:
            logger.error("s3.error", url=item.get("url"), error=str(e))
            raise DropItem(f"Failed to process item in S3Pipeline: {e}") from e


class PostgresPipeline:
    @classmethod
    def from_crawler(cls, crawler):
        return cls(stats=crawler.stats)

    def __init__(self, stats=None):
        self.stats = stats
        self.db = None
        self.seen_urls = set()
        self.source_id = None

    def open_spider(self):
        self.db = SessionLocal()

    def close_spider(self):
        if self.db and self.source_id:
            pages_deleted = self._mark_deleted_pages()
            if self.stats:
                self.stats.inc_value("pages_deleted", pages_deleted)
        self.db.close()

    def process_item(self, item):
        try:
            source = self.db.query(Source).filter_by(code=item["source_code"]).first()
            if not source:
                raise DropItem(f"Source {item['source_code']} not found in DB")

            self.source_id = source.id
            self.seen_urls.add(item["url"])

            content_hash = item.get("content_hash", "")
            _EMPTY_HASH = hashlib.sha256(b"").hexdigest()

            # Step 1: Cross-URL duplicate content detection
            # Skip if content is empty — empty pages share the same hash by definition
            # and must not be treated as duplicates of each other.
            hash_match = (
                self.db.query(RawDocument).filter_by(content_hash=content_hash).first()
                if content_hash and content_hash != _EMPTY_HASH
                else None
            )
            if hash_match and hash_match.url != item["url"]:
                logger.warning(
                    "page.skipped_dup",
                    url=item["url"],
                    matched_url=hash_match.url,
                    source=item["source_code"],
                    hash=content_hash[:12],
                )
                s3_path = item.get("s3_path")
                if s3_path:
                    try:
                        delete_s3_object(s3_path)
                        logger.info("s3.dup_deleted", url=item["url"], s3_path=s3_path, source=item["source_code"])
                    except Exception as e:
                        logger.warning("s3.dup_delete_failed", url=item["url"], s3_path=s3_path, error=str(e))
                if self.stats:
                    self.stats.inc_value("pages_skipped_dup")
                return item

            # Step 2: URL-level change detection
            existing = (
                self.db.query(RawDocument).filter_by(source_id=source.id, url=item["url"]).first()
            )

            if existing:
                if existing.content_hash != content_hash:
                    old_hash = existing.content_hash
                    existing.content_hash = content_hash
                    existing.content_type = item.get("content_type")
                    existing.raw_text = item.get("raw_text", "")
                    existing.s3_path = item.get("s3_path") or existing.s3_path
                    existing.needs_ocr = item.get("needs_ocr", False)
                    existing.extraction_flags = item.get("extraction_flags")
                    existing.status = "pending"
                    self.db.commit()
                    if self.stats:
                        self.stats.inc_value("pages_changed")
                    logger.info("page.updated", url=item["url"], source=item["source_code"], old_hash=old_hash[:12], new_hash=content_hash[:12])
                else:
                    logger.info("page.unchanged", url=item["url"], source=item["source_code"], hash=content_hash[:12])
                    existing.last_seen_at = func.now()  # Explicitly update liveness timestamp
                    self.db.commit()
                    if self.stats:
                        self.stats.inc_value("pages_unchanged")
            else:
                doc = RawDocument(
                    source_id=source.id,
                    url=item["url"],
                    content_hash=content_hash,
                    content_type=item.get("content_type"),
                    raw_text=item.get("raw_text", ""),
                    s3_path=item.get("s3_path"),
                    needs_ocr=item.get("needs_ocr", False),
                    extraction_flags=item.get("extraction_flags"),
                    status="pending",
                )
                self.db.add(doc)
                self.db.commit()
                if self.stats:
                    self.stats.inc_value("pages_new")
                word_count = len(item.get("raw_text", "").split())
                logger.info("page.created", url=item["url"], source=item["source_code"], hash=content_hash[:12], word_count=word_count)

            return item
        except DropItem:
            raise
        except Exception as e:
            self.db.rollback()
            logger.error("db.error", url=item.get("url"), source=item.get("source_code"), error=str(e))
            raise DropItem(f"Failed to persist to DB: {e}") from e

    def _mark_deleted_pages(self) -> int:
        """Mark pages that were in DB but not seen in this crawl as deleted. Returns count of deleted pages."""
        deleted_docs = self.db.query(RawDocument).filter(
            RawDocument.source_id == self.source_id,
            RawDocument.status != "deleted",
            RawDocument.url.notin_(self.seen_urls),
        ).all()

        deleted_count = 0
        for doc in deleted_docs:
            doc.status = "deleted"
            deleted_count += 1
            logger.info("page.deleted", url=doc.url, source_id=self.source_id)

        if deleted_count > 0:
            self.db.commit()

        return deleted_count
