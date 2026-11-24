import json
import httpx
import structlog
from config.settings import settings

logger = structlog.get_logger(__name__)

def send_slack_notification(message: str, blocks: list | None = None) -> bool:
    """Send a message to Slack via webhook."""
    if not settings.slack_webhook_url:
        logger.warning("slack.disabled", reason="SLACK_WEBHOOK_URL not set")
        return False

    payload = {"text": message}
    if blocks:
        payload["blocks"] = blocks

    try:
        response = httpx.post(
            settings.slack_webhook_url,
            json=payload,
            timeout=10.0
        )
        response.raise_for_status()
        logger.info("slack.sent", status=response.status_code)
        return True
    except Exception as e:
        logger.error("slack.failed", error=str(e))
        return False

def notify_crawl_failure(source_code: str, job_id: str, error: str) -> None:
    """Send a formatted failure notification to Slack."""
    blocks = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": "🚨 Crawl Job Failed"}
        },
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*Source:*\n{source_code}"},
                {"type": "mrkdwn", "text": f"*Job ID:*\n`{job_id}`"}
            ]
        },
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*Error:*\n```{error}```"}
        }
    ]
    send_slack_notification(f"Crawl job failed for {source_code}", blocks=blocks)
