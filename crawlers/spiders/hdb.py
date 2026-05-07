from collections.abc import Generator

from crawlers.base import BaseCrawler
from crawlers.items import CrawlItem
from config.logger import get_logger

logger = get_logger(__name__)


class HDBSpider(BaseCrawler):
    name = "hdb"
    source_name = "hdb"
    custom_settings = {
        "ROBOTSTXT_OBEY": True,
        "USER_AGENT": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    }

    HDB_SKIP_PATTERNS = {
        "/feedback",
        "/careers",
        "/eservices",
        "/news",
        "/publications",
        "/corporate",
        "/my-nice-home-gallery",
        "/home-gallery",
        "/virtual-tour",
    }

    def get_start_urls(self) -> list[str]:
        return self.source_config.get("start_urls", [])

    def parse_document(self, response) -> Generator[CrawlItem, None, None]:
        content_type_header = response.headers.get("Content-Type", b"").decode("utf-8", errors="ignore").lower()
        is_pdf = self._is_pdf_url(response.url) or "application/pdf" in content_type_header

        is_html = "text/html" in content_type_header

        if is_pdf:
            yield CrawlItem(
                url=response.url,
                source_code=self.source_name,
                content_type="pdf",
                raw_pdf=response.body,
                content_hash="",
            )
        elif is_html:
            content = self.extract_main_content(response.text)
            if len(content) < 100:
                return

            yield CrawlItem(
                url=response.url,
                source_code=self.source_name,
                content_type="html",
                raw_html=response.body,
                content_hash="",
            )

    def should_follow_link(self, url: str, allowed_domains: list[str]) -> bool:
        if not super().should_follow_link(url, allowed_domains):
            return False

        if "assets.hdb.gov.sg" in url.lower():
            return False

        if self._is_pdf_url(url):
            return True

        if any(pattern in url.lower() for pattern in self.HDB_SKIP_PATTERNS):
            return False

        hdb_paths = {
            "/buying-a-flat",
            "/selling-a-flat",
            "/renting-a-flat",
            "/managing-my-home",
            "/living-in-an-hdb-flat",
        }
        return any(path.lower() in url.lower() for path in hdb_paths)
