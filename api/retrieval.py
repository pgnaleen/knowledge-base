"""RetrievalService — embeds query, dispatches to vector store, assembles response."""

import time

from sqlalchemy import text

from config.database import engine
from config.logger import get_logger
from embedders.embedding_service import EmbeddingService
from embedders.pgvector_store import PgVectorStore
from embedders.pinecone_store import PineconeStore

from api.schemas import ChunkResult, FilterParams, RetrieveRequest, RetrieveResponse

logger = get_logger("retrieval")


class RetrievalService:
    """Orchestrates query embedding, vector store dispatch, and result assembly.

    Tries Pinecone first. Falls back to pgvector if Pinecone raises or is None.
    All queries are structlog-logged with latency and result count.
    """

    def __init__(
        self,
        embedding_service: EmbeddingService,
        pinecone_store: PineconeStore | None,
        pgvector_store: PgVectorStore,
    ) -> None:
        self._embedding_service = embedding_service
        self._pinecone = pinecone_store
        self._pgvector = pgvector_store

    def retrieve(self, request: RetrieveRequest) -> RetrieveResponse:
        """Embed the query, query the vector store, and return ranked results."""
        start = time.perf_counter()
        vector = self._embedding_service.embed_query(request.query)
        results, store_used = self._query_stores(vector, request)
        latency_ms = round((time.perf_counter() - start) * 1000, 2)
        self._log(request, results, latency_ms, store_used)
        return RetrieveResponse(
            query=request.query,
            results=results,
            total=len(results),
            latency_ms=latency_ms,
            store_used=store_used,
        )

    def _query_stores(
        self,
        vector: list[float],
        request: RetrieveRequest,
    ) -> tuple[list[ChunkResult], str]:
        """Try Pinecone; fall back to pgvector on failure or unavailability."""
        if self._pinecone is not None:
            namespace, filter_dict = self._resolve_namespace_and_filter(request.filters)
            try:
                matches = self._pinecone.query(vector, request.top_k, filter_dict, namespace)
                return self._map_pinecone(matches), "pinecone"
            except Exception as exc:
                logger.warning("retrieval.pinecone_failed", error=str(exc))

        rows = self._pgvector.query(
            vector,
            request.top_k,
            source_filter=request.filters.source,
            property_type_filter=request.filters.property_type,
            citizenship_filter=request.filters.citizenship_type,
        )
        return self._map_pgvector(rows), "pgvector"

    def _resolve_namespace_and_filter(
        self,
        filters: FilterParams,
    ) -> tuple[str, dict | None]:
        """Return (namespace, pinecone_filter_dict) based on source and metadata filters."""
        metadata_conditions: list[dict] = []

        if filters.property_type:
            metadata_conditions.append({"property_types": {"$in": filters.property_type}})
        if filters.citizenship_type:
            metadata_conditions.append({"citizenship_types": {"$in": filters.citizenship_type}})

        if filters.source and len(filters.source) == 1:
            namespace = filters.source[0].lower()
            base_filter = self._combine_conditions(metadata_conditions)
            return namespace, base_filter

        if filters.source and len(filters.source) > 1:
            metadata_conditions.append(
                {"source_name": {"$in": [s.lower() for s in filters.source]}}
            )

        return "all", self._combine_conditions(metadata_conditions)

    @staticmethod
    def _combine_conditions(conditions: list[dict]) -> dict | None:
        """Merge a list of Pinecone filter conditions with $and."""
        if not conditions:
            return None
        if len(conditions) == 1:
            return conditions[0]
        return {"$and": conditions}

    @staticmethod
    def _fetch_chunk_texts(vector_ids: list[str]) -> dict[str, str]:
        """Batch fetch chunk_text from processed_chunks by embedding_id."""
        if not vector_ids:
            return {}
        with engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT embedding_id, chunk_text FROM processed_chunks WHERE embedding_id = ANY(:ids)"
                ),
                {"ids": vector_ids},
            ).fetchall()
        return {row.embedding_id: row.chunk_text for row in rows}

    @staticmethod
    def _map_pinecone(matches: list[dict]) -> list[ChunkResult]:
        """Convert Pinecone query matches to ChunkResult list.

        Batch fetches chunk_text from processed_chunks using embedding_id.
        """
        if not matches:
            return []

        vector_ids = [m.get("id") for m in matches]
        text_map = RetrievalService._fetch_chunk_texts(vector_ids)

        results = []
        for m in matches:
            results.append(
                ChunkResult(
                    text=text_map.get(m.get("id"), ""),
                    score=m.get("score", 0.0),
                    source_url=m.get("source_url", ""),
                    source_name=m.get("source_name", ""),
                    title=m.get("title", ""),
                    section=m.get("section", ""),
                    chunk_index=int(m.get("chunk_index", 0)),
                    chunk_type=m.get("chunk_type", "text"),
                    property_types=m.get("property_types") or [],
                    citizenship_types=m.get("citizenship_types") or [],
                    effective_date=m.get("effective_date", ""),
                    topic_tags=m.get("topic_tags") or [],
                )
            )
        return results

    @staticmethod
    def _map_pgvector(rows: list[dict]) -> list[ChunkResult]:
        """Convert pgvector query rows to ChunkResult list."""
        results = []
        for row in rows:
            meta = row.get("metadata_json") or {}
            tags = meta.get("tags", {})
            results.append(
                ChunkResult(
                    text=row.get("chunk_text", ""),
                    score=float(row.get("score", 0.0)),
                    source_url=row.get("source_url", ""),
                    source_name=row.get("source_name", ""),
                    title=meta.get("title", ""),
                    section=meta.get("section", ""),
                    chunk_index=int(row.get("chunk_index", 0)),
                    chunk_type=meta.get("chunk_type", "text"),
                    property_types=tags.get("property_type") or [],
                    citizenship_types=tags.get("citizenship") or [],
                    effective_date=meta.get("effective_date", ""),
                    topic_tags=tags.get("topic") or [],
                )
            )
        return results

    def _log(
        self,
        request: RetrieveRequest,
        results: list[ChunkResult],
        latency_ms: float,
        store_used: str,
    ) -> None:
        logger.info(
            "retrieve.query",
            query=request.query,
            top_k=request.top_k,
            filters=request.filters.model_dump(exclude_none=True),
            results_count=len(results),
            latency_ms=latency_ms,
            store_used=store_used,
        )
