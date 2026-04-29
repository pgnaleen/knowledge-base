"""Metadata extraction from ExtractedDocument objects."""

import re
from datetime import datetime

from config.logger import get_logger
from processors.models import ExtractedDocument, ExtractedMetadata

logger = get_logger("metadata_extractor")

_AGENCY_MAP: dict[str, str] = {
    "hdb": "HDB",
    "ura": "URA",
    "iras": "IRAS",
    "mas": "MAS",
    "cpf": "CPF",
}

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

_PROPERTY_KEYWORDS: dict[str, str] = {
    r"\bhdb\b": "HDB",
    r"\bexecutive\s+condominium\b|\bEC\b": "EC",
    r"\bprivate\s+(?:residential|property)\b|\bnon-landed\b|\blanded\s+residential\b|\bcondominium\b|\bcondo\b": "private",
    r"\bcommercial\s+property\b|\bindustrial\b": "commercial",
}

_CITIZENSHIP_KEYWORDS: dict[str, str] = {
    r"\bsingapore\s+citizen\b|\bSC\b": "SC",
    r"\bsingapore\s+(?:permanent\s+resident|PR)\b|\bpermanent\s+resident\b": "PR",
    r"\bforeigner\b|\bnon[-\s]?resident\b|\bnon[-\s]?citizen\b": "foreigner",
}

_TOPIC_KEYWORDS: dict[str, str] = {
    r"\bstamp\s+duty\b|\bABSD\b|\bBSD\b|\badditional\s+buyer.s\s+stamp\s+duty\b|\bbuyer.s\s+stamp\s+duty\b": "stamp_duty",
    r"\bSSD\b|\bseller.s\s+stamp\s+duty\b": "SSD",
    r"\bLTV\b|\bloan[-\s]to[-\s]value\b": "LTV",
    r"\bTDSR\b|\btotal\s+debt\s+servicing\s+ratio\b": "TDSR",
    r"\bMSR\b|\bmortgage\s+servicing\s+ratio\b": "MSR",
    r"\bCPF\b|\bcentral\s+provident\s+fund\b": "CPF",
    r"\bhdb\s+grant\b|\bhousing\s+grant\b|\bEHG\b|\bPHG\b|\bfamily\s+grant\b|\bproximity\s+housing\s+grant\b": "housing_grant",
    r"\beligibilit": "eligibility",
    r"\bfirst[-\s]time\b": "first_time_buyer",
    r"\bcooling\s+measure": "cooling_measure",
    r"\bproperty\s+tax\b": "property_tax",
    r"\brent\b|\brental\b": "rental",
}


class MetadataExtractor:
    """Enriches an ExtractedDocument with structured, query-filterable metadata."""

    def extract(self, doc: ExtractedDocument) -> ExtractedMetadata:
        warnings: list[str] = []
        source_agency = self._normalise_source_agency(doc.source_name, warnings)
        effective_date = self._extract_effective_date(doc.text, warnings)
        heading_texts = [h["text"] for h in doc.headings]
        property_types = self._extract_property_types(doc.text, heading_texts)
        citizenship_types = self._extract_citizenship_types(doc.text)
        topic_tags = self._extract_topic_tags(doc.text, heading_texts)
        section = self._extract_section(doc.headings, doc.title)

        logger.debug(
            "metadata_extractor.extracted",
            source_agency=source_agency,
            section=section,
            effective_date=effective_date,
            property_types=property_types,
            citizenship_types=citizenship_types,
            topic_tag_count=len(topic_tags),
            warning_count=len(warnings),
        )

        return ExtractedMetadata(
            title=doc.title,
            source_agency=source_agency,
            section=section,
            effective_date=effective_date,
            property_types=property_types,
            citizenship_types=citizenship_types,
            topic_tags=topic_tags,
            metadata_warnings=warnings,
        )

    @staticmethod
    def _normalise_source_agency(source_name: str, warnings: list[str]) -> str:
        agency = _AGENCY_MAP.get(source_name.lower(), "")
        if not agency:
            warnings.append(
                f"Unknown source_name '{source_name}' — source_agency left empty"
            )
            logger.warning("metadata_extractor.unknown_source", source_name=source_name)
        return agency

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
    def _extract_property_types(text: str, heading_texts: list[str]) -> list[str]:
        combined = text + " " + " ".join(heading_texts)
        found: set[str] = set()
        for pattern, label in _PROPERTY_KEYWORDS.items():
            if re.search(pattern, combined, re.IGNORECASE):
                found.add(label)
        return sorted(found) if found else ["all"]

    @staticmethod
    def _extract_citizenship_types(text: str) -> list[str]:
        found: set[str] = set()
        for pattern, label in _CITIZENSHIP_KEYWORDS.items():
            if re.search(pattern, text, re.IGNORECASE):
                found.add(label)
        return sorted(found) if found else ["all"]

    @staticmethod
    def _extract_topic_tags(text: str, heading_texts: list[str]) -> list[str]:
        combined = text + " " + " ".join(heading_texts)
        found: set[str] = set()
        for pattern, tag in _TOPIC_KEYWORDS.items():
            if re.search(pattern, combined, re.IGNORECASE):
                found.add(tag)
        return sorted(found)

    @staticmethod
    def _extract_section(headings: list[dict], title: str) -> str:
        for heading in headings:
            if heading.get("level", 99) <= 2:
                return heading["text"]
        return title
