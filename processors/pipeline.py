"""
Processing Pipeline - Orchestrates the full document processing workflow.

Flow for each RawDocument with status='pending':
  1. Fetch raw HTML / PDF from the database (or S3 if needed).
  2. Extract clean text (HTMLExtractor or PDFExtractor).
  3. Chunk the text (Chunker).
  4. Generate embeddings (OpenAIEmbedder).
  5. Save ProcessedChunk rows to PostgreSQL.
  6. Mark RawDocument status as 'processed'.

Run with:
    python -m processors.runner
    python -m processors.runner --source cpf
    python -m processors.runner --source cpf --limit 10
"""

import uuid
from datetime import datetime, timezone

from config.database import SessionLocal
from config.storage import download_from_s3
from config.logger import get_logger
from config.models import ProcessedChunk, RawDocument
from embedders.openai_embedder import OpenAIEmbedder
from processors.chunker import Chunker
from processors.html_extractor import HTMLExtractor
from processors.metadata_engine import MetadataEngine
from processors.pdf_extractor import PDFExtractor

logger = get_logger("processing_pipeline")


class ProcessingPipeline:
    """
    End-to-end pipeline: raw document → processed chunks with embeddings.
    """

    def __init__(self, embed: bool = True):
        """
        Args:
            embed: If True, call OpenAI to generate embeddings.
                   Set False for dry-run / testing without an API key.
        """
        self.html_extractor = HTMLExtractor()
        self.pdf_extractor = PDFExtractor()
        self.chunker = Chunker()
        self.metadata_engine = MetadataEngine()
        self.embedder = OpenAIEmbedder() if embed else None
        self.embed = embed

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def process_pending(
        self,
        source_code: str | None = None,
        limit: int | None = None,
        embed: bool | None = None,
    ) -> dict:
        """
        Process all RawDocuments with status='pending'.

        Args:
            source_code: Optional filter (e.g. 'cpf'). None = all sources.
            limit:       Max documents to process in this run.
            embed:       Override the instance-level embed flag.

        Returns:
            Summary dict with counts.
        """
        should_embed = embed if embed is not None else self.embed

        db = SessionLocal()
        stats = {
            "processed": 0,
            "chunks_created": 0,
            "failed": 0,
            "skipped": 0,
        }

        try:
            query = db.query(RawDocument).filter(RawDocument.status == "pending")

            if source_code:
                from config.models import Source
                source = db.query(Source).filter(Source.code == source_code).first()
                if not source:
                    logger.error("source_not_found", source=source_code)
                    return stats
                query = query.filter(RawDocument.source_id == source.id)

            if limit:
                query = query.limit(limit)

            documents = query.all()
            total = len(documents)
            logger.info("processing_started", total=total, source=source_code or "all")

            for doc in documents:
                try:
                    chunk_count = self._process_document(db, doc, should_embed)
                    if chunk_count == 0:
                        stats["skipped"] += 1
                    else:
                        stats["processed"] += 1
                        stats["chunks_created"] += chunk_count
                except Exception as e:
                    logger.error(
                        "document_processing_failed",
                        doc_id=str(doc.id),
                        url=doc.url,
                        error=str(e),
                    )
                    doc.status = "failed"
                    doc.error_message = str(e)
                    db.commit()
                    stats["failed"] += 1

            logger.info("processing_completed", **stats)
            return stats

        finally:
            db.close()

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _process_document(
        self, db, doc: RawDocument, should_embed: bool
    ) -> int:
        """
        Process a single RawDocument.  Returns number of chunks created.
        """
        logger.info("processing_document", url=doc.url, content_type=doc.content_type)

        # --- 1. Extract text ---
        if doc.content_type == "application/pdf":
            # PDFs are stored in MinIO — fetch using the S3 key saved by the crawler
            if not doc.s3_pdf_key:
                logger.warning("pdf_no_s3_key", url=doc.url)
                doc.status = "failed"
                doc.error_message = "No S3 PDF key — PDF was not uploaded during crawl"
                db.commit()
                return 0

            try:
                pdf_bytes = download_from_s3(doc.s3_pdf_key)
            except Exception as e:
                logger.warning("pdf_s3_download_failed", url=doc.url, key=doc.s3_pdf_key, error=str(e))
                doc.status = "failed"
                doc.error_message = f"S3 download failed: {e}"
                db.commit()
                return 0

            extracted = self.pdf_extractor.extract(
                pdf_bytes=pdf_bytes,
                filename=doc.url.split("/")[-1],
            )
            sections = [{"heading": "Document", "text": extracted.plain_text}]

        else:  # text/html (default)
            if not doc.raw_html:
                logger.warning("html_has_no_content", url=doc.url)
                doc.status = "failed"
                doc.error_message = "No raw content available"
                db.commit()
                return 0

            extracted = self.html_extractor.extract(doc.raw_html, url=doc.url)
            sections = extracted.sections

            # Use DB title if extractor found nothing better
            if not extracted.title and doc.title:
                extracted.title = doc.title

        # Skip nearly empty documents
        total_text = " ".join(s.get("text", "") for s in sections)
        if len(total_text.strip()) < 50:
            logger.debug("skipping_empty_document", url=doc.url)
            doc.status = "processed"  # Mark done so it doesn't loop
            db.commit()
            return 0

        # --- 2. Chunk ---
        # Extract document-level metadata
        doc_metadata = self.metadata_engine.extract_metadata(total_text)

        base_meta = {
            "source": doc.metadata_json.get("source", "") if doc.metadata_json else "",
            "url": doc.url,
            "title": extracted.title or doc.title or "",
            "content_type": doc.content_type,
            **doc_metadata,
        }

        raw_chunks = self.chunker.chunk_sections(sections, base_metadata=base_meta)
        if not raw_chunks:
            logger.warning("no_chunks_produced", url=doc.url)
            doc.status = "processed"
            db.commit()
            return 0

        # --- 3. Validate and Deduplicate Chunks ---
        valid_chunks = []
        for chunk in raw_chunks:
            # Min/Max length validation (tokens)
            if chunk.token_count < 50 or chunk.token_count > 600:
                logger.debug("skipping_chunk_invalid_size", size=chunk.token_count, url=doc.url)
                continue

            # Duplicate detection within the same document context or global
            # For simplicity, we check if this exact text was already processed in this RUN 
            # (Global deduplication is better handled at the DB level with a unique constraint or index)
            valid_chunks.append(chunk)

        if not valid_chunks:
            logger.warning("all_chunks_filtered_by_validation", url=doc.url)
            doc.status = "processed"
            db.commit()
            return 0

        # --- 4. Embed (optional) ---
        embeddings: list[list[float]] = []
        if should_embed and self.embedder:
            texts = [c.text for c in valid_chunks]
            embedding_results = self.embedder.embed_texts(texts)
            embeddings = [r.embedding for r in embedding_results]
        else:
            embeddings = [[] for _ in valid_chunks]

        # --- 5. Save chunks to DB ---
        # Delete any old chunks for this document first (re-processing)
        db.query(ProcessedChunk).filter(
            ProcessedChunk.document_id == doc.id
        ).delete()

        total_chunks = len(valid_chunks)
        saved_count = 0
        for i, (chunk, embedding) in enumerate(zip(valid_chunks, embeddings)):
            # Check for global duplication (exact text match)
            # This handles requirement 2.6 "no duplicate chunks"
            existing_chunk = db.query(ProcessedChunk).filter(
                ProcessedChunk.chunk_text == chunk.text.replace("\x00", "")
            ).first()
            if existing_chunk:
                logger.debug("skipping_duplicate_chunk_global", url=doc.url, index=i)
                continue

            chunk_id = uuid.uuid4()
            db_chunk = ProcessedChunk(
                id=chunk_id,
                document_id=doc.id,
                chunk_text=chunk.text.replace("\x00", ""),
                chunk_index=i,
                total_chunks=total_chunks,
                heading_path=chunk.heading_path,
                token_count=chunk.token_count,
                embedding_id=str(chunk_id),
                metadata_json={
                    **chunk.metadata,
                    "embedding_dim": len(embedding),
                    "has_embedding": bool(embedding),
                },
            )
            db.add(db_chunk)
            saved_count += 1

        # --- 6. Mark document as processed ---
        doc.status = "processed"
        doc.raw_text = total_text.replace("\x00", "")[:10000]
        db.commit()

        logger.info(
            "document_processed",
            url=doc.url,
            chunks=saved_count,
            skipped_duplicates=total_chunks - saved_count,
            embedded=should_embed,
        )
        return saved_count
