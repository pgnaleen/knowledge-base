"""BM25 sparse retrieval — in-memory full-text search via rank_bm25 library."""

import json

from rank_bm25 import BM25Okapi
from sqlalchemy import text

from config.database import engine
from config.logger import get_logger
from embedders.chunk_metadata_filters import chunk_matches_tag_filters

logger = get_logger("bm25_store")


class BM25Store:
    """In-memory BM25 index built from processed_chunks at startup.

    Loads all embedded chunks and builds a BM25Okapi corpus for sparse
    (keyword-based) retrieval. Ranked alongside dense results via RRF.
    """

    def __init__(self) -> None:
        self._embedding_ids: list[str] = []
        self._sources: list[str] = []
        self._metadata_json: list[dict] = []
        self._index: BM25Okapi | None = None

    def build(self) -> int:
        """Load all embedded chunks from DB and build BM25 index.

        Returns:
            Corpus size (number of chunks indexed).
        """
        with engine.connect() as conn:
            rows = conn.execute(text("""
                    SELECT pc.embedding_id, pc.chunk_text, s.code AS source_name,
                           pc.metadata_json
                    FROM processed_chunks pc
                    JOIN raw_documents rd ON pc.document_id = rd.id
                    JOIN sources s ON rd.source_id = s.id
                    WHERE pc.embedding_id IS NOT NULL
                    ORDER BY pc.embedding_id
                    """)).fetchall()

        if not rows:
            logger.warning("bm25.corpus_empty")
            return 0

        self._embedding_ids = [row.embedding_id for row in rows]
        self._sources = [row.source_name for row in rows]
        self._metadata_json = []
        for row in rows:
            meta = row.metadata_json or {}
            if isinstance(meta, str):
                meta = json.loads(meta)
            self._metadata_json.append(meta if isinstance(meta, dict) else {})
        tokenized = [row.chunk_text.lower().split() for row in rows]
        self._index = BM25Okapi(tokenized)

        logger.info("bm25.corpus_built", corpus_size=len(rows))
        return len(rows)

    def query(
        self,
        query_text: str,
        top_k: int,
        source_filter: list[str] | None = None,
        property_type_filter: list[str] | None = None,
        citizenship_filter: list[str] | None = None,
    ) -> list[tuple[str, float]]:
        """Score query against BM25 index. Returns (embedding_id, bm25_score) tuples.

        Args:
            query_text: The query string to score.
            top_k: Number of top results to return.
            source_filter: Optional list of source codes (e.g. ["hdb", "cpf"]).
                Only return results from these sources.
            property_type_filter: Optional chunk tag filter (``tags.property_type``).
            citizenship_filter: Optional chunk tag filter (``tags.citizenship``).

        Returns:
            List of (embedding_id, bm25_score) sorted by score descending.
        """
        if self._index is None:
            logger.warning("bm25.index_not_built")
            return []

        tokens = query_text.lower().split()
        if not tokens:
            return []

        scores = self._index.get_scores(tokens)
        scored_ids = list(enumerate(scores))

        if source_filter:
            source_lower = {s.lower() for s in source_filter}
            scored_ids = [
                (i, s)
                for i, s in scored_ids
                if i < len(self._sources) and self._sources[i].lower() in source_lower
            ]

        scored_ids.sort(key=lambda x: x[1], reverse=True)

        out: list[tuple[str, float]] = []
        for i, score in scored_ids:
            if len(out) >= top_k:
                break
            if i >= len(self._embedding_ids):
                continue
            meta = self._metadata_json[i] if i < len(self._metadata_json) else {}
            if not chunk_matches_tag_filters(meta, property_type_filter, citizenship_filter):
                continue
            out.append((self._embedding_ids[i], score))
        return out
