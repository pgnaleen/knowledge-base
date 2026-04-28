"""
OpenAI Embedder - Generates vector embeddings using OpenAI's API.

Model: text-embedding-3-large (3072 dimensions) as per CLAUDE.md.
Handles batching, rate limiting, and retries automatically.
"""

import time
from dataclasses import dataclass

from config.logger import get_logger
from config.settings import settings

logger = get_logger("openai_embedder")

# OpenAI hard limit is 2048 inputs per batch; we stay well under it
_BATCH_SIZE = 100
_EMBEDDING_MODEL = "text-embedding-3-large"
_EMBEDDING_DIM = 3072


@dataclass
class EmbeddingResult:
    """A single embedding result."""
    text: str
    embedding: list[float]
    model: str
    token_count: int


class OpenAIEmbedder:
    """Generate embeddings via OpenAI text-embedding-3-large."""

    def __init__(self, model: str = _EMBEDDING_MODEL):
        self.model = model
        self._client = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def embed_texts(self, texts: list[str]) -> list[EmbeddingResult]:
        """
        Embed a list of text strings.

        Automatically batches requests and retries on transient errors.

        Args:
            texts: List of plain text strings to embed.

        Returns:
            List of EmbeddingResult in the same order as input.
        """
        if not texts:
            return []

        client = self._get_client()
        results: list[EmbeddingResult] = []

        for batch_start in range(0, len(texts), _BATCH_SIZE):
            batch = texts[batch_start : batch_start + _BATCH_SIZE]
            batch_results = self._embed_batch(client, batch)
            results.extend(batch_results)

        logger.info(
            "embeddings_generated",
            model=self.model,
            count=len(results),
        )
        return results

    def embed_single(self, text: str) -> list[float]:
        """Convenience method — embed one string and return the vector."""
        results = self.embed_texts([text])
        return results[0].embedding if results else []

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _get_client(self):
        """Lazy-initialize the OpenAI client."""
        if self._client is None:
            try:
                from openai import OpenAI
                api_key = settings.openai_api_key
                if not api_key or api_key == "sk-your-key-here":
                    raise ValueError(
                        "OPENAI_API_KEY is not set. "
                        "Please add your real key to the .env file."
                    )
                self._client = OpenAI(api_key=api_key)
            except ImportError:
                raise ImportError(
                    "openai package is not installed. "
                    "Run: pip install openai"
                )
        return self._client

    def _embed_batch(self, client, texts: list[str]) -> list[EmbeddingResult]:
        """Call OpenAI API for one batch, with simple retry logic."""
        max_retries = 3
        for attempt in range(1, max_retries + 1):
            try:
                response = client.embeddings.create(
                    model=self.model,
                    input=texts,
                )
                results = []
                for item in response.data:
                    results.append(
                        EmbeddingResult(
                            text=texts[item.index],
                            embedding=item.embedding,
                            model=self.model,
                            token_count=response.usage.total_tokens // len(texts),
                        )
                    )
                return results

            except Exception as e:
                error_str = str(e)
                logger.warning(
                    "embedding_batch_error",
                    attempt=attempt,
                    error=error_str,
                )
                if attempt < max_retries:
                    # Exponential back-off: 2s, 4s, 8s
                    time.sleep(2 ** attempt)
                else:
                    raise
