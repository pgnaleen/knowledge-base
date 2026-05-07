"""Document chunking — splits ExtractedDocument into embeddable DocumentChunk objects."""

import tiktoken
from langchain_text_splitters import RecursiveCharacterTextSplitter

from config.logger import get_logger
from processors.models import DocumentChunk, ExtractedDocument, ExtractedMetadata
from processors.table_extractor import TableExtractor

logger = get_logger("chunker")

_DEFAULT_CHUNK_SIZE = 512
_DEFAULT_CHUNK_OVERLAP = 64
_enc = tiktoken.get_encoding("cl100k_base")


class DocumentChunker:
    """Splits an ExtractedDocument into embeddable DocumentChunk objects.

    Text is split using LangChain's RecursiveCharacterTextSplitter with tiktoken
    (cl100k_base) encoding so token counts match the OpenAI embedding model.
    Each ExtractedTable is appended as a separate Markdown-formatted chunk.
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
        )

    def chunk(
        self,
        doc: ExtractedDocument,
        metadata: ExtractedMetadata,
    ) -> list[DocumentChunk]:
        chunks: list[DocumentChunk] = []
        base_meta = metadata.to_dict()
        counter = 0

        if doc.text.strip():
            pieces = self._splitter.split_text(doc.text)
            piece_offsets = self._compute_piece_offsets(doc.text, pieces)
            for piece, offset in zip(pieces, piece_offsets):
                heading_path = self._heading_path_at(offset, doc.text, doc.headings)
                chunk_meta = {**base_meta, "chunk_index": counter, "chunk_type": "text"}
                chunks.append(
                    DocumentChunk(
                        chunk_text=piece,
                        chunk_index=counter,
                        chunk_type="text",
                        heading_path=heading_path,
                        metadata=chunk_meta,
                        source_url=doc.source_url,
                        source_name=doc.source_name,
                        content_type=doc.content_type,
                        word_count=len(piece.split()),
                        token_count=len(_enc.encode(piece)),
                    )
                )
                counter += 1

        for table in doc.tables:
            md = TableExtractor.to_markdown(table)
            if not md:
                continue
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

        logger.debug(
            "chunker.chunked",
            source_url=doc.source_url,
            source_name=doc.source_name,
            text_chunks=sum(1 for c in chunks if c.chunk_type == "text"),
            table_chunks=sum(1 for c in chunks if c.chunk_type == "table"),
            total_chunks=len(chunks),
        )
        return chunks

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
