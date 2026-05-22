import structlog
from config.celery_app import app
from run_pipeline import run_full_pipeline
from config.notifications import notify_crawl_failure

logger = structlog.get_logger(__name__)

@app.task(bind=True, max_retries=3)
def run_source_pipeline_task(self, source_code: str, job_type: str = "incremental"):
    """Celery task to run the full pipeline for a specific source."""
    log = logger.bind(source=source_code, job_type=job_type)
    log.info("task.pipeline_started")

    try:
        run_full_pipeline(
            source_codes=[source_code],
            job_type=job_type
        )
        log.info("task.pipeline_completed")
    except Exception as e:
        log.error("task.pipeline_failed", error=str(e))
        
        # Notify on failure (only on final retry or if retries disabled)
        if self.request.retries >= self.max_retries:
            notify_crawl_failure(source_code, self.request.id, str(e))
        
        # Retry the task
        raise self.retry(exc=e, countdown=60 * 5)  # Retry in 5 minutes
