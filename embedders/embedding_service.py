"""OpenAI embedding service — batches DocumentChunks and returns vectors."""

from typing import Iterator

import tiktoken
from openai import OpenAI
from tenacity import retry, stop_after_attempt, wait_exponential

from config.logger import get_logger
from config.settings import settings
from embedders.models import EmbeddingResult
from processors.models import DocumentChunk

EMBEDDING_MODEL = "text-embedding-3-large"
EMBEDDING_DIM = 3072
TOKEN_LIMIT_PER_BATCH = 250_000  # OpenAI cap is 300k; 250k leaves headroom

logger = get_logger("embedding_service")


class EmbeddingService:
    """Embeds DocumentChunks via OpenAI text-embedding-3-large.

    Chunks are sent in batches (default 2048 per request — OpenAI's max).
    Each call is retried up to 3 times with exponential backoff on failure.
    Token usage is logged after every batch for cost tracking.
    """

    def __init__(
        self,
        api_key: str | None = None,
        batch_size: int = 2048,
    ) -> None:
        self._client = OpenAI(api_key=api_key or settings.openai_api_key)
        self._batch_size = batch_size

    def embed_chunks(self, chunks: list[DocumentChunk]) -> list[EmbeddingResult]:
        if not chunks:
            return []

        results: list[EmbeddingResult] = []
        total_tokens = 0

        for batch in self._batches(chunks):
            texts = [c.chunk_text for c in batch]
            vectors, token_count = self._embed_batch(texts)
            total_tokens += token_count
            per_chunk_tokens = token_count // len(batch) if batch else 0

            for chunk, vector in zip(batch, vectors):
                results.append(
                    EmbeddingResult(
                        chunk=chunk,
                        embedding=vector,
                        token_count=per_chunk_tokens,
                        model=EMBEDDING_MODEL,
                    )
                )

            logger.info(
                "embedding_service.batch_done",
                batch_size=len(batch),
                tokens=token_count,
            )

        logger.info(
            "embedding_service.complete",
            total_chunks=len(chunks),
            total_tokens=total_tokens,
        )
        return results

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        reraise=True,
    )
    def _embed_batch(self, texts: list[str]) -> tuple[list[list[float]], int]:
        response = self._client.embeddings.create(
            model=EMBEDDING_MODEL,
            input=texts,
        )
        # Sort by index — OpenAI doesn't guarantee response order
        vectors = [
            item.embedding for item in sorted(response.data, key=lambda x: x.index)
        ]
        return vectors, response.usage.total_tokens

    def _batches(
        self, chunks: list[DocumentChunk]
    ) -> Iterator[list[DocumentChunk]]:
        """Yield batches respecting both item count and token limits."""
        enc = tiktoken.get_encoding("cl100k_base")
        current_batch: list[DocumentChunk] = []
        current_tokens = 0

        for chunk in chunks:
            n = len(enc.encode(chunk.chunk_text))
            if current_batch and (
                current_tokens + n > TOKEN_LIMIT_PER_BATCH
                or len(current_batch) >= self._batch_size
            ):
                yield current_batch
                current_batch = []
                current_tokens = 0
            current_batch.append(chunk)
            current_tokens += n

        if current_batch:
            yield current_batch
