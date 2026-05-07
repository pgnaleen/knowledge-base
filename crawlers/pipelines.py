import hashlib
import re

from scrapy.exceptions import DropItem

from config.database import SessionLocal
from config.logger import get_logger
from config.models import RawDocument, Source
from config.storage import upload_raw_html, upload_raw_pdf
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
            markdown_tables.append(md)

    if not markdown_tables:
        return text

    return text + "\n\n" + "\n\n".join(markdown_tables)


class S3Pipeline:
    def process_item(self, item, spider):
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
                    is_empty = not extracted.text.strip()
                    item["needs_ocr"] = False
                    item["extraction_flags"] = {
                        "warnings": extracted.extraction_warnings,
                        "word_count": extracted.word_count,
                        "is_empty": is_empty,
                        "needs_ocr": False,
                        "content_type": "html",
                        "table_count": len(extracted.tables),
                    }
                    logger.debug("HTML extraction complete", url=item.get("url"), text_length=len(item["raw_text"]), table_count=len(extracted.tables))
                except Exception as e:
                    logger.warning("HTML extraction failed, falling back to empty text", url=item.get("url"), error=str(e))
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
                    is_empty = not extracted.text.strip()
                    is_scanned = any("Scanned PDF" in w for w in extracted.extraction_warnings)
                    item["needs_ocr"] = is_scanned
                    item["extraction_flags"] = {
                        "warnings": extracted.extraction_warnings,
                        "word_count": extracted.word_count,
                        "is_empty": is_empty,
                        "needs_ocr": is_scanned,
                        "content_type": "pdf",
                        "table_count": len(extracted.tables),
                    }
                    logger.debug("PDF extraction complete", url=item.get("url"), text_length=len(item["raw_text"]), table_count=len(extracted.tables), needs_ocr=is_scanned)
                except Exception as e:
                    logger.warning("PDF extraction failed, falling back to empty text", url=item.get("url"), error=str(e))
                    item["raw_text"] = ""
                    item["content_hash"] = hashlib.sha256(b"").hexdigest()
                    item["needs_ocr"] = False
                    item["extraction_flags"] = {"warnings": [str(e)], "word_count": 0, "is_empty": True, "needs_ocr": False, "content_type": "pdf", "table_count": 0}

            return item
        except Exception as e:
            logger.error("S3Pipeline error", url=item.get("url"), error=str(e))
            raise DropItem(f"Failed to process item in S3Pipeline: {e}") from e


class PostgresPipeline:
    def open_spider(self, spider):
        self.db = SessionLocal()

    def close_spider(self, spider):
        self.db.close()

    def process_item(self, item, spider):
        try:
            source = self.db.query(Source).filter_by(code=item["source_code"]).first()
            if not source:
                raise DropItem(f"Source {item['source_code']} not found in DB")

            content_hash = item.get("content_hash", "")

            # Step 1: Cross-URL duplicate content detection
            hash_match = self.db.query(RawDocument).filter_by(content_hash=content_hash).first()
            if hash_match and hash_match.url != item["url"]:
                logger.info(
                    "Skipped duplicate content",
                    url=item["url"],
                    matched_url=hash_match.url,
                    source=item["source_code"],
                )
                return item

            # Step 2: URL-level change detection
            existing = (
                self.db.query(RawDocument).filter_by(source_id=source.id, url=item["url"]).first()
            )

            if existing:
                if existing.content_hash != content_hash:
                    existing.content_hash = content_hash
                    existing.content_type = item.get("content_type")
                    existing.raw_text = item.get("raw_text", "")
                    existing.s3_path = item.get("s3_path") or existing.s3_path
                    existing.needs_ocr = item.get("needs_ocr", False)
                    existing.extraction_flags = item.get("extraction_flags")
                    existing.status = "pending"
                    self.db.commit()
                    logger.info("Updated document", url=item["url"], source=item["source_code"])
                else:
                    logger.info("Skipped unchanged", url=item["url"], source=item["source_code"])
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
                logger.info("Created document", url=item["url"], source=item["source_code"])

            return item
        except DropItem:
            raise
        except Exception as e:
            self.db.rollback()
            logger.error("PostgresPipeline error", url=item.get("url"), error=str(e))
            raise DropItem(f"Failed to persist to DB: {e}") from e
