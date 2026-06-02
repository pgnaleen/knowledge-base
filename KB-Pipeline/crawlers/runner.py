import uuid
from datetime import datetime

from scrapy import signals
from scrapy.crawler import CrawlerRunner
from scrapy.utils.project import get_project_settings
from scrapy.utils.reactor import install_reactor

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
CUSTOM_SPIDER_CODES = set(SPIDER_MAP.keys())


def _apply_source_scrapy_settings(settings, source_code: str, crawl_config: dict) -> None:
    source_settings = {
        "ROBOTSTXT_OBEY": crawl_config.get("respect_robots_txt", True),
    }
    if (delay := crawl_config.get("crawl_delay")) is not None:
        source_settings["DOWNLOAD_DELAY"] = delay
    if user_agent := crawl_config.get("user_agent"):
        source_settings["USER_AGENT"] = user_agent

    for key, value in source_settings.items():
        settings.set(key, value, priority="spider")

    logger.info(
        "crawl.source_scrapy_settings_applied",
        source=source_code,
        scrapy_settings=source_settings,
    )


def run_crawlers(source_codes: list[str] | None = None, job_type: str = "full", scrapy_settings: dict | None = None) -> list[dict]:
    # If no codes provided, run all custom spiders + generic spider (discovers non-custom sources)
    if source_codes is None:
        codes = list(SPIDER_MAP.keys())
        run_generic = True
    else:
        codes = source_codes
        run_generic = False

    logger.info(
        "crawl.runner_started",
        sources=codes,
        job_type=job_type,
        run_generic=run_generic,
        scrapy_settings=scrapy_settings or {},
    )

    settings = get_project_settings()
    if scrapy_settings:
        settings.update(scrapy_settings)
        logger.info("crawl.scrapy_settings_applied", scrapy_settings=scrapy_settings)
    install_reactor(settings.get("TWISTED_REACTOR"))
    from twisted.internet import reactor

    runner = CrawlerRunner(settings)
    db = SessionLocal()
    job_map: dict[str, uuid.UUID] = {}
    summary: list[dict] = []

    logger.info("crawl.runner_initialized", crawler_count=len(runner.crawlers))

    # Capture stats via spider_closed signal
    spider_results: dict[str, dict] = {}

    def _on_spider_closed(spider, reason):
        stats = spider.crawler.stats.get_stats() if spider.crawler.stats else {}
        spider_results[spider.name] = {"stats": stats, "finish_reason": reason}
        logger.info(
            "crawl.spider_closed",
            spider=spider.name,
            reason=reason,
            request_count=stats.get("scheduler/enqueued", 0),
            response_count=stats.get("downloader/response_count", 0),
            exception_count=stats.get("downloader/exception_count", 0),
            item_scraped_count=stats.get("item_scraped_count", 0),
        )

    def _on_request_scheduled(request, spider):
        logger.info("crawl.request_scheduled", spider=spider.name, url=request.url)

    def _on_request_dropped(request, spider):
        logger.warning("crawl.request_dropped", spider=spider.name, url=request.url)

    def _on_response_received(response, request, spider):
        logger.info(
            "crawl.response_received",
            spider=spider.name,
            url=response.url,
            status=response.status,
            request_url=request.url,
        )

    def _on_spider_error(failure, response, spider):
        logger.error(
            "crawl.spider_error",
            spider=spider.name,
            url=response.url if response else None,
            error=failure.getErrorMessage(),
            traceback=failure.getTraceback(),
        )

    try:
        for code in codes:
            logger.info("crawl.source_lookup_started", source=code)
            source = db.query(Source).filter_by(code=code).first()
            if not source:
                logger.error("crawl.source_not_found", source=code)
                continue
            crawl_config = source.crawl_config or {}
            logger.info(
                "crawl.source_loaded",
                source=code,
                source_id=str(source.id),
                is_active=source.is_active,
                start_url_count=len(crawl_config.get("start_urls", [])),
                allowed_domain_count=len(crawl_config.get("allowed_domains", [])),
                crawl_config_keys=sorted(crawl_config.keys()),
            )

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

            _apply_source_scrapy_settings(settings, code, crawl_config)
            logger.info(
                "crawl.spider_schedule_started",
                source=code,
                spider=SPIDER_MAP[code],
                job_id=str(job.id),
            )
            deferred = runner.crawl(SPIDER_MAP[code])
            deferred.addErrback(
                lambda failure, source_code=code, spider_name=SPIDER_MAP[code]: logger.error(
                    "crawl.spider_failed",
                    source=source_code,
                    spider=spider_name,
                    error=failure.getErrorMessage(),
                    traceback=failure.getTraceback(),
                )
            )
            logger.info("crawl.spider_scheduled", source=code, spider=SPIDER_MAP[code])

        # If running all sources, also run generic spider to cover any non-custom sources
        if run_generic:
            logger.info("crawl.generic_spider_enabled")
            deferred = runner.crawl("generic")
            deferred.addErrback(
                lambda failure: logger.error(
                    "crawl.spider_failed",
                    source="generic",
                    spider="generic",
                    error=failure.getErrorMessage(),
                    traceback=failure.getTraceback(),
                )
            )
            logger.info("crawl.generic_spider_scheduled")

        # Connect signal to every crawler before start() — crawlers are still in the set here
        for crawler in runner.crawlers:
            crawler.signals.connect(_on_spider_closed, signal=signals.spider_closed)
            crawler.signals.connect(_on_request_scheduled, signal=signals.request_scheduled)
            crawler.signals.connect(_on_request_dropped, signal=signals.request_dropped)
            crawler.signals.connect(_on_response_received, signal=signals.response_received)
            crawler.signals.connect(_on_spider_error, signal=signals.spider_error)
            logger.info("crawl.spider_signal_connected", spider=crawler.spider.name)

        # Use CrawlerRunner.join() which returns a Deferred that fires when all crawlers complete
        logger.info("crawl.reactor_starting", scheduled_spiders=len(runner.crawlers))
        d = runner.join()
        d.addErrback(
            lambda failure: logger.error(
                "crawl.runner_join_failed",
                error=failure.getErrorMessage(),
                traceback=failure.getTraceback(),
            )
        )
        d.addBoth(lambda _: reactor.stop())
        reactor.run()
        logger.info("crawl.all_completed", result_count=len(spider_results))

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
