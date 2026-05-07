"""Unit tests for crawler pipelines (S3Pipeline, PostgresPipeline)."""

import hashlib
from unittest.mock import MagicMock, patch

import pytest

from crawlers.items import CrawlItem
from crawlers.pipelines import S3Pipeline, PostgresPipeline, _normalize_text


class TestNormalizeText:
    """Tests for _normalize_text helper function."""

    def test_normalize_collapses_spaces(self):
        assert _normalize_text("hello   world") == "hello world"

    def test_normalize_collapses_newlines(self):
        assert _normalize_text("hello\n\n\nworld") == "hello world"

    def test_normalize_strips_leading_trailing(self):
        assert _normalize_text("  hello world  ") == "hello world"

    def test_normalize_handles_mixed_whitespace(self):
        assert _normalize_text("hello \t\n  world") == "hello world"

    def test_normalize_empty_string(self):
        assert _normalize_text("") == ""

    def test_normalize_preserves_content(self):
        text = "This is a test document with important content."
        assert _normalize_text(text) == text


class TestS3Pipeline:
    """Tests for S3Pipeline text extraction and hash generation."""

    @pytest.fixture
    def pipeline(self):
        return S3Pipeline()

    @pytest.fixture
    def html_item(self):
        return {
            "url": "http://example.com/page1",
            "source_code": "hdb",
            "content_type": "html",
            "raw_html": b"<html><body>Hello World</body></html>",
        }

    @pytest.fixture
    def pdf_item(self):
        return {
            "url": "http://example.com/doc.pdf",
            "source_code": "cpf",
            "content_type": "pdf",
            "raw_pdf": b"%PDF-1.0...",
        }

    def test_hash_computed_from_normalized_text_not_raw_bytes(self, pipeline, html_item):
        """content_hash must be sha256 of normalized text, not raw HTML bytes."""
        with patch("crawlers.pipelines.HTMLExtractor.extract") as mock_extract, \
             patch("crawlers.pipelines.upload_raw_html") as mock_upload:
            mock_doc = MagicMock()
            mock_doc.text = "Hello World"
            mock_extract.return_value = mock_doc
            mock_upload.return_value = "raw-html/hdb/2026-05-06/abc.html"

            result = pipeline.process_item(html_item, None)

            expected_hash = hashlib.sha256(b"Hello World").hexdigest()
            assert result["content_hash"] == expected_hash
            assert result["content_hash"] != hashlib.sha256(html_item["raw_html"]).hexdigest()

    def test_s3_path_set_from_upload(self, pipeline, html_item):
        """s3_path should be the key returned by upload_raw_html."""
        with patch("crawlers.pipelines.HTMLExtractor.extract") as mock_extract, \
             patch("crawlers.pipelines.upload_raw_html") as mock_upload:
            mock_doc = MagicMock()
            mock_doc.text = "Hello World"
            mock_extract.return_value = mock_doc
            mock_upload.return_value = "raw-html/hdb/2026-05-06/abc.html"

            result = pipeline.process_item(html_item, None)

            assert result["s3_path"] == "raw-html/hdb/2026-05-06/abc.html"

    def test_raw_text_preserves_structure_from_extraction(self, pipeline, html_item):
        """raw_text should be extracted text with structure preserved (not collapsed)."""
        with patch("crawlers.pipelines.HTMLExtractor.extract") as mock_extract, \
             patch("crawlers.pipelines.upload_raw_html") as mock_upload:
            mock_doc = MagicMock()
            mock_doc.text = "Eligibility\nYou must be a Singapore Citizen\n\nIncome Ceiling\nHousehold income must not exceed $14,000"
            mock_extract.return_value = mock_doc
            mock_upload.return_value = "raw-html/hdb/2026-05-06/abc.html"

            result = pipeline.process_item(html_item, None)

            assert result["raw_text"] == "Eligibility\nYou must be a Singapore Citizen\n\nIncome Ceiling\nHousehold income must not exceed $14,000"

    def test_extraction_failure_fallback(self, pipeline, html_item):
        """Extraction failure should fall back to empty text and hash of empty bytes."""
        with patch("crawlers.pipelines.HTMLExtractor.extract") as mock_extract, \
             patch("crawlers.pipelines.upload_raw_html") as mock_upload:
            mock_extract.side_effect = Exception("Extraction failed")
            mock_upload.return_value = "raw-html/hdb/2026-05-06/abc.html"

            result = pipeline.process_item(html_item, None)

            assert result["raw_text"] == ""
            assert result["content_hash"] == hashlib.sha256(b"").hexdigest()
            # s3_path still set — raw file was uploaded before extraction
            assert result["s3_path"] == "raw-html/hdb/2026-05-06/abc.html"

    def test_pdf_item_sets_s3_path_with_pdf_prefix(self, pipeline, pdf_item):
        """PDF upload should set s3_path under raw-pdf/ prefix."""
        with patch("crawlers.pipelines.PDFExtractor.extract") as mock_extract, \
             patch("crawlers.pipelines.upload_raw_pdf") as mock_upload:
            mock_doc = MagicMock()
            mock_doc.text = "PDF Content"
            mock_extract.return_value = mock_doc
            mock_upload.return_value = "raw-pdf/cpf/2026-05-06/abc.pdf"

            result = pipeline.process_item(pdf_item, None)

            assert result["s3_path"] == "raw-pdf/cpf/2026-05-06/abc.pdf"
            expected_hash = hashlib.sha256(b"PDF Content").hexdigest()
            assert result["content_hash"] == expected_hash
            assert result["raw_text"] == "PDF Content"


