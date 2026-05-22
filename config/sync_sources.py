"""Sync sources from sources.yml into the database crawl_config column."""

import yaml

from config.database import SessionLocal
from config.logger import get_logger
from config.models import Source

logger = get_logger("sync_sources")


def sync_sources_config():
    """Load sources.yml and upsert crawl_config into each Source row.

    Now writes the full schema: crawler behavior + processor tags + metadata.
    """
    with open("config/sources.yml") as f:
        config = yaml.safe_load(f)

    sources_config = config.get("sources", {})
    db = SessionLocal()

    try:
        for source_code, source_cfg in sources_config.items():
            source = db.query(Source).filter_by(code=source_code).first()

            # Upsert: create missing source rows
            if not source:
                source = Source(
                    code=source_code,
                    name=source_cfg.get("name", source_code),
                    base_url=source_cfg.get("base_url", ""),
                )
                db.add(source)
                logger.info("sync.source_created", source_code=source_code)

            # Build full crawl_config schema from YAML
            crawl_config = {
                "start_urls":               source_cfg.get("start_urls", []),
                "allowed_domains":          source_cfg.get("allowed_domains", []),
                "target_prefixes":          source_cfg.get("target_prefixes", []),
                "skip_prefixes":            source_cfg.get("skip_prefixes", []),
                "blocked_subdomains":       source_cfg.get("blocked_subdomains", []),
                "js_rendering":             source_cfg.get("js_rendering", False),
                "playwright_wait_event":    source_cfg.get("playwright_wait_event", "domcontentloaded"),
                "crawl_delay":              source_cfg.get("crawl_delay", None),
                "respect_robots_txt":       source_cfg.get("respect_robots_txt", True),
                "user_agent":               source_cfg.get("user_agent", None),
                "min_content_length":       source_cfg.get("min_content_length", 100),
                "content_selectors":        source_cfg.get("content_selectors", []),
                "content_keywords_filter":  source_cfg.get("content_keywords_filter", None),
                "tag_config":               source_cfg.get("tag_config", {}),
                "estimated_pages":          source_cfg.get("estimated_pages", None),
                "content_types":            source_cfg.get("content_types", []),
            }

            source.crawl_config = crawl_config
            db.commit()
            logger.info("sync.source_done", source_code=source_code)

        logger.info("sync.complete")

    except Exception as e:
        logger.error("sync.failed", error=str(e))
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    sync_sources_config()
