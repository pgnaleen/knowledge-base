"""FastAPI application factory for the KB-Pipeline Retrieval API."""

from contextlib import asynccontextmanager
from typing import AsyncGenerator

import structlog
from fastapi import Depends, FastAPI

from api.dependencies import get_retrieval_service, init_services
from api.retrieval import RetrievalService
from api.schemas import RetrieveRequest, RetrieveResponse

log = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Initialise shared services once at startup."""
    init_services()
    yield


app = FastAPI(
    title="KB-Pipeline Retrieval API",
    version="1.0.0",
    description="Semantic retrieval over Singapore property regulatory knowledge base.",
    lifespan=lifespan,
)


@app.get("/health")
def health() -> dict:
    """Liveness check — returns 200 when the server is running."""
    return {"status": "ok"}


@app.post("/retrieve", response_model=RetrieveResponse)
def retrieve(
    request: RetrieveRequest,
    svc: RetrievalService = Depends(get_retrieval_service),
) -> RetrieveResponse:
    """Retrieve the top-k most relevant chunks for a query."""
    log.info(
        "retrieve_request",
        query=request.query,
        top_k=request.top_k,
        search_mode=request.search_mode,
    )
    response = svc.retrieve(request)
    log.info(
        "retrieve_response",
        query=request.query,
        chunks_returned=len(response.results),
        latency_ms=response.latency_ms,
        store_used=response.store_used,
        top_score=round(response.results[0].score, 4) if response.results else None,
        top_title=response.results[0].title if response.results else None,
    )
    return response
