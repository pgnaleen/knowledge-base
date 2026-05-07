from collections.abc import Generator

from crawlers.base import BaseCrawler
from crawlers.items import CrawlItem
from config.logger import get_logger

logger = get_logger(__name__)


class URASpider(BaseCrawler):
    name = "ura"
    source_name = "ura"
    custom_settings = {"ROBOTSTXT_OBEY": False}

    URA_SECTIONS = {
        "/Corporate/Property",
        "/Corporate/Guidelines",
        "/Corporate/Media-Room",
        "/property-market-information",
        "/residential",
        "/guidelines",
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

        if self._is_pdf_url(url):
            return True

        url_lower = url.lower()
        if any(skip in url_lower for skip in ["/maps", "/space", "/corporate/data"]):
            return False

        return any(section.lower() in url_lower for section in self.URA_SECTIONS)
