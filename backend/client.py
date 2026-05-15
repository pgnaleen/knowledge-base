"""HTTP client for KB-Pipeline /retrieve endpoint."""

import httpx
from dataclasses import dataclass


@dataclass
class Chunk:
    """Retrieved chunk from KB-Pipeline."""

    text: str
    source_url: str
    title: str
    score: float


class KBPipelineClient:
    """Client for KB-Pipeline retrieval API (async)."""

    def __init__(self, base_url: str) -> None:
        self._base_url = base_url.rstrip("/")

    async def retrieve(self, query: str, top_k: int = 5) -> list[Chunk]:
        """Query KB-Pipeline and return chunks.

        Args:
            query: The search query
            top_k: Number of results to return

        Returns:
            List of Chunk objects

        Raises:
            httpx.HTTPError: If KB-Pipeline is unavailable
        """
        async with httpx.AsyncClient(timeout=30) as http:
            resp = await http.post(
                f"{self._base_url}/retrieve",
                json={"query": query, "top_k": top_k, "search_mode": "hybrid"},
            )
            resp.raise_for_status()

        data = resp.json()
        return [
            Chunk(
                text=r["text"],
                source_url=r["source_url"],
                title=r["title"],
                score=r["score"],
            )
            for r in data["results"]
        ]
