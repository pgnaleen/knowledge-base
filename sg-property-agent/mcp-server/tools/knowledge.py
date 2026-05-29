"""KB-Pipeline retrieval tool — adapts between agent interface and KB-Pipeline schema."""

import asyncio
import os
from typing import Optional

import httpx

KB_PIPELINE_URL = os.getenv("KB_PIPELINE_URL", "http://localhost:8000")

_MAX_RETRIES = 3
_RETRY_BACKOFF = [0.5, 1.0, 2.0]  # seconds between attempts 1→2, 2→3


async def query_knowledge_base(
    query: str,
    source_filter: Optional[list[str]] = None,
    top_k: int = 5,
    search_mode: str = "hybrid",
) -> list[dict]:
    """
    Retrieve relevant property knowledge chunks from the KB-Pipeline.

    Retries up to 3 times with exponential backoff on network errors or 5xx responses.
    4xx errors are not retried (bad query/params — retrying won't help).

    Args:
        query: Search query in English
        source_filter: Optional list of sources to restrict to.
                       Valid values: hdb, iras, ura, mas, sla, bca, cea
        top_k: Number of chunks to return (1-50)
        search_mode: 'hybrid' (BM25 + vector) or 'vector'

    Returns:
        List of chunks, each with keys: text, source, url
    """
    # KB-Pipeline expects filters nested under "filters.source", not flat "source_filter"
    payload: dict = {
        "query": query,
        "top_k": top_k,
        "search_mode": search_mode,
    }
    if source_filter:
        payload["filters"] = {"source": source_filter}

    last_exc: Exception = RuntimeError("No attempts made")
    resp: Optional[httpx.Response] = None

    for attempt in range(_MAX_RETRIES):
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(f"{KB_PIPELINE_URL}/retrieve", json=payload)

            if resp.status_code < 500:
                # 2xx success or 4xx client error — stop retrying either way
                resp.raise_for_status()
                break

            # 5xx server error — will retry
            last_exc = RuntimeError(f"KB-Pipeline returned HTTP {resp.status_code}")

        except (httpx.TimeoutException, httpx.ConnectError, httpx.RemoteProtocolError) as exc:
            last_exc = exc

        # Sleep before next attempt (no sleep after the last attempt)
        if attempt < _MAX_RETRIES - 1:
            await asyncio.sleep(_RETRY_BACKOFF[attempt])

    else:
        raise RuntimeError(
            f"KB-Pipeline unreachable after {_MAX_RETRIES} attempts: {last_exc}"
        ) from last_exc

    raw_chunks: list[dict] = resp.json().get("results", [])

    # KB-Pipeline returns source_name / source_url — normalize to source / url
    # so agents keep the same field names they used before MCP migration
    return [
        {
            "text": chunk.get("text", ""),
            "source": chunk.get("source_name", "unknown"),
            "url": chunk.get("source_url", ""),
        }
        for chunk in raw_chunks
    ]
