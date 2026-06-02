from collections.abc import Generator
from urllib.parse import urlparse

import scrapy
from bs4 import BeautifulSoup

from scrapy_playwright.page import PageMethod

from config.logger import get_logger
from crawlers.items import CrawlItem

logger = get_logger(__name__)


def load_source_config_from_db(source_name: str) -> dict:
    """Load source config from PostgreSQL.

    Used only if source_config is not already set as a class attribute
    (preserves test patterns where TestSpider sets source_config directly).
    """
    
    from config.database import SessionLocal
    from config.models import Source

    db = SessionLocal()
    try:
        logger.info("spider.config_lookup_started", source=source_name)
        source = db.query(Source).filter_by(code=source_name, is_active=True).first()
        if not source:
            logger.error("spider.config_not_found", source=source_name)
            raise RuntimeError(f"Source '{source_name}' not found or inactive in DB")
        crawl_config = source.crawl_config or {}
        logger.info(
            "spider.config_loaded",
            source=source_name,
            source_id=str(source.id),
            base_url=source.base_url,
            start_url_count=len(crawl_config.get("start_urls", [])),
            allowed_domain_count=len(crawl_config.get("allowed_domains", [])),
            crawl_config_keys=sorted(crawl_config.keys()),
        )
        return crawl_config
    finally:
        db.close()

