from collections.abc import Generator

from crawlers.base import BaseCrawler
from crawlers.items import CrawlItem


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
                metadata_json={"source": "hdb", "type": "pdf"},
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
                    "source": "hdb",
                    "type": "html",
                    "title": title,
                    "property_type": "hdb",
                },
            )

    def should_follow_link(self, url: str, allowed_domains: list[str]) -> bool:
        if not super().should_follow_link(url, allowed_domains):
            return False

        if any(pattern in url.lower() for pattern in self.HDB_SKIP_PATTERNS):
            return False

        if url.endswith(".pdf"):
            return True

        hdb_paths = {"/buying-a-flat", "/managing-my-home", "/renting-a-flat", "/selling-a-flat"}
        return any(path.lower() in url.lower() for path in hdb_paths)
