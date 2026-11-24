"""Celery tasks: crawl+process+embed per source, plus stand-alone process and embed tasks.

Every task records a ``task_executions`` row (status, result summary, log tail) so the
``GET /jobs`` endpoint can show history.

The crawl task runs ``run_pipeline.py`` in a **subprocess**. Scrapy runs on a Twisted
reactor, which can be started only once per process; a long-lived Celery worker process
would raise ``ReactorNotRestartable`` on the second crawl. A fresh interpreter per crawl
avoids that (Celery workers are daemonic, so ``multiprocessing`` children are not allowed).
"""

import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import structlog
from sqlalchemy.orm import Session

from config.celery_app import app
from config.database import engine
from config.models import TaskExecution
from config.notifications import notify_crawl_failure

logger = structlog.get_logger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_LOG_TAIL_LINES = 60
_CRAWL_TIMEOUT_SECONDS = 6 * 60 * 60
_RETRY_COUNTDOWN = 60 * 5


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)  # DB columns are naive UTC


def _create_task_execution(task_id: str, task_name: str, source_code: str | None = None) -> None:
    """Insert (or reset, on Celery retry) the TaskExecution row for this task id."""
    with Session(engine) as session:
        execution = session.get(TaskExecution, task_id)
        if execution is None:
            execution = TaskExecution(id=task_id, task_name=task_name, source_code=source_code)
            session.add(execution)
        execution.status = "started"
        execution.started_at = _utcnow()
        execution.completed_at = None
        execution.error_message = None
        execution.logs = []
        execution.result_summary = {}
        session.commit()


def _update_task_execution(
    task_id: str,
    status: str,
    result_summary: dict | None = None,
    logs: list | None = None,
    error_message: str | None = None,
) -> None:
    """Update a TaskExecution row. Never raises: bookkeeping must not mask the task result."""
    try:
        with Session(engine) as session:
            execution = session.get(TaskExecution, task_id)
            if execution is None:
                logger.warning("task_execution.not_found", task_id=task_id, status=status)
                return
            execution.status = status
            if status in ("success", "failed"):
                execution.completed_at = _utcnow()
            if result_summary is not None:
                execution.result_summary = result_summary
            if logs is not None:
                execution.logs = logs
            if error_message is not None:
                execution.error_message = error_message
            session.commit()
    except Exception as exc:  # noqa: BLE001
        logger.error("task_execution.update_failed", task_id=task_id, error=str(exc))


def build_crawl_command(
    source_code: str, job_type: str, scrapy_settings: dict | None = None
) -> list[str]:
    """Build the ``run_pipeline.py`` command line for one source."""
    cmd = [sys.executable, str(_PROJECT_ROOT / "run_pipeline.py"), source_code]
    if job_type == "incremental":
        cmd.append("--incremental")
    for key, value in (scrapy_settings or {}).items():
        cmd += ["-S", f"{key}={value}"]
    return cmd


def _fail_or_retry(task, task_id: str, exc: Exception, log, *, notify_source: str | None = None):
    """Record failure/retry state, notify on the final failure, then re-raise via retry."""
    final = task.request.retries >= task.max_retries
    _update_task_execution(task_id, "failed" if final else "retry", error_message=str(exc))
    if final and notify_source:
        notify_crawl_failure(notify_source, task_id, str(exc))
    log.error("task.failed", error=str(exc), final=final)
    raise task.retry(exc=exc, countdown=_RETRY_COUNTDOWN)


@app.task(bind=True, max_retries=3)
def run_source_pipeline_task(
    self,
    source_code: str,
    job_type: str = "incremental",
    scrapy_settings: dict | None = None,
):
    """Crawl → process → embed one source (in a subprocess)."""
    task_id = self.request.id
    log = logger.bind(source=source_code, job_type=job_type, task_id=task_id)
    log.info("task.pipeline_started", retries=self.request.retries)
    _create_task_execution(task_id, "crawl", source_code)

    try:
        cmd = build_crawl_command(source_code, job_type, scrapy_settings)
        proc = subprocess.run(
            cmd,
            cwd=_PROJECT_ROOT,
            capture_output=True,
            text=True,
            timeout=_CRAWL_TIMEOUT_SECONDS,
        )
        tail = (proc.stdout + proc.stderr).splitlines()[-_LOG_TAIL_LINES:]
        logs = [{"event": "output", "level": "info", "details": {"line": ln}} for ln in tail]
        if proc.returncode != 0:
            _update_task_execution(task_id, "retry", logs=logs)
            raise RuntimeError(f"run_pipeline exited with code {proc.returncode}")
        _update_task_execution(
            task_id,
            "success",
            result_summary={"status": "completed", "source": source_code, "job_type": job_type},
            logs=logs,
        )
        log.info("task.pipeline_completed")
    except Exception as exc:  # noqa: BLE001
        _fail_or_retry(self, task_id, exc, log, notify_source=source_code)


@app.task(bind=True, max_retries=3)
def process_documents_task(self):
    """Extract/chunk/validate all pending raw documents."""
    from processors.runner import process_pending_documents

    task_id = self.request.id
    log = logger.bind(task_id=task_id)
    _create_task_execution(task_id, "process", None)
    try:
        summary = process_pending_documents()
        _update_task_execution(
            task_id,
            "success",
            result_summary={
                "docs_processed": sum(s.get("docs", 0) for s in summary),
                "chunks_created": sum(s.get("chunks", 0) for s in summary),
                "per_source": summary,
            },
        )
    except Exception as exc:  # noqa: BLE001
        _fail_or_retry(self, task_id, exc, log)


@app.task(bind=True, max_retries=3)
def embed_chunks_task(self):
    """Embed all un-embedded chunks into Pinecone + pgvector."""
    from config.settings import settings
    from embedders.pipeline import EmbeddingPipeline

    task_id = self.request.id
    log = logger.bind(task_id=task_id)
    _create_task_execution(task_id, "embed", None)
    try:
        pipeline = EmbeddingPipeline(
            openai_api_key=settings.openai_api_key or None,
            pinecone_api_key=settings.pinecone_api_key or None,
            pinecone_index=settings.pinecone_index or None,
        )
        embedded = pipeline.embed_chunks()
        _update_task_execution(task_id, "success", result_summary={"vectors_stored": embedded})
    except Exception as exc:  # noqa: BLE001
        _fail_or_retry(self, task_id, exc, log)
