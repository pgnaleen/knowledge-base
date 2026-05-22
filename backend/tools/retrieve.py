import os
import time
import httpx
from langchain_core.tools import tool
from logging_config import get_logger

log = get_logger(__name__)


@tool
async def retrieve_property_info(query: str) -> str:
    """Search the Singapore property knowledge base for official rules, policies, and eligibility criteria.
    Use this for any question about ABSD, HDB eligibility, stamp duties, buying procedures, or property regulations.
    Returns relevant excerpts with source URLs from official Singapore government sites."""
    t0 = time.monotonic()
    try:
        kb_url = os.environ.get("KB_PIPELINE_URL", "")
        if not kb_url:
            log.error("kb_url_missing", error="KB_PIPELINE_URL env var not set")
            return "Knowledge base unavailable: KB_PIPELINE_URL is not configured."
        log.info("kb_retrieve_start", query=query, kb_url=kb_url)
        async with httpx.AsyncClient(timeout=30) as http:
            resp = await http.post(
                f"{kb_url}/retrieve",
                json={"query": query, "top_k": 5, "search_mode": "hybrid"},
            )
            resp.raise_for_status()
            data = resp.json()

        elapsed_ms = round((time.monotonic() - t0) * 1000)
        chunks = data.get("results", [])

        log.info(
            "kb_retrieve_done",
            query=query,
            chunks_returned=len(chunks),
            latency_ms=elapsed_ms,
            kb_latency_ms=data.get("latency_ms"),
            store_used=data.get("store_used"),
            top_score=round(chunks[0]["score"], 4) if chunks else None,
            top_title=chunks[0].get("title") if chunks else None,
        )

        if not chunks:
            return "(no results from knowledge base)"

        parts = []
        for i, chunk in enumerate(chunks, 1):
            parts.append(
                f"[{i}] {chunk.get('title', 'Untitled')} ({chunk.get('source_url', '')})\n{chunk.get('text', '')}"
            )
        return "\n\n".join(parts)

    except Exception as exc:
        elapsed_ms = round((time.monotonic() - t0) * 1000)
        log.error(
            "kb_retrieve_failed",
            query=query,
            error=str(exc),
            exc_type=type(exc).__name__,
            latency_ms=elapsed_ms,
        )
        return f"Knowledge base unavailable: {type(exc).__name__}: {exc}"
