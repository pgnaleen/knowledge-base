"""
Integration tests for the crawling pipeline.

These tests hit live infrastructure (government websites, MinIO, PostgreSQL).
NOT run in CI by default.

To run:
    pytest -m integration tests/integration/

Requires:
    docker compose up (postgres, redis, minio)
"""

import json
import uuid

import pytest
import sqlalchemy

from config.database import SessionLocal, init_db
from config.models import RawDocument, Source
from config.settings import settings
from config.storage import (
    download_from_s3,
    get_s3_client,
    upload_embeddings,
    upload_processed_text,
    upload_raw_html,
)


# ── Helpers ──────────────────────────────────────────────────────────────────


def _check_db() -> bool:
    try:
        db = SessionLocal()
        db.execute(sqlalchemy.text("SELECT 1"))
        db.close()
        return True
    except Exception:
        return False


def _check_s3() -> bool:
    try:
        client = get_s3_client()
        client.head_bucket(Bucket=settings.s3_bucket)
        return True
    except Exception:
        return False


requires_db = pytest.mark.skipif(not _check_db(), reason="PostgreSQL not reachable")
requires_s3 = pytest.mark.skipif(not _check_s3(), reason="MinIO/S3 not reachable")


# ── S3 Storage Tests ─────────────────────────────────────────────────────────


@pytest.mark.integration
@requires_s3
class TestS3Storage:
    def test_upload_and_download_html(self):
        content = "<html><body>Integration test content</body></html>"
        key = upload_raw_html("test_source", "integ_test_hash", content)
        assert key.startswith("raw-html/test_source/")

        downloaded = download_from_s3(key)
        assert downloaded.decode("utf-8") == content

    def test_upload_processed_text(self):
        key = upload_processed_text("test_source", "integ_hash_proc", "Processed content here.")
        assert key.startswith("processed/test_source/")
        downloaded = download_from_s3(key)
        assert "Processed content" in downloaded.decode("utf-8")

    def test_upload_embeddings(self):
        payload = json.dumps({"batch_id": "b001", "vectors": [[0.1, 0.2, 0.3]]})
        key = upload_embeddings("batch_integ_001", payload)
        assert key == "embeddings/batch_integ_001/embeddings.json"
        downloaded = download_from_s3(key)
        data = json.loads(downloaded.decode("utf-8"))
        assert data["batch_id"] == "b001"


# ── DB Persistence Tests ──────────────────────────────────────────────────────


@pytest.mark.integration
@requires_db
class TestDBPersistence:
    def test_source_creation(self):
        init_db()
        db = SessionLocal()
        try:
            existing = db.query(Source).filter(Source.code == "integ_test").first()
            if existing:
                db.delete(existing)
                db.commit()

            source = Source(
                name="Integration Test Source",
                code="integ_test",
                base_url="https://test.example.sg",
            )
            db.add(source)
            db.commit()
            db.refresh(source)
            assert source.id is not None

            db.delete(source)
            db.commit()
        finally:
            db.close()

    def test_raw_document_persistence(self):
        init_db()
        db = SessionLocal()
        try:
            source = Source(
                name="Integration Test Source 2",
                code="integ_test2",
                base_url="https://test2.example.sg",
            )
            db.add(source)
            db.commit()
            db.refresh(source)

            doc = RawDocument(
                id=uuid.uuid4(),
                source_id=source.id,
                url="https://test2.example.sg/page1",
                content_hash="a" * 64,
                content_type="text/html",
                title="Test Page",
                raw_html="<html><body>Test</body></html>",
                status="pending",
            )
            db.add(doc)
            db.commit()
            db.refresh(doc)
            assert doc.status == "pending"
            assert doc.title == "Test Page"

            db.delete(doc)
            db.delete(source)
            db.commit()
        finally:
            db.close()


# ── Live Crawl Tests ──────────────────────────────────────────────────────────


@pytest.mark.integration
@pytest.mark.slow
class TestLiveCrawl:
    def test_iras_single_page(self):
        """Crawl one IRAS page (no JS rendering) and verify CrawlResult."""
        import yaml
        from pathlib import Path

        from crawlers.base_crawler import CrawlResult
        from crawlers.spiders.iras_spider import IRASCrawler

        config_path = Path(__file__).parent.parent.parent / "config" / "sources.yml"
        with open(config_path) as f:
            sources = yaml.safe_load(f)["sources"]

        iras_config = {**sources["iras"], "start_urls": [sources["iras"]["start_urls"][0]]}
        crawler = IRASCrawler(iras_config)
        try:
            response = crawler.fetch_page(iras_config["start_urls"][0])
            if response is None:
                pytest.skip("IRAS site unreachable")
            results = crawler.parse_page(iras_config["start_urls"][0], response)
            assert isinstance(results, list)
            for r in results:
                assert isinstance(r, CrawlResult)
                assert r.url
                assert r.content_hash
        finally:
            crawler.close()

    def test_ura_single_page(self):
        """Crawl one URA page (no JS rendering)."""
        import yaml
        from pathlib import Path

        from crawlers.spiders.ura_spider import URACrawler

        config_path = Path(__file__).parent.parent.parent / "config" / "sources.yml"
        with open(config_path) as f:
            sources = yaml.safe_load(f)["sources"]

        ura_config = {**sources["ura"], "start_urls": [sources["ura"]["start_urls"][0]]}
        crawler = URACrawler(ura_config)
        try:
            response = crawler.fetch_page(ura_config["start_urls"][0])
            if response is None:
                pytest.skip("URA site unreachable")
            results = crawler.parse_page(ura_config["start_urls"][0], response)
            assert isinstance(results, list)
        finally:
            crawler.close()
