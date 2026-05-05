from collections.abc import Generator

from crawlers.base import BaseCrawler
from crawlers.items import CrawlItem


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
        if response.url.endswith(".pdf"):
            yield CrawlItem(
                url=response.url,
                source_code=self.source_name,
                content_type="pdf",
                raw_pdf=response.body,
                content_hash="",
                metadata_json={"source": "mas", "type": "pdf"},
            )
        else:
            content = self.extract_main_content(response.text)
            if len(content) < 100:
                return

            if not self._is_property_related(content):
                return

            title = self.extract_title(response.text)
            yield CrawlItem(
                url=response.url,
                source_code=self.source_name,
                content_type="html",
                raw_html=response.body,

                content_hash="",
                metadata_json={
                    "source": "mas",
                    "type": "html",
                    "title": title,
                    "property_related": True,
                },
            )

    def _is_property_related(self, text: str) -> bool:
        text_lower = text.lower()
        return any(keyword in text_lower for keyword in self.PROPERTY_KEYWORDS)

    def should_follow_link(self, url: str, allowed_domains: list[str]) -> bool:
        if not super().should_follow_link(url, allowed_domains):
            return False

        if url.endswith(".pdf"):
            return True

        url_lower = url.lower()
        return not any(
            skip in url_lower for skip in ["/careers", "/media", "/about", "/corporate-actions"]
        )
