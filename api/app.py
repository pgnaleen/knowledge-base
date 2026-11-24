"""FastAPI application for the KB-Pipeline Retrieval + pipeline-control API."""

import secrets
from contextlib import asynccontextmanager
from typing import AsyncGenerator

import structlog
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import desc, text
from sqlalchemy.orm import Session

from api.dependencies import get_retrieval_service, init_services
from api.retrieval import RetrievalService
from api.schemas import (
    CrawlRequest,
    JobsListResponse,
    RetrieveRequest,
    RetrieveResponse,
    SourceStats,
    StatsResponse,
    TaskExecutionDetail,
    TaskResponse,
)
from config.database import engine
from config.models import Source, TaskExecution
from config.settings import settings

log = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Initialise shared services once at startup."""
    init_services()
    yield


app = FastAPI(
    title="KB-Pipeline Retrieval API",
    version="1.1.0",
    description="Semantic retrieval over Singapore property regulatory knowledge base, "
    "plus pipeline control and monitoring endpoints.",
    lifespan=lifespan,
)


def require_admin(x_api_key: str | None = Header(default=None)) -> None:
    """Protect pipeline-control endpoints when ADMIN_API_KEY is configured."""
    if not settings.admin_api_key:
        return  # open: local development only
    if not x_api_key or not secrets.compare_digest(x_api_key, settings.admin_api_key):
        raise HTTPException(status_code=401, detail="Invalid or missing X-API-Key")


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    """Log invalid API payloads before returning FastAPI's normal 422 shape."""
    errors = jsonable_encoder(exc.errors())
    log.warning("api.request_validation_failed", path=request.url.path, errors=errors)
    return JSONResponse(status_code=422, content={"detail": errors})


@app.get("/health")
def health() -> dict:
    """Liveness check — returns 200 when the server is running."""
    return {"status": "ok"}


@app.get("/config", dependencies=[Depends(require_admin)])
def config() -> dict:
    """Active vector-store configuration (used by eval scripts to verify the right index)."""
    return {
        "pinecone_index": settings.pinecone_index,
        "pinecone_environment": settings.pinecone_environment,
    }


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
        filters=request.filters.model_dump(exclude_none=True),
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


# ── Pipeline control (queued on Celery) ────────────────────────────────────


@app.post(
    "/crawl", response_model=TaskResponse, status_code=202, dependencies=[Depends(require_admin)]
)
def start_crawl(request: CrawlRequest) -> TaskResponse:
    """Queue crawl -> process -> embed for one source. Returns immediately with a task id."""
    from tasks.pipeline_tasks import run_source_pipeline_task

    with Session(engine) as session:
        known = session.query(Source).filter_by(code=request.source_code, is_active=True).first()
    if known is None:
        raise HTTPException(
            status_code=404, detail=f"Unknown or inactive source '{request.source_code}'"
        )

    scrapy_settings = dict(request.scrapy_settings or {})
    if request.page_limit:
        scrapy_settings["CLOSESPIDER_PAGECOUNT"] = request.page_limit

    task = run_source_pipeline_task.delay(
        request.source_code, request.job_type, scrapy_settings=scrapy_settings
    )
    log.info("api.crawl_enqueued", source=request.source_code, task_id=task.id)
    return TaskResponse(
        task_id=task.id, status="queued", source_code=request.source_code, job_type=request.job_type
    )


@app.post(
    "/process", response_model=TaskResponse, status_code=202, dependencies=[Depends(require_admin)]
)
def start_process() -> TaskResponse:
    """Queue processing of all pending documents."""
    from tasks.pipeline_tasks import process_documents_task

    return TaskResponse(task_id=process_documents_task.delay().id, status="queued")


@app.post(
    "/embed", response_model=TaskResponse, status_code=202, dependencies=[Depends(require_admin)]
)
def start_embed() -> TaskResponse:
    """Queue embedding of all un-embedded chunks."""
    from tasks.pipeline_tasks import embed_chunks_task

    return TaskResponse(task_id=embed_chunks_task.delay().id, status="queued")


