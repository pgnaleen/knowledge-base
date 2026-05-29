"""GenericSpider: Hot-deployable crawler for DB-configured sources.

This spider crawls all active sources in the database that do NOT have
a dedicated custom Python spider. New sources can be added as DB rows
without any code changes or restart.

To exclude a source from GenericSpider (e.g. when moving to a custom spider),
add its code to CUSTOM_SPIDER_CODES.
"""

from crawlers.base import BaseCrawler

CUSTOM_SPIDER_CODES = {"hdb", "ura", "iras", "mas", "cpf"}


class GenericSpider(BaseCrawler):
    """Crawl all active DB sources except those in CUSTOM_SPIDER_CODES."""

    name = "generic"
    source_name = "generic"
    source_config = {}  # overridden per-request via response.meta

    def start_requests(self):
        """Discover all non-custom sources and generate start requests."""
        from config.database import SessionLocal
        from config.models import Source

        db = SessionLocal()
        try:
            sources = db.query(Source).filter(
                Source.is_active == True,
                ~Source.code.in_(CUSTOM_SPIDER_CODES),
            ).all()

            for source in sources:
                cfg = source.crawl_config or {}
                for url in cfg.get("start_urls", []):
                    js = cfg.get("js_rendering", False)
                    wait_event = cfg.get("playwright_wait_event", "domcontentloaded")

                    # Pass source identity + config via meta for per-request usage
                    meta = {
                        "source_code": source.code,
                        "crawl_config": cfg,
                    }

                    # Attach Playwright if needed
                    if js and not url.lower().endswith(".pdf"):
                        from scrapy_playwright.page import PageMethod
                        meta["playwright"] = True
                        meta["playwright_page_methods"] = [
                            PageMethod("wait_for_load_state", wait_event)
                        ]

                    yield self.make_requests_from_url(url, meta=meta)
        finally:
            db.close()

    def handle_response(self, response):
        """Set per-request source config before delegating to base."""
        # GenericSpider handles multiple sources; switch config per request
        self.source_config = response.meta.get("crawl_config", {})
        self.source_name = response.meta.get("source_code", "unknown")
        # Delegate to base: parse_document, _follow_links, etc.
        yield from super().handle_response(response)
