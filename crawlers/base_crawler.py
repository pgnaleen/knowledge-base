"""
Base Crawler Framework

Abstract base class for all government source crawlers.
Provides: rate limiting, retry logic, content hashing, S3 storage,
metadata capture, robots.txt compliance, and JS rendering via Playwright.
"""

import contextlib
import hashlib
import time
import urllib.robotparser
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from config.logger import get_logger
from config.settings import settings
from config.storage import upload_raw_html, upload_raw_pdf

logger = get_logger("base_crawler")


class CrawlResult:
    """Result from crawling a single page."""

    def __init__(
        self,
        url: str,
        content_type: str,
        raw_html: str | None = None,
        raw_pdf: bytes | None = None,
        title: str | None = None,
        last_modified: datetime | None = None,
        metadata: dict[str, Any] | None = None,
    ):
        self.url = url
        self.content_type = content_type
        self.raw_html = raw_html
        self.raw_pdf = raw_pdf
        self.title = title
        self.last_modified = last_modified
        self.metadata = metadata or {}
        self.content_hash = self._compute_hash()
        self.crawled_at = datetime.utcnow()

    def _compute_hash(self) -> str:
        """SHA-256 hash of the content for change detection."""
        content = self.raw_html or ""
        if self.raw_pdf:
            content = self.raw_pdf.hex()
        return hashlib.sha256(content.encode("utf-8")).hexdigest()

    @property
    def url_hash(self) -> str:
        """Short hash of the URL for file naming."""
        return hashlib.md5(self.url.encode()).hexdigest()[:12]


class _PlaywrightResponse:
    """Minimal httpx.Response-compatible wrapper for Playwright-rendered pages.

    Spiders access response.text, response.headers, response.content —
    this wrapper provides those so parse_page() needs no changes.
    """

    def __init__(self, html: str, url: str, status_code: int = 200):
        self._text = html
        self._content = html.encode("utf-8")
        self.status_code = status_code
        self.headers: dict[str, str] = {"content-type": "text/html; charset=utf-8"}
        self.url = url

    @property
    def text(self) -> str:
        return self._text

    @property
    def content(self) -> bytes:
        return self._content

    def raise_for_status(self) -> None:
        pass


