"""Processors package — HTML/PDF extraction, chunking, and validation."""

from processors.chunker import DocumentChunker
from processors.html_extractor import ExtractionError, HTMLExtractor
from processors.metadata_extractor import MetadataExtractor
from processors.models import (
    ChunkValidationIssue,
    DocumentChunk,
    ExtractedDocument,
    ExtractedMetadata,
    ExtractedTable,
    ValidationResult,
)
from processors.pdf_extractor import PDFExtractionError, PDFExtractor
from processors.table_extractor import TableExtractor
from processors.validator import ChunkValidator

__all__ = [
    "ChunkValidationIssue",
    "ChunkValidator",
    "DocumentChunk",
    "DocumentChunker",
    "ExtractedDocument",
    "ExtractedMetadata",
    "ExtractedTable",
    "ExtractionError",
    "HTMLExtractor",
    "MetadataExtractor",
    "PDFExtractionError",
    "PDFExtractor",
    "TableExtractor",
    "ValidationResult",
]
