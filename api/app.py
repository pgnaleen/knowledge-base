"""FastAPI application factory for the KB-Pipeline Retrieval API."""

from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import Depends, FastAPI

from api.dependencies import get_retrieval_service, init_services
from api.retrieval import RetrievalService
from api.schemas import RetrieveRequest, RetrieveResponse


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
    """Retrieve the top-k most relevant chunks for a query.

    Searches Pinecone (primary) with pgvector fallback. Supports optional
    filtering by source agency, property type, and citizenship type.
    """
    return svc.retrieve(request)
