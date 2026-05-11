"""Runner script to orchestrate the processing of raw documents."""

import traceback

import structlog
from sqlalchemy.orm import Session

from config.database import SessionLocal
from config.logger import get_logger
from config.models import ProcessedChunk, RawDocument
from processors.chunker import DocumentChunker
from processors.metadata_extractor import MetadataExtractor
from processors.models import ExtractedDocument
from processors.validator import ChunkValidator

logger = get_logger("processor_runner")

def process_pending_documents():
    """Find all pending raw documents, chunk, validate, and save processed chunks."""
    db: Session = SessionLocal()

    metadata_extractor = MetadataExtractor()
    chunker = DocumentChunker()
    validator = ChunkValidator()

    try:
        pending_docs = db.query(RawDocument).filter(RawDocument.status == "pending").all()
        logger.info("process.batch_start", doc_count=len(pending_docs))

        success_count = 0
        failure_count = 0

        for doc in pending_docs:
            source_name = doc.source.code if doc.source else "unknown"
            structlog.contextvars.bind_contextvars(source=source_name, url=doc.url)

            try:
                logger.info("process.doc_start", doc_id=str(doc.id))

                if doc.status == "processed":
                    existing_chunks = db.query(ProcessedChunk).filter_by(document_id=doc.id).count()
                    if existing_chunks > 0:
                        logger.info("process.doc_skipped", doc_id=str(doc.id), chunk_count=existing_chunks)
                        continue

                extracted_doc: ExtractedDocument | None = None
                try:
                    source_name = doc.source.code if doc.source else ""
                    source_agency = doc.source.name if doc.source else ""
                    crawl_config = doc.source.crawl_config or {} if doc.source else {}
                    tag_config = crawl_config.get("tag_config")

                    # Build ExtractedDocument directly from raw_text (already extracted in Pipeline 1)
                    # No S3 download needed — raw_text is stored in DB from crawl time
                    if not doc.raw_text:
                        raise ValueError("Document has no raw_text — extraction failed at crawl time.")

                    extraction_flags = doc.extraction_flags or {}
                    extracted_doc = ExtractedDocument(
                        title=extraction_flags.get("title", ""),
                        text=doc.raw_text,  # Already contains tables as markdown inline
                        headings=extraction_flags.get("headings", []),  # Restored from extraction_flags
                        tables=[],    # Tables already merged inline as markdown
                        source_url=doc.url,
                        source_name=source_name,
                        content_type=doc.content_type or "html",
                        word_count=len(doc.raw_text.split()),
                        extraction_warnings=extraction_flags.get("warnings", []),
                    )

                    metadata = metadata_extractor.extract(
                        extracted_doc,
                        source_agency=source_agency,
                        tag_config=tag_config,
                    )

                    chunks = chunker.chunk(extracted_doc, metadata)
                    result = validator.validate(chunks)

                    db.query(ProcessedChunk).filter_by(document_id=doc.id).delete()

                    total_chunks = len(result.valid_chunks)
                    for chunk in result.valid_chunks:
                        chunk_meta = dict(chunk.metadata)
                        chunk_meta["parent_doc_id"] = str(doc.id)
                        chunk_meta["total_chunks"] = total_chunks
                        chunk_meta["heading_path"] = chunk.heading_path
                        db.add(ProcessedChunk(
                            document_id=doc.id,
                            chunk_text=chunk.chunk_text,
                            chunk_index=chunk.chunk_index,
                            token_count=chunk.token_count,
                            metadata_json=chunk_meta,
                        ))

                    for issue in result.issues:
                        if issue.severity == "error":
                            logger.warning(
                                "chunk.filtered",
                                url=doc.url,
                                chunk_index=issue.chunk_index,
                                reason=issue.message,
                            )

                    # raw_text, needs_ocr, extraction_flags already set by Pipeline 1
                    doc.status = "processed"
                    doc.error_message = None

                    db.commit()
                    success_count += 1
                    logger.info(
                        "process.doc_done",
                        doc_id=str(doc.id),
                        chunks_created=len(result.valid_chunks),
                        chunks_filtered=result.filtered_count,
                    )

                except Exception as e:
                    logger.error("process.doc_failed", doc_id=str(doc.id), error=str(e))
                    doc.status = "failed"
                    doc.error_message = str(e) + "\n" + traceback.format_exc()
                    db.commit()
                    failure_count += 1
            finally:
                structlog.contextvars.clear_contextvars()

        logger.info("process.batch_done", success=success_count, failed=failure_count)

    except Exception as e:
        logger.error("process.batch_failed", error=str(e))
        db.rollback()
    finally:
        db.close()

if __name__ == "__main__":
    process_pending_documents()
