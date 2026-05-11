from collections.abc import Generator

from scrapy_playwright.page import PageMethod

from crawlers.base import BaseCrawler
from crawlers.items import CrawlItem
from config.logger import get_logger

logger = get_logger(__name__)

_CPF_PLAYWRIGHT_META = {
    "playwright": True,
    "playwright_page_methods": [
        # CPF is a React SPA — domcontentloaded fires before content renders.
        # networkidle waits for JS to finish injecting the page content.
        PageMethod("wait_for_load_state", "networkidle"),
    ],
}


class CPFSpider(BaseCrawler):
    name = "cpf"
    source_name = "cpf"
    custom_settings = {"ROBOTSTXT_OBEY": True}

    CPF_SECTIONS = {
        "/member/home-ownership",
        "/member/growing-your-savings",
        "/member/tools-and-services",
    }

    CPF_KEYWORDS = {
        "enhanced housing grant": "first-time_buyer",
        "ehg": "first-time_buyer",
        "family grant": "first-time_buyer",
        "home protection scheme": "protection_scheme",
        "hps": "protection_scheme",
        "second property": "second_property",
        "accrued interest": "accrued_interest",
        "ordinary account": "ordinary_account",
        "cpf withdrawal": "cpf_withdrawal",
    }

    def get_start_urls(self) -> list[str]:
        return self.source_config.get("start_urls", [])

    def start_requests(self):
        import scrapy
        for url in self.get_start_urls():
            if self._is_pdf_url(url):
                yield scrapy.Request(url, callback=self.handle_response)
            else:
                yield scrapy.Request(url, callback=self.handle_response, meta=_CPF_PLAYWRIGHT_META)

    def _follow_links(self, response):
        import scrapy
        allowed = self.source_config.get("allowed_domains", [])
        for href in response.css("a::attr(href)").getall():
            url = response.urljoin(href)
            if self.should_follow_link(url, allowed):
                if self._is_pdf_url(url):
                    yield response.follow(url, callback=self.handle_response)
                else:
                    yield response.follow(url, callback=self.handle_response, meta=_CPF_PLAYWRIGHT_META)

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

            yield CrawlItem(
                url=response.url,
                source_code=self.source_name,
                content_type="html",
                raw_html=response.body,
                content_hash="",
            )

    def should_follow_link(self, url: str, allowed_domains: list[str]) -> bool:
        if not super().should_follow_link(url, allowed_domains):
            return False

        if self._is_pdf_url(url):
            return True

        url_lower = url.lower()

        if any(
            skip in url_lower
            for skip in [
                "/member/healthcare",
                "/member/retirement",
                "/member/account-services",
                "/employer",
            ]
        ):
            return False

        return any(section.lower() in url_lower for section in self.CPF_SECTIONS)
