from collections.abc import Generator

from crawlers.base import BaseCrawler
from crawlers.items import CrawlItem


class URASpider(BaseCrawler):
    name = "ura"
    source_name = "ura"
    custom_settings = {"ROBOTSTXT_OBEY": False}

    URA_SECTIONS = {
        "/Corporate/Property",
        "/Corporate/Guidelines",
        "/Corporate/Media-Room",
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
                metadata_json={"source": "ura", "type": "pdf"},
            )
        else:
            content = self.extract_main_content(response.text)
            if len(content) < 100:
                return

            title = self.extract_title(response.text)
            yield CrawlItem(
                url=response.url,
                source_code=self.source_name,
                content_type="html",
                raw_html=response.body,

                content_hash="",
                metadata_json={
                    "source": "ura",
                    "type": "html",
                    "title": title,
                    "property_type": "private",
                },
            )

    def should_follow_link(self, url: str, allowed_domains: list[str]) -> bool:
        if not super().should_follow_link(url, allowed_domains):
            return False

        url_lower = url.lower()
        if any(skip in url_lower for skip in ["/maps", "/space", "/corporate/data"]):
            return False

        if url.endswith(".pdf"):
            return True

        return any(section.lower() in url_lower for section in self.URA_SECTIONS)
