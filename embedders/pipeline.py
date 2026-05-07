"""Embedding pipeline — processes raw docs into chunks and embeds them."""

import hashlib
import json
import uuid
from datetime import date

import tiktoken
from sqlalchemy import bindparam, text

from config.database import engine
from config.logger import get_logger
from config.storage import upload_embeddings, upload_processed_text
from embedders.embedding_service import EmbeddingService
from embedders.pgvector_store import PgVectorStore
from embedders.pinecone_store import PineconeStore
from processors import (
    ChunkValidator,
    DocumentChunker,
    ExtractionError,
    HTMLExtractor,
    MetadataExtractor,
)
from processors.models import DocumentChunk, ExtractedDocument

logger = get_logger("embedding_pipeline")
_TIKTOKEN = tiktoken.get_encoding("cl100k_base")

# Fetch raw_documents that have no processed_chunks rows yet.
# Adapted to my schema: document_id (UUID), s.code as source identifier.
_UNPROCESSED_DOCS_SQL = """
    SELECT rd.id, rd.url, rd.raw_html, rd.raw_text, s.code AS source_code
    FROM raw_documents rd
    JOIN sources s ON rd.source_id = s.id
    WHERE NOT EXISTS (
        SELECT 1 FROM processed_chunks pc WHERE pc.document_id = rd.id
    )
    AND (rd.raw_html IS NOT NULL OR rd.raw_text IS NOT NULL)
    {source_filter}
"""

# Fetch processed_chunks not yet embedded.
_UNEMBEDDED_CHUNKS_SQL = """
    SELECT pc.id, pc.chunk_text, pc.chunk_index, pc.heading_path,
           pc.metadata_json, rd.url AS source_url, s.code AS source_code
    FROM processed_chunks pc
    JOIN raw_documents rd ON pc.document_id = rd.id
    JOIN sources s ON rd.source_id = s.id
    WHERE pc.embedding_id IS NULL
    {source_filter}
    ORDER BY pc.id
"""


