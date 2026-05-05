import os
import boto3
from config.database import SessionLocal
from config.models import RawDocument, Source
from config.settings import settings

def clean_database():
    print("Cleaning database...")
    db = SessionLocal()
    try:
        # Delete all raw documents
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
    try:
        s3 = boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint,
            aws_access_key_id=settings.s3_access_key,
            aws_secret_access_key=settings.s3_secret_key,
            region_name=settings.s3_region,
        )
        
        # List all objects in the bucket
        bucket = settings.s3_bucket
        paginator = s3.get_paginator('list_objects_v2')
        pages = paginator.paginate(Bucket=bucket)
        
        deleted_count = 0
        for page in pages:
            if 'Contents' in page:
                for obj in page['Contents']:
                    s3.delete_object(Bucket=bucket, Key=obj['Key'])
                    deleted_count += 1
                    
        print(f"Deleted {deleted_count} files from MinIO bucket '{bucket}'.")
    except Exception as e:
        print(f"Error cleaning MinIO: {e}")

if __name__ == "__main__":
    print("Starting data cleanup...")
    clean_database()
    clean_minio()
    print("Cleanup complete!")
