import boto3
from config.database import SessionLocal
from config.models import RawDocument, ProcessedChunk, CrawlJob, TaskExecution
from config.settings import settings
from embedders.pinecone_store import PineconeStore

PINECONE_NAMESPACES = ["hdb", "ura", "iras", "mas", "cpf", "all"]


def clean_database():
    print("Cleaning database...")
    db = SessionLocal()
    try:
        deleted_chunks = db.query(ProcessedChunk).delete()
        deleted_docs = db.query(RawDocument).delete()
        deleted_crawls = db.query(CrawlJob).delete()
        deleted_tasks = db.query(TaskExecution).delete()
        db.commit()
        print(f"Deleted {deleted_chunks} chunks, {deleted_docs} documents, {deleted_crawls} crawl jobs, and {deleted_tasks} task executions from PostgreSQL.")
    except Exception as e:
        print(f"Error cleaning database: {e}")
        db.rollback()
    finally:
        db.close()


def clean_pinecone():
    print("Cleaning Pinecone vector store...")
    try:
        store = PineconeStore()
        for namespace in PINECONE_NAMESPACES:
            store.delete_all_in_namespace(namespace)
            print(f"Purged all vectors from Pinecone namespace '{namespace}'.")
    except Exception as e:
        print(f"Error cleaning Pinecone: {e}")


def clean_minio():
    print("Cleaning MinIO bucket...")
    s3 = boto3.client(
        "s3",
        endpoint_url=settings.s3_endpoint,
        aws_access_key_id=settings.s3_access_key,
        aws_secret_access_key=settings.s3_secret_key,
        region_name=settings.s3_region,
    )
    bucket = settings.s3_bucket
    paginator = s3.get_paginator("list_objects_v2")
    prefixes = ["raw-html/", "raw-pdf/", "processed/", "embeddings/"]

    for prefix in prefixes:
        deleted_count = 0
        try:
            for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
                for obj in page.get("Contents", []):
                    s3.delete_object(Bucket=bucket, Key=obj["Key"])
                    deleted_count += 1
            print(f"Deleted {deleted_count} files under '{prefix}' in bucket '{bucket}'.")
        except Exception as e:
            print(f"Error cleaning prefix '{prefix}': {e}")

if __name__ == "__main__":
    print("Starting data cleanup...")
    clean_database()
    clean_pinecone()
    clean_minio()
    print("Cleanup complete!")
