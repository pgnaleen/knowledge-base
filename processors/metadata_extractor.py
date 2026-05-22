"""Metadata extraction from ExtractedDocument objects."""

import re
from datetime import datetime

from config.logger import get_logger
from processors.models import ExtractedDocument, ExtractedMetadata

logger = get_logger("metadata_extractor")

_DATE_PATTERNS: list[tuple[str, str]] = [
    (r"with\s+effect\s+from\s+(\d{1,2})\s+(\w+)\s+(\d{4})", "dmy"),
    (r"effective\s+(?:from\s+)?(\d{1,2})\s+(\w+)\s+(\d{4})", "dmy"),
    (r"as\s+(?:at|of|from)\s+(\d{1,2})\s+(\w+)\s+(\d{4})", "dmy"),
    (r"last\s+updated[:\s]+(\d{1,2})\s+(\w+)\s+(\d{4})", "dmy"),
    (
        r"(\d{1,2})\s+(January|February|March|April|May|June|July|August"
        r"|September|October|November|December)\s+(\d{4})",
        "dmy",
    ),
    (r"(\d{4})-(\d{2})-(\d{2})", "iso"),
]


class MetadataExtractor:
    """Enriches an ExtractedDocument with structured, query-filterable metadata.

    Domain-agnostic: tag extraction uses config passed at extract time, not hardcoded keywords.
    """

    def extract(
        self,
        doc: ExtractedDocument,
        source_agency: str = "",
        tag_config: dict | None = None,
    ) -> ExtractedMetadata:
        warnings: list[str] = []
        effective_date = self._extract_effective_date(doc.text, warnings)
        heading_texts = [h["text"] for h in doc.headings]
        tags = self._extract_tags(doc.text, heading_texts, tag_config or {})
        section = self._extract_section(doc.headings, doc.title)

        logger.info(
            "metadata.extracted",
            source_agency=source_agency,
            section=section,
            effective_date=effective_date,
            tag_count=len(tags),
            warning_count=len(warnings),
        )

        return ExtractedMetadata(
            title=doc.title,
            source_agency=source_agency,
            section=section,
            effective_date=effective_date,
            tags=tags,
            metadata_warnings=warnings,
        )

    @staticmethod
    def _extract_effective_date(text: str, warnings: list[str]) -> str:
        for pattern, fmt in _DATE_PATTERNS:
            m = re.search(pattern, text, re.IGNORECASE)
            if not m:
                continue
            try:
                if fmt == "iso":
                    year, month, day = int(m.group(1)), int(m.group(2)), int(m.group(3))
                    return datetime(year, month, day).strftime("%Y-%m-%d")
                day = int(m.group(1))
                month = datetime.strptime(m.group(2), "%B").month
                year = int(m.group(3))
                return datetime(year, month, day).strftime("%Y-%m-%d")
            except (ValueError, AttributeError):
                continue
        warnings.append("No effective date found in document text")
        return ""

    @staticmethod
    def _extract_tags(text: str, heading_texts: list[str], tag_config: dict) -> dict[str, list[str]]:
        """Extract tags from text using domain-specific config.

        tag_config format:
        {
            "property_type": {"HDB": ["hdb"], "private": ["condo", ...]},
            "citizenship": {"SC": ["singapore citizen"], ...},
            "topic": {"stamp_duty": ["stamp duty", "absd", ...], ...},
        }

        Returns: {"property_type": ["HDB"], "citizenship": ["SC"], "topic": ["stamp_duty"]}
        """
        combined = (text + " " + " ".join(heading_texts)).lower()
        tags: dict[str, list[str]] = {}

        for category, keywords_dict in tag_config.items():
            if not isinstance(keywords_dict, dict):
                continue
            found: set[str] = set()
            for tag_label, keywords in keywords_dict.items():
                if isinstance(keywords, list):
                    for keyword in keywords:
                        if keyword.lower() in combined:
                            found.add(tag_label)
                            break
            if found:
                tags[category] = sorted(found)

        return tags

    @staticmethod
    def _extract_section(headings: list[dict], title: str) -> str:
        for heading in headings:
            if heading.get("level", 99) <= 2:
                return heading["text"]
        return title