@app.get("/jobs", response_model=JobsListResponse, dependencies=[Depends(require_admin)])
def get_jobs(
    source: str | None = None,
    status: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> JobsListResponse:
    """Paginated task execution history."""
    limit = max(1, min(limit, 200))
    offset = max(0, offset)
    with Session(engine) as session:
        query = session.query(TaskExecution)
        if source:
            query = query.filter(TaskExecution.source_code == source)
        if status:
            query = query.filter(TaskExecution.status == status)
        total = query.count()
        rows = query.order_by(desc(TaskExecution.created_at)).offset(offset).limit(limit).all()
        jobs = [
            TaskExecutionDetail(
                task_id=ex.id,
                task_name=ex.task_name,
                source_code=ex.source_code,
                status=ex.status,
                started_at=ex.started_at.isoformat() if ex.started_at else None,
                completed_at=ex.completed_at.isoformat() if ex.completed_at else None,
                result_summary=ex.result_summary or {},
                logs=ex.logs or [],
                error_message=ex.error_message,
            )
            for ex in rows
        ]
    return JobsListResponse(jobs=jobs, total=total)


# ── Monitoring ─────────────────────────────────────────────────────────────

_DOC_COUNTS_SQL = text(
    "SELECT s.code, rd.status, COUNT(*) FROM raw_documents rd "
    "JOIN sources s ON rd.source_id = s.id GROUP BY s.code, rd.status"
)
_CHUNK_COUNTS_SQL = text(
    "SELECT s.code, COUNT(pc.id), COUNT(pc.embedding_id), COALESCE(SUM(pc.token_count), 0) "
    "FROM processed_chunks pc JOIN raw_documents rd ON pc.document_id = rd.id "
    "JOIN sources s ON rd.source_id = s.id WHERE rd.status != 'deleted' GROUP BY s.code"
)
_LAST_CRAWL_SQL = text(
    "SELECT DISTINCT ON (s.code) s.code, cj.started_at, cj.status FROM crawl_jobs cj "
    "JOIN sources s ON cj.source_id = s.id ORDER BY s.code, cj.started_at DESC"
)


@app.get("/stats", response_model=StatsResponse, dependencies=[Depends(require_admin)])
def stats(svc: RetrievalService = Depends(get_retrieval_service)) -> StatsResponse:
    """Per-source document/chunk/embedding counts and last crawl status."""
    per: dict[str, SourceStats] = {}

    def entry(code: str) -> SourceStats:
        return per.setdefault(code, SourceStats(source=code))

    with engine.connect() as conn:
        for code, status, count in conn.execute(_DOC_COUNTS_SQL):
            entry(code).documents[status] = count
        for code, chunks, embedded, tokens in conn.execute(_CHUNK_COUNTS_SQL):
            e = entry(code)
            e.chunks, e.embedded_chunks, e.total_tokens = chunks, embedded, int(tokens)
        for code, started, status in conn.execute(_LAST_CRAWL_SQL):
            e = entry(code)
            e.last_crawl_at = started.isoformat() if started else None
            e.last_crawl_status = status

    sources = sorted(per.values(), key=lambda s: s.source)
    totals = {
        "documents": sum(sum(s.documents.values()) for s in sources),
        "chunks": sum(s.chunks for s in sources),
        "embedded_chunks": sum(s.embedded_chunks for s in sources),
        "unembedded_chunks": sum(s.chunks - s.embedded_chunks for s in sources),
    }
    return StatsResponse(sources=sources, totals=totals, bm25_corpus_size=svc.bm25_corpus_size)


@app.post("/admin/reindex-bm25", dependencies=[Depends(require_admin)])
def reindex_bm25(svc: RetrievalService = Depends(get_retrieval_service)) -> dict:
    """Rebuild the in-memory BM25 index now (e.g. right after an embed run)."""
    size = svc.reindex_bm25()
    if size is None:
        raise HTTPException(status_code=503, detail="BM25 store is not available")
    return {"bm25_corpus_size": size}
