import hashlib

from scrapy.exceptions import DropItem

from config.database import SessionLocal
from config.logger import get_logger
from config.models import RawDocument, Source
from config.storage import upload_raw_html, upload_raw_pdf

logger = get_logger(__name__)


class S3Pipeline:
    def process_item(self, item, spider):
        try:
            url_hash = hashlib.md5(item["url"].encode()).hexdigest()[:12]

            if item.get("raw_html"):
                # Compute SHA-256 hash of raw HTML bytes for change detection
                item["content_hash"] = hashlib.sha256(item["raw_html"]).hexdigest()
                key = upload_raw_html(
                    item["source_code"],
                    url_hash,
                    item["raw_html"].decode("utf-8", errors="replace"),
                )
                item["s3_html_key"] = key

            if item.get("raw_pdf"):
                # Compute SHA-256 hash of raw PDF bytes for change detection
                item["content_hash"] = hashlib.sha256(item["raw_pdf"]).hexdigest()
                key = upload_raw_pdf(item["source_code"], url_hash, item["raw_pdf"])
                item["s3_pdf_key"] = key

            return item
        except Exception as e:
            logger.error("S3Pipeline error", url=item.get("url"), error=str(e))
            raise DropItem(f"Failed to upload to S3: {e}") from e


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

            existing = (
                self.db.query(RawDocument).filter_by(source_id=source.id, url=item["url"]).first()
            )

            if existing:
                if existing.content_hash != item.get("content_hash", ""):
                    # Content changed — update S3 keys and reset status for re-processing
                    existing.content_hash = item.get("content_hash", "")
                    existing.s3_html_key = item.get("s3_html_key") or existing.s3_html_key
                    existing.s3_pdf_key = item.get("s3_pdf_key") or existing.s3_pdf_key
                    existing.status = "pending"
                    existing.metadata_json = item.get("metadata_json", {})
                    self.db.commit()
                    logger.info("Updated document", url=item["url"], source=item["source_code"])
                else:
                    logger.info("Skipped unchanged", url=item["url"], source=item["source_code"])
            else:
                # New document — raw_text is NOT set here (populated by Week 2 processors)
                doc = RawDocument(
                    source_id=source.id,
                    url=item["url"],
                    content_hash=item.get("content_hash", ""),
                    s3_html_key=item.get("s3_html_key"),
                    s3_pdf_key=item.get("s3_pdf_key"),
                    status="pending",
                    metadata_json=item.get("metadata_json", {}),
                )
                self.db.add(doc)
                self.db.commit()
                logger.info("Created document", url=item["url"], source=item["source_code"])

            return item
        except DropItem:
            raise
        except Exception as e:
            logger.error("PostgresPipeline error", url=item.get("url"), error=str(e))
            raise DropItem(f"Failed to persist to DB: {e}") from e
