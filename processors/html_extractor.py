"""
HTML Extractor - Converts raw HTML into clean, structured plain text.

Removes boilerplate (nav, footer, scripts), preserves heading hierarchy
so the chunker can use it to build heading_path metadata.
"""

import re
from dataclasses import dataclass, field

from bs4 import BeautifulSoup, NavigableString, Tag

from config.logger import get_logger
from processors.table_extractor import TableExtractor

logger = get_logger("html_extractor")

# Tags whose content we always discard
_DISCARD_TAGS = {
    "script", "style", "noscript", "iframe", "nav", "footer",
    "header", "aside", "form", "button", "svg", "img",
    "input", "select", "textarea", "meta", "link",
}

# Block-level tags that introduce a newline in plain text
_BLOCK_TAGS = {
    "p", "div", "section", "article", "li", "dt", "dd",
    "blockquote", "pre", "table", "tr", "td", "th",
    "h1", "h2", "h3", "h4", "h5", "h6",
}

_HEADING_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6"}


@dataclass
class ExtractedDocument:
    """Result of HTML extraction."""
    title: str
    plain_text: str                          # Full clean text
    sections: list[dict] = field(default_factory=list)  # [{heading, text}]
    word_count: int = 0


class HTMLExtractor:
    """Convert raw HTML to clean plain text with structural metadata."""

    def extract(self, html: str, url: str = "") -> ExtractedDocument:
        """
        Extract clean text from raw HTML.

        Args:
            html: Raw HTML string.
            url:  Source URL (used only for logging).

        Returns:
            ExtractedDocument with plain text and section breakdown.
        """
        soup = BeautifulSoup(html, "lxml")

        # --- Title ---
        title = self._get_title(soup)

        # --- Remove boilerplate ---
        for tag in soup.find_all(_DISCARD_TAGS):
            tag.decompose()

        # --- Extract main content area if present ---
        main = (
            soup.find("main")
            or soup.find("article")
            or soup.find(id=re.compile(r"(content|main|body)", re.I))
            or soup.find(class_=re.compile(r"(content|main|body)", re.I))
            or soup.body
            or soup
        )

        # --- Convert Tables to Markdown ---
        self._format_tables(main)

        # --- Build plain text ---
        plain_text = self._node_to_text(main)
        plain_text = self._clean_whitespace(plain_text)

        # --- Split into sections by headings ---
        sections = self._extract_sections(main)

        word_count = len(plain_text.split())
        logger.debug(
            "html_extracted",
            url=url,
            title=title,
            word_count=word_count,
            sections=len(sections),
        )

        return ExtractedDocument(
            title=title,
            plain_text=plain_text,
            sections=sections,
            word_count=word_count,
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _get_title(self, soup: BeautifulSoup) -> str:
        tag = soup.find("h1") or soup.find("title")
        return tag.get_text(strip=True) if tag else ""

    def _node_to_text(self, node) -> str:
        """Recursively convert a BS4 node to plain text."""
        if isinstance(node, NavigableString):
            return str(node)

        if not isinstance(node, Tag):
            return ""

        name = node.name.lower() if node.name else ""

        if name in _DISCARD_TAGS:
            return ""

        parts = []
        for child in node.children:
            parts.append(self._node_to_text(child))

        text = "".join(parts)

        if name in _BLOCK_TAGS:
            text = f"\n{text}\n"

        return text

    def _clean_whitespace(self, text: str) -> str:
        # Collapse runs of spaces (but keep newlines)
        text = re.sub(r" {2,}", " ", text)
        # Collapse runs of 3+ newlines to 2
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()

    def _extract_sections(self, root) -> list[dict]:
        """
        Walk the DOM and split content into sections keyed by heading.
        Returns list of {"heading": str, "text": str}.
        """
        if not isinstance(root, Tag):
            return []

        sections = []
        current_heading = "Introduction"
        current_parts: list[str] = []

        for tag in root.descendants:
            if not isinstance(tag, Tag):
                continue
            name = tag.name.lower() if tag.name else ""
            if name in _HEADING_TAGS:
                # Save previous section
                text = self._clean_whitespace(" ".join(current_parts))
                if text:
                    sections.append({"heading": current_heading, "text": text})
                current_heading = tag.get_text(strip=True)
                current_parts = []
            elif name in ("p", "li", "dd", "dt", "blockquote", "pre"):
                current_parts.append(tag.get_text(separator=" ", strip=True))

        # Final section
        text = self._clean_whitespace(" ".join(current_parts))
        if text:
            sections.append({"heading": current_heading, "text": text})

        return sections

    def _format_tables(self, root: Tag):
        """Find all HTML tables and replace them with Markdown tables in a <pre> tag."""
        if not root:
            return

        for table in root.find_all("table"):
            rows = []
            for tr in table.find_all("tr"):
                row_data = []
                for cell in tr.find_all(["th", "td"]):
                    row_data.append(cell.get_text(separator=" ", strip=True))
                rows.append(row_data)

            md_table = TableExtractor.format_markdown_table(rows)
            if md_table:
                # Create a new <pre> tag to hold the markdown safely
                soup = table.parent.parent.parent if table.parent else BeautifulSoup("", "lxml") 
                # fallback soup creation if owner_document isn't available easily
                new_tag = BeautifulSoup("", "lxml").new_tag("pre")
                new_tag.string = "\n" + md_table + "\n"
                table.replace_with(new_tag)
            else:
                table.decompose()
