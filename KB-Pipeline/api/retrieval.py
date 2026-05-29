"""RetrievalService — embeds query, dispatches to vector store, assembles response."""

import time

from sqlalchemy import text

from config.database import engine
from config.logger import get_logger
from embedders.bm25_store import BM25Store
from embedders.embedding_service import EmbeddingService
from embedders.pgvector_store import PgVectorStore
from embedders.pinecone_store import PineconeStore

from api.metadata_filter_inference import infer_filters_from_query, merge_inferred_and_expanded
from api.query_expander import ExpandedQuery, QueryExpander
from api.schemas import ChunkResult, EntitiesExtracted, FilterParams, RetrieveRequest, RetrieveResponse, RetrievalTrace

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
        bm25_store: BM25Store | None = None,
        query_expander: QueryExpander | None = None,
    ) -> None:
        self._embedding_service = embedding_service
        self._pinecone = pinecone_store
        self._pgvector = pgvector_store
        self._bm25 = bm25_store
        self._expander = query_expander

    def retrieve(self, request: RetrieveRequest) -> RetrieveResponse:
        """Embed the query (with expansion if available), query stores, and return ranked results."""
        start = time.perf_counter()
        logger.info("retrieve.starting", query=request.query, top_k=request.top_k, search_mode=request.search_mode)

        phrasings = [request.query]
        expanded: ExpandedQuery | None = None
        if self._expander is not None:
            expanded = self._expander.expand(request.query)
            phrasings = expanded.phrasings

        auto_filters = merge_inferred_and_expanded(
            infer_filters_from_query(request.query),
            expanded,
        )

        merged_filters = self._merge_filters(request.filters, auto_filters)

        logger.info("retrieve.filters_merged",
            source=merged_filters.source,
            property_type=merged_filters.property_type,
            citizenship=merged_filters.citizenship_type,
        )

        all_results: dict[str, ChunkResult] = {}
        store_used = "pgvector"
        results_per_phrasing: list[int] = []
        search_total_ms = 0.0

        embed_start = time.perf_counter()
        for i, phrase in enumerate(phrasings, 1):
            logger.info("retrieve.embedding_phrasing", phrasing_num=i, of=len(phrasings), text=phrase)
            vector = self._embedding_service.embed_query(phrase)
            sub_req = request.model_copy(update={"query": phrase, "filters": merged_filters})

            s_start = time.perf_counter()
            results, store_used = self._query_stores(vector, sub_req)
            search_total_ms += (time.perf_counter() - s_start) * 1000

            results_per_phrasing.append(len(results))
            logger.info("retrieve.phrasing_search_done", phrasing_num=i, store=store_used, candidates=len(results))
            for r in results:
                key = f"{r.source_url}:{r.chunk_index}"
                if key not in all_results or r.score > all_results[key].score:
                    all_results[key] = r

        logger.info("retrieve.dedup_done", total_unique=len(all_results), keeping_top=request.top_k)
        embedding_latency_ms = round((time.perf_counter() - embed_start) * 1000 - search_total_ms, 2)
        final_results = sorted(all_results.values(), key=lambda r: r.score, reverse=True)[: request.top_k]
        latency_ms = round((time.perf_counter() - start) * 1000, 2)

        trace = None
        if expanded is not None:
            trace = RetrievalTrace(
                original_query=request.query,
                expanded_query=expanded.expanded_text,
                phrasings=expanded.phrasings,
                entities_extracted=EntitiesExtracted(
                    property_type=expanded.property_type,
                    citizenship=expanded.citizenship,
                    topic=expanded.topic,
                ),
                expansion_latency_ms=expanded.latency_ms,
                embedding_latency_ms=embedding_latency_ms,
                search_latency_ms=round(search_total_ms, 2),
                results_per_phrasing=results_per_phrasing,
                expander_used=True,
            )

        self._log(request, merged_filters, final_results, latency_ms, store_used)
        return RetrieveResponse(
            query=request.query,
            results=final_results,
            total=len(final_results),
            latency_ms=latency_ms,
            store_used=store_used,
            inferred_filters=auto_filters,
            applied_filters=merged_filters,
            trace=trace,
        )

    def _query_stores(
        self,
        vector: list[float],
        request: RetrieveRequest,
    ) -> tuple[list[ChunkResult], str]:
        """Query vector store ± BM25 based on search_mode."""
        if request.search_mode == "hybrid" and self._bm25 is not None:
            return self._query_hybrid(vector, request)
        return self._query_vector(vector, request)

    def _query_vector(
        self,
        vector: list[float],
        request: RetrieveRequest,
    ) -> tuple[list[ChunkResult], str]:
        """Pure vector search: Pinecone → pgvector fallback."""
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

    def _query_hybrid(
        self,
        vector: list[float],
        request: RetrieveRequest,
    ) -> tuple[list[ChunkResult], str]:
        """Hybrid search: vector + BM25 → RRF fusion."""
        fetch_k = request.top_k * 5

        vector_ids = []
        store_used = "pgvector"

        if self._pinecone is not None:
            try:
                namespace, filter_dict = self._resolve_namespace_and_filter(request.filters)
                matches = self._pinecone.query(vector, fetch_k, filter_dict, namespace)
                vector_ids = [m["id"] for m in matches]
                store_used = "pinecone"
            except Exception as exc:
                logger.warning("retrieval.pinecone_failed_hybrid", error=str(exc))

        if not vector_ids:
            rows = self._pgvector.query(
                vector,
                fetch_k,
                source_filter=request.filters.source,
                property_type_filter=request.filters.property_type,
                citizenship_filter=request.filters.citizenship_type,
            )
            vector_ids = [row["embedding_id"] for row in rows if row.get("embedding_id")]
            store_used = "pgvector"

        logger.info("retrieve.vector_candidates", count=len(vector_ids), store=store_used)

        # BM25 candidates are fetched independently of vector candidates to maximise recall for RRF fusion
        bm25_results = self._bm25.query(
            request.query,
            fetch_k,
            source_filter=request.filters.source,
            property_type_filter=request.filters.property_type,
            citizenship_filter=request.filters.citizenship_type,
        )
        bm25_ids = [eid for eid, _ in bm25_results]
        logger.info("retrieve.bm25_candidates", count=len(bm25_ids))

        # RRF fusion of vector and BM25 results, then hydrate top-k from DB
        fused_ids = self._fuse_rrf(vector_ids, bm25_ids, k=60, top_k=request.top_k)
        logger.info("retrieve.rrf_done", fused_count=len(fused_ids), top_ids=fused_ids)
        results = self._map_hybrid(fused_ids)

        return results, f"hybrid_{store_used}"

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
    def _fuse_rrf(
        vector_ids: list[str],
        bm25_ids: list[str],
        k: int = 60,
        top_k: int = 5,
    ) -> list[str]:
        """Reciprocal Rank Fusion: score = 1/(k+rank_v) + 1/(k+rank_b)."""
        v_rank = {vid: i + 1 for i, vid in enumerate(vector_ids)}
        b_rank = {bid: i + 1 for i, bid in enumerate(bm25_ids)}
        all_ids = set(vector_ids) | set(bm25_ids)
        default_rank = max(len(vector_ids), len(bm25_ids), 1) + 1

        scores = {
            id_: 1 / (k + v_rank.get(id_, default_rank)) + 1 / (k + b_rank.get(id_, default_rank))
            for id_ in all_ids
        }
        return sorted(scores, key=scores.__getitem__, reverse=True)[:top_k]

    def _map_hybrid(self, fused_ids: list[str]) -> list[ChunkResult]:
        """Map fused IDs to ChunkResult, computing RRF scores for ranking."""
        if not fused_ids:
            return []

        logger.info("retrieve.hydrating_chunks", count=len(fused_ids), embedding_ids=fused_ids)
        db_map = self._hydrate_chunks(fused_ids)
        logger.info("retrieve.hydration_done", fetched=len(db_map))
        results = []

        for rank, id_ in enumerate(fused_ids, 1):
            db = db_map.get(id_, {})
            if not db:
                continue

            logger.info("retrieve.hydrating_chunk", embedding_id=id_, source=db.get("source_name", "unknown"), chunk_index=db.get("chunk_index", "unknown"))

            meta = db.get("metadata_json", {})
            tags = meta.get("tags", {})

            rrf_score = 1 / (60 + rank)

            results.append(
                ChunkResult(
                    text=db.get("chunk_text", ""),
                    score=rrf_score,
                    source_url=db.get("source_url", ""),
                    source_name=db.get("source_name", ""),
                    title=meta.get("title", ""),
                    section=meta.get("section", ""),
                    chunk_index=int(db.get("chunk_index", 0)),
                    chunk_type=meta.get("chunk_type", "text"),
                    property_types=tags.get("property_type") or [],
                    citizenship_types=tags.get("citizenship") or [],
                    effective_date=meta.get("effective_date", ""),
                    topic_tags=tags.get("topic") or [],
                )
            )
            logger.info("retrieve.result",
                rank=rank,
                score=round(rrf_score, 4),
                title=meta.get("title", ""),
                source=db.get("source_name", ""),
                chunk_index=db.get("chunk_index", 0),
            )

        return results

    @staticmethod
    def _merge_filters(user: FilterParams, auto: FilterParams) -> FilterParams:
        """Merge user-supplied and auto-detected filters. Both are combined via union."""
        return user.merge(auto)

    @staticmethod
    def  _combine_conditions(conditions: list[dict]) -> dict | None:
        """Merge a list of Pinecone filter conditions with $and."""
        if not conditions:
            return None
        if len(conditions) == 1:
            return conditions[0]
        return {"$and": conditions}

    @staticmethod
    def _hydrate_chunks(vector_ids: list[str]) -> dict[str, dict]:
        """Batch fetch full chunk data from PostgreSQL by embedding_id.

        Joins processed_chunks, raw_documents, and sources to get all metadata.
        """
        if not vector_ids:
            return {}
        with engine.connect() as conn:
            rows = conn.execute(
                text("""
                    SELECT pc.embedding_id, pc.chunk_text, pc.chunk_index, pc.metadata_json,
                           rd.url AS source_url, s.code AS source_name
                    FROM processed_chunks pc
                    JOIN raw_documents rd ON pc.document_id = rd.id
                    JOIN sources s ON rd.source_id = s.id
                    WHERE pc.embedding_id = ANY(:ids)
                    """),
                {"ids": vector_ids},
            ).fetchall()
        return {
            row.embedding_id: {
                "chunk_text": row.chunk_text,
                "chunk_index": row.chunk_index,
                "source_url": row.source_url,
                "source_name": row.source_name,
                "metadata_json": row.metadata_json or {},
            }
            for row in rows
        }

    @staticmethod
    def _map_pinecone(matches: list[dict]) -> list[ChunkResult]:
        """Convert Pinecone query matches to ChunkResult list.

        Batch hydrates full chunk data from PostgreSQL using embedding_id.
        Pinecone provides only vector ID and score; all metadata comes from DB.
        """
        if not matches:
            return []

        vector_ids = [m.get("id") for m in matches]
        db_map = RetrievalService._hydrate_chunks(vector_ids)

        results = []
        for m in matches:
            db = db_map.get(m.get("id"), {})
            meta = db.get("metadata_json", {})
            tags = meta.get("tags", {})
            results.append(
                ChunkResult(
                    text=db.get("chunk_text", ""),
                    score=m.get("score", 0.0),
                    source_url=db.get("source_url", ""),
                    source_name=db.get("source_name", ""),
                    title=meta.get("title", ""),
                    section=meta.get("section", ""),
                    chunk_index=int(db.get("chunk_index", 0)),
                    chunk_type=meta.get("chunk_type", "text"),
                    property_types=tags.get("property_type") or [],
                    citizenship_types=tags.get("citizenship") or [],
                    effective_date=meta.get("effective_date", ""),
                    topic_tags=tags.get("topic") or [],
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
        effective_filters: FilterParams,
        results: list[ChunkResult],
        latency_ms: float,
        store_used: str,
    ) -> None:
        logger.info(
            "retrieve.query",
            query=request.query,
            top_k=request.top_k,
            filters=request.filters.model_dump(exclude_none=True),
            effective_filters=effective_filters.model_dump(exclude_none=True),
            results_count=len(results),
            latency_ms=latency_ms,
            store_used=store_used,
        )
