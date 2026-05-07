"""Data models for the embeddings pipeline."""

from dataclasses import dataclass

from processors.models import DocumentChunk


@dataclass
class EmbeddingResult:
    """A DocumentChunk paired with its embedding vector."""

    chunk: DocumentChunk
    embedding: list[float]  # 3072-dim vector (text-embedding-3-large)
    token_count: int  # tokens consumed by this chunk — for cost tracking
    model: str  # e.g. "text-embedding-3-large"
