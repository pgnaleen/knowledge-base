"""Runner script to orchestrate the processing of raw documents."""

import traceback

from sqlalchemy.orm import Session

from config.database import SessionLocal
from config.logger import get_logger
from config.models import RawDocument
from config.storage import StorageClient
from processors.html_extractor import HTMLExtractor
from processors.metadata_extractor import MetadataExtractor
from processors.models import ExtractedDocument
from processors.pdf_extractor import PDFExtractor

logger = get_logger("processor_runner")

def format_tables_to_markdown(tables: list) -> str:
    """Format ExtractedTable objects into markdown strings to append to raw_text."""
    if not tables:
        return ""
    
    md = []
    for table in tables:
        if table.caption:
            md.append(f"### {table.caption}")
        
        if table.headers:
            header_row = "| " + " | ".join(table.headers) + " |"
            separator_row = "| " + " | ".join(["---"] * len(table.headers)) + " |"
            md.extend([header_row, separator_row])
        
        for row in table.rows:
            # Clean newlines from cells so it doesn't break markdown table
            clean_row = [str(cell).replace("\n", " ").replace("|", "\\|") for cell in row]
            md.append("| " + " | ".join(clean_row) + " |")
        
        md.append("")
    
    return "\n".join(md)

def process_pending_documents():
    """Find all pending raw documents, extract text and metadata, and update status."""
    db: Session = SessionLocal()
    storage = StorageClient()
    
    html_extractor = HTMLExtractor()
    pdf_extractor = PDFExtractor()
    metadata_extractor = MetadataExtractor()

    try:
        pending_docs = db.query(RawDocument).filter(RawDocument.status == "pending").all()
        logger.info("Starting processing batch", doc_count=len(pending_docs))

        success_count = 0
        failure_count = 0

        for doc in pending_docs:
            logger.info("Processing document", doc_id=str(doc.id), url=doc.url)
            
            extracted_doc: ExtractedDocument | None = None
            try:
                source_name = doc.source.code if doc.source else ""
                
                if doc.s3_html_key:
                    raw_bytes = storage.download_from_s3(doc.s3_html_key)
                    extracted_doc = html_extractor.extract(
                        html=raw_bytes,
                        source_url=doc.url,
                        source_name=source_name
                    )
                elif doc.s3_pdf_key:
                    raw_bytes = storage.download_from_s3(doc.s3_pdf_key)
                    extracted_doc = pdf_extractor.extract(
                        pdf_bytes=raw_bytes,
                        source_url=doc.url,
                        source_name=source_name
                    )
                else:
                    raise ValueError("Document has neither s3_html_key nor s3_pdf_key.")
                
                # Combine extracted text with markdown tables
                tables_md = format_tables_to_markdown(extracted_doc.tables)
                final_raw_text = extracted_doc.text
                if tables_md:
                    final_raw_text += "\n\n## Tables\n\n" + tables_md

                # Extract and enrich metadata
                metadata = metadata_extractor.extract(extracted_doc)
                
                # Update DB
                doc.raw_text = final_raw_text
                doc.metadata_json = metadata.to_dict()
                doc.status = "processed"
                doc.error_message = None
                
                db.commit()
                success_count += 1
                logger.info("Successfully processed document", doc_id=str(doc.id))

            except Exception as e:
                logger.error("Failed to process document", doc_id=str(doc.id), error=str(e))
                doc.status = "failed"
                doc.error_message = str(e) + "\n" + traceback.format_exc()
                db.commit()
                failure_count += 1
        
        logger.info("Finished processing batch", success=success_count, failed=failure_count)

    except Exception as e:
        logger.error("Database or execution error during processor runner", error=str(e))
        db.rollback()
    finally:
        db.close()

if __name__ == "__main__":
    process_pending_documents()
