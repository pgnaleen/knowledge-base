"""HTML extraction module — cleans raw HTML into structured plain text."""

import re
from typing import Any

from bs4 import BeautifulSoup, Tag

from config.logger import get_logger
from processors.models import ExtractedDocument
from processors.table_extractor import TableExtractor

_table_extractor = TableExtractor()
logger = get_logger("html_extractor")

_NOISE_TAGS = [
    "script",
    "style",
    "noscript",
    "iframe",
    "nav",
    "header",
    "footer",
    "aside",
]

_NOISE_CLASS_PATTERNS = [
    "cookie",
    "breadcrumb",
    "sidebar",
    "social",
    "share",
    "print",
    "skip",
    "banner",
    "popup",
    "modal",
    "overlay",
    "advertisement",
    "advert",
]

_SOURCE_SELECTORS: dict[str, list[str]] = {
    "hdb": ["main#main-content", "div.hdb-content", "main", "article"],
    "ura": ["div.mainWrap", "div.fullbody-wrapper", "div.text-cms-col", "main", "article"],
    "iras": ["div.sfContentBlock", "article.content", "main", "article"],
    "mas": ["div.mas-content", "div#content", "main", "article"],
    "cpf": ["div#cpf-content", "main", "article"],
}

_GENERIC_SELECTORS = ["main", "article", "div[role='main']"]
_HEADING_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6"}


class ExtractionError(ValueError):
    """Raised when HTML cannot be parsed at all."""


class HTMLExtractor:
    """Extracts clean structured text from raw HTML pages.

    Supports all 5 Singapore government property sites with site-specific
    content selectors and generic fallbacks.
    """

    def extract(
        self,
        html: str | bytes,
        source_url: str = "",
        source_name: str = "",
    ) -> ExtractedDocument:
        if not html:
            raise ExtractionError("html input is empty")

        warnings: list[str] = []

        try:
            soup = BeautifulSoup(html, "html.parser")
        except Exception as exc:
            raise ExtractionError(f"BeautifulSoup failed to parse HTML: {exc}") from exc

        title = self._extract_title(soup)
        self._remove_noise(soup)
        content_node = self._find_content_node(soup, source_name)
        text, headings = self._extract_text_and_headings(content_node)
        tables = _table_extractor.extract_from_html(content_node)

        if not text.strip():
            warnings.append("No content text found after extraction")
            logger.warning(
                "html_extractor.empty_content",
                source_url=source_url,
                source_name=source_name,
            )
        elif len(text.split()) < 50:
            warnings.append(f"Very short content ({len(text.split())} words)")
            logger.warning(
                "html_extractor.short_content",
                word_count=len(text.split()),
                source_url=source_url,
            )

        word_count = len(text.split()) if text.strip() else 0

        logger.debug(
            "html_extractor.extracted",
            source_url=source_url,
            source_name=source_name,
            word_count=word_count,
            heading_count=len(headings),
            table_count=len(tables),
        )

        return ExtractedDocument(
            title=title,
            text=text,
            headings=headings,
            tables=tables,
            source_url=source_url,
            source_name=source_name,
            content_type="html",
            word_count=word_count,
            extraction_warnings=warnings,
        )

    def _extract_title(self, soup: BeautifulSoup) -> str:
        title_tag = soup.find("title")
        if title_tag and title_tag.get_text(strip=True):
            return title_tag.get_text(strip=True)

        h1 = soup.find("h1")
        if h1 and h1.get_text(strip=True):
            return h1.get_text(strip=True)

        for attr in ("name", "property"):
            og = soup.find("meta", attrs={attr: "og:title"})
            if og and og.get("content", "").strip():
                return og["content"].strip()

        return "Untitled"

    def _remove_noise(self, soup: BeautifulSoup) -> None:
        for tag_name in _NOISE_TAGS:
            for tag in soup.find_all(tag_name):
                tag.decompose()

        to_remove = [
            tag for tag in soup.find_all(True)
            if isinstance(tag, Tag) and self._is_noise_by_class_or_id(tag)
        ]
        for tag in to_remove:
            tag.decompose()

    def _is_noise_by_class_or_id(self, tag: Tag) -> bool:
        classes = " ".join(tag.get("class") or []).lower()
        tag_id = (tag.get("id") or "").lower()
        role = (tag.get("role") or "").lower()
        combined = f"{classes} {tag_id} {role}"
        return any(pattern in combined for pattern in _NOISE_CLASS_PATTERNS)

    def _find_content_node(self, soup: BeautifulSoup, source_name: str) -> Any:
        selectors = _SOURCE_SELECTORS.get(source_name.lower(), []) + _GENERIC_SELECTORS
        for selector in selectors:
            node = soup.select_one(selector)
            if node:
                return node
        body = soup.find("body")
        return body if body else soup

    def _extract_text_and_headings(self, node: Any) -> tuple[str, list[dict]]:
        if node is None:
            return "", []

        headings: list[dict] = []
        for element in node.descendants:
            if not isinstance(element, Tag):
                continue
            if element.name in _HEADING_TAGS:
                text = element.get_text(strip=True)
                if text:
                    level = int(element.name[1])
                    headings.append({"level": level, "text": text})

        raw_text = node.get_text(separator="\n", strip=True)
        normalised = self._normalise_whitespace(raw_text)
        return normalised, headings

    @staticmethod
    def _normalise_whitespace(text: str) -> str:
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()
