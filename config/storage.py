"""S3/MinIO storage client."""

from datetime import datetime

import boto3
from botocore.config import Config

from config.settings import settings


def get_s3_client():
    """Create S3 client configured for MinIO (local) or AWS S3."""
    return boto3.client(
        "s3",
        endpoint_url=settings.s3_endpoint,
        aws_access_key_id=settings.s3_access_key,
        aws_secret_access_key=settings.s3_secret_key,
        region_name=settings.s3_region,
        config=Config(signature_version="s3v4"),
    )


def upload_raw_html(source_code: str, url_hash: str, content: str) -> str:
    """Upload raw HTML to S3. Returns the S3 key."""
    date_str = datetime.utcnow().strftime("%Y-%m-%d")
    key = f"raw-html/{source_code}/{date_str}/{url_hash}.html"
    client = get_s3_client()
    client.put_object(
        Bucket=settings.s3_bucket,
        Key=key,
        Body=content.encode("utf-8"),
        ContentType="text/html",
    )
    return key


def upload_raw_pdf(source_code: str, url_hash: str, content: bytes) -> str:
    """Upload raw PDF to S3. Returns the S3 key."""
    date_str = datetime.utcnow().strftime("%Y-%m-%d")
    key = f"raw-pdf/{source_code}/{date_str}/{url_hash}.pdf"
    client = get_s3_client()
    client.put_object(
        Bucket=settings.s3_bucket,
        Key=key,
        Body=content,
        ContentType="application/pdf",
    )
    return key


def upload_processed_text(source_code: str, url_hash: str, content: str) -> str:
    """Upload processed/extracted text to S3. Returns the S3 key."""
    date_str = datetime.utcnow().strftime("%Y-%m-%d")
    key = f"processed/{source_code}/{date_str}/{url_hash}.txt"
    client = get_s3_client()
    client.put_object(
        Bucket=settings.s3_bucket,
        Key=key,
        Body=content.encode("utf-8"),
        ContentType="text/plain; charset=utf-8",
    )
    return key


def upload_embeddings(batch_id: str, content: str) -> str:
    """Upload a batch of embeddings (JSON) to S3. Returns the S3 key."""
    key = f"embeddings/{batch_id}/embeddings.json"
    client = get_s3_client()
    client.put_object(
        Bucket=settings.s3_bucket,
        Key=key,
        Body=content.encode("utf-8"),
        ContentType="application/json",
    )
    return key


def download_from_s3(key: str) -> bytes:
    """Download any object from S3 by key. Returns raw bytes."""
    client = get_s3_client()
    response = client.get_object(Bucket=settings.s3_bucket, Key=key)
    return response["Body"].read()