class BaseCrawler(scrapy.Spider):
    source_name: str
    source_config: dict = {}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        logger.info(
            "spider.init_started",
            spider=self.name,
            source=self.source_name,
            has_class_source_config=bool(getattr(self, "source_config", None)),
        )
        # Load from DB only if not already set (preserves test class-attr pattern)
        if not getattr(self, "source_config", None):
            self.source_config = load_source_config_from_db(self.source_name)
        self._apply_db_custom_settings()
        logger.info(
            "spider.initialized",
            spider=self.name,
            source=self.source_name,
            start_url_count=len(self.source_config.get("start_urls", [])),
            js_rendering=self.source_config.get("js_rendering", False),
        )


    def _apply_db_custom_settings(self):
        """Merge crawler DB config into custom_settings. Subclass values win."""
        base = {}
        if (delay := self.source_config.get("crawl_delay")) is not None:
            base["DOWNLOAD_DELAY"] = delay
        base["ROBOTSTXT_OBEY"] = self.source_config.get("respect_robots_txt", True)
        if ua := self.source_config.get("user_agent"):
            base["USER_AGENT"] = ua
        # Merge: subclass custom_settings takes precedence
        self.custom_settings = {**base, **(self.custom_settings or {})}

        logger.info(
            "spider.custom_settings_applied",
            source=self.source_name,
            download_delay=base.get("DOWNLOAD_DELAY"),
            respect_robots_txt=base.get("ROBOTSTXT_OBEY"),
            has_user_agent="USER_AGENT" in base,
            custom_settings_keys=sorted(self.custom_settings.keys()),
        )

    def get_start_urls(self) -> list[str]:
        """Return start URLs for this source. Reads from DB config."""
        start_urls = self.source_config.get("start_urls", [])
        logger.info(
            "spider.start_urls_loaded",
            source=self.source_name,
            start_url_count=len(start_urls),
            start_urls=start_urls,
        )
        return start_urls

    def parse_document(self, response) -> Generator[CrawlItem, None, None]:
        """Parse HTML/PDF response and yield CrawlItem."""
        ct = response.headers.get("Content-Type", b"").decode("utf-8", errors="ignore").lower()
        is_pdf = self._is_pdf_url(response.url) or "application/pdf" in ct
        is_html = "text/html" in ct

        if is_pdf:
            logger.info("spider.document_parsed", source=self.source_name, url=response.url, content_type="pdf")
            yield CrawlItem(
                url=response.url,
                source_code=self.source_name,
                content_type="pdf",
                raw_pdf=response.body,
                content_hash="",
            )
        elif is_html:
            content = self.extract_main_content(response.text)
            min_len = self.source_config.get("min_content_length", 100)
            if len(content) < min_len:
                logger.info(
                    "spider.document_skipped_short_content",
                    source=self.source_name,
                    url=response.url,
                    text_length=len(content),
                    min_content_length=min_len,
                )
                return
            # Optional content keyword filter (e.g. MAS filtering for property-related)
            kw_filter = self.source_config.get("content_keywords_filter")
            if kw_filter and not any(kw in content.lower() for kw in kw_filter):
                logger.info(
                    "spider.document_skipped_keyword_filter",
                    source=self.source_name,
                    url=response.url,
                    keyword_count=len(kw_filter),
                )
                return
            logger.info(
                "spider.document_parsed",
                source=self.source_name,
                url=response.url,
                content_type="html",
                text_length=len(content),
            )
            yield CrawlItem(
                url=response.url,
                source_code=self.source_name,
                content_type="html",
                raw_html=response.body,
                content_hash="",
                content_selectors=self.source_config.get("content_selectors", []),
            )

    def start_requests(self):
        js = self.source_config.get("js_rendering", False)
        wait_event = self.source_config.get("playwright_wait_event", "domcontentloaded")
        start_urls = self.get_start_urls()
        if not start_urls:
            logger.warning("spider.no_start_urls", source=self.source_name, spider=self.name)
        logger.info(
            "spider.start_requests_started",
            source=self.source_name,
            spider=self.name,
            start_url_count=len(start_urls),
            js_rendering=js,
            wait_event=wait_event,
        )
        for url in start_urls:
            meta = {}
            if js and not url.lower().endswith(".pdf"):
                meta["playwright"] = True
                meta["playwright_page_methods"] = [PageMethod("wait_for_load_state", wait_event)]
            logger.info(
                "spider.start_request_scheduled",
                source=self.source_name,
                url=url,
                playwright=meta.get("playwright", False),
            )
            yield scrapy.Request(url, callback=self.handle_response, meta=meta)

    async def start(self):
        logger.info("spider.start_method_entered", source=self.source_name, spider=self.name)
        for request in self.start_requests():
            yield request

    def handle_response(self, response):
        logger.info(
            "spider.response_received",
            source=self.source_name,
            url=response.url,
            status=response.status,
            content_type=response.headers.get("Content-Type", b"").decode("utf-8", errors="ignore"),
        )
        yield from self.parse_document(response)

        content_type = response.headers.get("Content-Type", b"").decode("utf-8", errors="ignore")
        if "text/html" in content_type:
            yield from self._follow_links(response)

    def _follow_links(self, response):
        js = self.source_config.get("js_rendering", False)
        wait_event = self.source_config.get("playwright_wait_event", "domcontentloaded")
        allowed = self.source_config.get("allowed_domains", [])

        discovered_links = response.css("a::attr(href)").getall()
        followed_count = 0
        skipped_count = 0
        for href in discovered_links:
            url = response.urljoin(href)
            if self.should_follow_link(url, allowed):
                meta = {}
                parsed_url = urlparse(url)
                if js and not parsed_url.path.lower().endswith(".pdf"):
                    meta["playwright"] = True
                    meta["playwright_page_methods"] = [PageMethod("wait_for_load_state", wait_event)]
                followed_count += 1
                logger.debug(
                    "spider.follow_link_scheduled",
                    source=self.source_name,
                    from_url=response.url,
                    to_url=url,
                    playwright=meta.get("playwright", False),
                )
                yield response.follow(url, callback=self.handle_response, meta=meta)
            else:
                skipped_count += 1
                logger.debug("spider.follow_link_skipped", source=self.source_name, from_url=response.url, to_url=url)
        logger.info(
            "spider.links_processed",
            source=self.source_name,
            url=response.url,
            discovered_count=len(discovered_links),
            followed_count=followed_count,
            skipped_count=skipped_count,
        )

    @staticmethod
    def _is_pdf_url(url: str) -> bool:
        """Return True if the URL path ends with .pdf (ignores query strings)."""
        return urlparse(url).path.lower().endswith(".pdf")

    def should_follow_link(self, url: str, allowed_domains: list[str]) -> bool:
        skip_exts = {
            ".css", ".js", ".png", ".jpg", ".jpeg", ".gif", ".ico", ".svg", ".woff", ".woff2",
        }
        parsed = urlparse(url)

        if parsed.scheme not in ("http", "https"):
            return False
        if any(parsed.path.lower().endswith(ext) for ext in skip_exts):
            return False
        if not any(parsed.netloc.endswith(d) for d in allowed_domains):
            return False

        # Block specific subdomains from DB config
        for sub in self.source_config.get("blocked_subdomains", []):
            if parsed.netloc == sub or parsed.netloc.endswith("." + sub):
                return False

        # PDFs always pass path checks
        if self._is_pdf_url(url):
            return True

        path_lower = parsed.path.lower()

        # Skip specific path prefixes/keywords
        for skip_prefix in self.source_config.get("skip_prefixes", []):
            if path_lower.startswith(skip_prefix.lower()) or skip_prefix.lower() in path_lower:
                return False

        # If target_prefixes is set, restrict crawl scope to those paths only
        target_prefixes = self.source_config.get("target_prefixes", [])
        if target_prefixes:
            return any(path_lower.startswith(p.lower()) for p in target_prefixes)

        return True

    def extract_main_content(self, html: str) -> str:
        """Extract main content from HTML, using content_selectors from config if available."""
        soup = BeautifulSoup(html, "lxml")

        # Decompose noise tags
        for tag in soup.find_all(["script", "style", "nav", "footer", "header", "noscript", "iframe"]):
            tag.decompose()

        # Decompose elements with noise class names
        for tag in soup.find_all():
            if getattr(tag, "attrs", None) and "class" in tag.attrs:
                classes = " ".join(tag.get("class", [])).lower()
                if any(x in classes for x in ["navbar", "sidebar", "cookie", "banner", "advertisement"]):
                    tag.decompose()

        # Try content_selectors from DB config first
        for selector in self.source_config.get("content_selectors", []):
            if el := soup.select_one(selector):
                return el.get_text(separator=" ", strip=True)

        # Fallback: try semantic main tags
        main = soup.find("main") or soup.find("article") or soup.find(role="main")
        if main:
            return main.get_text(separator=" ", strip=True)

        # Last resort: body text
        return soup.body.get_text(separator=" ", strip=True) if soup.body else ""

    @staticmethod
    def extract_title(html: str) -> str:
        soup = BeautifulSoup(html, "lxml")
        title_tag = soup.find("title")
        if title_tag:
            return title_tag.get_text(strip=True)
        h1 = soup.find("h1")
        if h1:
            return h1.get_text(strip=True)
        return ""
