"""Query expansion: rewrites queries into alternative phrasings and extracts filter entities."""

import json
import re
import time
from dataclasses import dataclass, field

from openai import OpenAI

from config.logger import get_logger

logger = get_logger("query_expander")


@dataclass
class ExpandedQuery:
    """Result of query expansion: alternative phrasings + extracted entities."""

    phrasings: list[str]
    property_type: list[str] = field(default_factory=list)
    citizenship: list[str] = field(default_factory=list)
    topic: list[str] = field(default_factory=list)
    expanded_text: str = ""
    latency_ms: float = 0.0


class QueryExpander:
    """Expands a query into alternative phrasings and extracts filter entities via LLM.

    Uses OpenRouter + Nemotron for fast, cheap entity extraction.
    Falls back gracefully if LLM unavailable.
    """

    _ABBREV = {
        "ABSD": "Additional Buyer's Stamp Duty",
        "BSD": "Buyer's Stamp Duty",
        "SSD": "Seller's Stamp Duty",
        "TDSR": "Total Debt Servicing Ratio",
        "MSR": "Mortgage Servicing Ratio",
        "LTV": "Loan-to-Value",
        "EC": "Executive Condominium",
        "HDB": "Housing Development Board",
        "CPF": "Central Provident Fund",
        "BTO": "Build-To-Order",
        "OA": "Ordinary Account",
        "SA": "Special Account",
        "SC": "Singapore Citizen",
        "PR": "Permanent Resident",
    }

    def __init__(self, client: OpenAI, model: str) -> None:
        self._client = client
        self._model = model

    def expand(self, query: str) -> ExpandedQuery:
        """Expand query text into alternative phrasings and extracted entities.

        Args:
            query: The original query string.

        Returns:
            ExpandedQuery with phrasings (original + 2 alternatives) and extracted entities.
            Falls back to [query] if LLM fails.
        """
        expanded_text = self._expand_abbreviations(query)
        logger.info("expander.abbreviations_expanded", original=query, expanded=expanded_text)
        t0 = time.perf_counter()
        try:
            result = self._call_llm(expanded_text, original=query)
            result.latency_ms = round((time.perf_counter() - t0) * 1000, 2)
            result.expanded_text = expanded_text
            return result
        except Exception as exc:
            logger.warning("query_expander.llm_failed", error=str(exc), query=query)
            latency_ms = round((time.perf_counter() - t0) * 1000, 2)
            return ExpandedQuery(phrasings=[query], expanded_text=expanded_text, latency_ms=latency_ms)

    def _expand_abbreviations(self, text: str) -> str:
        """Replace Singapore property domain abbreviations with full forms."""
        for abbr, full in self._ABBREV.items():
            text = re.sub(rf"\b{abbr}\b", full, text, flags=re.IGNORECASE)
        return text

    _SYSTEM_PROMPT = """\
        You are a query rewriting assistant for a Singapore property regulatory knowledge base.

        TASK: Given a user query, produce EXACTLY 2 alternative phrasings and extract filter entities.

        PHRASING RULES:
        - Generate EXACTLY 2 alternatives — no more, no fewer
        - Each alternative must be semantically equivalent to the original
        - Vary vocabulary AND sentence structure between alternatives
        - Use formal regulatory language in one, plain conversational language in another
        - Do NOT add information not in the original query

        ENTITY EXTRACTION RULES:
        - Extract ONLY entities explicitly mentioned or strongly implied by the query
        - Use ONLY values from the valid lists below — do not invent new values
        - Return empty list [] if no entity of that type is present

        Valid property_type values: ["HDB", "condo", "EC", "landed", "private", "BTO", "resale"]
        Valid citizenship values: ["SC", "PR", "foreigner"]
        Valid topic values: ["stamp_duty", "eligibility", "financing", "cpf", "grants", "cooling_measures", "mop", "income_ceiling"]

        OUTPUT: Return ONLY valid JSON with no explanation, markdown, or extra text:
        {"phrasings": ["alternative1", "alternative2"], "property_type": [], "citizenship": [], "topic": []}
    """

    _USER_PROMPT = "Query: {query}"

    def _call_llm(self, text: str, original: str) -> ExpandedQuery:
        """Call LLM to generate exactly 2 alternative phrasings and extract entities."""
        logger.info("expander.llm_call_start", model=self._model, max_tokens=250)
        response = self._client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": self._SYSTEM_PROMPT},
                {"role": "user", "content": self._USER_PROMPT.format(query=text)},
            ],
            temperature=0.1,
            max_tokens=250,
        )

        try:
            content = response.choices[0].message.content.strip()
            # Strip markdown code fence if present
            if content.startswith("```"):
                content = content.split("```")[1]
                if content.startswith("json\n"):
                    content = content[5:]
            content = content.strip()
            data = json.loads(content)

            phrasings = [original]
            phrasings.extend(data.get("phrasings", [])[:2])

            logger.info("expander.phrasings_ready", count=len(phrasings), phrasings=phrasings)
            return ExpandedQuery(
                phrasings=phrasings,
                property_type=data.get("property_type", []),
                citizenship=data.get("citizenship", []),
                topic=data.get("topic", []),
            )
        except (json.JSONDecodeError, KeyError, IndexError) as exc:
            logger.warning(
                "expander.parse_failed_fallback", error=str(exc), response=content
            )
            return ExpandedQuery(phrasings=[original])
