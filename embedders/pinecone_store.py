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
                "pinecone.index_created",
                index=self._index_name,
                dimension=dimension,
            )
        else:
            logger.info("pinecone.index_exists", index=self._index_name)

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
            "pinecone.stored",
            index=self._index_name,
            chunks=len(results),
            namespaces=list(by_namespace.keys()),
            total_upserted=total_upserted,
        )
        return id_map

    def query(
        self,
        vector: list[float],
        top_k: int,
        filter_dict: dict | None = None,
        namespace: str = "all",
    ) -> list[dict]:
        """ANN search on Pinecone. Returns list of matches with id, score, and metadata."""
        results = self._query_with_retry(vector, top_k, filter_dict, namespace)
        matches = []
        for match in results.matches:
            matches.append(
                {
                    "id": match.id,
                    "score": match.score,
                    **match.metadata,
                }
            )
        logger.debug(
            "pinecone.query_complete",
            namespace=namespace,
            top_k=top_k,
            matches_returned=len(matches),
        )
        return matches

    def delete_all_in_namespace(self, namespace: str) -> None:
        """Delete every vector in a namespace. Used for full purge when DB is wiped."""
        self._index.delete(delete_all=True, namespace=namespace)
        logger.info("pinecone.namespace_purged", namespace=namespace)

    def delete_vectors(self, vector_ids: list[str], source_name: str) -> None:
        """Delete vectors from both source and 'all' namespaces by vector ID."""
        if not vector_ids:
            return
        namespaces = [source_name.lower(), "all"]
        total_deleted = 0
        for namespace in namespaces:
            for i in range(0, len(vector_ids), _PINECONE_UPSERT_BATCH):
                batch = vector_ids[i : i + _PINECONE_UPSERT_BATCH]
                self._delete_batch(batch, namespace)
                total_deleted += len(batch)
        logger.info(
            "pinecone.deleted",
            source=source_name,
            count=len(vector_ids),
            namespaces=namespaces,
        )

    @retry(
        stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=30), reraise=True
    )
    def _query_with_retry(
        self,
        vector: list[float],
        top_k: int,
        filter_dict: dict | None = None,
        namespace: str = "all",
    ):
        """Query the index with retry logic."""
        return self._index.query(
            vector=vector,
            top_k=top_k,
            filter=filter_dict,
            namespace=namespace,
            include_metadata=True,
        )

    @retry(
        stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=30), reraise=True
    )
    def _delete_batch(self, vector_ids: list[str], namespace: str) -> None:
        self._index.delete(ids=vector_ids, namespace=namespace)

    @retry(
        stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=30), reraise=True
    )
    def _upsert_batch(self, batch: list[dict], namespace: str) -> None:
        self._index.upsert(vectors=batch, namespace=namespace)

    @staticmethod
    def _build_metadata(result: EmbeddingResult) -> dict:
        chunk = result.chunk
        m = chunk.metadata or {}
        tags = m.get("tags", {})
        return {
            "source_name": chunk.source_name,
            "property_types": tags.get("property_type", []),
            "citizenship_types": tags.get("citizenship", []),
        }
