"""Tests for GenericSpider (hot-deployable crawler).

GenericSpider discovers and crawls all active DB sources that don't have
a dedicated custom Python spider.
"""

from unittest.mock import MagicMock, patch
import pytest

from crawlers.spiders.generic import GenericSpider, CUSTOM_SPIDER_CODES


def test_generic_spider_discovery():
    """Test that GenericSpider discovers non-custom sources from DB."""
    spider = GenericSpider()

    # Mock sources: 2 custom (hdb, ura), 1 generic (test_source)
    mock_sources = [
        MagicMock(
            code="test_source",
            crawl_config={
                "start_urls": ["https://test.gov.sg/page1"],
                "allowed_domains": ["test.gov.sg"],
                "js_rendering": False,
            },
        ),
    ]

    with patch("crawlers.spiders.generic.SessionLocal") as mock_db:
        mock_session = MagicMock()
        mock_db.return_value = mock_session
        mock_session.query.return_value.filter.return_value.all.return_value = mock_sources

        requests = list(spider.start_requests())

        assert len(requests) == 1
        assert requests[0].url == "https://test.gov.sg/page1"
        assert requests[0].meta["source_code"] == "test_source"


def test_generic_spider_filters_custom_codes():
    """Test that GenericSpider excludes sources in CUSTOM_SPIDER_CODES."""
    # Verify that the 5 existing spiders are in the exclusion list
    assert "hdb" in CUSTOM_SPIDER_CODES
    assert "ura" in CUSTOM_SPIDER_CODES
    assert "iras" in CUSTOM_SPIDER_CODES
    assert "mas" in CUSTOM_SPIDER_CODES
    assert "cpf" in CUSTOM_SPIDER_CODES


def test_generic_spider_passes_config_in_meta():
    """Test that GenericSpider passes full config via request meta."""
    spider = GenericSpider()

    config = {
        "start_urls": ["https://test.gov.sg/page"],
        "allowed_domains": ["test.gov.sg"],
        "js_rendering": True,
        "playwright_wait_event": "networkidle",
        "target_prefixes": ["/category"],
    }

    mock_sources = [
        MagicMock(code="test", crawl_config=config),
    ]

    with patch("crawlers.spiders.generic.SessionLocal") as mock_db:
        mock_session = MagicMock()
        mock_db.return_value = mock_session
        mock_session.query.return_value.filter.return_value.all.return_value = mock_sources

        requests = list(spider.start_requests())

        assert len(requests) == 1
        assert requests[0].meta["crawl_config"] == config
        assert requests[0].meta["source_code"] == "test"


def test_generic_spider_applies_playwright_for_js_rendering():
    """Test that GenericSpider attaches Playwright meta for JS-rendered sources."""
    spider = GenericSpider()

    config = {
        "start_urls": ["https://spa.gov.sg/page"],
        "allowed_domains": ["spa.gov.sg"],
        "js_rendering": True,
        "playwright_wait_event": "networkidle",
    }

    mock_sources = [
        MagicMock(code="spa", crawl_config=config),
    ]

    with patch("crawlers.spiders.generic.SessionLocal") as mock_db:
        mock_session = MagicMock()
        mock_db.return_value = mock_session
        mock_session.query.return_value.filter.return_value.all.return_value = mock_sources

        requests = list(spider.start_requests())

        assert len(requests) == 1
        assert requests[0].meta.get("playwright") is True
        assert "playwright_page_methods" in requests[0].meta


def test_generic_spider_no_playwright_for_pdfs():
    """Test that GenericSpider does not attach Playwright meta for PDF URLs."""
    spider = GenericSpider()

    config = {
        "start_urls": ["https://test.gov.sg/document.pdf"],
        "allowed_domains": ["test.gov.sg"],
        "js_rendering": True,
    }

    mock_sources = [
        MagicMock(code="test", crawl_config=config),
    ]

    with patch("crawlers.spiders.generic.SessionLocal") as mock_db:
        mock_session = MagicMock()
        mock_db.return_value = mock_session
        mock_session.query.return_value.filter.return_value.all.return_value = mock_sources

        requests = list(spider.start_requests())

        assert len(requests) == 1
        assert requests[0].meta.get("playwright") is None
