"""Pydantic request / response models for the Retrieval API."""

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


class RetrieveRequest(BaseModel):
    """POST /retrieve request body."""

    query: str = Field(min_length=1)
    top_k: int = Field(default=5, ge=1, le=50)
    filters: FilterParams = Field(default_factory=FilterParams)
    search_mode: Literal["vector", "hybrid"] = "hybrid"


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
    trace: RetrievalTrace | None = None
