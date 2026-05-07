"""Sync sources from sources.yml into the database crawl_config column."""

import yaml

from config.database import SessionLocal
from config.logger import get_logger
from config.models import Source

logger = get_logger("sync_sources")


def sync_sources_config():
    """Load sources.yml and upsert crawl_config into each Source row."""
    with open("config/sources.yml") as f:
        config = yaml.safe_load(f)

    sources_config = config.get("sources", {})
    db = SessionLocal()

    try:
        for source_code, source_cfg in sources_config.items():
            source = db.query(Source).filter_by(code=source_code).first()
            if not source:
                logger.warning("Source not found in DB", source_code=source_code)
                continue

            # Extract config keys needed for processors (selectors, tags)
            # Keep all keys from sources.yml for future extensibility
            crawl_config = {
                "content_selectors": source_cfg.get("content_selectors", []),
                "tag_config": source_cfg.get("tag_config", {}),
            }

            source.crawl_config = crawl_config
            db.commit()
            logger.info("Synced source config", source_code=source_code)

        logger.info("Source config sync complete")

    except Exception as e:
        logger.error("Failed to sync sources", error=str(e))
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    sync_sources_config()
