"""FastAPI application factory for the KB-Pipeline Retrieval API."""

from contextlib import asynccontextmanager
from typing import AsyncGenerator
from datetime import datetime

import structlog
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from api.dependencies import get_retrieval_service, init_services
from api.retrieval import RetrievalService
from api.schemas import (
    RetrieveRequest,
    RetrieveResponse,
    CrawlRequest,
    TaskResponse,
    JobsListResponse,
    TaskExecutionDetail,
)
from config.database import engine
from config.models import TaskExecution
from sqlalchemy.orm import Session
from sqlalchemy import desc

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


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    """Log invalid API payloads before returning FastAPI's normal 422 shape."""
    errors = jsonable_encoder(exc.errors())
    log.warning(
        "api.request_validation_failed",
        path=request.url.path,
        method=request.method,
        errors=errors,
    )
    return JSONResponse(status_code=422, content={"detail": errors})


@app.get("/health")
def health() -> dict:
    """Liveness check — returns 200 when the server is running."""
    return {"status": "ok"}


@app.get("/config")
def config() -> dict:
    """Return active configuration — used by eval scripts to verify the correct Pinecone index."""
    from config.settings import settings
    return {"pinecone_index": settings.pinecone_index, "pinecone_environment": settings.pinecone_environment}


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
        filters=request.filters.dict(exclude_none=True),
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


# ── Pipeline Task Endpoints ────────────────────────────────────────────────


@app.post("/crawl", response_model=TaskResponse, status_code=202)
def start_crawl(request: CrawlRequest) -> TaskResponse:
    """Start a crawl job for a specific source.

    Queues a Celery task to crawl the source with optional page limit and custom settings.
    Returns immediately with task_id for tracking.
    """
    from tasks.pipeline_tasks import run_source_pipeline_task

    log.info(
        "api.crawl_request_validated",
        source=request.source_code,
        job_type=request.job_type,
        page_limit=request.page_limit,
        has_custom_scrapy_settings=bool(request.scrapy_settings),
    )

    # Prepare Scrapy settings with page limit if provided
    scrapy_settings = request.scrapy_settings or {}
    if request.page_limit:
        scrapy_settings["CLOSESPIDER_PAGECOUNT"] = request.page_limit
        log.info(
            "api.crawl_page_limit_applied",
            source=request.source_code,
            page_limit=request.page_limit,
        )

    # Queue the Celery task
    log.info(
        "api.crawl_task_enqueue_started",
        source=request.source_code,
        job_type=request.job_type,
        scrapy_settings=scrapy_settings,
    )
    task = run_source_pipeline_task.delay(
        request.source_code,
        request.job_type,
        scrapy_settings=scrapy_settings,
    )

    log.info(
        "api.crawl_task_enqueued",
        source=request.source_code,
        job_type=request.job_type,
        task_id=task.id,
        page_limit=request.page_limit,
        scrapy_settings=scrapy_settings,
    )

    return TaskResponse(
        task_id=task.id,
        status="queued",
        source_code=request.source_code,
        job_type=request.job_type,
    )


@app.post("/process", response_model=TaskResponse, status_code=202)
def start_process() -> TaskResponse:
    """Start processing of all pending documents.

    Queues a Celery task to extract, chunk, and validate pending raw documents.
    Returns immediately with task_id for tracking.
    """
    from tasks.pipeline_tasks import process_documents_task

    log.info("process_requested")

    task = process_documents_task.delay()

    return TaskResponse(
        task_id=task.id,
        status="queued",
    )


@app.post("/embed", response_model=TaskResponse, status_code=202)
def start_embed() -> TaskResponse:
    """Start embedding of all unembedded chunks.

    Queues a Celery task to embed unembedded chunks and store in vector DB.
    Returns immediately with task_id for tracking.
    """
    from tasks.pipeline_tasks import embed_chunks_task

    log.info("embed_requested")

    task = embed_chunks_task.delay()

    return TaskResponse(
        task_id=task.id,
        status="queued",
    )


@app.get("/jobs", response_model=JobsListResponse)
def get_jobs(
    source: str | None = None,
    status: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> JobsListResponse:
    """Get task execution history with optional filtering.

    Returns paginated list of task executions with logs and results.
    """
    log.info(
        "jobs_query",
        source=source,
        status=status,
        limit=limit,
        offset=offset,
    )

    with Session(engine) as session:
        query = session.query(TaskExecution)

        if source:
            query = query.filter(TaskExecution.source_code == source)
        if status:
            query = query.filter(TaskExecution.status == status)

        total = query.count()
        executions = (
            query.order_by(desc(TaskExecution.created_at))
            .offset(offset)
            .limit(limit)
            .all()
        )

        jobs = [
            TaskExecutionDetail(
                task_id=ex.id,
                task_name=ex.task_name,
                source_code=ex.source_code,
                status=ex.status,
                started_at=ex.started_at.isoformat(),
                completed_at=ex.completed_at.isoformat() if ex.completed_at else None,
                result_summary=ex.result_summary or {},
                logs=ex.logs or [],
                error_message=ex.error_message,
            )
            for ex in executions
        ]

        return JobsListResponse(jobs=jobs, total=total)