class EmbeddingPipeline:
    """End-to-end pipeline: raw_documents -> processed_chunks -> vector store.

    Two independent steps that can be run together or separately:
      1. process_documents — extract/chunk/validate raw HTML and PDF text,
         save valid chunks to processed_chunks (incremental: skips already-chunked docs).
      2. embed_chunks — read unembedded processed_chunks, call OpenAI, upsert to
         Pinecone (or pgvector fallback), and update processed_chunks.embedding_id.
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

    def run(self, source_code: str | None = None) -> dict:
        """Run both pipeline steps and return a stats dict."""
        docs_processed, chunks_saved = self.process_documents(source_code)
        chunks_embedded = self.embed_chunks(source_code)
        stats = {
            "docs_processed": docs_processed,
            "chunks_saved": chunks_saved,
            "chunks_embedded": chunks_embedded,
        }
        logger.info("pipeline.run_complete", source_code=source_code or "all", **stats)
        return stats

    def process_documents(self, source_code: str | None = None) -> tuple[int, int]:
        """Step 1 — extract and chunk unprocessed raw_documents."""
        source_filter, params = _source_filter(source_code)
        sql = _UNPROCESSED_DOCS_SQL.format(source_filter=source_filter)

        with self._engine.connect() as conn:
            rows = conn.execute(text(sql), params).fetchall()

        docs_processed = 0
        chunks_saved = 0
        processed_doc_ids: list = []

        for row in rows:
            doc_id, url, raw_html, raw_text, src_code = row
            try:
                saved = self._process_one_document(
                    doc_id, url, raw_html, raw_text, src_code
                )
                chunks_saved += saved
                docs_processed += 1
                processed_doc_ids.append(doc_id)
            except Exception as exc:
                logger.error(
                    "pipeline.doc_failed",
                    doc_id=str(doc_id),
                    url=url,
                    error=str(exc),
                )

        # Mark successfully-processed documents using explicit IDs — not a time window
        if processed_doc_ids:
            with self._engine.begin() as conn:
                conn.execute(
                    text(
                        "UPDATE raw_documents SET status = 'processed' WHERE id IN :ids"
                    ).bindparams(bindparam("ids", expanding=True)),
                    {"ids": processed_doc_ids},
                )

        logger.info(
            "pipeline.process_documents_done",
            source_code=source_code or "all",
            docs_processed=docs_processed,
            chunks_saved=chunks_saved,
        )
        return docs_processed, chunks_saved

    def embed_chunks(self, source_code: str | None = None) -> int:
        """Step 2 — embed unembedded processed_chunks and upsert to vector store."""
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
            chunk_id, chunk_text_val, chunk_index, heading_path, metadata_json, source_url, src_code = row
            db_ids.append(chunk_id)
            try:
                hp = json.loads(heading_path) if heading_path else []
            except (TypeError, json.JSONDecodeError):
                hp = []
            chunks.append(
                DocumentChunk(
                    chunk_text=chunk_text_val,
                    chunk_index=chunk_index,
                    chunk_type=(metadata_json or {}).get("chunk_type", "text"),
                    heading_path=hp,
                    metadata=metadata_json or {},
                    source_url=source_url or "",
                    source_name=src_code,
                    content_type="html",
                    word_count=len(chunk_text_val.split()),
                )
            )

        results = self._embedding_service.embed_chunks(chunks)

        id_map: dict = {}
        if self._pinecone_store is not None:
            try:
                id_map = self._pinecone_store.upsert(results, db_ids)
            except Exception as exc:
                logger.warning("pipeline.pinecone_upsert_failed", error=str(exc))
                id_map = self._pgvector_store.upsert(results, db_ids)
        else:
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

        logger.info("pipeline.embed_chunks_done", embedded=len(results))
        return len(results)

    def _process_one_document(
        self,
        doc_id,
        url: str,
        raw_html: str | None,
        raw_text: str | None,
        source_code: str,
    ) -> int:
        """Extract, chunk, validate and save one raw_document. Returns chunk count."""
        if raw_html:
            try:
                doc = HTMLExtractor().extract(
                    raw_html, source_url=url, source_name=source_code
                )
            except ExtractionError as exc:
                logger.warning(
                    "pipeline.extraction_failed", doc_id=str(doc_id), error=str(exc)
                )
                return 0
        else:
            doc = ExtractedDocument(
                title="",
                text=raw_text or "",
                source_url=url,
                source_name=source_code,
                content_type="pdf",
                word_count=len((raw_text or "").split()),
            )

        # Archive cleaned text to S3
        url_hash = hashlib.md5(url.encode()).hexdigest()[:12]
        try:
            upload_processed_text(source_code, url_hash, doc.text)
        except Exception as exc:
            logger.warning("pipeline.s3_processed_archive_failed", url=url, error=str(exc))

        metadata = MetadataExtractor().extract(doc)
        chunks = DocumentChunker().chunk(doc, metadata)
        result = ChunkValidator().validate(chunks)

        if not result.valid_chunks:
            return 0

        total = len(result.valid_chunks)
        with self._engine.begin() as conn:
            for chunk in result.valid_chunks:
                token_count = len(_TIKTOKEN.encode(chunk.chunk_text))
                heading_path_json = json.dumps(chunk.heading_path)
                conn.execute(
                    text("""
                        INSERT INTO processed_chunks
                            (id, document_id, chunk_text, chunk_index, total_chunks,
                             heading_path, token_count, metadata_json)
                        VALUES
                            (:id, :document_id, :chunk_text, :chunk_index, :total_chunks,
                             :heading_path, :token_count, CAST(:metadata_json AS JSON))
                        """),
                    {
                        "id": uuid.uuid4(),
                        "document_id": doc_id,
                        "chunk_text": chunk.chunk_text,
                        "chunk_index": chunk.chunk_index,
                        "total_chunks": total,
                        "heading_path": heading_path_json,
                        "token_count": token_count,
                        "metadata_json": json.dumps(chunk.metadata),
                    },
                )

        return total


def _source_filter(source_code: str | None) -> tuple[str, dict]:
    """Return (SQL fragment, params dict) for optional source filtering."""
    if source_code:
        return "AND s.code = :source_code", {"source_code": source_code.lower()}
    return "", {}
