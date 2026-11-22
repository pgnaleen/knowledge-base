"""Backfill processed_chunks.embedding (pgvector) from the S3 embedding archive.

Before dual-write was introduced, vectors that went to Pinecone were not stored in
pgvector, so the fallback store was empty. Every embedding was archived to S3 at
``processed/embeddings/{date}/{vector_id}.json``; this script restores them into Postgres
without calling the embedding API again.

Usage:
    docker exec KB-Pipeline-App python backfill_pgvector.py
"""

import json

from sqlalchemy import text

from config.database import engine
from config.logger import get_logger
from config.settings import settings
from config.storage import get_s3_client

logger = get_logger("backfill_pgvector")

_PREFIX = "processed/embeddings/"


def main() -> int:
    s3 = get_s3_client()
    paginator = s3.get_paginator("list_objects_v2")
    restored = skipped = 0

    for page in paginator.paginate(Bucket=settings.s3_bucket, Prefix=_PREFIX):
        for obj in page.get("Contents", []):
            payload = json.loads(s3.get_object(Bucket=settings.s3_bucket, Key=obj["Key"])["Body"].read())
            vector_id, embedding = payload.get("vector_id"), payload.get("embedding")
            if not vector_id or not embedding:
                skipped += 1
                continue
            with engine.begin() as conn:
                res = conn.execute(
                    text(
                        "UPDATE processed_chunks SET embedding = CAST(:vec AS vector) "
                        "WHERE embedding_id = :eid AND embedding IS NULL"
                    ),
                    {"vec": str(embedding), "eid": vector_id},
                )
            restored += res.rowcount
            skipped += 0 if res.rowcount else 1

    logger.info("backfill.done", restored=restored, skipped=skipped)
    return restored


if __name__ == "__main__":
    main()
