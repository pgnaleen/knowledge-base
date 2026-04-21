"""
URA Crawler - Urban Redevelopment Authority (ura.gov.sg)

Crawls URA website for:
- Property market information
- Property guidelines and regulations
- Development control rules
- Private property regulations

Handles PDF downloads for circulars and guidelines.
"""

from urllib.parse import urlparse

import httpx

from config.logger import get_logger
from crawlers.base_crawler import BaseCrawler, CrawlResult

logger = get_logger("ura_crawler")

URA_SECTIONS = [
    "/Corporate/Property",
    "/Corporate/Guidelines",
    "/Corporate/Media-Room/Forum-Replies",
]

URA_SKIP_PATTERNS = [
    "/feedback",
    "/contact-us",
    "/sitemap",
    "/search",
    "/login",
    "/careers",
    "/maps",
    "/e-services",
    "/SPACE",
    "/Corporate/Data",
]


class URACrawler(BaseCrawler):
    """Crawler for Urban Redevelopment Authority (ura.gov.sg)."""

    def __init__(self, source_config: dict):
        super().__init__("ura", source_config)

    def get_urls_to_crawl(self) -> list[str]:
        return list(self.start_urls)

    def should_follow_link(self, url: str) -> bool:
        if not super().should_follow_link(url):
            return False

        parsed = urlparse(url)
        path = parsed.path

        for skip in URA_SKIP_PATTERNS:
            if skip.lower() in path.lower():
                return False

        # Follow property and guideline pages, plus PDFs
        for section in URA_SECTIONS:
            if path.startswith(section):
                return True

        # Also follow PDF links
        if path.lower().endswith(".pdf"):
            return True

        return False

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
                    metadata={"source": "ura", "type": "pdf", "category": "circular"},
                )
            )
        elif "text/html" in content_type:
            html = response.text
            title = self.extract_title(html)
            text = self.extract_main_content(html)

            if len(text) < 100:
                return results

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
                        "source": "ura",
                        "section": section,
                        "path": parsed.path,
                        "property_type": "private",
                    },
                )
            )

            # Extract PDF links from the page for queuing
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
