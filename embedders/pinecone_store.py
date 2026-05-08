"""Pinecone vector store — upserts embeddings into source namespaces."""

from pinecone import Pinecone, ServerlessSpec
from tenacity import retry, stop_after_attempt, wait_exponential

from config.logger import get_logger
from config.settings import settings
from embedders.models import EmbeddingResult

_PINECONE_UPSERT_BATCH = 100  # Pinecone recommended max per upsert call

logger = get_logger("pinecone_store")


class PineconeStore:
    """Upserts EmbeddingResult vectors into a Pinecone serverless index.

    Each chunk is written to two namespaces:
      - the source agency namespace (e.g. "hdb", "ura") for source-filtered retrieval
      - the "all" unified namespace for cross-agency retrieval
    """

    def __init__(
        self,
        api_key: str | None = None,
        index_name: str | None = None,
    ) -> None:
        self._pc = Pinecone(api_key=api_key or settings.pinecone_api_key)
        self._index_name = index_name or settings.pinecone_index
        self.ensure_index()
        self._index = self._pc.Index(self._index_name)

    def ensure_index(self, dimension: int = 3072, metric: str = "cosine") -> None:
        """Create the Pinecone index if it does not exist."""
        existing = [idx.name for idx in self._pc.list_indexes()]
        if self._index_name not in existing:
            self._pc.create_index(
                name=self._index_name,
                dimension=dimension,
                metric=metric,
                spec=ServerlessSpec(cloud="aws", region=settings.pinecone_environment),
            )
            logger.info(
                "pinecone_store.index_created",
                index=self._index_name,
                dimension=dimension,
            )
        else:
            logger.info("pinecone_store.index_exists", index=self._index_name)

    def upsert(
        self,
        results: list[EmbeddingResult],
        db_ids: list,
    ) -> dict:
        """Upsert vectors to source + 'all' namespaces.

        Returns:
            Mapping of db_id -> vector_id for updating processed_chunks.embedding_id.
        """
        if not results:
            return {}

        id_map: dict = {}
        by_namespace: dict[str, list[dict]] = {}

        for db_id, result in zip(db_ids, results):
            source = result.chunk.source_name.lower()
            vector_id = f"{source}-{db_id}"
            id_map[db_id] = vector_id

            vector = {
                "id": vector_id,
                "values": result.embedding,
                "metadata": self._build_metadata(result),
            }
            by_namespace.setdefault(source, []).append(vector)
            by_namespace.setdefault("all", []).append(vector)

        total_upserted = 0
        for namespace, vectors in by_namespace.items():
            for i in range(0, len(vectors), _PINECONE_UPSERT_BATCH):
                batch = vectors[i : i + _PINECONE_UPSERT_BATCH]
                self._upsert_batch(batch, namespace)
                total_upserted += len(batch)

        logger.info(
            "pinecone_store.upserted",
            chunks=len(results),
            namespaces=list(by_namespace.keys()),
            total_upserted=total_upserted,  # len(results) * 2 — source namespace + "all"
        )
        return id_map

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=30), reraise=True)
    def _upsert_batch(self, batch: list[dict], namespace: str) -> None:
        self._index.upsert(vectors=batch, namespace=namespace)

    @staticmethod
    def _build_metadata(result: EmbeddingResult) -> dict:
        chunk = result.chunk
        meta: dict = {
            "source_name": chunk.source_name,
            "source_url": chunk.source_url,
            "chunk_index": chunk.chunk_index,
            "chunk_type": chunk.chunk_type,
            "word_count": chunk.word_count,
        }
        m = chunk.metadata or {}
        meta["title"] = m.get("title", "")
        meta["section"] = m.get("section", "")
        meta["source_agency"] = m.get("source_agency", "")
        meta["effective_date"] = m.get("effective_date", "")
        meta["topic_tags"] = m.get("topic_tags", [])
        meta["property_types"] = m.get("property_types", [])
        meta["citizenship_types"] = m.get("citizenship_types", [])
        return meta
