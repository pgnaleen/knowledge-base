"""Pytest configuration for unit tests."""

import pytest
from unittest.mock import patch


@pytest.fixture(autouse=True)
def mock_load_source_config_from_db():
    """Mock DB config loading for all tests.

    Prevents tests from hitting the actual database.
    Returns fixture config for each source code.
    """
    def _load_config(source_name: str) -> dict:
        configs = {
            "hdb": {
                "start_urls": ["https://www.hdb.gov.sg/buying-a-flat"],
                "allowed_domains": ["www.hdb.gov.sg"],
                "target_prefixes": ["/buying-a-flat"],
                "skip_prefixes": ["/feedback", "/careers"],
                "blocked_subdomains": ["assets.hdb.gov.sg"],
                "js_rendering": True,
                "playwright_wait_event": "domcontentloaded",
                "crawl_delay": 2.0,
                "respect_robots_txt": True,
                "user_agent": "Mozilla/5.0...",
                "min_content_length": 100,
                "content_selectors": ["main"],
                "content_keywords_filter": None,
                "tag_config": {},
                "estimated_pages": 300,
                "content_types": ["eligibility"],
            },
            "test": {
                "start_urls": ["http://www.example.com"],
                "allowed_domains": ["www.example.com"],
                "js_rendering": False,
            },
        }
        return configs.get(source_name, {})

    with patch("crawlers.base.load_source_config_from_db", side_effect=_load_config):
        yield
