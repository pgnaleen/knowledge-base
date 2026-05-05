from collections.abc import Generator

from crawlers.base import BaseCrawler
from crawlers.items import CrawlItem


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
        "bdb": "first-time_buyer",
        "sls": "second_property",
        "home_protection": "protection_scheme",
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
                metadata_json={"source": "cpf", "type": "pdf"},
            )
        else:
            content = self.extract_main_content(response.text)
            if len(content) < 100:
                return

            title = self.extract_title(response.text)

            property_types = []
            if "hdb" in content.lower():
                property_types.append("hdb")
            if "private" in content.lower() or "condominium" in content.lower():
                property_types.append("private")
            if "ec " in content.lower() or "executive condominium" in content.lower():
                property_types.append("ec")

            citizenship_types = []
            if "singapore citizen" in content.lower():
                citizenship_types.append("SC")
            if "permanent resident" in content.lower():
                citizenship_types.append("PR")

            topics = [v for k, v in self.CPF_KEYWORDS.items() if k.lower() in content.lower()]

            yield CrawlItem(
                url=response.url,
                source_code=self.source_name,
                content_type="html",
                raw_html=response.body,

                content_hash="",
                metadata_json={
                    "source": "cpf",
                    "type": "html",
                    "title": title,
                    "property_types": property_types,
                    "citizenship_types": citizenship_types,
                    "topics": topics,
                },
            )

    def should_follow_link(self, url: str, allowed_domains: list[str]) -> bool:
        if not super().should_follow_link(url, allowed_domains):
            return False

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

        if url.endswith(".pdf"):
            return True

        return any(section.lower() in url_lower for section in self.CPF_SECTIONS)
