from abc import abstractmethod
from collections.abc import Generator
from urllib.parse import urlparse

import scrapy
import yaml
from bs4 import BeautifulSoup

from scrapy_playwright.page import PageMethod

from config.logger import get_logger
from crawlers.items import CrawlItem

logger = get_logger(__name__)


def load_sources_config():
    with open("config/sources.yml") as f:
        config = yaml.safe_load(f)
    return config["sources"]


class BaseCrawler(scrapy.Spider):
    source_name: str

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        sources_config = load_sources_config()
        self.source_config = sources_config.get(self.source_name, {})

    @abstractmethod
    def get_start_urls(self) -> list[str]:
        pass

    @abstractmethod
    def parse_document(self, response) -> Generator[CrawlItem, None, None]:
        pass

    def start_requests(self):
        js = self.source_config.get("js_rendering", False)
        for url in self.get_start_urls():
            meta = {}
            if js and not url.lower().endswith(".pdf"):
                meta["playwright"] = True
                meta["playwright_page_methods"] = [
                    PageMethod("wait_for_load_state", "domcontentloaded")
                ]
            yield scrapy.Request(url, callback=self.handle_response, meta=meta)

    def handle_response(self, response):
        yield from self.parse_document(response)

        content_type = response.headers.get("Content-Type", b"").decode("utf-8", errors="ignore")
        if "text/html" in content_type:
            yield from self._follow_links(response)

    def _follow_links(self, response):
        js = self.source_config.get("js_rendering", False)
        allowed = self.source_config.get("allowed_domains", [])

        for href in response.css("a::attr(href)").getall():
            url = response.urljoin(href)
            if self.should_follow_link(url, allowed):
                meta = {}
                parsed_url = urlparse(url)
                if js and not parsed_url.path.lower().endswith(".pdf"):
                    meta["playwright"] = True
                    meta["playwright_page_methods"] = [
                        PageMethod("wait_for_load_state", "domcontentloaded")
                    ]
                yield response.follow(url, callback=self.handle_response, meta=meta)

    @staticmethod
    def _is_pdf_url(url: str) -> bool:
        """Return True if the URL path ends with .pdf (ignores query strings)."""
        return urlparse(url).path.lower().endswith(".pdf")

    def should_follow_link(self, url: str, allowed_domains: list[str]) -> bool:
        skip_exts = {
            ".css",
            ".js",
            ".png",
            ".jpg",
            ".jpeg",
            ".gif",
            ".ico",
            ".svg",
            ".woff",
            ".woff2",
        }
        parsed = urlparse(url)

        if parsed.scheme not in ("http", "https"):
            return False

        if any(parsed.path.lower().endswith(ext) for ext in skip_exts):
            return False

        return any(parsed.netloc.endswith(d) for d in allowed_domains)

    @staticmethod
    def extract_main_content(html: str) -> str:
        soup = BeautifulSoup(html, "lxml")
        for tag in soup.find_all(
            ["script", "style", "nav", "footer", "header", "noscript", "iframe"]
        ):
            tag.decompose()

        for tag in soup.find_all():
            if getattr(tag, "attrs", None) and "class" in tag.attrs:
                classes = " ".join(tag.get("class", [])).lower()
                if any(
                    x in classes for x in ["navbar", "sidebar", "cookie", "banner", "advertisement"]
                ):
                    tag.decompose()

        main = soup.find("main") or soup.find("article") or soup.find(role="main")
        if main:
            return main.get_text(separator=" ", strip=True)

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
