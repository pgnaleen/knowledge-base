import os
import yaml
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
    """Read sources.yml and generate a Celery Beat schedule."""
    sources_path = os.path.join(os.path.dirname(__file__), "sources.yml")
    if not os.path.exists(sources_path):
        return {}

    with open(sources_path, "r") as f:
        config = yaml.safe_load(f)
    
    sources = config.get("sources", {})
    schedule = {}

    for code, source in sources.items():
        sched_config = source.get("schedule", {})
        
        # Full Crawl Schedule
        if "full" in sched_config:
            cron = sched_config["full"].split()
            if len(cron) == 5:
                schedule[f"crawl-{code}-full"] = {
                    "task": "tasks.pipeline_tasks.run_source_pipeline_task",
                    "schedule": crontab(
                        minute=cron[0],
                        hour=cron[1],
                        day_of_month=cron[2],
                        month_of_year=cron[3],
                        day_of_week=cron[4]
                    ),
                    "args": (code, "full")
                }

        # Incremental Crawl Schedule
        if "incremental" in sched_config:
            cron = sched_config["incremental"].split()
            if len(cron) == 5:
                schedule[f"crawl-{code}-incremental"] = {
                    "task": "tasks.pipeline_tasks.run_source_pipeline_task",
                    "schedule": crontab(
                        minute=cron[0],
                        hour=cron[1],
                        day_of_month=cron[2],
                        month_of_year=cron[3],
                        day_of_week=cron[4]
                    ),
                    "args": (code, "incremental")
                }

    return schedule

# Set the beat schedule
app.conf.beat_schedule = get_dynamic_beat_schedule()

if __name__ == "__main__":
    app.start()
