"""Unit tests for the base crawler framework."""

import hashlib

import httpx
import pytest

from crawlers.base_crawler import BaseCrawler, CrawlResult


class MockCrawler(BaseCrawler):
    """Concrete implementation for testing."""

    def __init__(self):
        config = {
            "base_url": "https://example.gov.sg",
            "start_urls": ["https://example.gov.sg/page1"],
            "allowed_domains": ["example.gov.sg"],
            "crawl_delay": 0.01,  # Fast for tests
        }
        super().__init__("test", config)

    def get_urls_to_crawl(self):
        return list(self.start_urls)

    def parse_page(self, url, response):
        return [
            CrawlResult(
                url=url,
                content_type="text/html",
                raw_html=response.text,
                title="Test Page",
            )
        ]


class TestCrawlResult:
    """Tests for CrawlResult data class."""

    def test_content_hash_generation(self):
        result = CrawlResult(
            url="https://example.com/page",
            content_type="text/html",
            raw_html="<html><body>Hello</body></html>",
        )
        expected_hash = hashlib.sha256("<html><body>Hello</body></html>".encode()).hexdigest()
        assert result.content_hash == expected_hash

    def test_url_hash(self):
        result = CrawlResult(url="https://example.com/page", content_type="text/html")
        assert len(result.url_hash) == 12
        assert result.url_hash.isalnum()

    def test_content_hash_changes_with_content(self):
        result1 = CrawlResult(
            url="https://example.com",
            content_type="text/html",
            raw_html="content1",
        )
        result2 = CrawlResult(
            url="https://example.com",
            content_type="text/html",
            raw_html="content2",
        )
        assert result1.content_hash != result2.content_hash

    def test_pdf_content_hash(self):
        result = CrawlResult(
            url="https://example.com/doc.pdf",
            content_type="application/pdf",
            raw_pdf=b"pdf-content-bytes",
        )
        assert len(result.content_hash) == 64

    def test_metadata_defaults_to_empty_dict(self):
        result = CrawlResult(url="https://example.com", content_type="text/html")
        assert result.metadata == {}


class TestBaseCrawler:
    """Tests for BaseCrawler functionality."""

    def test_initialization(self):
        crawler = MockCrawler()
        assert crawler.source_code == "test"
        assert crawler.base_url == "https://example.gov.sg"
        assert len(crawler.visited_urls) == 0
        assert len(crawler.results) == 0

    def test_is_allowed_url(self):
        crawler = MockCrawler()
        assert crawler._is_allowed_url("https://example.gov.sg/page") is True
        assert crawler._is_allowed_url("https://other.com/page") is False

    def test_normalize_url(self):
        crawler = MockCrawler()

        # Relative URL
        result = crawler._normalize_url("/page2", "https://example.gov.sg/page1")
        assert result == "https://example.gov.sg/page2"

        # Absolute URL
        result = crawler._normalize_url(
            "https://example.gov.sg/page3", "https://example.gov.sg"
        )
        assert result == "https://example.gov.sg/page3"

        # Trailing slash removed
        result = crawler._normalize_url("/page/", "https://example.gov.sg")
        assert result == "https://example.gov.sg/page"

    def test_should_follow_link_skips_images(self):
        crawler = MockCrawler()
        assert crawler.should_follow_link("https://example.gov.sg/img.jpg") is False
        assert crawler.should_follow_link("https://example.gov.sg/style.css") is False
        assert crawler.should_follow_link("https://example.gov.sg/app.js") is False

    def test_should_follow_link_allows_html(self):
        crawler = MockCrawler()
        assert crawler.should_follow_link("https://example.gov.sg/page") is True

    def test_extract_title(self):
        crawler = MockCrawler()

        html_with_title = "<html><head><title>Test Title</title></head><body></body></html>"
        assert crawler.extract_title(html_with_title) == "Test Title"

        html_with_h1 = "<html><body><h1>Heading Title</h1></body></html>"
        assert crawler.extract_title(html_with_h1) == "Heading Title"

    def test_extract_main_content(self):
        crawler = MockCrawler()
        html = """
        <html>
        <body>
            <nav>Navigation</nav>
            <main>
                <h1>Main Content</h1>
                <p>Important text here.</p>
            </main>
            <footer>Footer</footer>
        </body>
        </html>
        """
        content = crawler.extract_main_content(html)
        assert "Main Content" in content
        assert "Important text" in content
        assert "Navigation" not in content
        assert "Footer" not in content

    def test_extract_links(self):
        crawler = MockCrawler()
        html = """
        <html><body>
            <a href="/page2">Page 2</a>
            <a href="https://example.gov.sg/page3">Page 3</a>
            <a href="https://other.com/page4">External</a>
        </body></html>
        """
        links = crawler.extract_links(html, "https://example.gov.sg")
        assert "https://example.gov.sg/page2" in links
        assert "https://example.gov.sg/page3" in links
        # External link should be excluded
        assert not any("other.com" in link for link in links)

    def test_close(self):
        crawler = MockCrawler()
        crawler.close()  # Should not raise
