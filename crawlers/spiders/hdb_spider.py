"""
HDB Crawler - Housing & Development Board (hdb.gov.sg)

Crawls HDB website for:
- Flat eligibility criteria
- Housing schemes and grants
- Resale rules and procedures
- BTO information
- Living in HDB flat guidelines

Uses Playwright for JS-rendered pages.
"""

from urllib.parse import urlparse

import httpx

from config.logger import get_logger
from crawlers.base_crawler import BaseCrawler, CrawlResult

logger = get_logger("hdb_crawler")

# Sections to crawl (URL path prefixes)
HDB_SECTIONS = [
    "/residential/buying-a-flat",
    "/residential/selling-a-flat",
    "/residential/living-in-an-hdb-flat",
    "/residential/renting-a-flat",
    "/residential/financing-a-flat-purchase",
    "/cs/infoweb/residential",
]

# URL patterns to skip
HDB_SKIP_PATTERNS = [
    "/feedback",
    "/contact-us",
    "/sitemap",
    "/search",
    "/login",
    "/e-services",
    "/about-us",
    "/careers",
    "/news",
    "/community",
    "/car-parks",
    "/business",
]


class HDBCrawler(BaseCrawler):
    """Crawler for Housing & Development Board (hdb.gov.sg)."""

    def __init__(self, source_config: dict):
        super().__init__("hdb", source_config)

    def get_urls_to_crawl(self) -> list[str]:
        """Start with seed URLs from config."""
        return list(self.start_urls)

    def should_follow_link(self, url: str) -> bool:
        """Only follow links within HDB residential sections."""
        if not super().should_follow_link(url):
            return False

        parsed = urlparse(url)
        path = parsed.path.lower()

        # Skip non-content patterns
        for skip in HDB_SKIP_PATTERNS:
            if skip in path:
                return False

        # Only follow residential content
        for section in HDB_SECTIONS:
            if path.startswith(section):
                return True

        return False

    def parse_page(self, url: str, response: httpx.Response) -> list[CrawlResult]:
        """Parse an HDB page into CrawlResults."""
        results = []
        content_type = response.headers.get("content-type", "")

        if "application/pdf" in content_type:
            results.append(
                CrawlResult(
                    url=url,
                    content_type="application/pdf",
                    raw_pdf=response.content,
                    title=url.split("/")[-1],
                    metadata={"source": "hdb", "type": "pdf"},
                )
            )
        elif "text/html" in content_type:
            html = response.text
            title = self.extract_title(html)
            text = self.extract_main_content(html)

            # Skip pages with very little content (likely navigation/redirect)
            if len(text) < 100:
                logger.debug("skipping_thin_page", url=url, text_length=len(text))
                return results

            # Determine section from URL path
            parsed = urlparse(url)
            path_parts = parsed.path.strip("/").split("/")
            section = path_parts[1] if len(path_parts) > 1 else "general"

            results.append(
                CrawlResult(
                    url=url,
                    content_type="text/html",
                    raw_html=html,
                    title=title,
                    metadata={
                        "source": "hdb",
                        "section": section,
                        "path": parsed.path,
                        "property_type": "hdb",
                    },
                )
            )

        return results
