from pathlib import Path

import structlog
import yaml
from celery import Celery
from celery.schedules import crontab

from config.settings import settings

logger = structlog.get_logger(__name__)

# Initialize Celery
app = Celery(
    "knowledge_base",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=["tasks.pipeline_tasks"],
)

app.conf.update(
    timezone=settings.celery_timezone,
    enable_utc=True,
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    beat_schedule_filename="celerybeat-schedule",
)

_SOURCES_YML = Path(__file__).with_name("sources.yml")


def _entries_for(code: str, schedule_cfg: dict) -> dict:
    """Build Beat entries for one source from {"full": "<cron>", "incremental": "<cron>"}."""
    entries = {}
    for job_type, cron_str in (schedule_cfg or {}).items():
        if job_type not in ("full", "incremental"):
            continue
        parts = str(cron_str).split()
        if len(parts) != 5:
            logger.warning("beat.bad_cron", source=code, job_type=job_type, cron=cron_str)
            continue
        entries[f"crawl-{code}-{job_type}"] = {
            "task": "tasks.pipeline_tasks.run_source_pipeline_task",
            "schedule": crontab(
                minute=parts[0],
                hour=parts[1],
                day_of_month=parts[2],
                month_of_year=parts[3],
                day_of_week=parts[4],
            ),
            "args": (code, job_type),
        }
    return entries


def _schedule_from_db() -> dict:
    """Source of truth at runtime: ``sources.crawl_config['schedule']`` in PostgreSQL."""
    from config.database import SessionLocal
    from config.models import Source

    schedule: dict = {}
    db = SessionLocal()
    try:
        for source in db.query(Source).filter_by(is_active=True).all():
            sched = (source.crawl_config or {}).get("schedule")
            if sched:
                schedule.update(_entries_for(source.code, sched))
    finally:
        db.close()
    return schedule


def _schedule_from_yaml() -> dict:
    """Fallback for a fresh database that has not run ``config.sync_sources`` yet."""
    if not _SOURCES_YML.exists():
        return {}
    config = yaml.safe_load(_SOURCES_YML.read_text(encoding="utf-8")) or {}
    schedule: dict = {}
    for code, source in (config.get("sources") or {}).items():
        schedule.update(_entries_for(code, source.get("schedule", {})))
    return schedule


def get_dynamic_beat_schedule() -> dict:
    """DB schedule if present, else sources.yml. Failures are logged, never silent."""
    try:
        schedule = _schedule_from_db()
        if schedule:
            return schedule
        logger.warning("beat.db_schedule_empty_using_yaml")
    except Exception as exc:  # noqa: BLE001 - DB may be down/unmigrated when Beat starts
        logger.warning("beat.db_schedule_failed_using_yaml", error=str(exc))
    return _schedule_from_yaml()


app.conf.beat_schedule = get_dynamic_beat_schedule()

if __name__ == "__main__":
    app.start()
