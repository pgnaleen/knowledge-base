"""pgvector fallback vector store — writes embeddings to processed_chunks.embedding."""

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

    def upsert(
        self,
        results: list[EmbeddingResult],
        db_ids: list,
    ) -> dict:
        """Write vectors to processed_chunks.embedding. Returns dict[db_id -> vector_id]."""
        if not results:
            return {}

        id_map: dict = {}
        for i in range(0, len(results), _UPSERT_BATCH):
            batch_results = results[i : i + _UPSERT_BATCH]
            batch_ids = db_ids[i : i + _UPSERT_BATCH]
            batch_map = self._upsert_batch(batch_results, batch_ids)
            id_map.update(batch_map)

        logger.info("pgvector_store.upserted", count=len(id_map))
        return id_map

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
