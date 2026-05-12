"""S3/MinIO storage client — single bucket with prefix-based layout.

Bucket: sg-property-kb
  raw-html/{source}/{date}/{url_hash}.html
  raw-pdf/{source}/{date}/{url_hash}.pdf
  raw-text/{source}/{date}/{url_hash}.txt
  processed/{source}/{date}/{url_hash}.txt
"""

from datetime import datetime

import boto3
from botocore.config import Config

from config.settings import settings

_client = None


def get_s3_client():
    """Return the singleton S3 client (created lazily on first use)."""
    global _client
    if _client is None:
        _client = boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint,
            aws_access_key_id=settings.s3_access_key,
            aws_secret_access_key=settings.s3_secret_key,
            region_name=settings.s3_region,
            config=Config(signature_version="s3v4"),
        )
    return _client


def upload_raw_html(source_code: str, url_hash: str, content: str) -> str:
    """Upload raw HTML. Returns the S3 key (prefix included)."""
    date_str = datetime.now().strftime("%Y-%m-%d")
    key = f"raw-html/{source_code}/{date_str}/{url_hash}.html"
    get_s3_client().put_object(
        Bucket=settings.s3_bucket,
        Key=key,
        Body=content.encode("utf-8"),
        ContentType="text/html",
    )
    return key


def upload_raw_pdf(source_code: str, url_hash: str, content: bytes) -> str:
    """Upload raw PDF. Returns the S3 key (prefix included)."""
    date_str = datetime.now().strftime("%Y-%m-%d")
    key = f"raw-pdf/{source_code}/{date_str}/{url_hash}.pdf"
    get_s3_client().put_object(
        Bucket=settings.s3_bucket,
        Key=key,
        Body=content,
        ContentType="application/pdf",
    )
    return key


def upload_processed_text(source_code: str, url_hash: str, content: str) -> str:
    """Upload processed/extracted text. Returns the S3 key (prefix included)."""
    date_str = datetime.now().strftime("%Y-%m-%d")
    key = f"processed/{source_code}/{date_str}/{url_hash}.txt"
    get_s3_client().put_object(
        Bucket=settings.s3_bucket,
        Key=key,
        Body=content.encode("utf-8"),
        ContentType="text/plain; charset=utf-8",
    )
    return key


def upload_embeddings(batch_id: str, content: str) -> str:
    """Upload a batch of embeddings (JSON). Returns the S3 key (prefix included)."""
    key = f"processed/embeddings/{batch_id}.json"
    get_s3_client().put_object(
        Bucket=settings.s3_bucket,
        Key=key,
        Body=content.encode("utf-8"),
        ContentType="application/json",
    )
    return key


def delete_s3_object(key: str) -> None:
    """Delete an object from the bucket by key. No-op if key is None or empty."""
    if not key:
        return
    get_s3_client().delete_object(Bucket=settings.s3_bucket, Key=key)


def download_from_s3(key: str) -> bytes:
    """Download any object from the single bucket by key. Returns raw bytes."""
    response = get_s3_client().get_object(Bucket=settings.s3_bucket, Key=key)
    return response["Body"].read()


class StorageClient:
    """S3/MinIO storage client wrapper with bucket management."""

    def __init__(self):
        self.client = get_s3_client()

    def ensure_buckets(self) -> None:
        """Ensure the single S3 bucket exists. Creates it if missing."""
        try:
            self.client.head_bucket(Bucket=settings.s3_bucket)
        except Exception:
            self.client.create_bucket(Bucket=settings.s3_bucket)

    def upload_raw_html(self, source_code: str, url_hash: str, content: str) -> str:
        return upload_raw_html(source_code, url_hash, content)

    def upload_raw_pdf(self, source_code: str, url_hash: str, content: bytes) -> str:
        return upload_raw_pdf(source_code, url_hash, content)

    def upload_processed_text(self, source_code: str, url_hash: str, content: str) -> str:
        return upload_processed_text(source_code, url_hash, content)

    def upload_embeddings(self, batch_id: str, content: str) -> str:
        return upload_embeddings(batch_id, content)

    def download_from_s3(self, key: str) -> bytes:
        return download_from_s3(key)
