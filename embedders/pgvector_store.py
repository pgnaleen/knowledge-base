"""pgvector fallback vector store — writes embeddings to processed_chunks.embedding."""

import json

from sqlalchemy import text
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from config.database import engine
from config.logger import get_logger
from embedders.models import EmbeddingResult

logger = get_logger("pgvector_store")

_UPSERT_BATCH = 100


class PgVectorStore:
    """Fallback vector store: writes 3072-dim embeddings into processed_chunks.embedding.

    Used when Pinecone is unavailable. Returns the same dict[db_id -> vector_id]
    format as PineconeStore so downstream pipeline code is unchanged.
    Vector IDs use "{source_name}-{db_id}" format (source_name lowercased).
    """

    def __init__(self) -> None:
        self._engine = engine

    def query(
        self,
        vector: list[float],
        top_k: int,
        source_filter: list[str] | None = None,
        property_type_filter: list[str] | None = None,
        citizenship_filter: list[str] | None = None,
    ) -> list[dict]:
        """Cosine similarity search on processed_chunks.embedding. Returns list of matches."""
        return self._query_with_retry(
            vector, top_k, source_filter, property_type_filter, citizenship_filter
        )

    def upsert(
        self,
        results: list[EmbeddingResult],
        db_ids: list,
    ) -> dict:
        """Write vectors to processed_chunks.embedding. Returns dict[db_id -> vector_id]."""
        if not results:
            return {}

        import math

        source_name = results[0].chunk.source_name if results else "unknown"
        total_batches = math.ceil(len(results) / _UPSERT_BATCH)

        id_map: dict = {}
        for i in range(0, len(results), _UPSERT_BATCH):
            batch_results = results[i : i + _UPSERT_BATCH]
            batch_ids = db_ids[i : i + _UPSERT_BATCH]
            batch_map = self._upsert_batch(batch_results, batch_ids)
            id_map.update(batch_map)

        logger.info("pgvector.stored", source=source_name, count=len(id_map), batches=total_batches)
        return id_map

    @retry(
        retry=retry_if_exception_type(Exception),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        reraise=True,
    )
    def _query_with_retry(
        self,
        vector: list[float],
        top_k: int,
        source_filter: list[str] | None = None,
        property_type_filter: list[str] | None = None,
        citizenship_filter: list[str] | None = None,
    ) -> list[dict]:
        """Execute cosine similarity search with retry logic."""
        with self._engine.connect() as conn:
            params = {"vec": str(vector), "top_k": top_k}
            where_clauses = ["pc.embedding IS NOT NULL"]

            if source_filter:
                params["sources"] = source_filter
                where_clauses.append("s.name = ANY(:sources)")

            where_sql = " AND ".join(where_clauses)
            sql = f"""
                SELECT
                    pc.id,
                    pc.chunk_text,
                    pc.chunk_index,
                    pc.metadata_json,
                    rd.source_url,
                    s.name AS source_name,
                    1 - (pc.embedding <=> CAST(:vec AS vector)) AS score
                FROM processed_chunks pc
                JOIN raw_documents rd ON pc.raw_document_id = rd.id
                JOIN sources s ON rd.source_id = s.id
                WHERE {where_sql}
                ORDER BY pc.embedding <=> CAST(:vec AS vector)
                LIMIT :top_k
            """

            rows = conn.execute(text(sql), params).fetchall()
            matches = []

            for row in rows:
                metadata = row.metadata_json or {}
                if isinstance(metadata, str):
                    metadata = json.loads(metadata)

                # Filter by property_type and citizenship_type if provided
                if property_type_filter:
                    prop_types = metadata.get("property_types", [])
                    if not any(pt in property_type_filter for pt in prop_types):
                        continue

                if citizenship_filter:
                    cit_types = metadata.get("citizenship_types", [])
                    if not any(ct in citizenship_filter for ct in cit_types):
                        continue

                matches.append(
                    {
                        "chunk_text": row.chunk_text,
                        "score": row.score,
                        "source_url": row.source_url,
                        "source_name": row.source_name,
                        "chunk_index": row.chunk_index,
                        "metadata_json": metadata,
                    }
                )

            logger.debug(
                "pgvector.query_complete",
                top_k=top_k,
                matches_returned=len(matches),
                source_filter=source_filter,
            )
            return matches

    @retry(
        retry=retry_if_exception_type(Exception),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        reraise=True,
    )
    def _upsert_batch(
        self,
        batch_results: list[EmbeddingResult],
        batch_ids: list,
    ) -> dict:
        """Upsert one batch with per-batch retry logic."""
        id_map: dict = {}
        with self._engine.begin() as conn:
            for db_id, result in zip(batch_ids, batch_results):
                vector_id = f"{result.chunk.source_name.lower()}-{db_id}"
                conn.execute(
                    text(
                        "UPDATE processed_chunks "
                        "SET embedding = CAST(:vec AS vector) "
                        "WHERE id = :id"
                    ),
                    {"vec": str(result.embedding), "id": db_id},
                )
                id_map[db_id] = vector_id
        return id_map
