import boto3
from config.database import SessionLocal
from config.models import RawDocument
from config.settings import settings
from config.storage import BUCKETS


def clean_database():
    print("Cleaning database...")
    db = SessionLocal()
    try:
        deleted_docs = db.query(RawDocument).delete()
        db.commit()
        print(f"Deleted {deleted_docs} documents from PostgreSQL.")
    except Exception as e:
        print(f"Error cleaning database: {e}")
        db.rollback()
    finally:
        db.close()


def clean_minio():
    print("Cleaning MinIO buckets...")
    s3 = boto3.client(
        "s3",
        endpoint_url=settings.s3_endpoint,
        aws_access_key_id=settings.s3_access_key,
        aws_secret_access_key=settings.s3_secret_key,
        region_name=settings.s3_region,
    )
    paginator = s3.get_paginator("list_objects_v2")

    for label, bucket in BUCKETS.items():
        try:
            deleted_count = 0
            for page in paginator.paginate(Bucket=bucket):
                for obj in page.get("Contents", []):
                    s3.delete_object(Bucket=bucket, Key=obj["Key"])
                    deleted_count += 1
            print(f"Deleted {deleted_count} files from '{bucket}' bucket.")
        except Exception as e:
            print(f"Error cleaning bucket '{bucket}': {e}")

if __name__ == "__main__":
    print("Starting data cleanup...")
    clean_database()
    clean_minio()
    print("Cleanup complete!")
