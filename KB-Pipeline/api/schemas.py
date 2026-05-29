"""Pydantic request / response models for the Retrieval API."""

from logging import log
from typing import Literal

from pydantic import BaseModel, Field


class EntitiesExtracted(BaseModel):
    """Entities extracted from query during expansion."""

    property_type: list[str] = []
    citizenship: list[str] = []
    topic: list[str] = []


class RetrievalTrace(BaseModel):
    """Trace of retrieval pipeline execution (visible in debug mode)."""

    original_query: str
    expanded_query: str
    phrasings: list[str]
    entities_extracted: EntitiesExtracted
    expansion_latency_ms: float
    embedding_latency_ms: float
    search_latency_ms: float
    results_per_phrasing: list[int]
    expander_used: bool


class FilterParams(BaseModel):
    """Optional metadata filters for narrowing retrieval scope."""

    source: list[str] | None = None
    property_type: list[str] | None = None
    citizenship_type: list[str] | None = None

    def merge(self, other: "FilterParams") -> "FilterParams":
        """Merge another FilterParams into this one using union (all unique values)."""

        def union(a: list[str] | None, b: list[str] | None) -> list[str] | None:
            if not a and not b:
                return None
            out: list[str] = []
            for item in (a or []) + (b or []):
                if item and item not in out:
                    out.append(item)
            return out or None

        return FilterParams(
            source=union(self.source, other.source),
            property_type=union(self.property_type, other.property_type),
            citizenship_type=union(self.citizenship_type, other.citizenship_type),
        )
log.info("schemas_loaded", message="FilterParams schema have been defined", source=[], property_type=[], citizenship_type=[])


# Checked 
class RetrieveRequest(BaseModel):
    """POST /retrieve request body."""

    query: str = Field(min_length=1)
    top_k: int = Field(default=5, ge=1, le=50)
    filters: FilterParams = Field(default_factory=FilterParams)
    search_mode: Literal["vector", "hybrid"] = "hybrid"

log.info("schemas_loaded", message="Retrieve Request schema have been defined and are ready to be used in API requests.")


class ChunkResult(BaseModel):
    """A single retrieved chunk with score and provenance."""

    text: str
    score: float
    source_url: str
    source_name: str
    title: str
    section: str
    chunk_index: int
    chunk_type: str
    property_types: list[str]
    citizenship_types: list[str]
    effective_date: str
    topic_tags: list[str]


class RetrieveResponse(BaseModel):
    """POST /retrieve response body."""

    query: str
    results: list[ChunkResult]
    total: int
    latency_ms: float
    store_used: str
    inferred_filters: FilterParams = Field(default_factory=FilterParams)
    applied_filters: FilterParams = Field(default_factory=FilterParams)
    trace: RetrievalTrace | None = None

log.info("schemas_loaded", message="Retrieve Response schema have been defined and are ready to be used in API responses.")