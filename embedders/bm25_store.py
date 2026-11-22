"""BM25 sparse retrieval — in-memory full-text search via rank_bm25 library."""

import json
import threading
import time

from rank_bm25 import BM25Okapi
from sqlalchemy import text

from config.database import engine
from config.logger import get_logger
from config.settings import settings
from embedders.chunk_metadata_filters import chunk_matches_tag_filters

logger = get_logger("bm25_store")


class BM25Store:
    """In-memory BM25 index built from processed_chunks.

    Loads all embedded chunks and builds a BM25Okapi corpus for sparse
    (keyword-based) retrieval. Ranked alongside dense results via RRF.

    The index is rebuilt automatically when it is older than
    ``settings.bm25_refresh_seconds`` (checked lazily on query) and can be
    forced with ``build()``, so chunks embedded after API start become searchable.
    Rebuilds construct a new index first and swap it in atomically.
    """

    def __init__(self) -> None:
        self._embedding_ids: list[str] = []
        self._sources: list[str] = []
        self._metadata_json: list[dict] = []
        self._index: BM25Okapi | None = None
        self._built_at: float = 0.0
        self._build_lock = threading.Lock()

    def build(self) -> int:
        """Load all embedded chunks from DB and (re)build the BM25 index.

        Returns:
            Corpus size (number of chunks indexed).
        """
        with self._build_lock:
            with engine.connect() as conn:
                rows = conn.execute(text("""
                        SELECT pc.embedding_id, pc.chunk_text, s.code AS source_name,
                               pc.metadata_json
                        FROM processed_chunks pc
                        JOIN raw_documents rd ON pc.document_id = rd.id
                        JOIN sources s ON rd.source_id = s.id
                        WHERE pc.embedding_id IS NOT NULL
                          AND rd.status != 'deleted'
                        ORDER BY pc.embedding_id
                        """)).fetchall()

            self._built_at = time.monotonic()
            if not rows:
                logger.warning("bm25.corpus_empty")
                self._index = None
                self._embedding_ids, self._sources, self._metadata_json = [], [], []
                return 0

            embedding_ids = [row.embedding_id for row in rows]
            sources = [row.source_name for row in rows]
            metadata_json: list[dict] = []
            for row in rows:
                meta = row.metadata_json or {}
                if isinstance(meta, str):
                    meta = json.loads(meta)
                metadata_json.append(meta if isinstance(meta, dict) else {})
            index = BM25Okapi([row.chunk_text.lower().split() for row in rows])

            # Swap all fields together so concurrent queries never see a mixed state.
            self._embedding_ids, self._sources = embedding_ids, sources
            self._metadata_json, self._index = metadata_json, index

            logger.info("bm25.corpus_built", corpus_size=len(rows))
            return len(rows)

    @property
    def corpus_size(self) -> int:
        return len(self._embedding_ids)

    def _refresh_if_stale(self) -> None:
        ttl = settings.bm25_refresh_seconds
        if ttl <= 0 or time.monotonic() - self._built_at < ttl:
            return
        if self._build_lock.locked():
            return  # another request is already rebuilding; use the current index
        try:
            self.build()
        except Exception as exc:
            self._built_at = time.monotonic()  # back off until the next TTL window
            logger.warning("bm25.refresh_failed", error=str(exc))

    def query(
        self,
        query_text: str,
        top_k: int,
        source_filter: list[str] | None = None,
        property_type_filter: list[str] | None = None,
        citizenship_filter: list[str] | None = None,
        topic_filter: list[str] | None = None,
    ) -> list[tuple[str, float]]:
        """Score query against BM25 index. Returns (embedding_id, bm25_score) tuples.

        Args:
            query_text: The query string to score.
            top_k: Number of top results to return.
            source_filter: Optional list of source codes (e.g. ["hdb", "cpf"]).
                Only return results from these sources.
            property_type_filter: Optional chunk tag filter (``tags.property_type``).
            citizenship_filter: Optional chunk tag filter (``tags.citizenship``).
            topic_filter: Optional chunk tag filter (``tags.topic``).

        Returns:
            List of (embedding_id, bm25_score) sorted by score descending.
        """
        self._refresh_if_stale()

        # Snapshot references once: a concurrent rebuild swaps them as a group.
        index = self._index
        embedding_ids, sources, metadata_json = (
            self._embedding_ids,
            self._sources,
            self._metadata_json,
        )
        if index is None:
            logger.warning("bm25.index_not_built")
            return []

        tokens = query_text.lower().split()
        if not tokens:
            return []

        scores = index.get_scores(tokens)
        scored_ids = list(enumerate(scores))

        if source_filter:
            source_lower = {s.lower() for s in source_filter}
            scored_ids = [
                (i, s)
                for i, s in scored_ids
                if i < len(sources) and sources[i].lower() in source_lower
            ]

        scored_ids.sort(key=lambda x: x[1], reverse=True)

        out: list[tuple[str, float]] = []
        for i, score in scored_ids:
            if len(out) >= top_k:
                break
            if i >= len(embedding_ids):
                continue
            meta = metadata_json[i] if i < len(metadata_json) else {}
            if not chunk_matches_tag_filters(
                meta, property_type_filter, citizenship_filter, topic_filter
            ):
                continue
            out.append((embedding_ids[i], score))
        return out
