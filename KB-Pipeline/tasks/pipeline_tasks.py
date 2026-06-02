import structlog
from datetime import datetime
from sqlalchemy.orm import Session

from config.celery_app import app
from config.database import engine
from config.models import TaskExecution
from run_pipeline import run_full_pipeline
from config.notifications import notify_crawl_failure

logger = structlog.get_logger(__name__)


def _create_task_execution(task_id: str, task_name: str, source_code: str | None = None) -> TaskExecution:
    """Create a TaskExecution record in the database."""
    logger.info(
        "task_execution.create_started",
        task_id=task_id,
        task_name=task_name,
        source=source_code,
    )
    with Session(engine) as session:
        execution = TaskExecution(
            id=task_id,
            task_name=task_name,
            source_code=source_code,
            status="started",
            started_at=datetime.utcnow(),
            logs=[],
            result_summary={},
        )
        session.add(execution)
        session.commit()
        logger.info(
            "task_execution.created",
            task_id=task_id,
            task_name=task_name,
            source=source_code,
        )
        return execution


def _update_task_execution(
    task_id: str,
    status: str,
    result_summary: dict | None = None,
    logs: list | None = None,
    error_message: str | None = None,
) -> None:
    """Update a TaskExecution record with results."""
    logger.info(
        "task_execution.update_started",
        task_id=task_id,
        status=status,
        has_result_summary=result_summary is not None,
        has_logs=logs is not None,
        has_error=error_message is not None,
    )
    with Session(engine) as session:
        execution = session.query(TaskExecution).filter(TaskExecution.id == task_id).first()
        if execution:
            execution.status = status
            execution.completed_at = datetime.utcnow()
            if result_summary is not None:
                execution.result_summary = result_summary
            if logs is not None:
                execution.logs = logs
            if error_message is not None:
                execution.error_message = error_message
            session.commit()
            logger.info("task_execution.updated", task_id=task_id, status=status)
        else:
            logger.warning("task_execution.not_found", task_id=task_id, status=status)


@app.task(bind=True, max_retries=3)
def run_source_pipeline_task(
    self,
    source_code: str,
    job_type: str = "incremental",
    scrapy_settings: dict | None = None,
):
    """Celery task to run the full pipeline for a specific source.

    Tracks execution in TaskExecution table with logs and result summary.
    """
    task_id = self.request.id
    log = logger.bind(source=source_code, job_type=job_type, task_id=task_id)
    log.info(
        "task.pipeline_started",
        retries=self.request.retries,
        scrapy_settings=scrapy_settings or {},
    )

    # Create task execution record
    _create_task_execution(task_id, "crawl", source_code)

    try:
        log.info("task.pipeline_calling_run_full_pipeline")
        run_full_pipeline(
            source_codes=[source_code],
            job_type=job_type,
            scrapy_settings=scrapy_settings,
        )
        log.info("task.pipeline_completed")

        # Update with success
        _update_task_execution(
            task_id,
            "success",
            result_summary={"status": "completed", "source": source_code},
        )
    except Exception as e:
        log.error("task.pipeline_failed", error=str(e))

        # Notify on failure (only on final retry or if retries disabled)
        if self.request.retries >= self.max_retries:
            notify_crawl_failure(source_code, task_id, str(e))
            _update_task_execution(task_id, "failed", error_message=str(e))
        else:
            _update_task_execution(task_id, "retry", error_message=str(e))

        # Retry the task
        raise self.retry(exc=e, countdown=60 * 5)  # Retry in 5 minutes


@app.task(bind=True, max_retries=3)
def process_documents_task(self):
    """Celery task to process all pending documents.

    Extracts, chunks, and validates pending raw documents.
    """
    from processors.runner import process_pending_documents

    task_id = self.request.id
    log = logger.bind(task_id=task_id)
    log.info("task.process_started")

    # Create task execution record
    _create_task_execution(task_id, "process", None)

    try:
        summary = process_pending_documents()
        log.info("task.process_completed", summary=summary)

        # Extract totals from summary
        total_docs = sum(s.get("docs", 0) for s in summary)
        total_chunks = sum(s.get("chunks", 0) for s in summary)

        _update_task_execution(
            task_id,
            "success",
            result_summary={
                "docs_processed": total_docs,
                "chunks_created": total_chunks,
                "per_source": summary,
            },
        )
    except Exception as e:
        log.error("task.process_failed", error=str(e))

        if self.request.retries >= self.max_retries:
            _update_task_execution(task_id, "failed", error_message=str(e))
        else:
            _update_task_execution(task_id, "retry", error_message=str(e))

        raise self.retry(exc=e, countdown=60 * 5)


@app.task(bind=True, max_retries=3)
def embed_chunks_task(self):
    """Celery task to embed all unembedded chunks.

    Embeds chunks and stores in Pinecone (or pgvector fallback).
    """
    from config.settings import settings
    from embedders.pipeline import EmbeddingPipeline

    task_id = self.request.id
    log = logger.bind(task_id=task_id)
    log.info("task.embed_started")

    # Create task execution record
    _create_task_execution(task_id, "embed", None)

    try:
        pipeline = EmbeddingPipeline(
            openai_api_key=settings.openai_api_key or None,
            pinecone_api_key=settings.pinecone_api_key or None,
            pinecone_index=settings.pinecone_index or None,
        )
        embedded_count = pipeline.embed_chunks()
        log.info("task.embed_completed", embedded=embedded_count)

        _update_task_execution(
            task_id,
            "success",
            result_summary={
                "vectors_stored": embedded_count,
            },
        )
    except Exception as e:
        log.error("task.embed_failed", error=str(e))

        if self.request.retries >= self.max_retries:
            _update_task_execution(task_id, "failed", error_message=str(e))
        else:
            _update_task_execution(task_id, "retry", error_message=str(e))

        raise self.retry(exc=e, countdown=60 * 5)
