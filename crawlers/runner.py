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


def run_crawlers(source_codes: list[str] | None = None, job_type: str = "full"):
    codes = source_codes or list(SPIDER_MAP.keys())
    process = CrawlerProcess(get_project_settings())
    db = SessionLocal()

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

            process.crawl(SPIDER_MAP[code])

        process.start()
        logger.info("All crawlers completed")
    finally:
        db.close()


if __name__ == "__main__":
    import sys

    source = sys.argv[1] if len(sys.argv) > 1 else None
    run_crawlers([source] if source else None)
