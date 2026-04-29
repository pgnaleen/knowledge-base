"""add unique constraint on (source_id, url) and pgvector embedding column

Revision ID: a1b2c3d4e5f6
Revises: b414e92d5213
Create Date: 2026-04-19 23:50:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, Sequence[str], None] = "b414e92d5213"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Unique constraint prevents duplicate (source_id, url) rows on parallel/repeated crawls
    op.create_unique_constraint(
        "uq_raw_documents_source_url",
        "raw_documents",
        ["source_id", "url"],
    )

    # pgvector fallback storage on processed_chunks
    op.execute(
        "ALTER TABLE processed_chunks "
        "ADD COLUMN IF NOT EXISTS embedding vector(3072)"
    )

    # HNSW index for fast cosine similarity search on the embedding column.
    # Parameters: m=16 (graph connectivity), ef_construction=128 (build quality).
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_processed_chunks_embedding_hnsw "
        "ON processed_chunks USING hnsw (embedding vector_cosine_ops) "
        "WITH (m = 16, ef_construction = 128)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_processed_chunks_embedding_hnsw")
    op.execute("ALTER TABLE processed_chunks DROP COLUMN IF EXISTS embedding")
    op.drop_constraint("uq_raw_documents_source_url", "raw_documents", type_="unique")
