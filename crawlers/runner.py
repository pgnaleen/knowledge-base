"""
Crawler Runner

Orchestrates crawling for all or specific government sources.
Loads source configs from YAML and persists results to database.
"""

import uuid
from datetime import datetime
from pathlib import Path

import yaml
from sqlalchemy.orm import Session

from config.database import SessionLocal, init_db
from config.logger import get_logger
from config.models import CrawlJob, RawDocument, Source
from crawlers.spiders.cpf_spider import CPFCrawler
from crawlers.spiders.hdb_spider import HDBCrawler
from crawlers.spiders.iras_spider import IRASCrawler
from crawlers.spiders.mas_spider import MASCrawler
from crawlers.spiders.ura_spider import URACrawler

logger = get_logger("crawler_runner")

CRAWLER_MAP = {
    "hdb": HDBCrawler,
    "ura": URACrawler,
    "iras": IRASCrawler,
    "mas": MASCrawler,
    "cpf": CPFCrawler,
}


def load_sources_config() -> dict:
    """Load source definitions from YAML config."""
    config_path = Path(__file__).parent.parent / "config" / "sources.yml"
    with open(config_path) as f:
        return yaml.safe_load(f)["sources"]


def ensure_source_exists(db: Session, code: str, config: dict) -> Source:
    """Ensure the source record exists in database."""
    source = db.query(Source).filter(Source.code == code).first()
    if not source:
        source = Source(
            id=uuid.uuid4(),
            name=config["name"],
            code=code,
            base_url=config["base_url"],
            crawl_config=config,
        )
        db.add(source)
        db.commit()
        db.refresh(source)
        logger.info("source_created", code=code, name=config["name"])
    return source


def persist_results(db: Session, source: Source, results: list, job: CrawlJob):
    """Persist crawl results to database."""
    new_count = 0
    changed_count = 0

    for result in results:
        existing = (
            db.query(RawDocument)
            .filter(RawDocument.source_id == source.id, RawDocument.url == result.url)
            .first()
        )

        if existing:
            if existing.content_hash != result.content_hash:
                # Content changed
                existing.content_hash = result.content_hash
                existing.raw_html = result.raw_html
                existing.raw_text = (
                    result.metadata.get("extracted_text") if result.raw_html else None
                )
                existing.title = result.title
                existing.crawled_at = result.crawled_at
                existing.s3_html_key = result.metadata.get("s3_html_key")
                existing.s3_pdf_key = result.metadata.get("s3_pdf_key")
                existing.metadata_json = result.metadata
                existing.status = "pending"
                changed_count += 1
        else:
            doc = RawDocument(
                id=uuid.uuid4(),
                source_id=source.id,
                url=result.url,
                content_hash=result.content_hash,
                content_type=result.content_type,
                title=result.title,
                raw_html=result.raw_html,
                s3_html_key=result.metadata.get("s3_html_key"),
                s3_pdf_key=result.metadata.get("s3_pdf_key"),
                crawled_at=result.crawled_at,
                last_modified=result.last_modified,
                metadata_json=result.metadata,
                status="pending",
            )
            db.add(doc)
            new_count += 1

    db.commit()

    job.pages_found = len(results)
    job.pages_new = new_count
    job.pages_changed = changed_count
    db.commit()

    logger.info(
        "results_persisted",
        source=source.code,
        total=len(results),
        new=new_count,
        changed=changed_count,
    )


def run_crawler(source_code: str, job_type: str = "full") -> dict:
    """Run a crawler for a specific source.

    Args:
        source_code: One of 'hdb', 'ura', 'iras', 'mas', 'cpf'
        job_type: 'full' or 'incremental'

    Returns:
        dict with crawl statistics
    """
    if source_code not in CRAWLER_MAP:
        raise ValueError(f"Unknown source: {source_code}. Valid: {list(CRAWLER_MAP.keys())}")

    sources_config = load_sources_config()
    source_config = sources_config[source_code]
    crawler_class = CRAWLER_MAP[source_code]

    db = SessionLocal()
    try:
        # Ensure DB tables exist
        init_db()

        # Ensure source record exists
        source = ensure_source_exists(db, source_code, source_config)

        # Create crawl job record
        job = CrawlJob(
            id=uuid.uuid4(),
            source_id=source.id,
            job_type=job_type,
            status="running",
        )
        db.add(job)
        db.commit()

        # Run crawler
        crawler = crawler_class(source_config)
        try:
            results = crawler.crawl()

            # Persist results
            persist_results(db, source, results, job)

            # Update job status
            job.status = "completed"
            job.completed_at = datetime.utcnow()
            job.pages_errored = len(crawler.errors)
            if crawler.errors:
                job.metadata_json = {"errors": crawler.errors}
            db.commit()

            stats = {
                "source": source_code,
                "status": "completed",
                "pages_crawled": len(crawler.visited_urls),
                "results_stored": len(results),
                "errors": len(crawler.errors),
                "new_pages": job.pages_new,
                "changed_pages": job.pages_changed,
            }
            logger.info("crawl_job_completed", **stats)
            return stats

        finally:
            crawler.close()

    except Exception as e:
        logger.error("crawl_job_failed", source=source_code, error=str(e))
        if "job" in locals():
            job.status = "failed"
            job.error_message = str(e)
            job.completed_at = datetime.utcnow()
            db.commit()
        raise
    finally:
        db.close()


def run_all_crawlers(job_type: str = "full") -> list[dict]:
    """Run crawlers for all sources sequentially."""
    results = []
    for source_code in CRAWLER_MAP:
        try:
            stats = run_crawler(source_code, job_type)
            results.append(stats)
        except Exception as e:
            logger.error("crawler_failed", source=source_code, error=str(e))
            results.append({"source": source_code, "status": "failed", "error": str(e)})
    return results


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1:
        source = sys.argv[1]
        print(f"Running crawler for: {source}")
        result = run_crawler(source)
    else:
        print("Running all crawlers...")
        result = run_all_crawlers()

    print(f"\nResults: {result}")