class BaseCrawler(ABC):
    """Abstract base class for all government source crawlers."""

    def __init__(self, source_code: str, source_config: dict[str, Any]):
        self.source_code = source_code
        self.config = source_config
        self.base_url = source_config["base_url"]
        self.start_urls = source_config["start_urls"]
        self.allowed_domains = source_config["allowed_domains"]
        self.crawl_delay = source_config.get("crawl_delay", settings.crawl_delay)
        self.max_retries = settings.crawl_max_retries
        self.visited_urls: set[str] = set()
        self.results: list[CrawlResult] = []
        self.errors: list[dict] = []
        self._last_request_time = 0.0

        self.client = httpx.Client(
            headers={
                "User-Agent": settings.crawl_user_agent,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.5",
            },
            follow_redirects=True,
            timeout=30.0,
        )

        # Robots.txt: one parser per allowed domain
        self._robots_parsers: dict[str, urllib.robotparser.RobotFileParser | None] = {}
        if settings.crawl_respect_robots_txt:
            self._prefetch_robots_txt()

        # Playwright: only if this source needs JS rendering
        self._use_js_rendering: bool = source_config.get("js_rendering", False)
        self._playwright_ctx = None
        self._browser = None
        if self._use_js_rendering:
            self._init_playwright()

        logger.info(
            "crawler_initialized",
            source=source_code,
            base_url=self.base_url,
            start_urls=len(self.start_urls),
            js_rendering=self._use_js_rendering,
        )

    # ── Robots.txt ────────────────────────────────────────────────────────

    def _prefetch_robots_txt(self) -> None:
        """Fetch and cache robots.txt for each allowed domain."""
        for domain in self.allowed_domains:
            robots_url = f"https://{domain}/robots.txt"
            parser = urllib.robotparser.RobotFileParser()
            parser.set_url(robots_url)
            try:
                parser.read()
                self._robots_parsers[domain] = parser
                logger.info("robots_txt_loaded", domain=domain)
            except Exception as e:
                logger.warning(
                    "robots_txt_fetch_failed",
                    domain=domain,
                    error=str(e),
                )
                self._robots_parsers[domain] = None

    def _is_robots_allowed(self, url: str) -> bool:
        """Check if URL is allowed by robots.txt. Defaults to True on failure."""
        if not settings.crawl_respect_robots_txt:
            return True
        parsed = urlparse(url)
        parser = self._robots_parsers.get(parsed.netloc)
        if parser is None:
            return True
        allowed = parser.can_fetch(settings.crawl_user_agent, url)
        if not allowed:
            logger.info("robots_txt_disallowed", url=url)
        return allowed

    # ── Playwright JS rendering ───────────────────────────────────────────

    def _init_playwright(self) -> None:
        """Launch a Playwright Chromium browser for JS-rendered pages."""
        try:
            from playwright.sync_api import sync_playwright

            self._playwright_ctx = sync_playwright().start()
            self._browser = self._playwright_ctx.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-dev-shm-usage"],
            )
            logger.info("playwright_browser_launched", source=self.source_code)
        except ImportError:
            logger.error(
                "playwright_not_installed",
                message="Run: pip install playwright && playwright install chromium",
            )
            self._use_js_rendering = False
        except Exception as e:
            logger.error("playwright_launch_failed", error=str(e))
            self._use_js_rendering = False

    def fetch_page_js(self, url: str) -> _PlaywrightResponse | None:
        """Fetch a JS-rendered page using Playwright."""
        if self._browser is None:
            logger.warning("playwright_not_available", url=url)
            return None

        for attempt in range(1, self.max_retries + 1):
            self._rate_limit()
            page = None
            try:
                page = self._browser.new_page(
                    user_agent=settings.crawl_user_agent,
                    extra_http_headers={"Accept-Language": "en-US,en;q=0.5"},
                )
                response = page.goto(url, wait_until="load", timeout=30_000)
                page.wait_for_timeout(3000)
                status = response.status if response else 200

                if status in (403, 404):
                    logger.warning("js_fetch_client_error", url=url, status=status)
                    return None

                page.wait_for_load_state("domcontentloaded")
                html = page.content()
                logger.debug("js_page_fetched", url=url, status=status)
                return _PlaywrightResponse(html=html, url=url, status_code=status)
            except Exception as e:
                logger.warning("js_fetch_error", url=url, error=str(e), attempt=attempt)
                if attempt < self.max_retries:
                    time.sleep(2**attempt)
            finally:
                if page is not None:
                    with contextlib.suppress(Exception):
                        page.close()

        self.errors.append({"url": url, "error": "js_max_retries_exceeded"})
        return None

    # ── Core fetching ─────────────────────────────────────────────────────

    def _rate_limit(self):
        """Enforce rate limiting between requests."""
        elapsed = time.time() - self._last_request_time
        if elapsed < self.crawl_delay:
            sleep_time = self.crawl_delay - elapsed
            time.sleep(sleep_time)
        self._last_request_time = time.time()

    def _is_allowed_url(self, url: str) -> bool:
        """Check if URL is within allowed domains."""
        parsed = urlparse(url)
        return parsed.netloc in self.allowed_domains

    def _normalize_url(self, url: str, base_url: str) -> str:
        """Normalize a URL relative to a base URL."""
        absolute = urljoin(base_url, url)
        parsed = urlparse(absolute)
        clean = f"{parsed.scheme}://{parsed.netloc}{parsed.path.rstrip('/')}"
        if parsed.query:
            clean += f"?{parsed.query}"
        return clean

    def fetch_page(self, url: str) -> httpx.Response | _PlaywrightResponse | None:
        """Fetch a page. Routes to Playwright for JS-rendered sources."""
        if self._use_js_rendering and not url.lower().endswith(".pdf"):
            return self.fetch_page_js(url)

        for attempt in range(1, self.max_retries + 1):
            self._rate_limit()
            try:
                response = self.client.get(url)
                response.raise_for_status()
                logger.debug("page_fetched", url=url, status=response.status_code)
                return response
            except httpx.HTTPStatusError as e:
                logger.warning(
                    "http_error",
                    url=url,
                    status=e.response.status_code,
                    attempt=attempt,
                )
                if e.response.status_code in (403, 404):
                    return None
            except httpx.RequestError as e:
                logger.warning(
                    "request_error",
                    url=url,
                    error=str(e),
                    attempt=attempt,
                )

            if attempt < self.max_retries:
                backoff = 2**attempt
                logger.info("retrying", url=url, backoff=backoff)
                time.sleep(backoff)

        self.errors.append({"url": url, "error": "max_retries_exceeded"})
        return None

    # ── HTML parsing helpers ──────────────────────────────────────────────

    def extract_links(self, html: str, base_url: str) -> list[str]:
        """Extract all links from HTML that match allowed domains."""
        soup = BeautifulSoup(html, "lxml")
        links = []
        for a_tag in soup.find_all("a", href=True):
            href = a_tag["href"]
            absolute = self._normalize_url(href, base_url)
            if self._is_allowed_url(absolute) and absolute not in self.visited_urls:
                links.append(absolute)
        return links

    def extract_title(self, html: str) -> str | None:
        """Extract page title from HTML."""
        soup = BeautifulSoup(html, "lxml")
        title_tag = soup.find("title")
        if title_tag:
            return title_tag.get_text(strip=True)
        h1_tag = soup.find("h1")
        if h1_tag:
            return h1_tag.get_text(strip=True)
        return None

    def extract_main_content(self, html: str) -> str:
        """Extract main content area, removing nav/footer/sidebar."""
        soup = BeautifulSoup(html, "lxml")

        for tag in soup.find_all(
            ["nav", "footer", "header", "script", "style", "noscript", "iframe"]
        ):
            tag.decompose()

        for selector in [
            "[class*='nav']",
            "[class*='footer']",
            "[class*='sidebar']",
            "[class*='cookie']",
            "[class*='banner']",
            "[class*='menu']",
            "[id*='nav']",
            "[id*='footer']",
            "[id*='sidebar']",
        ]:
            for tag in soup.select(selector):
                tag.decompose()

        main = soup.find("main") or soup.find("article") or soup.find(
            "div", {"role": "main"}
        )
        if main:
            return main.get_text(separator="\n", strip=True)

        body = soup.find("body")
        if body:
            return body.get_text(separator="\n", strip=True)

        return soup.get_text(separator="\n", strip=True)

    # ── Storage ───────────────────────────────────────────────────────────

    def store_result(self, result: CrawlResult):
        """Store crawl result to S3 and add to results list."""
        try:
            if result.raw_html:
                result.metadata["s3_html_key"] = upload_raw_html(
                    self.source_code, result.url_hash, result.raw_html
                )
            if result.raw_pdf:
                result.metadata["s3_pdf_key"] = upload_raw_pdf(
                    self.source_code, result.url_hash, result.raw_pdf
                )
            self.results.append(result)
            logger.info(
                "result_stored",
                source=self.source_code,
                url=result.url,
                content_type=result.content_type,
                hash=result.content_hash[:12],
            )
        except Exception as e:
            logger.error("store_failed", url=result.url, error=str(e))
            self.errors.append({"url": result.url, "error": f"store_failed: {e}"})

    # ── Abstract interface ────────────────────────────────────────────────

    @abstractmethod
    def get_urls_to_crawl(self) -> list[str]:
        """Return list of URLs to crawl. Override in subclass."""
        ...

    @abstractmethod
    def parse_page(self, url: str, response: httpx.Response) -> list[CrawlResult]:
        """Parse a fetched page into CrawlResults. Override in subclass."""
        ...

    def should_follow_link(self, url: str) -> bool:
        """Determine if a discovered link should be followed."""
        skip_extensions = (".jpg", ".jpeg", ".png", ".gif", ".svg", ".css", ".js", ".ico")
        parsed = urlparse(url)
        if any(parsed.path.lower().endswith(ext) for ext in skip_extensions):
            return False
        return True

    # ── Crawl loop ────────────────────────────────────────────────────────

    def crawl(self) -> list[CrawlResult]:
        """Execute the crawl. Returns list of CrawlResults."""
        logger.info("crawl_started", source=self.source_code)
        start_time = time.time()

        urls_to_crawl = self.get_urls_to_crawl()
        queue = list(urls_to_crawl)

        while queue:
            url = queue.pop(0)
            if url in self.visited_urls:
                continue
            self.visited_urls.add(url)

            if not self._is_robots_allowed(url):
                continue

            response = self.fetch_page(url)
            if not response:
                continue

            results = self.parse_page(url, response)
            for result in results:
                self.store_result(result)

            content_type = response.headers.get("content-type", "")
            if "text/html" in content_type:
                new_links = self.extract_links(response.text, url)
                for link in new_links:
                    if self.should_follow_link(link) and link not in self.visited_urls:
                        queue.append(link)

        elapsed = time.time() - start_time
        logger.info(
            "crawl_completed",
            source=self.source_code,
            pages_crawled=len(self.visited_urls),
            results=len(self.results),
            errors=len(self.errors),
            duration_seconds=round(elapsed, 1),
        )
        return self.results

    def close(self):
        """Clean up resources."""
        self.client.close()
        if self._browser is not None:
            with contextlib.suppress(Exception):
                self._browser.close()
        if self._playwright_ctx is not None:
            with contextlib.suppress(Exception):
                self._playwright_ctx.stop()
