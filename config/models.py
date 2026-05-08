"""Database models for the knowledge base pipeline."""

import uuid

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import relationship

from config.database import Base


class Source(Base):
    """Government source definition."""

    __tablename__ = "sources"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(100), nullable=False, unique=True)
    code = Column(String(20), nullable=False, unique=True)  # hdb, ura, iras, mas, cpf
    base_url = Column(String(500), nullable=False)
    crawl_config = Column(JSON, default=dict)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    documents = relationship("RawDocument", back_populates="source")


class RawDocument(Base):
    """Raw crawled document (HTML page or PDF)."""

    __tablename__ = "raw_documents"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source_id = Column(UUID(as_uuid=True), ForeignKey("sources.id"), nullable=False)
    url = Column(String(2000), nullable=False)
    content_hash = Column(String(64), nullable=False)  # SHA-256 of normalized extracted text
    content_type = Column(String(20))  # "html" or "pdf"
    raw_text = Column(Text)  # Normalized extracted text (populated at crawl time)
    s3_path = Column(String(500))  # Single S3 key, e.g. raw-html/hdb/2026-05-06/abc.html
    crawled_at = Column(DateTime, server_default=func.now())
    status = Column(
        Enum("pending", "processed", "failed", "deleted", name="document_status"),
        default="pending",
    )
    error_message = Column(Text)  # Last error traceback if status="failed"
    needs_ocr = Column(Boolean, default=False, nullable=False)
    extraction_flags = Column(JSON, default=dict)

    source = relationship("Source", back_populates="documents")
    chunks = relationship("ProcessedChunk", back_populates="document")

    __table_args__ = (
        UniqueConstraint("source_id", "url", name="uq_raw_documents_source_url"),
        Index("ix_raw_documents_source_url", "source_id", "url"),
        Index("ix_raw_documents_content_hash", "content_hash"),
        Index("ix_raw_documents_status", "status"),
        Index("ix_raw_documents_needs_ocr", "needs_ocr"),
    )


class ProcessedChunk(Base):
    """Processed and chunked text ready for embedding."""

    __tablename__ = "processed_chunks"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    document_id = Column(UUID(as_uuid=True), ForeignKey("raw_documents.id"), nullable=False)
    chunk_text = Column(Text, nullable=False)
    chunk_index = Column(Integer, nullable=False)  # Sequential within document, 0-based
    token_count = Column(Integer)
    embedding_id = Column(String(100))  # ID in vector store
    embedding = Column(Vector(3072))  # pgvector fallback storage
    metadata_json = Column(JSON, default=dict)  # Full chunk metadata (source_agency, tags, etc.)
    created_at = Column(DateTime, server_default=func.now())

    document = relationship("RawDocument", back_populates="chunks")

    __table_args__ = (
        Index("ix_processed_chunks_document", "document_id"),
        Index("ix_processed_chunks_embedding", "embedding_id"),
    )


class CrawlJob(Base):
    """Crawl job execution history."""

    __tablename__ = "crawl_jobs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source_id = Column(UUID(as_uuid=True), ForeignKey("sources.id"), nullable=False)
    job_type = Column(
        Enum("full", "incremental", name="crawl_job_type"),
        nullable=False,
    )
    status = Column(
        Enum("running", "completed", "failed", name="crawl_job_status"),
        default="running",
    )
    pages_found = Column(Integer, default=0)
    pages_new = Column(Integer, default=0)
    pages_changed = Column(Integer, default=0)
    pages_deleted = Column(Integer, default=0)
    pages_errored = Column(Integer, default=0)
    started_at = Column(DateTime, server_default=func.now())
    completed_at = Column(DateTime)
    error_message = Column(Text)

    source = relationship("Source")

    __table_args__ = (Index("ix_crawl_jobs_source_status", "source_id", "status"),)
