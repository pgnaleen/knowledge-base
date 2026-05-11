"""Embedding pipeline — embeds processed_chunks and upserts to vector stores."""

import json
from datetime import date

import openai

import tiktoken
from sqlalchemy import text

from config.database import engine
from config.logger import get_logger
from config.storage import upload_embeddings
from embedders.embedding_service import EmbeddingService
from embedders.pgvector_store import PgVectorStore
from embedders.pinecone_store import PineconeStore
from processors.models import DocumentChunk

logger = get_logger("embedding_pipeline")
_TIKTOKEN = tiktoken.get_encoding("cl100k_base")

# Fetch processed_chunks not yet embedded.
_UNEMBEDDED_CHUNKS_SQL = """
    SELECT pc.id, pc.chunk_text, pc.chunk_index, pc.token_count,
           pc.metadata_json, rd.url AS source_url, rd.content_type, s.code AS source_code
    FROM processed_chunks pc
    JOIN raw_documents rd ON pc.document_id = rd.id
    JOIN sources s ON rd.source_id = s.id
    WHERE pc.embedding_id IS NULL
    {source_filter}
    ORDER BY pc.id
"""


class EmbeddingPipeline:
    """Embeds processed_chunks and upserts to Pinecone (primary) and pgvector (fallback).

    Reads unembedded rows from processed_chunks, calls OpenAI, writes vectors to
    Pinecone namespaces and pgvector, then updates embedding_id in the DB.
    """

    def __init__(
        self,
        openai_api_key: str | None = None,
        pinecone_api_key: str | None = None,
        pinecone_index: str | None = None,
        use_pinecone: bool = True,
    ) -> None:
        self._engine = engine
        self._embedding_service = EmbeddingService(api_key=openai_api_key)
        self._use_pinecone = use_pinecone
        self._pinecone_store: PineconeStore | None = None
        if use_pinecone:
            try:
                self._pinecone_store = PineconeStore(
                    api_key=pinecone_api_key,
                    index_name=pinecone_index,
                )
            except Exception as exc:
                logger.warning("pipeline.pinecone_init_failed", error=str(exc))
                self._pinecone_store = None
        self._pgvector_store = PgVectorStore()

    def embed_chunks(self, source_code: str | None = None) -> int:
        """Embed unembedded processed_chunks and upsert to vector store."""
        source_filter, params = _source_filter(source_code)
        sql = _UNEMBEDDED_CHUNKS_SQL.format(source_filter=source_filter)

        with self._engine.connect() as conn:
            rows = conn.execute(text(sql), params).fetchall()

        if not rows:
            logger.info("pipeline.embed_chunks_done", embedded=0)
            return 0

        db_ids: list = []
        chunks: list[DocumentChunk] = []

        for row in rows:
            chunk_id, chunk_text_val, chunk_index, token_count, metadata_json, source_url, content_type, src_code = row
            db_ids.append(chunk_id)
            chunks.append(
                DocumentChunk(
                    chunk_text=chunk_text_val,
                    chunk_index=chunk_index,
                    chunk_type=(metadata_json or {}).get("chunk_type", "text"),
                    heading_path=(metadata_json or {}).get("heading_path", []),
                    metadata=metadata_json or {},
                    source_url=source_url or "",
                    source_name=src_code,
                    content_type=content_type or "html",
                    word_count=len(chunk_text_val.split()),
                    token_count=token_count or 0,
                )
            )

        logger.info("embed.started", source=source_code or "all", chunks=len(chunks))

        try:
            results = self._embedding_service.embed_chunks(chunks)
        except openai.AuthenticationError as exc:
            logger.error(
                "pipeline.openai_auth_failed",
                error=str(exc),
                hint="Check that OPENAI_API_KEY is set and not expired. Chunks remain unembedded and will be retried on next run.",
            )
            return 0

        id_map: dict = {}
        store_used = "pgvector"
        if self._pinecone_store is not None:
            try:
                logger.info("pinecone.storing", source=source_code or "all", chunks=len(results))
                id_map = self._pinecone_store.upsert(results, db_ids)
                store_used = "pinecone"
            except Exception as exc:
                logger.warning("pipeline.pinecone_upsert_failed", error=str(exc))
                logger.info("pgvector.storing", source=source_code or "all", chunks=len(results), reason="pinecone_fallback")
                id_map = self._pgvector_store.upsert(results, db_ids)
        else:
            logger.info("pgvector.storing", source=source_code or "all", chunks=len(results))
            id_map = self._pgvector_store.upsert(results, db_ids)

        # Archive embeddings to S3
        batch_id = date.today().isoformat()
        for db_id, result in zip(db_ids, results):
            vector_id = id_map.get(db_id)
            if vector_id:
                payload = json.dumps(
                    {
                        "vector_id": vector_id,
                        "model": result.model,
                        "token_count": result.token_count,
                        "embedding": result.embedding,
                        "source_name": result.chunk.source_name,
                        "source_url": result.chunk.source_url,
                        "chunk_index": result.chunk.chunk_index,
                        "metadata": result.chunk.metadata,
                    }
                )
                try:
                    upload_embeddings(f"{batch_id}/{vector_id}", payload)
                except Exception as exc:
                    logger.warning("pipeline.s3_archive_failed", vector_id=vector_id, error=str(exc))

        # Update embedding_id in DB
        with self._engine.begin() as conn:
            for chunk_id, vector_id in id_map.items():
                conn.execute(
                    text(
                        "UPDATE processed_chunks SET embedding_id = :eid WHERE id = :id"
                    ),
                    {"eid": vector_id, "id": chunk_id},
                )

        logger.info("pipeline.embed_chunks_done", source=source_code or "all", embedded=len(results), store=store_used)
        return len(results)


def _source_filter(source_code: str | None) -> tuple[str, dict]:
    """Return (SQL fragment, params dict) for optional source filtering."""
    if source_code:
        return "AND s.code = :source_code", {"source_code": source_code.lower()}
    return "", {}
