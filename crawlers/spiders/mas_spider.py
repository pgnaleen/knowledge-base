"""
MAS Crawler - Monetary Authority of Singapore (mas.gov.sg)

Crawls MAS website for:
- Property loan regulations (LTV limits)
- Total Debt Servicing Ratio (TDSR) rules
- Mortgage guidelines
- Relevant circulars and notices

Handles PDF-heavy content (circulars, notices, guidelines).
"""

from urllib.parse import urlparse

import httpx

from config.logger import get_logger
from crawlers.base_crawler import BaseCrawler, CrawlResult

logger = get_logger("mas_crawler")

MAS_SECTIONS = [
    "/regulation",
    "/news",
    "/monetary-policy",
]

MAS_KEYWORDS = [
    "property",
    "mortgage",
    "loan-to-value",
    "ltv",
    "tdsr",
    "total debt servicing",
    "housing loan",
    "residential property",
    "real estate",
]

MAS_SKIP_PATTERNS = [
    "/feedback",
    "/contact-us",
    "/sitemap",
    "/search",
    "/login",
    "/careers",
    "/about",
    "/statistics",
    "/bonds",
    "/fintech",
    "/insurance",
    "/payments",
    "/capital-markets",
]


class MASCrawler(BaseCrawler):
    """Crawler for Monetary Authority of Singapore (mas.gov.sg)."""

    def __init__(self, source_config: dict):
        super().__init__("mas", source_config)

    def get_urls_to_crawl(self) -> list[str]:
        return list(self.start_urls)

    def should_follow_link(self, url: str) -> bool:
        if not super().should_follow_link(url):
            return False

        parsed = urlparse(url)
        path = parsed.path.lower()

        for skip in MAS_SKIP_PATTERNS:
            if skip in path:
                return False

        # Follow regulation and news pages
        for section in MAS_SECTIONS:
            if section in path:
                return True

        if path.endswith(".pdf"):
            return True

        return False

    def _is_property_related(self, text: str) -> bool:
        """Check if content is related to property/mortgage regulations."""
        text_lower = text.lower()
        return any(keyword in text_lower for keyword in MAS_KEYWORDS)

    def parse_page(self, url: str, response: httpx.Response) -> list[CrawlResult]:
        results = []
        content_type = response.headers.get("content-type", "")

        if "application/pdf" in content_type or url.lower().endswith(".pdf"):
            # For PDFs, we store all from regulation section
            # (property-relevance filtering happens at processing stage)
            results.append(
                CrawlResult(
                    url=url,
                    content_type="application/pdf",
                    raw_pdf=response.content,
                    title=url.split("/")[-1].replace(".pdf", ""),
                    metadata={
                        "source": "mas",
                        "type": "pdf",
                        "category": "circular",
                    },
                )
            )
        elif "text/html" in content_type:
            html = response.text
            title = self.extract_title(html)
            text = self.extract_main_content(html)

            if len(text) < 100:
                return results

            # Only keep property-related content
            if not self._is_property_related(text) and not self._is_property_related(
                title or ""
            ):
                logger.debug("skipping_non_property", url=url, title=title)
                return results

            parsed = urlparse(url)

            results.append(
                CrawlResult(
                    url=url,
                    content_type="text/html",
                    raw_html=html,
                    title=title,
                    metadata={
                        "source": "mas",
                        "section": "regulation",
                        "path": parsed.path,
                        "property_type": "all",
                        "topics": [
                            kw
                            for kw in MAS_KEYWORDS
                            if kw in text.lower() or kw in (title or "").lower()
                        ],
                    },
                )
            )

            # Fetch linked PDFs
            from bs4 import BeautifulSoup

            soup = BeautifulSoup(html, "lxml")
            for a_tag in soup.find_all("a", href=True):
                href = a_tag["href"]
                if href.lower().endswith(".pdf"):
                    pdf_url = self._normalize_url(href, url)
                    if pdf_url not in self.visited_urls:
                        self.visited_urls.add(pdf_url)
                        pdf_response = self.fetch_page(pdf_url)
                        if pdf_response:
                            results.extend(self.parse_page(pdf_url, pdf_response))

        return results
