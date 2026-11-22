"""Add HNSW index on processed_chunks.embedding (via halfvec) for pgvector search.

Revision ID: 008
Revises: 007

pgvector cannot HNSW/IVFFlat-index the ``vector`` type above 2000 dimensions, and we
store 3072-dim vectors (text-embedding-3-large). Casting to ``halfvec`` (supported up to
4000 dims, pgvector >= 0.7) via an expression index fixes this. Queries must use the
same expression: ``embedding::halfvec(3072) <=> CAST(:vec AS halfvec(3072))``
(see embedders/pgvector_store.py). Image pgvector/pgvector:0.8.0-pg16 satisfies this.
"""
from alembic import op

revision = "008"
down_revision = "007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_processed_chunks_embedding_hnsw "
        "ON processed_chunks USING hnsw ((embedding::halfvec(3072)) halfvec_cosine_ops) "
        "WITH (m = 16, ef_construction = 128)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_processed_chunks_embedding_hnsw")
