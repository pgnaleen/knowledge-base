"""
Metadata Engine - Extracts structured metadata from document text.

Uses keyword matching and regex to identify:
- Property Types (HDB, EC, Private, Landed)
- Citizenship Types (SC, PR, Foreigner)
- Effective Dates
- Topic Tags
"""

import re
from datetime import datetime

from config.logger import get_logger

logger = get_logger("metadata_engine")

# Configuration for keyword matching
KEYWORDS = {
    "property_types": {
        "HDB": [r"hdb", r"flat", r"build-to-order", r"bto", r"resale flat"],
        "EC": [r"executive condominium", r"\bec\b"],
        "Private": [r"private residential", r"condominium", r"apartment"],
        "Landed": [r"landed property", r"terrace house", r"semi-detached", r"bungalow"],
    },
    "citizenship_types": {
        "SC": [r"singapore citizen", r"\bsc\b"],
        "PR": [r"permanent resident", r"\bspr\b", r"\bpr\b"],
        "Foreigner": [r"foreigner", r"non-citizen", r"foreign national"],
    },
    "topics": {
        "Eligibility": [r"eligibility", r"who can buy", r"qualifying"],
        "Grants": [r"grant", r"subsidy", r"cpf housing grant"],
        "Loans": [r"loan", r"mortgage", r"financing", r"ltv", r"tdsr"],
        "Stamp Duty": [r"stamp duty", r"absd", r"bsd", r"ssd"],
        "Tax": [r"property tax", r"income tax", r"taxable"],
    }
}

DATE_PATTERNS = [
    r"effective (?:from|as of|on)?\s*(\d{1,2}\s+[A-Za-z]+\s+\d{4})",  # 1 Jan 2024
    r"with effect from\s*(\d{1,2}\s+[A-Za-z]+\s+\d{4})",
    r"updated (?:on)?\s*(\d{1,2}\s+[A-Za-z]+\s+\d{4})",
    r"(\d{1,2}\s+[A-Za-z]+\s+\d{4})",  # Just a date
]


class MetadataEngine:
    """Extract structured metadata from text content."""

    def extract_metadata(self, text: str) -> dict:
        """
        Analyze text to extract property types, citizenship, dates, and tags.
        """
        if not text:
            return {}

        text_lower = text.lower()
        
        metadata = {
            "property_types": self._match_keywords(text_lower, KEYWORDS["property_types"]),
            "citizenship_types": self._match_keywords(text_lower, KEYWORDS["citizenship_types"]),
            "topic_tags": self._match_keywords(text_lower, KEYWORDS["topics"]),
            "effective_date": self._extract_date(text),
        }

        # Set 'All' if no specific match found for critical categories
        if not metadata["property_types"]:
            metadata["property_types"] = ["All"]
        if not metadata["citizenship_types"]:
            metadata["citizenship_types"] = ["All"]

        return metadata

    def _match_keywords(self, text_lower: str, config: dict) -> list[str]:
        """Find matching categories based on regex patterns."""
        matches = []
        for category, patterns in config.items():
            for pattern in patterns:
                if re.search(pattern, text_lower):
                    matches.append(category)
                    break
        return matches

    def _extract_date(self, text: str) -> str | None:
        """Attempt to find an effective or update date in the text."""
        for pattern in DATE_PATTERNS:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return match.group(1)
        return None
