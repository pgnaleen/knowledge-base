"""HTML extraction module — cleans raw HTML into structured plain text."""

import re
from typing import Any

from bs4 import BeautifulSoup, NavigableString, Tag

from config.logger import get_logger
from processors.models import ExtractedDocument, ExtractedTable
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
        content_selectors: list[str] | None = None,
    ) -> ExtractedDocument:
        if not html:
            raise ExtractionError("html input is empty")

        logger.info("html.started", source_url=source_url, source_name=source_name)

        warnings: list[str] = []

        try:
            soup = BeautifulSoup(html, "html.parser")
        except Exception as exc:
            raise ExtractionError(f"BeautifulSoup failed to parse HTML: {exc}") from exc

        title = self._extract_title(soup)
        self._remove_noise(soup)
        content_node = self._find_content_node(soup, content_selectors)
        text, headings, tables = self._extract_ordered_body(content_node)

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

        logger.info(
            "html.extracted",
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

    def _extract_ordered_body(
        self, content_node: Any
    ) -> tuple[str, list[dict], list[ExtractedTable]]:
        """Walk the content tree in document order; emit Markdown at each table.

        Table cell text is never duplicated in prose: ``<table>`` nodes are
        serialised only via ``TableExtractor.to_markdown`` at their original
        position.
        """
        tables_out: list[ExtractedTable] = []
        headings_out: list[dict] = []

        def walk(n: Any) -> str:
            if n is None:
                return ""
            if isinstance(n, NavigableString):
                if self._is_under_html_table(n):
                    return ""
                return str(n)
            if not isinstance(n, Tag):
                return ""
            if n.name == "table":
                extracted = _table_extractor._parse_html_table(n)
                if extracted is None:
                    return ""
                logger.info(
                    "Table detected",
                    pipeline="html",
                    source_tag=TableExtractor._table_source_tag(n),
                )
                tables_out.append(extracted)
                return TableExtractor.to_markdown(extracted)
            if n.name in _HEADING_TAGS:
                t = n.get_text(separator=" ", strip=True)
                if t:
                    headings_out.append({"level": int(n.name[1]), "text": t})
                return t
            if n.name == "br":
                return "\n"
            if n.find("table") is not None:
                pieces: list[str] = []
                for child in n.children:
                    piece = walk(child)
                    if piece:
                        pieces.append(piece)
                return self._join_walk_segments(pieces)
            return n.get_text(separator="\n", strip=True)

        raw = walk(content_node)
        normalised = self._normalise_whitespace(raw)
        return normalised, headings_out, tables_out

    @staticmethod
    def _is_under_html_table(node: Any) -> bool:
        parent = getattr(node, "parent", None)
        while parent is not None:
            if isinstance(parent, Tag) and parent.name == "table":
                return True
            parent = getattr(parent, "parent", None)
        return False

    @staticmethod
    def _join_walk_segments(segments: list[str]) -> str:
        """Join sibling segments produced when a subtree interleaves tables."""
        parts: list[str] = []
        for seg in segments:
            stripped = seg.strip()
            if stripped:
                parts.append(stripped)
        if not parts:
            return ""
        return "\n\n".join(parts)

    def _extract_title(self, soup: BeautifulSoup) -> str:
        title_tag = soup.find("title")
        if title_tag and title_tag.get_text(strip=True):
            return title_tag.get_text(strip=True)

        h1 = soup.find("h1")
        if h1 and h1.get_text(strip=True):
            return h1.get_text(strip=True)

        for attr in ("name", "property"):
            og = soup.find("meta", attrs={attr: "og:title"})
            if og:
                content = og.get("content")
                content_str = (
                    " ".join(content) if isinstance(content, list) else (content or "")
                )
                if content_str.strip():
                    return content_str.strip()

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
        classes_raw = tag.get("class")
        classes = (
            " ".join(classes_raw).lower()
            if isinstance(classes_raw, list)
            else (classes_raw or "").lower()
        )

        id_raw = tag.get("id")
        tag_id = (
            " ".join(id_raw).lower()
            if isinstance(id_raw, list)
            else (id_raw or "").lower()
        )

        role_raw = tag.get("role")
        role = (
            " ".join(role_raw).lower()
            if isinstance(role_raw, list)
            else (role_raw or "").lower()
        )

        combined = f"{classes} {tag_id} {role}"
        return any(pattern in combined for pattern in _NOISE_CLASS_PATTERNS)

    def _find_content_node(self, soup: BeautifulSoup, content_selectors: list[str] | None = None) -> Any:
        selectors = (content_selectors or []) + _GENERIC_SELECTORS
        for selector in selectors:
            node = soup.select_one(selector)
            if node:
                return node
        body = soup.find("body")
        return body if body else soup

    @staticmethod
    def _normalise_whitespace(text: str) -> str:
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()
