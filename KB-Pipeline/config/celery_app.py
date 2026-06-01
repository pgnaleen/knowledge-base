from celery import Celery
from celery.schedules import crontab
from config.settings import settings

# Initialize Celery
app = Celery(
    "knowledge_base",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=["tasks.pipeline_tasks"]
)

# Configure Celery
app.conf.update(
    timezone=settings.celery_timezone,
    enable_utc=True,
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    beat_schedule_filename="celerybeat-schedule",
)

def get_dynamic_beat_schedule():
    """Read source schedules from DB and generate a Celery Beat schedule."""
    from config.database import SessionLocal
    from config.models import Source

    schedule = {}
    try:
        db = SessionLocal()
        try:
            for source in db.query(Source).filter_by(is_active=True).all():
                sched = (source.crawl_config or {}).get("schedule", {})
                for job_type, cron_str in sched.items():
                    parts = cron_str.split()
                    if len(parts) == 5:
                        schedule[f"crawl-{source.code}-{job_type}"] = {
                            "task": "tasks.pipeline_tasks.run_source_pipeline_task",
                            "schedule": crontab(
                                minute=parts[0],
                                hour=parts[1],
                                day_of_month=parts[2],
                                month_of_year=parts[3],
                                day_of_week=parts[4],
                            ),
                            "args": (source.code, job_type),
                        }
        finally:
            db.close()
    except Exception:
        pass
    return schedule

# Set the beat schedule
app.conf.beat_schedule = get_dynamic_beat_schedule()

if __name__ == "__main__":
    app.start()
