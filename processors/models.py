"""Shared data models for the processors pipeline."""

from dataclasses import asdict, dataclass, field


@dataclass
class ExtractedTable:
    """A single structured table extracted from HTML or PDF content."""

    headers: list[str]
    rows: list[list[str]]
    caption: str = ""
    page_number: int = 0  # PDF only; 0 for HTML tables
    source_tag: str = ""  # e.g. "table#stamp-duty-rates"


@dataclass
class ExtractedMetadata:
    """Document-level metadata enriched from an ExtractedDocument.

    Serialised to metadata_json (JSONB) per chunk in processed_chunks.
    """

    title: str
    source_agency: str  # "HDB" | "URA" | "IRAS" | "MAS" | "CPF" | ""
    section: str  # First h1/h2 heading, or title if no headings
    effective_date: str  # ISO "YYYY-MM-DD" string, or "" if not found
    property_types: list[str]  # e.g. ["HDB", "EC", "private"] or ["all"]
    citizenship_types: list[str]  # e.g. ["SC", "PR", "foreigner"] or ["all"]
    topic_tags: list[str]  # e.g. ["stamp_duty", "ABSD", "LTV"]
    metadata_warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class DocumentChunk:
    """A single embeddable unit produced by DocumentChunker.

    Maps 1:1 to a row in processed_chunks.
    """

    chunk_text: str
    chunk_index: int
    chunk_type: str  # "text" | "table"
    heading_path: list[dict]  # [{level, text}, ...] active at this position
    metadata: dict
    source_url: str
    source_name: str
    content_type: str  # "html" | "pdf"
    word_count: int


@dataclass
class ChunkValidationIssue:
    """A single validation issue found during chunk quality checking."""

    chunk_index: int  # -1 = document-level
    field: str
    severity: str  # "error" | "warning"
    message: str


@dataclass
class ValidationResult:
    """Output of ChunkValidator.validate()."""

    valid_chunks: list["DocumentChunk"]
    issues: list[ChunkValidationIssue]
    filtered_count: int

    @property
    def is_valid(self) -> bool:
        return self.filtered_count == 0

    @property
    def error_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == "error")

    @property
    def warning_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == "warning")


@dataclass
class ExtractedDocument:
    """Structured output produced by HTML and PDF extractors."""

    title: str
    text: str
    headings: list[dict] = field(default_factory=list)
    tables: list[ExtractedTable] = field(default_factory=list)
    source_url: str = ""
    source_name: str = ""
    content_type: str = "html"
    word_count: int = 0
    extraction_warnings: list[str] = field(default_factory=list)
