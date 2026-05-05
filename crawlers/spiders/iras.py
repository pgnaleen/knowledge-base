from collections.abc import Generator

from bs4 import BeautifulSoup

from crawlers.base import BaseCrawler
from crawlers.items import CrawlItem


class IRASSpider(BaseCrawler):
    name = "iras"
    source_name = "iras"
    custom_settings = {"ROBOTSTXT_OBEY": False}

    TAX_KEYWORDS = {"stamp duty", "property tax", "absd", "bsd", "ssd"}

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
                metadata_json={"source": "iras", "type": "pdf"},
            )
        else:
            content = self.extract_main_content(response.text)
            if len(content) < 100:
                return

            title = self.extract_title(response.text)

            tax_type = "stamp_duty" if "stamp" in response.url.lower() else "property_tax"
            tax_types = [kw for kw in self.TAX_KEYWORDS if kw in content.lower()]

            tables = self._extract_tables(response.text)

            yield CrawlItem(
                url=response.url,
                source_code=self.source_name,
                content_type="html",
                raw_html=response.body,

                content_hash="",
                metadata_json={
                    "source": "iras",
                    "type": "html",
                    "title": title,
                    "tax_type": tax_type,
                    "tax_types": tax_types,
                    "has_rate_tables": len(tables) > 0,
                    "tables": tables,
                },
            )

    def _extract_tables(self, html: str) -> list[dict]:
        soup = BeautifulSoup(html, "lxml")
        tables = []
        for table in soup.find_all("table"):
            headers = []
            rows = []
            for th in table.find_all("th"):
                headers.append(th.get_text(strip=True))
            for tr in table.find_all("tr")[1:]:
                row = [td.get_text(strip=True) for td in tr.find_all("td")]
                if row:
                    rows.append(row)
            if headers or rows:
                tables.append({"headers": headers, "rows": rows})
        return tables

    def should_follow_link(self, url: str, allowed_domains: list[str]) -> bool:
        if not super().should_follow_link(url, allowed_domains):
            return False

        if url.endswith(".pdf"):
            return True

        iras_paths = {"/taxes/stamp-duty", "/taxes/property-tax"}
        return any(path.lower() in url.lower() for path in iras_paths)
