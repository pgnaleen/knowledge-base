"""S3/MinIO storage client."""

from datetime import UTC, datetime

import boto3
from botocore.config import Config

from config.settings import settings

# Module-level singleton — boto3 clients are thread-safe and connection-pooled
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
    """Upload raw HTML to S3. Returns the S3 key."""
    date_str = datetime.now(UTC).strftime("%Y-%m-%d")
    key = f"raw-html/{source_code}/{date_str}/{url_hash}.html"
    get_s3_client().put_object(
        Bucket=settings.s3_bucket,
        Key=key,
        Body=content.encode("utf-8"),
        ContentType="text/html",
    )
    return key


def upload_raw_pdf(source_code: str, url_hash: str, content: bytes) -> str:
    """Upload raw PDF to S3. Returns the S3 key."""
    date_str = datetime.now(UTC).strftime("%Y-%m-%d")
    key = f"raw-pdf/{source_code}/{date_str}/{url_hash}.pdf"
    get_s3_client().put_object(
        Bucket=settings.s3_bucket,
        Key=key,
        Body=content,
        ContentType="application/pdf",
    )
    return key


def upload_processed_text(source_code: str, url_hash: str, content: str) -> str:
    """Upload processed/extracted text to S3. Returns the S3 key."""
    date_str = datetime.now(UTC).strftime("%Y-%m-%d")
    key = f"processed/{source_code}/{date_str}/{url_hash}.txt"
    get_s3_client().put_object(
        Bucket=settings.s3_bucket,
        Key=key,
        Body=content.encode("utf-8"),
        ContentType="text/plain; charset=utf-8",
    )
    return key


def upload_embeddings(batch_id: str, content: str) -> str:
    """Upload a batch of embeddings (JSON) to S3. Returns the S3 key."""
    key = f"embeddings/{batch_id}/embeddings.json"
    get_s3_client().put_object(
        Bucket=settings.s3_bucket,
        Key=key,
        Body=content.encode("utf-8"),
        ContentType="application/json",
    )
    return key


def download_from_s3(key: str) -> bytes:
    """Download any object from S3 by key. Returns raw bytes."""
    response = get_s3_client().get_object(Bucket=settings.s3_bucket, Key=key)
    return response["Body"].read()


class StorageClient:
    """S3/MinIO storage client wrapper with bucket management."""

    def __init__(self):
        """Initialize storage client."""
        self.client = get_s3_client()
        self.bucket = settings.s3_bucket

    def ensure_buckets(self) -> None:
        """Ensure the required S3 bucket exists. Creates it if missing."""
        try:
            self.client.head_bucket(Bucket=self.bucket)
        except self.client.exceptions.NoSuchBucket:
            self.client.create_bucket(Bucket=self.bucket)

    def upload_raw_html(self, source_code: str, url_hash: str, content: str) -> str:
        """Upload raw HTML to S3. Returns the S3 key."""
        return upload_raw_html(source_code, url_hash, content)

    def upload_raw_pdf(self, source_code: str, url_hash: str, content: bytes) -> str:
        """Upload raw PDF to S3. Returns the S3 key."""
        return upload_raw_pdf(source_code, url_hash, content)

    def upload_processed_text(self, source_code: str, url_hash: str, content: str) -> str:
        """Upload processed/extracted text to S3. Returns the S3 key."""
        return upload_processed_text(source_code, url_hash, content)

    def upload_embeddings(self, batch_id: str, content: str) -> str:
        """Upload a batch of embeddings (JSON) to S3. Returns the S3 key."""
        return upload_embeddings(batch_id, content)

    def download_from_s3(self, key: str) -> bytes:
        """Download any object from S3 by key. Returns raw bytes."""
        return download_from_s3(key)
