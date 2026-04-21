"""
IRAS Crawler - Inland Revenue Authority of Singapore (iras.gov.sg)

Crawls IRAS website for:
- Stamp duty information (BSD, ABSD, SSD)
- Property tax rules
- Tax rate tables and schedules
- Tax reliefs and exemptions

Extracts tax rate tables as structured data.
"""

from urllib.parse import urlparse

import httpx

from config.logger import get_logger
from crawlers.base_crawler import BaseCrawler, CrawlResult

logger = get_logger("iras_crawler")

IRAS_SECTIONS = [
    "/taxes/stamp-duty",
    "/taxes/property-tax",
    "/taxes/stamp-duty-for-property",
    "/quick-links/buyers-sellers",
]

IRAS_SKIP_PATTERNS = [
    "/feedback",
    "/contact-us",
    "/sitemap",
    "/search",
    "/login",
    "/e-services",
    "/careers",
    "/news-events",
    "/about-us",
    "/irashome",
]


class IRASCrawler(BaseCrawler):
    """Crawler for Inland Revenue Authority of Singapore (iras.gov.sg)."""

    def __init__(self, source_config: dict):
        super().__init__("iras", source_config)

    def get_urls_to_crawl(self) -> list[str]:
        return list(self.start_urls)

    def should_follow_link(self, url: str) -> bool:
        if not super().should_follow_link(url):
            return False

        parsed = urlparse(url)
        path = parsed.path.lower()

        for skip in IRAS_SKIP_PATTERNS:
            if skip in path:
                return False

        for section in IRAS_SECTIONS:
            if section in path:
                return True

        if path.endswith(".pdf"):
            return True

        return False

    def _extract_tables(self, html: str) -> list[dict]:
        """Extract tax rate tables as structured data."""
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, "lxml")
        tables = []

        for table_tag in soup.find_all("table"):
            rows = []
            headers = []

            # Extract headers
            header_row = table_tag.find("thead")
            if header_row:
                for th in header_row.find_all(["th", "td"]):
                    headers.append(th.get_text(strip=True))

            # Extract body rows
            tbody = table_tag.find("tbody") or table_tag
            for tr in tbody.find_all("tr"):
                cells = [td.get_text(strip=True) for td in tr.find_all(["td", "th"])]
                if cells and any(cells):  # Skip empty rows
                    if not headers and len(rows) == 0:
                        headers = cells  # First row as headers if no thead
                    else:
                        rows.append(cells)

            if rows:
                tables.append({"headers": headers, "rows": rows})

        return tables

    def parse_page(self, url: str, response: httpx.Response) -> list[CrawlResult]:
        results = []
        content_type = response.headers.get("content-type", "")

        if "application/pdf" in content_type or url.lower().endswith(".pdf"):
            results.append(
                CrawlResult(
                    url=url,
                    content_type="application/pdf",
                    raw_pdf=response.content,
                    title=url.split("/")[-1].replace(".pdf", ""),
                    metadata={"source": "iras", "type": "pdf", "category": "tax_guide"},
                )
            )
        elif "text/html" in content_type:
            html = response.text
            title = self.extract_title(html)
            text = self.extract_main_content(html)

            if len(text) < 100:
                return results

            # Extract tax rate tables
            tables = self._extract_tables(html)

            parsed = urlparse(url)
            path = parsed.path.lower()

            # Classify content type
            category = "general"
            if "stamp-duty" in path:
                category = "stamp_duty"
            elif "property-tax" in path:
                category = "property_tax"

            # Determine applicable tax types
            tax_types = []
            text_lower = text.lower()
            if "buyer" in text_lower or "bsd" in text_lower:
                tax_types.append("BSD")
            if "additional" in text_lower or "absd" in text_lower:
                tax_types.append("ABSD")
            if "seller" in text_lower or "ssd" in text_lower:
                tax_types.append("SSD")

            results.append(
                CrawlResult(
                    url=url,
                    content_type="text/html",
                    raw_html=html,
                    title=title,
                    metadata={
                        "source": "iras",
                        "section": category,
                        "path": parsed.path,
                        "property_type": "all",
                        "tax_types": tax_types,
                        "tables": tables,
                        "has_rate_tables": len(tables) > 0,
                    },
                )
            )

        return results
