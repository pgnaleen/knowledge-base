import uuid
from datetime import datetime

from scrapy import signals
from scrapy.crawler import CrawlerProcess
from scrapy.utils.project import get_project_settings

from config.database import SessionLocal
from config.logger import get_logger
from config.models import CrawlJob, Source

logger = get_logger(__name__)

SPIDER_MAP = {
    "hdb": "hdb",
    "ura": "ura",
    "iras": "iras",
    "mas": "mas",
    "cpf": "cpf",
}


def run_crawlers(source_codes: list[str] | None = None, job_type: str = "full", scrapy_settings: dict | None = None) -> list[dict]:
    codes = source_codes or list(SPIDER_MAP.keys())
    settings = get_project_settings()
    if scrapy_settings:
        settings.update(scrapy_settings)
    process = CrawlerProcess(settings)
    db = SessionLocal()
    job_map: dict[str, uuid.UUID] = {}
    summary: list[dict] = []

    # Capture stats via spider_closed signal — process.crawlers is empty after start() returns
    # in Scrapy 2.x because crawlers are removed from the set as they complete.
    spider_results: dict[str, dict] = {}

    def _on_spider_closed(spider, reason):
        stats = spider.crawler.stats.get_stats() if spider.crawler.stats else {}
        spider_results[spider.name] = {"stats": stats, "finish_reason": reason}

    try:
        for code in codes:
            source = db.query(Source).filter_by(code=code).first()
            if not source:
                logger.error("crawl.source_not_found", source=code)
                continue

            logger.info("crawl.started", source=code)

            job = CrawlJob(
                id=uuid.uuid4(),
                source_id=source.id,
                job_type=job_type,
                status="running",
                started_at=datetime.now(),
            )
            db.add(job)
            db.commit()
            logger.info("crawl.job_created", source=code, job_id=str(job.id))
            job_map[SPIDER_MAP[code]] = job.id

            process.crawl(SPIDER_MAP[code])

        # Connect signal to every crawler before start() — crawlers are still in the set here
        for crawler in process.crawlers:
            crawler.signals.connect(_on_spider_closed, signal=signals.spider_closed)

        process.start()
        logger.info("crawl.all_completed")

        # Update jobs using stats captured by the spider_closed signal handler
        for spider_name, result in spider_results.items():
            if spider_name not in job_map:
                continue
            stats = result["stats"]
            finish_reason = result["finish_reason"]
            status = "completed" if finish_reason and finish_reason != "shutdown" else "failed"

            job = db.query(CrawlJob).filter_by(id=job_map[spider_name]).first()
            if job:
                job.status = status
                job.completed_at = datetime.now()
                job.pages_found = stats.get("item_scraped_count", 0)
                job.pages_new = stats.get("pages_new", 0)
                job.pages_changed = stats.get("pages_changed", 0)
                job.pages_deleted = stats.get("pages_deleted", 0)
                job.pages_errored = stats.get("log_count/ERROR", 0)
                db.commit()
                summary.append({
                    "source":        spider_name,
                    "status":        status,
                    "pages_found":   job.pages_found,
                    "pages_new":     job.pages_new,
                    "pages_changed": job.pages_changed,
                    "pages_deleted": job.pages_deleted,
                    "pages_errored": job.pages_errored,
                })
                logger.info(
                    "crawl.finished",
                    source=spider_name,
                    job_id=str(job.id),
                    status=job.status,
                    pages_found=job.pages_found,
                    pages_new=job.pages_new,
                    pages_changed=job.pages_changed,
                    pages_deleted=stats.get("pages_deleted", 0),
                    pages_unchanged=stats.get("pages_unchanged", 0),
                    pages_skipped_dup=stats.get("pages_skipped_dup", 0),
                    pages_needs_ocr=stats.get("pages_needs_ocr", 0),
                    pages_pymupdf_fallback=stats.get("pages_pymupdf_fallback", 0),
                    pages_dropped=stats.get("item_dropped_count", 0),
                    pages_errored=job.pages_errored,
                )
    except Exception as e:
        # Mark any in-progress jobs as failed
        logger.error("crawl.process_failed", error=str(e))
        for job_id in job_map.values():
            job = db.query(CrawlJob).filter_by(id=job_id).first()
            if job and job.status == "running":
                job.status = "failed"
                job.error_message = str(e)
                job.completed_at = datetime.now()
                db.commit()
        raise
    finally:
        db.close()

    return summary


if __name__ == "__main__":
    import sys
    from run_pipeline import _parse_scrapy_settings

    scrapy_s, remaining = _parse_scrapy_settings(sys.argv[1:])
    source = remaining[0] if remaining else None
    run_crawlers([source] if source else None, scrapy_settings=scrapy_s or None)
