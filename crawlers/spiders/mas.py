from collections.abc import Generator

from crawlers.base import BaseCrawler
from crawlers.items import CrawlItem
from config.logger import get_logger

logger = get_logger(__name__)


class MASSpider(BaseCrawler):
    name = "mas"
    source_name = "mas"
    custom_settings = {"ROBOTSTXT_OBEY": True, "DOWNLOAD_DELAY": 3.0}

    PROPERTY_KEYWORDS = {
        "property",
        "mortgage",
        "loan-to-value",
        "ltv",
        "tdsr",
        "total debt servicing",
        "housing loan",
        "residential property",
        "real estate",
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

            if not self._is_property_related(content):
                return

            yield CrawlItem(
                url=response.url,
                source_code=self.source_name,
                content_type="html",
                raw_html=response.body,
                content_hash="",
            )
        else:
            logger.debug("Skipping non-HTML non-PDF response", url=response.url, content_type=content_type_header)

    def _is_property_related(self, text: str) -> bool:
        text_lower = text.lower()
        return any(keyword in text_lower for keyword in self.PROPERTY_KEYWORDS)

    def should_follow_link(self, url: str, allowed_domains: list[str]) -> bool:
        if not super().should_follow_link(url, allowed_domains):
            return False

        if self._is_pdf_url(url):
            return True

        url_lower = url.lower()
        return not any(
            skip in url_lower for skip in [
                "/careers", "/media", "/about", "/corporate-actions",
                "/statistics", "/data-and-statistics", "/publications/statistics",
                "/investor-alert", "/complaints", "/contact",
            ]
        )
