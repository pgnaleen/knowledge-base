"""Embedding service — OpenRouter primary, OpenAI fallback."""

import math
from typing import Iterator

import openai
import tiktoken
from openai import OpenAI
from tenacity import retry, retry_if_not_exception_type, stop_after_attempt, wait_exponential

from config.logger import get_logger
from config.settings import settings
from embedders.models import EmbeddingResult
from processors.models import DocumentChunk

EMBEDDING_MODEL = "text-embedding-3-large"
EMBEDDING_DIM = 3072
TOKEN_LIMIT_PER_BATCH = 250_000  # OpenAI cap is 300k; 250k leaves headroom

logger = get_logger("embedding_service")


class EmbeddingService:
    """Embeds DocumentChunks via OpenRouter (primary) with OpenAI fallback.

    Tries OpenRouter first on every batch. If OpenRouter fails after retries,
    falls back to OpenAI for that batch and all subsequent batches in the run.
    Chunks are batched by item count and token limits.
    Token usage is logged after every batch for cost tracking.
    """

    def __init__(
        self,
        api_key: str | None = None,
        batch_size: int = 2048,
    ) -> None:
        # api_key arg kept for backwards-compat — if passed, used as OpenAI key
        openrouter_key = settings.openrouter_api_key
        openai_key = api_key or settings.openai_api_key

        self._openrouter_client: OpenAI | None = None
        if openrouter_key:
            self._openrouter_client = OpenAI(
                api_key=openrouter_key,
                base_url=settings.openrouter_base_url,
            )
            logger.debug("embed.provider_configured", provider="openrouter")
        else:
            logger.debug(
                "embed.provider_skipped", provider="openrouter", reason="no OPENROUTER_API_KEY"
            )

        self._openai_client: OpenAI | None = None
        if openai_key:
            self._openai_client = OpenAI(api_key=openai_key)
            logger.debug("embed.provider_configured", provider="openai")
        else:
            logger.debug("embed.provider_skipped", provider="openai", reason="no OPENAI_API_KEY")

        self._batch_size = batch_size
        # Tracks which client is active for the current run — starts at primary
        self._active_provider: str = "openrouter" if self._openrouter_client else "openai"

        logger.info(
            "embedding_service_initialized",
            openrouter_available=self._openrouter_client is not None,
            openai_available=self._openai_client is not None,
            active_provider=self._active_provider,
        )

    def embed_chunks(self, chunks: list[DocumentChunk]) -> list[EmbeddingResult]:
        if not chunks:
            return []

        total_batches = math.ceil(len(chunks) / self._batch_size)
        logger.info(
            "embedding.started",
            total_chunks=len(chunks),
            model=EMBEDDING_MODEL,
            batches=total_batches,
            primary_provider=self._active_provider,
        )

        results: list[EmbeddingResult] = []
        total_tokens = 0
        batch_num = 0

        for batch in self._batches(chunks):
            batch_num += 1
            texts = [c.chunk_text for c in batch]
            vectors, token_count, provider_used = self._embed_batch_with_fallback(
                texts, batch_num, total_batches
            )
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
                "embed.batch_done",
                batch=batch_num,
                of=total_batches,
                chunks=len(batch),
                tokens=token_count,
                provider=provider_used,
                model=EMBEDDING_MODEL,
            )

        logger.info(
            "embed.complete",
            total_chunks=len(chunks),
            total_tokens=total_tokens,
            avg_tokens_per_chunk=total_tokens // len(chunks) if chunks else 0,
            model=EMBEDDING_MODEL,
        )
        return results

    def embed_query(self, query: str) -> list[float]:
        """Embed a single query string for retrieval."""
        if not query:
            raise ValueError("Query cannot be empty")

        vectors, _, _ = self._embed_batch_with_fallback([query], 1, 1)
        return vectors[0]

    def _embed_batch_with_fallback(
        self,
        texts: list[str],
        batch_num: int,
        total_batches: int,
    ) -> tuple[list[list[float]], int, str]:
        """Embed a batch. Tries OpenRouter first; falls back to OpenAI on failure."""
        if self._openrouter_client and self._active_provider == "openrouter":
            try:
                logger.debug(
                    "embed.batch_attempt",
                    batch=batch_num,
                    of=total_batches,
                    provider="openrouter",
                )
                vectors, tokens = self._call_api(self._openrouter_client, texts)
                return vectors, tokens, "openrouter"
            except openai.AuthenticationError as exc:
                logger.warning(
                    "embed.provider_auth_failed",
                    provider="openrouter",
                    error=str(exc),
                    action="switching to openai fallback for remaining batches",
                )
                self._active_provider = "openai"
            except Exception as exc:
                logger.warning(
                    "embed.provider_failed",
                    provider="openrouter",
                    batch=batch_num,
                    error=str(exc),
                    action="falling back to openai for this batch",
                )
                # Don't switch permanently on transient errors — only auth failures do that

        if self._openai_client:
            logger.debug(
                "embed.batch_attempt",
                batch=batch_num,
                of=total_batches,
                provider="openai",
            )
            vectors, tokens = self._call_api(self._openai_client, texts)
            return vectors, tokens, "openai"

        raise RuntimeError(
            "No embedding provider available — set OPENROUTER_API_KEY or OPENAI_API_KEY"
        )

    @retry(
        retry=retry_if_not_exception_type(openai.AuthenticationError),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        reraise=True,
    )
    def _call_api(self, client: OpenAI, texts: list[str]) -> tuple[list[list[float]], int]:
        """Call the embeddings API on a given client with retry logic."""
        response = client.embeddings.create(
            model=EMBEDDING_MODEL,
            input=texts,
        )
        vectors = [item.embedding for item in sorted(response.data, key=lambda x: x.index)]
        return vectors, response.usage.total_tokens

    def _batches(self, chunks: list[DocumentChunk]) -> Iterator[list[DocumentChunk]]:
        """Yield batches respecting both item count and token limits."""
        enc = tiktoken.get_encoding("cl100k_base")
        current_batch: list[DocumentChunk] = []
        current_tokens = 0

        for chunk in chunks:
            n = len(enc.encode(chunk.chunk_text))
            if current_batch and (
                current_tokens + n > TOKEN_LIMIT_PER_BATCH or len(current_batch) >= self._batch_size
            ):
                yield current_batch
                current_batch = []
                current_tokens = 0
            current_batch.append(chunk)
            current_tokens += n

        if current_batch:
            yield current_batch
