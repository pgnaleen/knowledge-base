"""Add ON DELETE CASCADE to processed_chunks.document_id FK.

Revision ID: 005
Revises: 004
"""

from alembic import op

revision = "005"
down_revision = "004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("processed_chunks_document_id_fkey", "processed_chunks", type_="foreignkey")
    op.create_foreign_key(
        "processed_chunks_document_id_fkey",
        "processed_chunks",
        "raw_documents",
        ["document_id"],
        ["id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    op.drop_constraint("processed_chunks_document_id_fkey", "processed_chunks", type_="foreignkey")
    op.create_foreign_key(
        "processed_chunks_document_id_fkey",
        "processed_chunks",
        "raw_documents",
        ["document_id"],
        ["id"],
    )
