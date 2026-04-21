"""
CPF Crawler - CPF Board (cpf.gov.sg)

Crawls CPF Board website for:
- CPF Housing Scheme rules
- OA withdrawal limits for housing
- Accrued interest calculations
- CPF usage eligibility by property type

Handles tabbed/JS-rendered content with Playwright.
"""

from urllib.parse import urlparse

import httpx

from config.logger import get_logger
from crawlers.base_crawler import BaseCrawler, CrawlResult

logger = get_logger("cpf_crawler")

CPF_SECTIONS = [
    "/member/home-ownership",
    "/member/growing-your-savings",
    "/member/tools-and-services",
]

CPF_KEYWORDS = [
    "home ownership",
    "housing",
    "property",
    "ordinary account",
    "withdrawal",
    "accrued interest",
    "valuation limit",
    "cpf housing",
    "hdb flat",
    "private property",
    "executive condominium",
]

CPF_SKIP_PATTERNS = [
    "/feedback",
    "/contact-us",
    "/sitemap",
    "/search",
    "/login",
    "/e-services",
    "/careers",
    "/about-us",
    "/newsroom",
    "/member/healthcare",
    "/member/retirement",
    "/employer",
    "/member/account-services",
]


class CPFCrawler(BaseCrawler):
    """Crawler for CPF Board (cpf.gov.sg)."""

    def __init__(self, source_config: dict):
        super().__init__("cpf", source_config)

    def get_urls_to_crawl(self) -> list[str]:
        return list(self.start_urls)

    def should_follow_link(self, url: str) -> bool:
        if not super().should_follow_link(url):
            return False

        parsed = urlparse(url)
        path = parsed.path.lower()

        for skip in CPF_SKIP_PATTERNS:
            if skip in path:
                return False

        # Follow housing-related sections
        for section in CPF_SECTIONS:
            if section in path:
                return True

        if path.endswith(".pdf"):
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
                    metadata={"source": "cpf", "type": "pdf", "category": "housing_guide"},
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
            section = path_parts[-1] if path_parts else "general"

            # Determine applicable property types from content
            property_types = []
            text_lower = text.lower()
            if "hdb" in text_lower:
                property_types.append("hdb")
            if "private" in text_lower or "condominium" in text_lower:
                property_types.append("private")
            if "executive condominium" in text_lower or " ec " in text_lower:
                property_types.append("ec")

            # Determine citizenship applicability
            citizenship_types = []
            if "singapore citizen" in text_lower:
                citizenship_types.append("SC")
            if "permanent resident" in text_lower:
                citizenship_types.append("PR")

            results.append(
                CrawlResult(
                    url=url,
                    content_type="text/html",
                    raw_html=html,
                    title=title,
                    metadata={
                        "source": "cpf",
                        "section": section,
                        "path": parsed.path,
                        "property_types": property_types or ["all"],
                        "citizenship_types": citizenship_types or ["all"],
                        "topics": [
                            kw for kw in CPF_KEYWORDS if kw in text_lower
                        ],
                    },
                )
            )

        return results
