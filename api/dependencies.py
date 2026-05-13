"""Singleton service instances for the Retrieval API.

init_services() is called once from the FastAPI lifespan context manager.
get_retrieval_service() is used as a FastAPI dependency on each request.
"""

from config.logger import get_logger
from embedders.embedding_service import EmbeddingService
from embedders.pgvector_store import PgVectorStore
from embedders.pinecone_store import PineconeStore

from api.retrieval import RetrievalService

logger = get_logger("api.dependencies")

_retrieval_service: RetrievalService | None = None


def init_services() -> None:
    """Initialise all service singletons. Called once at application startup."""
    global _retrieval_service

    embedding_svc = EmbeddingService()

    pinecone: PineconeStore | None = None
    try:
        pinecone = PineconeStore()
    except Exception as exc:
        logger.warning("api.pinecone_unavailable", error=str(exc))

    _retrieval_service = RetrievalService(embedding_svc, pinecone, PgVectorStore())
    logger.info("api.services_ready", pinecone_available=pinecone is not None)


def get_retrieval_service() -> RetrievalService:
    """FastAPI dependency that returns the shared RetrievalService instance."""
    if _retrieval_service is None:
        raise RuntimeError("Services not initialised — init_services() was not called")
    return _retrieval_service
