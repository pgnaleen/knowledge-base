import uuid
from datetime import UTC, datetime

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


def run_crawlers(source_codes: list[str] | None = None, job_type: str = "full", scrapy_settings: dict | None = None):
    codes = source_codes or list(SPIDER_MAP.keys())
    settings = get_project_settings()
    if scrapy_settings:
        settings.update(scrapy_settings)
    process = CrawlerProcess(settings)
    db = SessionLocal()
    job_map: dict[str, uuid.UUID] = {}

    try:
        for code in codes:
            source = db.query(Source).filter_by(code=code).first()
            if not source:
                logger.error(f"Source {code} not found in database")
                continue

            job = CrawlJob(
                id=uuid.uuid4(),
                source_id=source.id,
                job_type=job_type,
                status="running",
                started_at=datetime.now(UTC),
            )
            db.add(job)
            db.commit()
            logger.info(f"Created crawl job {job.id} for source {code}")
            job_map[SPIDER_MAP[code]] = job.id

            process.crawl(SPIDER_MAP[code])

        process.start()
        logger.info("All crawlers completed")

        # Update jobs with stats from completed crawlers
        for crawler in process.crawlers:
            spider_name = crawler.spider.name if crawler.spider else None
            if not spider_name or spider_name not in job_map:
                continue
            stats = crawler.stats.get_stats() if crawler.stats else {}
            finish_reason = stats.get("finish_reason", "")
            status = "completed" if finish_reason and finish_reason != "shutdown" else "failed"

            job = db.query(CrawlJob).filter_by(id=job_map[spider_name]).first()
            if job:
                job.status = status
                job.completed_at = datetime.now(UTC)
                job.pages_found = stats.get("item_scraped_count", 0)
                job.pages_new = stats.get("pages_new", 0)
                job.pages_changed = stats.get("pages_changed", 0)
                job.pages_errored = stats.get("log_count/ERROR", 0)
                db.commit()
                logger.info(
                    "Updated crawl job",
                    job_id=job.id,
                    status=job.status,
                    pages_found=job.pages_found,
                    pages_new=job.pages_new,
                    pages_changed=job.pages_changed,
                    pages_errored=job.pages_errored,
                )
    except Exception as e:
        # Mark any in-progress jobs as failed
        logger.error(f"Crawler process failed: {e}")
        for job_id in job_map.values():
            job = db.query(CrawlJob).filter_by(id=job_id).first()
            if job and job.status == "running":
                job.status = "failed"
                job.error_message = str(e)
                job.completed_at = datetime.now(UTC)
                db.commit()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    import sys
    from run_pipeline import _parse_scrapy_settings

    scrapy_s, remaining = _parse_scrapy_settings(sys.argv[1:])
    source = remaining[0] if remaining else None
    run_crawlers([source] if source else None, scrapy_settings=scrapy_s or None)
