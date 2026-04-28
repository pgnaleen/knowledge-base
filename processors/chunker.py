"""
Chunker - Splits extracted plain text into overlapping token-aware chunks.

Strategy:
  - 512-token target chunk size with 64-token overlap (per CLAUDE.md).
  - Uses LangChain's RecursiveCharacterTextSplitter (token-based).
  - Preserves heading context in each chunk's metadata.
"""

from dataclasses import dataclass, field

from config.logger import get_logger

logger = get_logger("chunker")

# Approx chars per token for English government text (conservative)
_CHARS_PER_TOKEN = 4
CHUNK_TOKENS = 512
OVERLAP_TOKENS = 64
CHUNK_CHARS = CHUNK_TOKENS * _CHARS_PER_TOKEN    # 2048
OVERLAP_CHARS = OVERLAP_TOKENS * _CHARS_PER_TOKEN  # 256


@dataclass
class TextChunk:
    """A single chunk ready for embedding."""
    text: str
    chunk_index: int
    heading_path: str = ""
    token_count: int = 0
    metadata: dict = field(default_factory=dict)


class Chunker:
    """
    Split a document's text into overlapping chunks using
    LangChain's RecursiveCharacterTextSplitter.
    """

    def __init__(
        self,
        chunk_size: int = CHUNK_TOKENS,
        chunk_overlap: int = OVERLAP_TOKENS,
    ):
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self._splitter = self._build_splitter()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def chunk_text(
        self,
        text: str,
        heading_path: str = "",
        base_metadata: dict | None = None,
    ) -> list[TextChunk]:
        """
        Split *text* into overlapping chunks.

        Args:
            text:          Clean plain text to chunk.
            heading_path:  Heading context string (e.g. "Eligibility > Citizens").
            base_metadata: Extra key/value pairs to attach to every chunk.

        Returns:
            Ordered list of TextChunk objects.
        """
        if not text or not text.strip():
            return []

        raw_chunks = self._splitter.split_text(text)
        chunks: list[TextChunk] = []

        for i, chunk_text in enumerate(raw_chunks):
            chunk_text = chunk_text.strip()
            if not chunk_text:
                continue

            token_count = self._estimate_tokens(chunk_text)

            meta = dict(base_metadata or {})
            meta["chunk_index"] = i
            meta["heading_path"] = heading_path

            chunks.append(
                TextChunk(
                    text=chunk_text,
                    chunk_index=i,
                    heading_path=heading_path,
                    token_count=token_count,
                    metadata=meta,
                )
            )

        logger.debug(
            "text_chunked",
            input_chars=len(text),
            chunks=len(chunks),
            heading_path=heading_path,
        )
        return chunks

    def chunk_sections(
        self,
        sections: list[dict],
        base_metadata: dict | None = None,
    ) -> list[TextChunk]:
        """
        Chunk a list of {heading, text} sections produced by HTMLExtractor.

        Each section is chunked independently so that heading context is
        preserved accurately.  Chunk indices are global across all sections.
        """
        all_chunks: list[TextChunk] = []
        global_index = 0

        for section in sections:
            heading = section.get("heading", "")
            text = section.get("text", "")
            if not text.strip():
                continue

            section_chunks = self.chunk_text(
                text=text,
                heading_path=heading,
                base_metadata=base_metadata,
            )

            # Re-index globally
            for chunk in section_chunks:
                chunk.chunk_index = global_index
                chunk.metadata["chunk_index"] = global_index
                global_index += 1
                all_chunks.append(chunk)

        return all_chunks

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _build_splitter(self):
        """Build a LangChain RecursiveCharacterTextSplitter."""
        try:
            from langchain_text_splitters import RecursiveCharacterTextSplitter

            return RecursiveCharacterTextSplitter(
                chunk_size=self.chunk_size * _CHARS_PER_TOKEN,
                chunk_overlap=self.chunk_overlap * _CHARS_PER_TOKEN,
                separators=["\n\n", "\n", ". ", " ", ""],
                length_function=len,
            )
        except ImportError:
            # Fallback: try the older langchain package
            try:
                from langchain.text_splitter import RecursiveCharacterTextSplitter

                return RecursiveCharacterTextSplitter(
                    chunk_size=self.chunk_size * _CHARS_PER_TOKEN,
                    chunk_overlap=self.chunk_overlap * _CHARS_PER_TOKEN,
                    separators=["\n\n", "\n", ". ", " ", ""],
                    length_function=len,
                )
            except ImportError:
                logger.warning(
                    "langchain_not_found_using_simple_splitter"
                )
                return _SimpleSplitter(
                    chunk_size=CHUNK_CHARS,
                    chunk_overlap=OVERLAP_CHARS,
                )

    @staticmethod
    def _estimate_tokens(text: str) -> int:
        """Fast token estimate: chars / 4 (good enough for metadata)."""
        return max(1, len(text) // _CHARS_PER_TOKEN)


class _SimpleSplitter:
    """Minimal fallback splitter (no LangChain dependency)."""

    def __init__(self, chunk_size: int, chunk_overlap: int):
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap

    def split_text(self, text: str) -> list[str]:
        chunks = []
        start = 0
        while start < len(text):
            end = start + self.chunk_size
            chunks.append(text[start:end])
            start += self.chunk_size - self.chunk_overlap
        return chunks
