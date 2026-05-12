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

def process_pending_documents(source_codes: list[str] | None = None) -> list[dict]:
    """Find all pending raw documents, chunk, validate, and save processed chunks.

    Returns a per-source summary list for the terminal summary table.
    """
    db: Session = SessionLocal()

    metadata_extractor = MetadataExtractor()
    chunker = DocumentChunker()
    validator = ChunkValidator()

    # source_code -> {"docs": 0, "chunks": 0, "dropped": 0, "failed": 0}
    per_source: dict[str, dict] = {}

    def _src(code: str) -> dict:
        if code not in per_source:
            per_source[code] = {"docs": 0, "chunks": 0, "dropped": 0, "failed": 0}
        return per_source[code]

    try:
        from config.models import Source
        query = db.query(RawDocument).filter(RawDocument.status == "pending")
        if source_codes:
            query = query.join(Source).filter(Source.code.in_([c.lower() for c in source_codes]))
        pending_docs = query.all()
        logger.info("process.batch_start", doc_count=len(pending_docs))

        for doc in pending_docs:
            src_code = doc.source.code if doc.source else "unknown"
            structlog.contextvars.bind_contextvars(source=src_code, url=doc.url)

            try:
                logger.info("process.doc_start", doc_id=str(doc.id))

                try:
                    source_agency = doc.source.name if doc.source else ""
                    crawl_config = doc.source.crawl_config or {} if doc.source else {}
                    tag_config = crawl_config.get("tag_config")

                    if not doc.raw_text:
                        raise ValueError("Document has no raw_text — extraction failed at crawl time.")

                    extraction_flags = doc.extraction_flags or {}
                    extracted_doc = ExtractedDocument(
                        title=extraction_flags.get("title", ""),
                        text=doc.raw_text,
                        headings=extraction_flags.get("headings", []),
                        tables=[],
                        source_url=doc.url,
                        source_name=src_code,
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

                    doc.status = "processed"
                    doc.error_message = None
                    db.commit()

                    _src(src_code)["docs"] += 1
                    _src(src_code)["chunks"] += len(result.valid_chunks)
                    _src(src_code)["dropped"] += result.filtered_count
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
                    _src(src_code)["failed"] += 1
            finally:
                structlog.contextvars.clear_contextvars()

        total_docs = sum(s["docs"] for s in per_source.values())
        total_chunks = sum(s["chunks"] for s in per_source.values())
        total_dropped = sum(s["dropped"] for s in per_source.values())
        total_failed = sum(s["failed"] for s in per_source.values())
        avg_chunks = round(total_chunks / total_docs, 1) if total_docs else 0
        logger.info(
            "process.batch_done",
            docs_total=len(pending_docs),
            docs_success=total_docs,
            docs_failed=total_failed,
            chunks_created=total_chunks,
            chunks_filtered=total_dropped,
            avg_chunks_per_doc=avg_chunks,
        )

    except Exception as e:
        logger.error("process.batch_failed", error=str(e))
        db.rollback()
    finally:
        db.close()

    return [
        {
            "source": code,
            "docs": s["docs"],
            "chunks": s["chunks"],
            "dropped": s["dropped"],
            "avg_chunks": round(s["chunks"] / s["docs"], 1) if s["docs"] else 0,
            "failed": s["failed"],
        }
        for code, s in sorted(per_source.items())
    ]

if __name__ == "__main__":
    process_pending_documents()