class TestPostgresPipeline:
    """Tests for PostgresPipeline dedup logic."""

    @pytest.fixture
    def pipeline(self):
        p = PostgresPipeline()
        p.db = MagicMock()
        return p

    @pytest.fixture
    def sample_item(self):
        return {
            "url": "http://example.com/page1",
            "source_code": "hdb",
            "content_type": "html",
            "content_hash": "abc123def456",
            "raw_text": "Document content here",
            "s3_path": "raw-html/hdb/2026-05-06/key1.html",
        }

    def test_cross_url_dedup_skips_duplicate_hash(self, pipeline, sample_item):
        """Same content_hash at a different URL should be skipped without DB write."""
        mock_source = MagicMock()
        mock_source.id = "source-id-1"
        mock_existing_doc = MagicMock()
        mock_existing_doc.url = "http://example.com/different-page"
        mock_existing_doc.content_hash = "abc123def456"

        pipeline.db.query.return_value.filter_by.side_effect = [
            MagicMock(first=lambda: mock_source),
            MagicMock(first=lambda: mock_existing_doc),
        ]

        result = pipeline.process_item(sample_item, None)

        assert result is sample_item
        pipeline.db.add.assert_not_called()

    def test_new_url_inserts_with_s3_path_and_raw_text(self, pipeline, sample_item):
        """New URL should insert a RawDocument with s3_path and raw_text set."""
        mock_source = MagicMock()
        mock_source.id = "source-id-1"

        pipeline.db.query.return_value.filter_by.side_effect = [
            MagicMock(first=lambda: mock_source),
            MagicMock(first=lambda: None),  # no hash match
            MagicMock(first=lambda: None),  # no URL match
        ]

        pipeline.process_item(sample_item, None)

        pipeline.db.add.assert_called_once()
        doc = pipeline.db.add.call_args[0][0]
        assert doc.raw_text == "Document content here"
        assert doc.content_hash == "abc123def456"
        assert doc.s3_path == "raw-html/hdb/2026-05-06/key1.html"
        assert doc.content_type == "html"

    def test_same_url_different_hash_updates(self, pipeline, sample_item):
        """Same URL with different hash should update the existing document."""
        mock_source = MagicMock()
        mock_source.id = "source-id-1"
        mock_existing = MagicMock()
        mock_existing.url = sample_item["url"]
        mock_existing.content_hash = "old-hash"
        mock_existing.s3_path = "raw-html/hdb/2026-01-01/old.html"

        pipeline.db.query.return_value.filter_by.side_effect = [
            MagicMock(first=lambda: mock_source),
            MagicMock(first=lambda: None),         # no hash match
            MagicMock(first=lambda: mock_existing), # URL match
        ]

        pipeline.process_item(sample_item, None)

        pipeline.db.commit.assert_called()
        assert mock_existing.raw_text == "Document content here"
        assert mock_existing.content_hash == "abc123def456"
        assert mock_existing.s3_path == "raw-html/hdb/2026-05-06/key1.html"
        assert mock_existing.status == "pending"

    def test_same_url_same_hash_skips(self, pipeline, sample_item):
        """Same URL with same hash should be a no-op."""
        mock_source = MagicMock()
        mock_source.id = "source-id-1"
        mock_existing = MagicMock()
        mock_existing.url = sample_item["url"]
        mock_existing.content_hash = "abc123def456"

        pipeline.db.query.return_value.filter_by.side_effect = [
            MagicMock(first=lambda: mock_source),
            MagicMock(first=lambda: None),         # no cross-URL hash match
            MagicMock(first=lambda: mock_existing), # URL match, same hash
        ]

        pipeline.process_item(sample_item, None)

        pipeline.db.add.assert_not_called()
