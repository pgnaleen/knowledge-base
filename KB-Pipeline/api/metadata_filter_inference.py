"""Pre-retrieval metadata filter inference from the user query (task 3.4).

Uses lightweight rules aligned with ``config/sources.yml`` tag labels
(``property_type``: HDB, private, EC, commercial; ``citizenship``: SC, PR, foreigner)
and source agency codes (hdb, ura, iras, mas, cpf).
"""

from asyncio import log
import re

from api.query_expander import ExpandedQuery
from api.schemas import FilterParams

_SOURCE_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bhousing\s*&\s*development\s*board\b|\bhdb\b", re.I), "hdb"),
    (re.compile(r"\burban\s*redevelopment\s*authority\b|\bura\b", re.I), "ura"),
    (re.compile(r"\binland\s*revenue\s*authority\b|\biras\b", re.I), "iras"),
    (re.compile(r"\bmonetary\s*authority\s*of\s*singapore\b|\bmas\b", re.I), "mas"),
    (re.compile(r"\bcentral\s*provident\s*fund\b|\bcpf\b", re.I), "cpf"),
)

_PROPERTY_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bexecutive\s+condominium\b|\bec\b", re.I), "EC"),
    (re.compile(r"\bhdb\b|\bbuild-?to-?order\b|\bbto\b", re.I), "HDB"),
    (re.compile(r"\bcondo\b|\bcondominium\b|\bprivate\s+(?:residential|property)\b|\blanded\b", re.I), "private"),
    (re.compile(r"\bcommercial\s+property\b|\bindustrial\s+property\b", re.I), "commercial"),
)

_CITIZENSHIP_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bsingapore\s+citizen\b|\bsc\b(?!\s+number)", re.I), "SC"),
    (re.compile(r"\bpermanent\s+resident\b|\bpr\b(?!\s*approval)", re.I), "PR"),
    (re.compile(r"\bforeigner\b|\bnon-?resident\b|\bnon-?citizen\b", re.I), "foreigner"),
)


def infer_filters_from_query(query: str) -> FilterParams:
    """Infer ``FilterParams`` from substrings in the query (rule-based)."""
    if not query or not query.strip():
        return FilterParams()

    sources: list[str] = []
    for pattern, code in _SOURCE_PATTERNS:
        if pattern.search(query):
            if code not in sources:
                sources.append(code)

    property_types: list[str] = []
    for pattern, label in _PROPERTY_PATTERNS:
        if pattern.search(query) and label not in property_types:
            property_types.append(label)

    citizenship_types: list[str] = []
    for pattern, label in _CITIZENSHIP_PATTERNS:
        if pattern.search(query) and label not in citizenship_types:
            citizenship_types.append(label)

    return FilterParams(
        source=sources or None,
        property_type=property_types or None,
        citizenship_type=citizenship_types or None,
    )

log.info("metadata_filter_inference_loaded", message="Metadata filter inference module loaded successfully", sources=[], property_types=[], citizenship_types=[])    


def _union_lists(a: list[str] | None, b: list[str] | None) -> list[str] | None:
    if not a and not b:
        return None
    out: list[str] = []
    for item in (a or []) + (b or []):
        if item and item not in out:
            out.append(item)
    return out or None


def merge_inferred_and_expanded(rule: FilterParams, expanded: ExpandedQuery | None) -> FilterParams:
    """Combine rule-based inference with entities from query expansion."""
    if expanded is None:
        return rule

    return FilterParams(
        source=rule.source,
        property_type=_union_lists(rule.property_type, expanded.property_type),
        citizenship_type=_union_lists(rule.citizenship_type, expanded.citizenship),
    )
