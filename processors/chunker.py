"""Document chunking — splits ExtractedDocument into embeddable DocumentChunk objects."""

import re

import tiktoken
from langchain_text_splitters import RecursiveCharacterTextSplitter

from config.logger import get_logger
from processors.models import DocumentChunk, ExtractedDocument, ExtractedMetadata
from processors.table_extractor import TableExtractor

logger = get_logger("chunker")

_DEFAULT_CHUNK_SIZE = 512
_DEFAULT_CHUNK_OVERLAP = 64
_enc = tiktoken.get_encoding("cl100k_base")

_TABLE_LINE = re.compile(r"^\s*\|")
_TABLE_CAPTION_LINE = re.compile(r"^\*\*Table: ")


class DocumentChunker:
    """Splits an ExtractedDocument into embeddable DocumentChunk objects.

    Text is split using LangChain's RecursiveCharacterTextSplitter with tiktoken
    (cl100k_base) encoding so token counts match the OpenAI embedding model.
    Markdown tables embedded in the text (placed inline by the extractors) are kept
    atomic: each becomes its own ``chunk_type="table"`` chunk, and tables larger than
    ``chunk_size`` are split by row groups with the header row repeated in every piece.
    """

    def __init__(
        self,
        chunk_size: int = _DEFAULT_CHUNK_SIZE,
        chunk_overlap: int = _DEFAULT_CHUNK_OVERLAP,
    ) -> None:
        self._chunk_size = chunk_size
        self._chunk_overlap = chunk_overlap
        self._splitter = RecursiveCharacterTextSplitter.from_tiktoken_encoder(
            encoding_name="cl100k_base",
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            separators=["\n\n", "\n", " "],
        )

    def chunk(
        self,
        doc: ExtractedDocument,
        metadata: ExtractedMetadata,
    ) -> list[DocumentChunk]:
        logger.info(
            "chunker.started",
            source_url=doc.source_url,
            source_name=doc.source_name,
            content_type=doc.content_type,
            word_count=doc.word_count,
        )

        chunks: list[DocumentChunk] = []
        base_meta = metadata.to_dict()
        counter = 0

        if doc.text.strip():
            for kind, seg_offset, seg_text in self._split_segments(doc.text):
                if kind == "text":
                    if not seg_text.strip():
                        continue
                    pieces = self._splitter.split_text(seg_text)
                    offsets = self._compute_piece_offsets(seg_text, pieces)
                    for piece, local in zip(pieces, offsets):
                        heading_path = self._heading_path_at(
                            seg_offset + local, doc.text, doc.headings
                        )
                        chunks.append(
                            self._make_chunk(doc, base_meta, counter, "text", piece, heading_path)
                        )
                        counter += 1
                else:
                    heading_path = self._heading_path_at(seg_offset, doc.text, doc.headings)
                    for part in self._split_table_markdown(seg_text):
                        chunks.append(
                            self._make_chunk(
                                doc, base_meta, counter, "table", part, heading_path
                            )
                        )
                        counter += 1

        for table in doc.tables:
            md = TableExtractor.to_markdown(table)
            if not md or md in doc.text:
                continue  # empty, or already emitted as an inline table chunk
            chunk_meta = {
                **base_meta,
                "chunk_index": counter,
                "chunk_type": "table",
                "table_caption": table.caption,
                "table_source_tag": table.source_tag,
            }
            chunks.append(
                DocumentChunk(
                    chunk_text=md,
                    chunk_index=counter,
                    chunk_type="table",
                    heading_path=[],
                    metadata=chunk_meta,
                    source_url=doc.source_url,
                    source_name=doc.source_name,
                    content_type=doc.content_type,
                    word_count=len(md.split()),
                    token_count=len(_enc.encode(md)),
                )
            )
            counter += 1

        logger.info(
            "chunker.done",
            source_url=doc.source_url,
            source_name=doc.source_name,
            text_chunks=sum(1 for c in chunks if c.chunk_type == "text"),
            table_chunks=sum(1 for c in chunks if c.chunk_type == "table"),
            total_chunks=len(chunks),
        )
        return chunks

    def _make_chunk(
        self,
        doc: ExtractedDocument,
        base_meta: dict,
        index: int,
        chunk_type: str,
        text: str,
        heading_path: list[dict],
    ) -> DocumentChunk:
        return DocumentChunk(
            chunk_text=text,
            chunk_index=index,
            chunk_type=chunk_type,
            heading_path=heading_path,
            metadata={**base_meta, "chunk_index": index, "chunk_type": chunk_type},
            source_url=doc.source_url,
            source_name=doc.source_name,
            content_type=doc.content_type,
            word_count=len(text.split()),
            token_count=len(_enc.encode(text)),
        )

    @staticmethod
    def _split_segments(text: str) -> list[tuple[str, int, str]]:
        """Split text into ("text" | "table", start_offset, content) segments.

        A table is a run of Markdown table lines (starting with ``|``), optionally
        preceded by a ``**Table: caption**`` line.
        """
        lines = text.splitlines(keepends=True)
        segments: list[tuple[str, int, str]] = []
        pos = 0
        cur_kind: str | None = None
        cur_start = 0
        cur: list[str] = []
        for i, line in enumerate(lines):
            is_table = bool(_TABLE_LINE.match(line)) or (
                bool(_TABLE_CAPTION_LINE.match(line))
                and i + 1 < len(lines)
                and bool(_TABLE_LINE.match(lines[i + 1]))
            )
            kind = "table" if is_table else "text"
            if kind != cur_kind:
                if cur:
                    segments.append((cur_kind, cur_start, "".join(cur)))  # type: ignore[arg-type]
                cur_kind, cur_start, cur = kind, pos, []
            cur.append(line)
            pos += len(line)
        if cur:
            segments.append((cur_kind, cur_start, "".join(cur)))  # type: ignore[arg-type]
        return segments

    def _split_table_markdown(self, md: str) -> list[str]:
        """Return the table as one chunk, or row-group chunks (header repeated) if too large."""
        md = md.strip("\n")
        if len(_enc.encode(md)) <= self._chunk_size:
            return [md]
        lines = md.split("\n")
        sep_idx = next(
            (i for i, ln in enumerate(lines) if re.match(r"^\s*\|(\s*:?-{3,}:?\s*\|)+\s*$", ln)),
            None,
        )
        if sep_idx is None:
            return [md]
        header, rows = lines[: sep_idx + 1], lines[sep_idx + 1 :]
        parts: list[str] = []
        current: list[str] = []
        for row in rows:
            candidate = "\n".join(header + current + [row])
            if current and len(_enc.encode(candidate)) > self._chunk_size:
                parts.append("\n".join(header + current))
                current = []
            current.append(row)
        if current:
            parts.append("\n".join(header + current))
        return parts or [md]

    @staticmethod
    def _compute_piece_offsets(full_text: str, pieces: list[str]) -> list[int]:
        """Find each chunk's start offset in full_text, advancing the search cursor.

        Avoids the first-occurrence bug: each piece is searched starting from
        the previous piece's start, so repeated phrases land at the right offset.
        """
        offsets: list[int] = []
        cursor = 0
        for piece in pieces:
            idx = full_text.find(piece, cursor)
            if idx == -1:
                idx = full_text.find(piece)
                if idx == -1:
                    idx = cursor
            offsets.append(idx)
            cursor = max(cursor, idx + 1)
        return offsets

    @staticmethod
    def _heading_path_at(
        offset: int,
        full_text: str,
        headings: list[dict],
    ) -> list[dict]:
        """Return the active heading breadcrumb at the given offset.

        Walks all headings whose first-occurrence offset is <= the chunk's
        start offset, maintaining a level-keyed path (new h1 resets h2/h3 etc.).
        """
        if not headings or not full_text:
            return []

        heading_offsets: list[tuple[int, dict]] = []
        cursor = 0
        for h in headings:
            o = full_text.find(h["text"], cursor)
            if o == -1:
                o = full_text.find(h["text"])
            if o != -1:
                heading_offsets.append((o, h))
                cursor = max(cursor, o + len(h["text"]))

        active = [(o, h) for o, h in heading_offsets if o <= offset]
        active.sort(key=lambda x: x[0])

        path: dict[int, str] = {}
        for _, h in active:
            level = h["level"]
            path[level] = h["text"]
            for deeper in list(path.keys()):
                if deeper > level:
                    del path[deeper]

        return [{"level": lvl, "text": path[lvl]} for lvl in sorted(path)]
