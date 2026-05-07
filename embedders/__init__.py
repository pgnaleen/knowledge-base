"""Embedders package — OpenAI embedding service and vector store upsert."""

from embedders.embedding_service import EMBEDDING_DIM, EMBEDDING_MODEL, EmbeddingService
from embedders.models import EmbeddingResult
from embedders.pgvector_store import PgVectorStore
from embedders.pinecone_store import PineconeStore
from embedders.pipeline import EmbeddingPipeline

__all__ = [
    "EMBEDDING_DIM",
    "EMBEDDING_MODEL",
    "EmbeddingPipeline",
    "EmbeddingResult",
    "EmbeddingService",
    "PgVectorStore",
    "PineconeStore",
]
